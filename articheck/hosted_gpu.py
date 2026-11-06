"""Private pull-worker GPU dispatch; cloud functions never need access to the LAN.

Only short-lived read URLs enter the private queue. Raw archives, SSH keys and
provider credentials are not exposed to the browser or artifact processes.
"""
import json
import re
import time
import uuid
from .review_api import ReviewError,decode_material,MAX_CODE_BYTES
from .hosted_sandbox import E2BExecutor

class OwnedGPUExecutor:
    def __init__(self,env,store):
        self.env,self.store=env,store
        self.prefix='articheck:gpu:'+env.get('ARTICHECK_BUDGET_ID','')+':'
    def heartbeat(self):
        if self.env.get('ARTICHECK_GPU_ENABLED')!='1':return None
        raw=self.store.command('GET',self.prefix+'heartbeat')
        value=json.loads(raw) if raw else None
        return value if value and time.time()-value.get('time',0)<100 else None
    @property
    def configured(self):return bool(self.heartbeat() and self.env.get('E2B_API_KEY'))
    @property
    def capacity(self):
        h=self.heartbeat()
        return {**h['capacity'],'provider':'owned_gpu','single_file_limit_mib':128} if h else None
    def key(self,job):
        if not isinstance(job,str) or not re.fullmatch(r'[a-f0-9]{32}',job):raise ReviewError('invalid_gpu_job','GPU 任务编号无效。')
        return self.prefix+'job:'+job
    def launch(self,assessment,body):
        from e2b import Sandbox
        h=self.heartbeat()
        if not h:raise ReviewError('gpu_unavailable','自有 GPU 执行服务暂未就绪，未改用 CPU 冒充执行。',503)
        raw,identity=decode_material(body.get('code'),'.zip',MAX_CODE_BYTES)
        if identity['sha256']!=assessment['materials']['code']:raise ReviewError('material_changed','代码已变化，请重新审查。',409)
        job=uuid.uuid4().hex;plan={**assessment['review']['plan'],'metrics':assessment['review']['metrics']}
        stage_lifetime=min(max(int(plan.get('max_seconds') or 300)+90,300),600)
        job_lifetime=max(int(plan.get('max_seconds') or 0)+90,86400);stage=None
        try:
            stage=Sandbox.create(api_key=self.env['E2B_API_KEY'],secure=True,timeout=stage_lifetime,retries=0,
                api_headers={'Idempotency-Key':'articheck-gpu-source-'+assessment['id']+'-'+assessment['execution']['attempt_id']},
                metadata={'project':'articheck','purpose':'gpu-source-transfer'},
                network={'allow_public_traffic':False,'deny_out':['0.0.0.0/0']})
            stage.files.write('/home/user/gpu-source.zip',raw,user='root')
            url=stage.download_url('/home/user/gpu-source.zip',user='root',use_signature_expiration=min(300,stage_lifetime))
            record={'id':job,'status':'queued','created_at':time.time(),'deadline':time.time()+job_lifetime,
                    'plan':plan,'source_url':url,'source_bytes':len(raw),'source_sha256':identity['sha256'],
                    'staging_id':stage.sandbox_id,'environment':h['capacity'],'result':None}
            script="if redis.call('EXISTS',KEYS[1])==1 then return 0 end; redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[3]); redis.call('RPUSH',KEYS[2],ARGV[2]); return 1"
            if self.store.command('EVAL',script,'2',self.key(job),self.prefix+'queue',json.dumps(record),job,'604800')!=1:raise ValueError('Queue conflict')
        except Exception:
            if stage:
                try:stage.kill()
                except Exception:pass
            raise
        return {'provider':'owned_gpu','gpu_job_id':job,'status':'queued','started_at':time.time(),
                'deadline':record['deadline'],'plan_sha256':assessment['review']['plan_sha256'],
                'environment':h['capacity'],'execution_performed':False,'scientific_validation':False,
                'stages':[],'metrics':[],'notice':'已进入自有 GPU 队列，执行器通常在 30 秒内接单。'}
    def record(self,execution):
        raw=self.store.command('GET',self.key(execution.get('gpu_job_id')))
        if not raw:raise ReviewError('gpu_job_missing','GPU 执行记录暂不可用，请稍后刷新。',503)
        return json.loads(raw)
    def poll(self,execution):
        record=self.record(execution)
        result=record.get('result') or {}
        state=record['status']
        if time.time()>record['deadline'] and state not in {'completed','failed','cancelled'}:
            self.store.command('SET',self.key(record['id'])+':cancel','1','EX','900')
            state='expired'
        if state!='queued':self.cleanup(record)
        # Whitelist process-generated fields; source URLs remain in the private queue.
        fields=('stages','metrics','events','runtime','elapsed_seconds','execution_performed','needs_user','question','acceptance','failure_category')
        return {**execution,**{key:result[key] for key in fields if key in result},'status':state,
                'scientific_validation':False,'notice':record.get('notice') or execution.get('notice','')}
    def stop(self,execution):
        record=self.record(execution)
        if record['status'] not in {'completed','failed','cancelled'}:
            self.store.command('SET',self.key(record['id'])+':cancel','1','EX','900')
            return False  # Only the worker can acknowledge process termination.
        self.cleanup(record);return True
    def cleanup(self,record):
        if record.get('staging_id'):
            from e2b import Sandbox
            try:Sandbox.kill(record['staging_id'],api_key=self.env['E2B_API_KEY'])
            except Exception:pass  # The hard lifetime remains the final bound.

class HybridExecutor:
    def __init__(self,env,store):self.cpu=E2BExecutor(env);self.gpu=OwnedGPUExecutor(env,store)
    @property
    def configured(self):return self.cpu.configured or self.gpu.configured
    @property
    def capacity(self):return self.gpu.capacity or self.cpu.capacity
    def launch(self,assessment,body):
        if assessment['review']['plan'].get('hardware')=='GPU':return self.gpu.launch(assessment,body)
        return self.cpu.launch(assessment,body)
    def poll(self,execution):return (self.gpu if execution.get('provider')=='owned_gpu' else self.cpu).poll(execution)
    def stop(self,execution):
        backend=self.gpu if execution.get('provider')=='owned_gpu' else self.cpu
        result=backend.stop(execution)
        return True if backend is self.cpu else result
