"""Persistent asynchronous jobs for the loopback workbench; Docker-only execution."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ..schema import dump
from .audit import audit_plan
from .engine import reproduce
from .protocol import load_plan


def now():return datetime.now(timezone.utc).isoformat()


class ReproductionService:
    def __init__(self, workspace, storage):
        self.workspace=Path(workspace).resolve();self.storage=Path(storage).resolve()
        self.storage.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='reproduction')
        self.jobs={};self.controls={};self.tokens={};self.cached_reports={}
        for path in self.storage.glob('*/job.json'):
            row=json.loads(path.read_text())
            if row['status'] not in ('completed','failed','cancelled'):
                row.update(status='failed',error='Runtime restarted before completion',finished_at=now());dump(path,row)
            self.jobs[row['id']]=row

    def path(self, value):
        if not isinstance(value,str):raise ValueError('plan_path must be text')
        path=(self.workspace/value).resolve()
        if not path.is_relative_to(self.workspace) or not path.is_file():
            raise ValueError('plan_path must identify a reproduction plan inside the workspace')
        load_plan(path,self.workspace)
        return path

    def audit(self, body):
        path=self.path(body.get('plan_path',''))
        imported=body.get('imported_snapshot')
        result=audit_plan(path,workspace=self.workspace,imported=imported)
        expected_paper=body.get('paper_sha256')
        plan,_=load_plan(path,self.workspace)
        if expected_paper and plan['paper'].get('sha256')!=expected_paper:
            result['checks'].append({'dimension':'scope','code':'project_paper_binding','status':'fail','detail':'Execution-plan paper digest differs from the imported project PDF','evidence':{}})
            result['blocking_failures']+=1
            result['dimensions']['scope']['fail']+=1
        if body.get('project_id') and not expected_paper:
            result['checks'].append({'dimension':'scope','code':'project_paper_binding','status':'unknown','detail':'Current project has no imported PDF content digest; cannot bind this execution plan to it','evidence':{}})
            result['dimensions']['scope']['unknown']+=1
        with self.lock:
            self.tokens={k:v for k,v in self.tokens.items() if time.monotonic()-v['created'] < 900 or v.get('job_id')}
            if len(self.tokens)>=1000:raise ValueError('Audit token limit reached')
            token=uuid.uuid4().hex
            self.tokens[token]={'path':path,'sha':result['plan_sha256'],'imported':imported,'result':result,'created':time.monotonic(),'project_id':body.get('project_id'),'paper_bound':bool(expected_paper)}
        return {**result,'audit_token':token,'expires_in_seconds':900}

    def start(self, body):
        if body.get('sandbox','docker')!='docker':raise ValueError('Workbench reproduction jobs only accept Docker; no local fallback')
        with self.lock:
            token=self.tokens.get(body.get('audit_token'))
            if not token:raise ValueError('Run material audit before starting an experiment')
            if token.get('job_id'):return self.get(token['job_id'])
            if time.monotonic()-token['created']>900:raise ValueError('Material audit expired; audit again')
            if hashlib.sha256(token['path'].read_bytes()).hexdigest()!=token['sha']:
                raise ValueError('Plan changed since material audit; audit again')
            if token['project_id'] and not token['paper_bound']:
                raise ValueError('Import the project PDF and bind its actual content digest before execution')
            failures=[c for c in token['result']['checks'] if c['status']=='fail' and (c['dimension'] in ('code','data','settings','environment') or c['code']=='project_paper_binding' or c['dimension']=='scope' and c['code'].startswith('file:'))]
            if failures:raise ValueError('Material contradictions must be resolved before execution')
            if sum(j['status'] in ('queued','running') for j in self.jobs.values())>=20:
                raise ValueError('Pending reproduction job limit reached')
            run_id=uuid.uuid4().hex
            row={'id':run_id,'status':'queued','created_at':now(),'started_at':None,'finished_at':None,'error':None,
                 'plan_sha256':token['sha'],'project_id':token['project_id'],'sandbox':'docker'}
            self.jobs[run_id]=row;self.controls[run_id]=threading.Event();token['job_id']=run_id
            dump(self.storage/run_id/'job.json',row)
            self.pool.submit(self.worker,run_id,dict(token))
            return self.get(run_id)

    def worker(self,run_id,token):
        import asyncio
        control=self.controls[run_id]
        with self.lock:
            row=self.jobs[run_id]
            row.update(status='running',started_at=now());dump(self.storage/run_id/'job.json',row)
        try:
            if control.is_set():raise InterruptedError('Cancelled before execution')
            if hashlib.sha256(token['path'].read_bytes()).hexdigest()!=token['sha']:
                raise ValueError('Queued plan changed; audit and submit again')
            result=asyncio.run(reproduce(token['path'],self.storage/run_id/'run',workspace=self.workspace,
                                        cancel=control,imported=token['imported']))
            with self.lock:
                row['status']=result['status'];row['error']='; '.join(result['errors']) or None
        except Exception as error:
            with self.lock:row.update(status='failed',error=type(error).__name__+': '+str(error))
        finally:
            with self.lock:
                if control.is_set():row['status']='cancelled'
                row['finished_at']=now();dump(self.storage/run_id/'job.json',row);self.controls.pop(run_id,None)

    def report(self,run_id):
        if run_id not in self.jobs:raise ValueError('Reproduction job not found')
        path=self.storage/run_id/'run/report.json'
        if path.is_file():
            try:self.cached_reports[run_id]=json.loads(path.read_text())
            except ValueError:pass  # Retain last complete snapshot during an in-progress write.
        return self.cached_reports.get(run_id)

    def get(self,run_id):
        with self.lock:
            if run_id not in self.jobs:raise ValueError('Reproduction job not found')
            row=dict(self.jobs[run_id]);report=self.report(run_id)
            rows=report.get('runs',[]) if report else []
            return {**row,'progress':{'completed_runs':sum(r['status']=='completed' for r in rows),
                                     'failed_runs':sum(r['status']=='failed' for r in rows),'recorded_runs':len(rows)},
                    'report_ready':report is not None,'report_url':'/api/reproduction/runs/'+run_id+'/report'}

    def cancel(self,run_id):
        with self.lock:
            if run_id not in self.controls:raise ValueError('No active reproduction job to cancel')
            self.controls[run_id].set()
            return self.get(run_id)

    def close(self):
        for control in list(self.controls.values()):control.set()
        self.pool.shutdown(wait=True)
