"""Headless client for the versioned review API; no model key in browser code."""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from .review_api import endpoint_url

class ReviewAPIClient:
    def __init__(self,base_url,token=None,timeout=60):
        self.base_url=endpoint_url(base_url);self.token=token;self.timeout=timeout
    def request(self,path,body=None):
        headers={'Accept':'application/json','X-ArtiCheck-Client':'review-api'}
        if self.token:headers['Authorization']='Bearer '+self.token
        if body is not None:headers['Content-Type']='application/json'
        req=urllib.request.Request(self.base_url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as response:raw=response.read(4_000_001)
        except urllib.error.HTTPError as error:
            try:detail=json.loads(error.read(10000)).get('error',{})
            except (ValueError,AttributeError):detail={}
            raise RuntimeError(str(detail.get('code',error.code))+': '+str(detail.get('message','Review API request failed'))) from None
        if len(raw)>4_000_000:raise ValueError('Review API response exceeds 4 MB')
        return json.loads(raw)
    def health(self):return self.request('/v1/health')
    def submit(self,paper,code,scope=''):
        body={'scope':scope}
        for key,path,limit in [('paper',Path(paper),20*1024**2),('code',Path(code),100*1024**2)]:
            if path.stat().st_size>limit:raise ValueError(key+' exceeds material limit')
            body[key]={'name':path.name,'content_base64':base64.b64encode(path.read_bytes()).decode()}
        return self.request('/v1/reviews',body)
    def get(self,job_id):return self.request('/v1/reviews/'+self.identifier(job_id))
    def report(self,job_id):return self.request('/v1/reviews/'+self.identifier(job_id)+'/report')
    def cancel(self,job_id):return self.request('/v1/reviews/'+self.identifier(job_id)+'/cancel',{})
    @staticmethod
    def identifier(value):
        if not isinstance(value,str) or not value or len(value)>128 or not all(c.isalnum() or c in '_-' for c in value):raise ValueError('Invalid job identifier')
        return value
    def wait(self,job_id,timeout=180,interval=1):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            job=self.get(job_id)
            if job['status'] in {'completed','failed','cancelled'}:return job
            time.sleep(interval)
        raise TimeoutError('Wait timed out; server job may continue. Query the returned job ID.')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base-url',default='http://127.0.0.1:8790');parser.add_argument('--paper',type=Path);parser.add_argument('--code',type=Path);parser.add_argument('--scope',default='');parser.add_argument('--output',type=Path);parser.add_argument('--health',action='store_true');parser.add_argument('--job-id');parser.add_argument('--wait-seconds',type=int,default=180)
    args=parser.parse_args();client=ReviewAPIClient(args.base_url,os.environ.get('ARTICHECK_REVIEW_TOKEN'))
    if args.health:print(json.dumps(client.health(),ensure_ascii=False,indent=2));return
    if args.job_id:job=client.get(args.job_id)
    else:
        if not args.paper or not args.code:parser.error('--paper and --code are required to submit')
        job=client.submit(args.paper,args.code,args.scope)
        print(json.dumps({'job_id':job['id'],'status':job['status']},ensure_ascii=False),flush=True)
    job=client.wait(job['id'],timeout=args.wait_seconds)
    if job['status']!='completed':raise SystemExit(json.dumps(job,ensure_ascii=False))
    report=client.report(job['id']);raw=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(raw);print(str(args.output))
    else:print(raw)

if __name__=='__main__':main()
