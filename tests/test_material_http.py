"""Real loopback binary import contract; optional full Docker success path."""
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from articheck.workbench import Workbench, handler_for, ROOT
from articheck.reproduction.protocol import fingerprint
from test_materials import make_zip
from test_reproduction import fixture, write


def text_pdf(text):
    # Self-owned synthetic test document, not a third-party paper.
    escaped=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    stream=('BT /F1 10 Tf 30 700 Td ('+escaped+') Tj ET').encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
      b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
      b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    raw=b'%PDF-1.4\n';offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(raw));raw+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref=len(raw);raw+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{v:010d} 00000 n \n'.encode() for v in offsets)
    return raw+b'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'


class MaterialHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.path,self.plan,self.repo=fixture(self.root,complete=True)
        self.pdf=text_pdf((self.root/'paper.txt').read_text())
        self.plan['paper']['sha256']=hashlib.sha256(self.pdf).hexdigest()
        self.app=Workbench(ROOT,self.root/'state');self.app.workspace=self.root
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app,ROOT/'web/dist'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.tmp.cleanup()
    def request(self,path,body=None,raw=None,headers=None):
        h={'X-ArtiCheck-Client':'workbench','Content-Type':'application/octet-stream' if raw is not None else 'application/json',**(headers or {})}
        data=raw if raw is not None else json.dumps(body).encode() if body is not None else None
        with urllib.request.urlopen(urllib.request.Request(self.origin+path,data=data,headers=h),timeout=25) as response:
            return json.load(response)
    def import_bundle(self):
        archive=make_zip([('package/'+p.name,p.read_bytes()) for p in self.repo.iterdir()])
        expected={'project_id':'http-paper','paper_sha256':hashlib.sha256(self.pdf).hexdigest(),'archive_sha256':hashlib.sha256(archive).hexdigest()}
        bundle=self.request('/api/materials',expected)
        for kind,raw in [('paper',self.pdf),('archive',archive),('plan',json.dumps(self.plan).encode())]:
            bundle=self.request('/api/materials/'+bundle['id']+'/'+kind,raw=raw)
        receipt=self.request('/api/materials/'+bundle['id']+'/bind',{'code_root':'package'})
        audit=self.request('/api/reproduction/audit',{**expected,'plan_path':receipt['plan_path'],'material_bundle_id':receipt['id']})
        return receipt,audit,expected
    def test_preview_matches_frozen_plan_and_reviews_append_without_changing_report(self):
        receipt,audit,expected=self.import_bundle()
        preview=audit['execution_preview']
        self.assertEqual(preview['plan_sha256'],audit['plan_sha256'])
        self.assertEqual(preview['resources'],self.plan['resources'])
        self.assertEqual(preview['experiments'][0]['stages'],self.plan['experiments'][0]['stages'])
        job_id='review-test';digest=audit['plan_sha256']
        self.app.reproduction.jobs[job_id]={'id':job_id,'status':'completed','plan_sha256':digest,'project_id':'http-paper'}
        report={'run_id':'engine-id','plan_sha256':digest,'source_manifest_sha256':'source','audit':{'checks':[{'status':'fail'}]},'runs':[],'experiments':[],'levels':{'conclusion':False}}
        self.app.reproduction.cached_reports[job_id]=report
        original=json.dumps(report,sort_keys=True)
        body={'plan_sha256':digest,'target_id':'check:0','decision':'disagree','reviewer':'test-reviewer','reason':'PDF page 1; verified source reference'}
        first=self.request('/api/reproduction/runs/'+job_id+'/reviews',body)
        self.request('/api/reproduction/runs/'+job_id+'/reviews',{**body,'decision':'needs_evidence'})
        rows=self.request('/api/reproduction/runs/'+job_id+'/reviews')['items']
        self.assertEqual(len(rows),2);self.assertEqual(first['source_manifest_sha256'],'source')
        self.assertEqual(original,json.dumps(report,sort_keys=True))
        for change in ({'target_id':'check:999'},{'plan_sha256':'wrong'},{'reviewer':' '},{'decision':'pass'}):
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/reproduction/runs/'+job_id+'/reviews',{**body,**change})
        self.app.reproduction.jobs[job_id]['status']='running'
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/reproduction/runs/'+job_id+'/reviews',body)

    def test_pdf_zip_plan_receipt_and_project_bound_audit(self):
        receipt,audit,expected=self.import_bundle()
        self.assertEqual(self.request('/api/materials/'+receipt['id'])['status'],'bound')
        self.assertEqual(receipt['files']['paper']['sha256'],expected['paper_sha256'])
        self.assertEqual(audit['blocking_failures'],0)
        self.assertEqual(next(c for c in audit['checks'] if c['code']=='project_archive_binding')['status'],'pass')
        # A report cannot be attached to another project, even with identical bytes.
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/reproduction/audit',{**expected,'project_id':'other','plan_path':receipt['plan_path'],'material_bundle_id':receipt['id']})
    def test_unbound_or_wrong_zip_blocks_execution(self):
        receipt,audit,expected=self.import_bundle()
        for archive in [expected['archive_sha256'],'0'*64]:
            result=self.request('/api/reproduction/audit',{**expected,'archive_sha256':archive,'plan_path':receipt['plan_path']})
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/reproduction/runs',{'audit_token':result['audit_token']})
        result=self.request('/api/reproduction/audit',{**expected,'archive_sha256':'0'*64,'plan_path':receipt['plan_path'],'material_bundle_id':receipt['id']})
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/reproduction/runs',{'audit_token':result['audit_token']})
    def test_scope_review_invalidates_old_audit_and_preserves_immutable_input(self):
        receipt,audit,expected=self.import_bundle()
        updated=self.request('/api/materials/'+receipt['id']+'/review',{'reviewer':'http-reviewer','review':receipt['review'],'parent_plan_sha256':receipt['active_plan_sha256']})
        self.assertNotEqual(receipt['plan_path'],updated['plan_path'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/reproduction/runs',{'audit_token':audit['audit_token']})
        fresh=self.request('/api/reproduction/audit',{**expected,'plan_path':updated['plan_path'],'material_bundle_id':updated['id']})
        self.assertNotEqual(audit['plan_sha256'],fresh['plan_sha256']);self.assertEqual(fresh['blocking_failures'],0)
    def test_binary_upload_has_same_origin_guard_and_size_limit(self):
        bundle=self.request('/api/materials',{'project_id':'x','paper_sha256':hashlib.sha256(self.pdf).hexdigest(),'archive_sha256':'0'*64})
        for headers in [{'Origin':'https://untrusted.example'},{'X-ArtiCheck-Client':''}]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/materials/'+bundle['id']+'/paper',raw=self.pdf,headers=headers)
            self.assertEqual(error.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/materials/'+bundle['id']+'/plan',raw=b'x',headers={'Content-Length':'2000001'})
        self.assertEqual(error.exception.code,413)
        self.assertEqual(self.request('/api/materials/'+bundle['id'])['files'],{})
    def test_malformed_nested_inputs_return_json_error(self):
        for body in [{'project_id':[]},{'project_id':'x','paper_sha256':[],'archive_sha256':[]}]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/materials',body)
            self.assertIn('message',json.load(error.exception)['error'])

    @unittest.skipUnless(os.environ.get('ARTICHECK_TEST_DOCKER')=='1','Explicit Docker integration run only')
    def test_import_bind_start_poll_download_positive_matrix(self):
        dockerfile=write(self.repo/'Dockerfile','FROM '+os.environ.get('ARTICHECK_TEST_BASE_IMAGE','python:3.11-slim')+'\n')
        self.plan['environment']={'dockerfile':'Dockerfile','dockerfile_sha256':fingerprint(dockerfile)['sha256'],'expected':{'python':'3.11','packages':{}},
            'verify':[['python3','-c','import sys; assert sys.version_info[:2] == (3,11)']]}
        self.plan['resources']['max_seconds']=240
        for stage in self.plan['experiments'][0]['stages']:stage['argv'][0]='python3'
        receipt,audit,expected=self.import_bundle()
        self.assertEqual(audit['blocking_failures'],0,audit['checks'])
        job=self.request('/api/reproduction/runs',{'audit_token':audit['audit_token']})
        self.assertEqual(self.request('/api/reproduction/runs',{'audit_token':audit['audit_token']})['id'],job['id'])
        deadline=time.monotonic()+260
        while time.monotonic()<deadline:
            state=self.request('/api/reproduction/runs/'+job['id'])
            if state['status'] in ('completed','failed','cancelled'):break
            time.sleep(.3)
        report=self.request('/api/reproduction/runs/'+job['id']+'/report')
        self.assertEqual(state['status'],'completed',report['errors'])
        self.assertEqual(len(report['runs']),15)
        self.assertTrue(all(report['levels'].values()),report['level_requirements'])
        self.assertEqual(report['audit']['imported_material']['archive_sha256'],expected['archive_sha256'])
