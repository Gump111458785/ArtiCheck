"""Short-lived direct uploads keep large material bytes out of cloud HTTP bodies.

Only path-bound write URLs reach the browser. Downloads use server credentials,
verify declared size/SHA256, and never forward provider credentials to an artifact.
"""
import hashlib
import re
import time
import urllib.request
import uuid

from .review_api import ReviewError, MAX_CODE_BYTES

LIFETIME = 900
LIMITS = {'paper': ('.pdf',20*1024**2), 'code': ('.zip',MAX_CODE_BYTES)}


class HostedUploads:
    def __init__(self,env,store):
        self.key=env.get('E2B_API_KEY','');self.store=store

    def create(self,owner,payload):
        files=payload.get('files');job=payload.get('request_id')
        if not isinstance(job,str) or not re.fullmatch(r'[a-f0-9]{32}',job):
            raise ReviewError('invalid_request_id','上传编号无效。')
        if not isinstance(files,list) or not 1<=len(files)<=2:
            raise ReviewError('invalid_upload','请选择论文 PDF 或代码 ZIP。')
        checked={}
        for item in files:
            if not isinstance(item,dict) or not isinstance(item.get('kind'),str) or item['kind'] not in LIMITS or item['kind'] in checked:
                raise ReviewError('invalid_upload','上传材料类型无效。')
            kind=item['kind'];suffix,limit=LIMITS[kind]
            name=item.get('name');size=item.get('bytes');sha=item.get('sha256')
            if not isinstance(name,str) or not name.lower().endswith(suffix) or len(name)>255 or type(size) is not int or not 1<=size<=limit or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):
                raise ReviewError('material_size','代码 ZIP 最大 100 MB，论文 PDF 最大 20 MB；请检查材料大小与格式。',413)
            checked[kind]={'name':name,'bytes':size,'sha256':sha}
        if not self.key:raise ReviewError('sandbox_not_configured','大文件传输服务尚未配置。',503)
        record={'id':job,'type':'material_upload','status':'starting','files':checked,'deadline':time.time()+LIFETIME}
        if not self.store.claim(owner,record):
            old=self.store.get(owner,job)
            if old.get('type')=='material_upload' and old.get('status')=='closed':
                raise ReviewError('upload_expired','本次传输已关闭，请重新提交材料。',410)
            if old.get('type')!='material_upload' or old.get('files')!=checked:
                raise ReviewError('request_changed','同一上传编号不能替换文件。',409)
            return self.delivery(old)
        from e2b import Sandbox
        sandbox=None
        starting = {**record}
        try:
            record['reservation']=self.store.reserve_compute()
            if not self.store.replace(owner,starting,record):
                raise ReviewError('upload_expired','本次传输已关闭。',410)
            starting = {**record}
            sandbox=Sandbox.create(api_key=self.key,secure=True,timeout=LIFETIME,retries=0,
                api_headers={'Idempotency-Key':'articheck-upload-'+job},
                metadata={'project':'articheck','purpose':'material-upload'},
                network={'allow_public_traffic':False,'deny_out':['0.0.0.0/0']})
            record.update(status='ready',sandbox_id=sandbox.sandbox_id)
            if not self.store.replace(owner,starting,record):
                raise ReviewError('upload_expired','本次传输已关闭。',410)
            starting = {**record}
            return self.delivery(record,sandbox)
        except Exception as exc:
            if sandbox:
                try:sandbox.kill()
                except Exception:pass
            record['status']='failed'
            self.store.replace(owner,starting,record)
            if isinstance(exc,ReviewError):raise
            raise ReviewError('upload_start_failed','临时传输通道创建失败，请重新提交上传；不会自动重复创建。',502) from exc

    def connect(self,record):
        if record.get('type')!='material_upload' or record.get('status')!='ready' or record['deadline']<=time.time():
            raise ReviewError('upload_expired','大文件传输通道已过期，请重新上传材料。',410)
        from e2b import Sandbox
        try:return Sandbox.connect(record['sandbox_id'],api_key=self.key,timeout=max(1,int(record['deadline']-time.time())))
        except Exception as exc:raise ReviewError('upload_expired','大文件传输通道暂不可用，请重新上传材料。',410) from exc

    def delivery(self,record,sandbox=None):
        if record.get('status')=='starting' and record['deadline']>time.time():
            raise ReviewError('upload_starting','传输通道正在创建，请稍后重新提交；不会重复创建实例。',409)
        sandbox=sandbox or self.connect(record)
        remaining=max(1,int(record['deadline']-time.time()))
        return {'id':record['id'],'expires_at':record['deadline'],'reserved_attempt':record['reservation'],
            'files':{kind:{**item,'upload_url':sandbox.upload_url('/home/user/articheck-stage-'+kind+LIMITS[kind][0],user='root',use_signature_expiration=remaining),
                          'material':{'name':item['name'],'upload_id':record['id'],'kind':kind}}
                     for kind,item in record['files'].items()}}

    def resolve(self,owner,material,kind):
        job=material.get('upload_id')
        if not isinstance(job,str) or not re.fullmatch(r'[a-f0-9]{32}',job):
            raise ReviewError('invalid_upload','上传材料引用无效。')
        record=self.store.get(owner,job)
        if record.get('type')!='material_upload' or kind not in record.get('files',{}) or material.get('kind')!=kind:
            raise ReviewError('invalid_upload','上传材料引用无效。',409)
        sandbox=self.connect(record);item=record['files'][kind]
        url=sandbox.download_url('/home/user/articheck-stage-'+kind+LIMITS[kind][0],user='root',use_signature_expiration=90)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise ValueError('Redirect disabled')
        try:
            with urllib.request.build_opener(NoRedirect()).open(url,timeout=60) as response:
                if int(response.headers.get('Content-Length','0'))>item['bytes']:raise ValueError('Size changed')
                raw=response.read(item['bytes']+1)
        except Exception as exc:
            raise ReviewError('upload_unavailable','未能读取完整上传材料，请重新上传。',422) from exc
        if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ReviewError('material_changed','上传材料大小或指纹不符，请重新上传。',409)
        return {'name':item['name'],'_raw_bytes':raw}

    def cancel(self,owner,job):
        for _ in range(6):
            try:
                record=self.store.get(owner,job)
            except ReviewError as exc:
                if exc.code!='not_found':
                    raise
                if self.store.claim(owner,{'id':job,'type':'material_upload','status':'closed'}):
                    return {'id':job,'status':'closed'}
                continue
            if record.get('type')!='material_upload':
                raise ReviewError('not_found','上传记录不存在。',404)
            if record.get('status')=='closed':
                return {'id':job,'status':'closed'}
            if record.get('status')=='ready':
                from e2b import Sandbox
                try:
                    Sandbox.kill(record['sandbox_id'],api_key=self.key)
                except Exception as exc:
                    if record['deadline']>time.time():
                        raise ReviewError('upload_cleanup_failed','未能确认临时通道关闭，到期后自动回收。',502) from exc
            if self.store.replace(owner,record,{**record,'status':'closed'}):
                return {'id':job,'status':'closed'}
        raise ReviewError('upload_cleanup_failed','上传状态正在更新，请重试关闭。',409)
