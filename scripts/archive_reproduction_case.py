"""Archive our public-case report with an exact original digest and CI provenance."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--workflow-url',required=True);parser.add_argument('--commit-sha',required=True)
    args=parser.parse_args();raw=args.input.read_bytes();report=json.loads(raw)
    if report.get('format')!='articheck-reproduction-report-v1' or report.get('status')!='completed':raise ValueError('Only completed reports are archived as public examples')
    report.pop('host',None) # Client host inventory is not needed in the teaching archive.
    report['provenance']={'workflow_url':args.workflow_url,'commit_sha':args.commit_sha,'original_report_sha256':hashlib.sha256(raw).hexdigest(),
        'scope':'LIBLINEAR Section 3.1 reconstruction; new seeded splits and added controls; Figure 1 and rcv1 unverified'}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'archived_bytes':args.output.stat().st_size,'original_report_sha256':report['provenance']['original_report_sha256']}))

if __name__=='__main__':main()
