"""Owned GPU pull-worker with unprivileged bubblewrap + network isolation.

Polls the private Redis queue using only scoped storage credentials, downloads
short-lived source archives over HTTPS, verifies SHA256, and runs each stage
inside an isolated user/network/PID/mount namespace with read-only CUDA runtime.
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import pwd
import re
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

MAX_CODE_BYTES = 100 * 1024**2
RUNTIME_DIR = '/opt/articheck-runtime'
ALLOWED_ARCHIVE_SUFFIXES = ('.e2b.app', '.e2b.dev')


class WorkerStore:
    def __init__(self, env):
        self.url = env.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
        self.token = env.get('UPSTASH_REDIS_REST_TOKEN', '')

    def command(self, *args):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                raise ValueError('Redirect disabled')
        req = urllib.request.Request(self.url, data=json.dumps(list(args)).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as resp:
            value = json.loads(resp.read(1_000_001))
        if 'error' in value or 'result' not in value:
            raise RuntimeError('Redis command error')
        return value['result']


def detect_capacity(runtime=RUNTIME_DIR):
    capacity = {'provider': 'owned_gpu', 'cpu_count': min(8, os.cpu_count() or 4),
                'memory_mb': 16384, 'gpu': True, 'gpu_name': 'NVIDIA GeForce RTX 4090',
                'gpu_memory_mb': 24564}
    python_bin = Path(runtime) / 'bin/python'
    if python_bin.exists():
        try:
            code = ('import json,torch;p=torch.cuda.get_device_properties(0);'
                    'print(json.dumps({"gpu":torch.cuda.is_available(),"gpu_name":p.name,'
                    '"gpu_memory_mb":int(p.total_memory//(1024*1024))}))')
            out = subprocess.check_output([str(python_bin), '-c', code],
                env={'PYTHONHOME': runtime, 'PATH': f'{runtime}/bin:/usr/bin:/bin',
                     'PYTHONNOUSERSITE': '1', 'CUDA_VISIBLE_DEVICES': '0'},
                text=True, timeout=15)
            capacity.update(json.loads(out.strip().splitlines()[-1]))
        except Exception:
            pass
    return capacity


def validate_source_url(url):
    parsed = urllib.parse.urlparse(url or '')
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not any(host.endswith(s) for s in ALLOWED_ARCHIVE_SUFFIXES):
        raise ValueError('Untrusted GPU source archive URL')
    return url


def fetch_source_archive(url, expected_bytes, expected_sha256):
    validate_source_url(url)
    if not isinstance(expected_bytes, int) or not 1 <= expected_bytes <= MAX_CODE_BYTES:
        raise ValueError('Invalid source archive size')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Redirect disabled')
    req = urllib.request.Request(url, headers={'User-Agent': 'ArtiCheck-GPU-Worker/1.0'})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=45) as resp:
        raw = resp.read(expected_bytes + 1)
    if len(raw) != expected_bytes:
        raise ValueError('Source archive size mismatch')
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Source archive SHA256 mismatch')
    return raw


def extract_archive(raw, dest):
    root = Path(dest).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if not n.endswith('/')]
        if not names or len(names) > 4000:
            raise ValueError('Archive file count out of bounds')
        prefix = names[0].split('/')[0] + '/'
        strip = bool(prefix) and all(n.startswith(prefix) for n in names)
        total = 0
        for item in archive.infolist():
            if item.is_dir():
                continue
            mode = item.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                raise ValueError('Symlinks are not allowed in archive')
            rel = item.filename[len(prefix):] if strip else item.filename
            if not rel or rel.startswith('/') or '..' in Path(rel).parts:
                raise ValueError('Unsafe archive path')
            target = (root / rel).resolve()
            if os.path.commonpath([str(root), str(target)]) != str(root):
                raise ValueError('Unsafe archive target')
            total += item.file_size
            if total > 512 * 1024 * 1024:
                raise ValueError('Uncompressed archive exceeds limit')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            if mode & 0o111:
                target.chmod(0o755)


def bwrap_args(work_dir, command, runtime=RUNTIME_DIR):
    args = ['/usr/bin/bwrap', '--unshare-all', '--new-session', '--die-with-parent',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/bin', '/bin',
            '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--ro-bind', '/sys', '/sys', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--ro-bind', runtime, runtime,
            '--tmpfs', runtime + '/conda-meta', '--tmpfs', runtime + '/etc',
            '--bind', str(work_dir), '/work', '--chdir', '/work',
            '--uid', '65534', '--gid', '65534', '--cap-drop', 'ALL']
    for dev in ('nvidia0', 'nvidiactl', 'nvidia-uvm', 'nvidia-uvm-tools'):
        dev_path = '/dev/' + dev
        if Path(dev_path).exists():
            args += ['--dev-bind', dev_path, dev_path]
    return args + ['/bin/bash', '-c', command]


def bwrap_env(runtime=RUNTIME_DIR):
    return {'PYTHONHOME': runtime,
            'PATH': f'{runtime}/bin:/usr/local/bin:/usr/bin:/bin',
            'HOME': '/work',
            'LANG': 'C.UTF-8',
            'OMP_NUM_THREADS': '4',
            'OPENBLAS_NUM_THREADS': '4',
            'MKL_NUM_THREADS': '4',
            'PYTHONUNBUFFERED': '1',
            'PYTHONNOUSERSITE': '1',
            'PIP_DISABLE_PIP_VERSION_CHECK': '1',
            'CUDA_VISIBLE_DEVICES': '0'}


def evaluate_metrics(plan, stage_logs, all_logs):
    logs = '\n'.join(all_logs)
    targets = {m['id']: m for m in plan.get('metrics', [])}
    metrics = []
    for rule in plan.get('metric_patterns', []):
        target = targets.get(rule['metric_id'])
        if not target:
            continue
        try:
            output = stage_logs.get(rule.get('stage_id'), logs if len(plan['stages']) == 1 else '')
            values = [float(m.group(1)) for m in re.finditer(rule['pattern'], output)]
            values = [v for v in values if math.isfinite(v)]
            observed = (statistics.mean(values) if rule.get('aggregation') == 'mean' else values[-1]) if values else None
        except (ValueError, re.error):
            observed = None
            values = []
        metrics.append({'id': target['id'], 'metric': target['metric'], 'expected': target['value'],
            'observed': observed, 'unit': target['unit'], 'tolerance': rule['tolerance'],
            'observations': values, 'n': len(values), 'std': statistics.stdev(values) if len(values) > 1 else None,
            'aggregation': rule.get('aggregation', 'last'),
            'stage_id': rule.get('stage_id'), 'target_evidence_kind': target.get('evidence_kind', 'text_verified'),
            'status': 'unobserved' if observed is None else 'within_tolerance' if abs(observed - target['value']) <= rule['tolerance'] else 'outside_tolerance',
            'evidence_kind': 'artifact_stdout', 'pattern': rule['pattern']})
    return metrics


class GPUWorker:
    def __init__(self, env, *, store=None, fetcher=fetch_source_archive,
                 runtime=RUNTIME_DIR, run_as='articheck', work_root=None):
        self.env = env
        self.store = store or WorkerStore(env)
        self.fetcher = fetcher
        self.runtime = runtime
        self.run_as = run_as
        self.prefix = 'articheck:gpu:' + env.get('ARTICHECK_BUDGET_ID', '') + ':'
        self.capacity = detect_capacity(runtime)
        shm = Path('/dev/shm')
        self.work_root = Path(work_root) if work_root else (shm if shm.is_dir() and os.access(shm, os.W_OK) else Path(tempfile.gettempdir()))
        self.last_heartbeat = 0.0

    def send_heartbeat(self, force=False):
        now = time.time()
        if not force and now - self.last_heartbeat < 20:
            return
        payload = {'time': now, 'capacity': self.capacity}
        self.store.command('SET', self.prefix + 'heartbeat', json.dumps(payload, ensure_ascii=False), 'EX', '120')
        self.last_heartbeat = now

    def job_key(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('Invalid GPU job id')
        return self.prefix + 'job:' + job_id

    def save_record(self, record):
        self.store.command('SET', self.job_key(record['id']), json.dumps(record, ensure_ascii=False), 'EX', '604800')

    def is_cancelled(self, job_id):
        return bool(self.store.command('GET', self.job_key(job_id) + ':cancel'))

    def run_stage_command(self, work_dir, log_path, command, deadline, job_id):
        args = bwrap_args(work_dir, command, self.runtime)
        env = bwrap_env(self.runtime)
        account = pwd.getpwnam(self.run_as) if self.run_as else None

        def child_setup():
            resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024**2, 256 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
            if account and os.getuid() == 0:
                os.setgroups([])
                os.setgid(account.pw_gid)
                os.setuid(account.pw_uid)

        timed_out = False
        cancelled = False
        with log_path.open('wb') as log:
            process = subprocess.Popen(args, cwd=work_dir, stdout=log, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=True, preexec_fn=child_setup)
            try:
                while True:
                    code = process.poll()
                    if code is not None:
                        break
                    self.send_heartbeat()
                    if self.is_cancelled(job_id):
                        cancelled = True
                        os.killpg(process.pid, signal.SIGKILL)
                        code = process.wait()
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGKILL)
                        code = process.wait()
                        break
                    time.sleep(1.0)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return code, timed_out, cancelled

    def process_job(self, job_id):
        raw_record = self.store.command('GET', self.job_key(job_id))
        if not raw_record:
            return None
        record = json.loads(raw_record)
        if record.get('status') not in {'queued', 'running'}:
            return record
        if self.is_cancelled(job_id):
            record.update(status='cancelled', source_url=None, notice='已按请求停止 GPU 任务。')
            self.save_record(record)
            return record
        if time.time() > record.get('deadline', 0):
            record.update(status='expired', source_url=None, notice='GPU 队列任务已超过最长时限。')
            self.save_record(record)
            return record

        source_url = record.get('source_url')
        try:
            archive_bytes = self.fetcher(source_url, record.get('source_bytes'), record.get('source_sha256'))
        except Exception as exc:
            record.update(status='failed', source_url=None,
                          notice='GPU 执行器未能取回源码归档：' + type(exc).__name__,
                          result={'status': 'failed', 'stages': [], 'metrics': [], 'events': [],
                                  'execution_performed': False, 'scientific_validation': False,
                                  'failure_category': 'transient_service'})
            self.save_record(record)
            return record

        plan = record['plan']
        started = time.time()
        deadline = min(time.monotonic() + plan['max_seconds'],
                       time.monotonic() + max(5, record['deadline'] - time.time()))
        report = {'status': 'running', 'started_at': started, 'stages': [], 'metrics': [],
                  'execution_performed': False, 'scientific_validation': False,
                  'hardware': {'cpu_count': self.capacity['cpu_count'], 'gpu': True,
                               'gpu_name': self.capacity.get('gpu_name')},
                  'events': []}

        def event(role, kind, **data):
            report['events'].append({'role': role, 'kind': kind, 'time': time.time(), **data})

        with tempfile.TemporaryDirectory(prefix='articheck-gpu-', dir=self.work_root) as tmp:
            base = Path(tmp)
            work_dir = base / 'artifact'
            results_dir = base / 'results'
            results_dir.mkdir(parents=True, exist_ok=True)
            extract_archive(archive_bytes, work_dir)
            if self.run_as and os.getuid() == 0:
                account = pwd.getpwnam(self.run_as)
                os.chown(base, account.pw_uid, account.pw_gid)
                base.chmod(0o700)
                for parent, dirs, files in os.walk(work_dir):
                    os.chown(parent, account.pw_uid, account.pw_gid)
                    for d in dirs:
                        os.chown(os.path.join(parent, d), account.pw_uid, account.pw_gid)
                    for f in files:
                        os.chown(os.path.join(parent, f), account.pw_uid, account.pw_gid)

            disk = shutil.disk_usage(work_dir)
            report['runtime'] = {'python': platform.python_version(), 'system': platform.system(),
                                 'release': platform.release(), 'architecture': platform.machine(),
                                 'gpu_name': self.capacity.get('gpu_name'),
                                 'disk_total_bytes': disk.total, 'disk_free_before_bytes': disk.free}
            event('planner', 'plan_scheduled', policy='frozen_api_plan', stages=len(plan['stages']), hardware='GPU')
            record.update(status='running', source_url=None,
                          notice='自有 GPU 执行器已接单，正在隔离环境中运行阶段计划。',
                          result=report)
            self.save_record(record)

            all_logs = []
            stage_logs = {}
            cancelled = False
            for stage in plan['stages']:
                row = {k: stage[k] for k in ('id', 'title', 'command', 'file')}
                row['experiment'] = stage.get('experiment', '')
                dependencies = stage.get('depends_on', [report['stages'][-1]['id']] if report['stages'] else [])
                blocked = any(not any(s['id'] == d and s['status'] == 'completed' for s in report['stages']) for d in dependencies)
                if cancelled or self.is_cancelled(job_id):
                    cancelled = True
                    row.update(status='skipped', reason='任务已按请求停止。')
                    report['stages'].append(row)
                    continue
                if blocked or deadline <= time.monotonic():
                    row.update(status='skipped', reason='依赖阶段未完成。' if blocked else '时间预算已用尽。')
                    report['stages'].append(row)
                    continue
                row.update(status='running', started_at=time.time())
                report['stages'].append(row)
                event('experiment_runner', 'stage_started', stage=stage['id'])
                record['result'] = report
                self.save_record(record)

                log_path = results_dir / (stage['id'] + '.log')
                code, timed_out, stage_cancelled = self.run_stage_command(
                    work_dir, log_path, stage['command'], deadline, job_id)
                report['execution_performed'] = True
                with log_path.open('rb') as stream:
                    raw_log = stream.read(24000)
                log_text = raw_log.decode(errors='replace')
                all_logs.append(log_text)
                stage_logs[stage['id']] = log_text
                if stage_cancelled:
                    cancelled = True
                    row.update(status='skipped', exit_code=code, timed_out=False,
                               finished_at=time.time(), output=log_text,
                               output_truncated=log_path.stat().st_size > len(raw_log),
                               reason='任务已按请求停止。')
                else:
                    row.update(status='completed' if code == 0 and not timed_out else 'failed',
                               exit_code=code, timed_out=timed_out, finished_at=time.time(),
                               output=log_text, output_truncated=log_path.stat().st_size > len(raw_log))
                row['child_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
                event('experiment_runner', 'stage_finished', stage=stage['id'], exit_code=code, timed_out=timed_out)
                event('cross_auditor', 'stage_checked', stage=stage['id'], status=row['status'])
                record['result'] = report
                self.save_record(record)

            report['metrics'] = evaluate_metrics(plan, stage_logs, all_logs)
            failed = any(s['status'] == 'failed' for s in report['stages'])
            if cancelled or self.is_cancelled(job_id):
                report['status'] = 'cancelled'
                record['notice'] = 'GPU 执行已停止。'
            elif all(s['status'] == 'completed' for s in report['stages']):
                report['status'] = 'completed'
                record['notice'] = '自有 GPU 阶段计划已执行完毕。'
            else:
                report['status'] = 'failed'
                record['notice'] = '部分 GPU 阶段未通过或受阻，请查看实际日志。'
            report['finished_at'] = time.time()
            report['elapsed_seconds'] = round(report['finished_at'] - started, 3)
            report['runtime']['disk_free_after_bytes'] = shutil.disk_usage(work_dir).free
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            report['runtime']['child_cpu_seconds'] = round(usage.ru_utime + usage.ru_stime, 3)
            failure_logs = '\n'.join(s.get('output', '') for s in report['stages'] if s['status'] == 'failed')
            report['failure_category'] = 'execution_blocked' if failed else None
            report['needs_user'] = failed and bool(re.search(
                r'(file not found|filenotfound|no such file|permission denied|credentials|download|dataset|checkpoint|cuda|out of memory|modulenotfounderror|importerror)',
                failure_logs, re.I))
            report['question'] = 'GPU 隔离环境无外网访问且仅含预装依赖，执行遇到缺失文件或依赖阻碍。能否补充所需数据、权重或代码文件？' if report['needs_user'] else None
            report['acceptance'] = {'process': report['status'] == 'completed', 'paper_conclusion': None,
                                    'notice': '阶段退出码和 stdout 指标仅证明本次 GPU 运行观测；主要结论需核对完整协议与对照。'}
            event('planner', 'stopped', reason=report['status'], policy='frozen_api_plan')
            event('cross_auditor', 'execution_checked', metrics=len(report['metrics']))
            event('reporter', 'report_written', status=report['status'])
            record['status'] = report['status']
            record['result'] = report
            self.save_record(record)
            return record

    def poll_once(self):
        self.send_heartbeat()
        job_id = self.store.command('LPOP', self.prefix + 'queue')
        if not job_id:
            return None
        return self.process_job(job_id)

    def serve_forever(self, poll_interval=2.0):
        self.send_heartbeat(force=True)
        while True:
            try:
                worked = self.poll_once()
                if not worked:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                sys.stderr.write(f'[gpu_worker] error: {type(exc).__name__}: {exc}\n')
                sys.stderr.flush()
                time.sleep(min(10.0, poll_interval * 2))


def main():
    env_file = os.environ.get('ARTICHECK_GPU_ENV_FILE')
    env = dict(os.environ)
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env.setdefault(k.strip(), v.strip())
    worker = GPUWorker(env)
    if '--once' in sys.argv:
        worker.send_heartbeat(force=True)
        worker.poll_once()
    else:
        worker.serve_forever()


if __name__ == '__main__':
    main()
