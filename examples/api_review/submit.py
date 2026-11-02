"""Run from repository root against a configured review service."""
import argparse
import json
from pathlib import Path
from articheck.review_client import ReviewAPIClient

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:8790')
parser.add_argument('--paper',type=Path,required=True)
parser.add_argument('--code',type=Path,required=True)
args=parser.parse_args()
client=ReviewAPIClient(args.base_url)
job=client.submit(args.paper,args.code,'核对论文材料和代码线索，给出需要人工复查的事项')
print('job_id:',job['id'],flush=True)
job=client.wait(job['id'])
if job['status']!='completed':raise SystemExit(json.dumps(job,ensure_ascii=False))
print(json.dumps(client.report(job['id']),ensure_ascii=False,indent=2))
