"""E2B adapter: durable VM-side execution, no serverless background threads."""
import json
from pathlib import Path
import time

from .review_api import ReviewError, decode_material, MAX_CODE_BYTES


class E2BExecutor:
    def __init__(self, env):
        self.key = env.get('E2B_API_KEY', '')

    @property
    def configured(self):
        return bool(self.key)

    def launch(self, assessment, body):
        from e2b import Sandbox
        if not self.configured:
            raise ReviewError('sandbox_not_configured', '云端执行服务正在配置，暂未启动。', 503)
        raw, identity = decode_material(body.get('code'), '.zip', MAX_CODE_BYTES)
        if identity['sha256'] != assessment['materials']['code']:
            raise ReviewError('material_changed', '代码已变化，请先重新审查并生成本次执行计划。', 409)
        plan = {**assessment['review']['plan'], 'metrics': assessment['review']['metrics']}
        # VM lifetime bounds billing even if the browser is closed or the control
        # function dies. Polling does NOT extend the deadline.
        lifetime = plan['max_seconds'] + 60
        started = time.time()
        sb = Sandbox.create(api_key=self.key, timeout=lifetime, secure=True,
            metadata={'project': 'articheck', 'assessment_id': assessment['id']},
            network={'allow_public_traffic': False,
                     'deny_out': ['0.0.0.0/0'],
                     'allow_out': ['pypi.org', 'files.pythonhosted.org', 'github.com', '*.github.com',
                                   '*.githubusercontent.com', 'archive.ics.uci.edu', 'www.csie.ntu.edu.tw',
                                   'huggingface.co', '*.huggingface.co', '*.hf.co', '*.xethub.hf.co',
                                   'download.pytorch.org', 'scikit-learn.org', '*.scikit-learn.org']},
            # Python 3.10-compatible SDK: send the API's idempotency header
            # directly and avoid automatic creation retries after ambiguity.
            retries=0, api_headers={'Idempotency-Key': 'articheck-' + assessment['id']+'-'+
                                   (assessment.get('execution') or {}).get('attempt_id','initial')})
        try:
            info=sb.get_info()
            environment={'template_id':info.template_id,'cpu_count':info.cpu_count,
                         'memory_mb':info.memory_mb,'envd_version':info.envd_version}
            # A fresh user has no default image user's sudo privileges.
            sb.commands.run('useradd -m -s /bin/bash articheck && install -d -m 700 /root/articheck && install -d -o articheck -g articheck /home/articheck/artifact', user='root')
            sb.files.write('/root/articheck/source.zip', raw, user='root')
            # One upload avoids thousands of SDK round trips. ZIP paths were
            # validated before the immutable material fingerprint was frozen.
            setup = '''import os, pathlib, zipfile, pwd, shutil
root=pathlib.Path('/home/articheck/artifact')
with zipfile.ZipFile('/root/articheck/source.zip') as z:
 names=[n for n in z.namelist() if not n.endswith('/')]
 prefix=names[0].split('/')[0]+'/'
 strip=all(n.startswith(prefix) for n in names)
 for item in z.infolist():
  if item.is_dir(): continue
  name=item.filename[len(prefix):] if strip else item.filename
  path=root/name
  if not path.resolve().is_relative_to(root): raise ValueError('Unsafe archive')
  path.parent.mkdir(parents=True,exist_ok=True)
  with z.open(item) as source, path.open('wb') as target:
   shutil.copyfileobj(source,target,1024*1024)
  if item.external_attr>>16 & 0o111: path.chmod(0o755)
uid=pwd.getpwnam('articheck').pw_uid
for parent,dirs,files in os.walk('/home/articheck'):
 os.chown(parent,uid,uid)
 for name in files: os.chown(os.path.join(parent,name),uid,uid)
'''
            sb.files.write('/root/articheck/setup.py', setup, user='root')
            sb.commands.run('python3 /root/articheck/setup.py && runuser -u articheck -- python3 -m venv --system-site-packages /home/articheck/venv', user='root', timeout=30)
            # Plan references retain archive paths for provenance; commands run at
            # the source root, as specified in the model contract.
            sb.files.write('/root/articheck/runner.py', Path(__file__).with_name('hosted_runner.py').read_text(), user='root')
            sb.files.write('/root/articheck/plan.json', json.dumps(plan), user='root')
            sb.commands.run('python3 /root/articheck/runner.py /root/articheck/plan.json /home/articheck/artifact /root/articheck > /root/articheck/supervisor.log 2>&1',
                            user='root', background=True, timeout=lifetime)
            return {'status': 'running', 'sandbox_id': sb.sandbox_id, 'started_at': started,
                    'deadline': started + lifetime, 'plan_sha256': assessment['review']['plan_sha256'],
                    'provider': 'e2b', 'execution_performed': False, 'scientific_validation': False,
                    'environment': environment,
                    'stages': [], 'metrics': []}
        except Exception:
            sb.kill()
            raise

    def poll(self, execution):
        from e2b import Sandbox
        if time.time() > execution['deadline']:
            return {**execution, 'status': 'expired', 'notice': '执行实例已达到最长存活时间；尚未取回的结果不视为通过。'}
        remaining = max(1, int(execution['deadline'] - time.time()))
        sb = Sandbox.connect(execution['sandbox_id'], api_key=self.key, timeout=remaining)
        try:
            raw = sb.files.read('/root/articheck/status.json', user='root')
        except Exception:
            # Startup can precede the supervisor's first atomic status write.
            if time.time() - execution['started_at'] < 20:
                return execution
            raise
        if len(raw.encode()) > 400_000:
            raise ReviewError('execution_report_size', '执行输出过大，请停止该任务。', 502)
        status = json.loads(raw)
        result = {**execution, **status}
        # The route first persists the report. VM cleanup is then best-effort;
        # the hard provider deadline still applies if cleanup is interrupted.
        return result

    def stop(self, execution):
        from e2b import Sandbox
        Sandbox.kill(execution['sandbox_id'], api_key=self.key)
