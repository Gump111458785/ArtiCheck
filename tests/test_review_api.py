import base64
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from articheck.review_api import ReviewService,ModelReviewer,ReviewError,prepare_context,validate_model_review,handler_for,DIMENSIONS,endpoint_url
from articheck.review_client import ReviewAPIClient
ROOT=Path(__file__).resolve().parents[1]
def payload():
    return {k:{'name':f,'content_base64':base64.b64encode((ROOT/'web/dist/samples'/f).read_bytes()).decode()} for k,f in [('paper','articheck-method-note.pdf'),('code','toy-artifact.zip')]}
def answer():
    return {'summary':'材料静态审阅完成，仍需实际执行。','criteria':[{'dimension':d,'status':'needs_review','note':'需要核对实际证据','page':1,'file':None} for d in DIMENSIONS],'findings':[{'title':'核对指标平均方式','detail':'模型静态建议','suggestion':'运行独立指标核对','page':1,'file':'toy-artifact/probe.py'}]}
class FakeProvider(BaseHTTPRequestHandler):
    calls=0
    def log_message(self,*a):pass
    def do_POST(self):
        assert self.path=='/v1/chat/completions'
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert body['model']=='local-fixture' and body['max_tokens']==3000
        type(self).calls+=1
        raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer(),ensure_ascii=False)}}],'usage':{'prompt_tokens':100,'completion_tokens':200}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
class ReviewAPITests(unittest.TestCase):
    def test_no_provider_cannot_create_fake_job_or_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=ReviewService(tmp)
            try:
                with self.assertRaises(ReviewError) as cm:service.submit(payload())
                self.assertEqual(cm.exception.status,503);self.assertEqual(service.jobs,{})
            finally:service.close()
    def test_materials_are_parsed_with_actual_fingerprints_and_bounded_context(self):
        c,_=prepare_context(payload())
        self.assertEqual(c['paper_pages'],2);self.assertEqual(len(c['files']),3);self.assertIn('toy-artifact/probe.py',c['files']);self.assertEqual(len(c['paper']['sha256']),64)
    def test_zip_traversal_symlinks_and_duplicates_are_rejected(self):
        for name,symlink in [('../secret.py',False),('link.py',True)]:
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:
                info=zipfile.ZipInfo(name)
                if symlink:info.external_attr=0o120777<<16
                z.writestr(info,'secret')
            body=payload();body['code']['content_base64']=base64.b64encode(b.getvalue()).decode()
            with self.assertRaises(ReviewError):prepare_context(body)
    def test_invalid_model_response_cannot_assert_execution_acceptance(self):
        c={'code_excerpts':[{'file':'actual.py'}],'paper_excerpts':[{'page':1}]}
        r=answer();r['criteria'][0]['status']='pass'
        with self.assertRaises(ReviewError):validate_model_review(r,c)
        r=answer();r['findings'][0]['file']='invented.py'
        with self.assertRaises(ReviewError):validate_model_review(r,c)
        r=answer();r['findings'][0]['file']=None;r['findings'][0]['page']=99
        with self.assertRaises(ReviewError):validate_model_review(r,c)
    def test_model_configuration_rejects_embedded_credentials_or_unsafe_schemes(self):
        for url in ['file:///tmp/model','http://remote.example/v1','https://secret@example.com/v1','https://example.com/v1?key=x']:
            with self.assertRaises(ValueError):endpoint_url(url)
        self.assertEqual(endpoint_url('http://127.0.0.1:8000/v1'),'http://127.0.0.1:8000/v1')
    def test_restart_preserves_failed_identity_instead_of_completing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'abc';folder.mkdir();(folder/'job.json').write_text(json.dumps({'id':'abc','status':'running','report_ready':False}))
            s=ReviewService(tmp)
            try:self.assertEqual(s.get('abc')['status'],'failed');self.assertEqual(s.get('abc')['error']['code'],'service_restarted')
            finally:s.close()
    def test_cancel_ignores_a_late_model_response(self):
        entered=threading.Event();release=threading.Event()
        class Reviewer:
            configured=True
            def review(self,*a):entered.set();release.wait(4);return {'review':answer()}
        with tempfile.TemporaryDirectory() as tmp,patch('articheck.review_api.prepare_context',return_value=({'paper':{},'code':{},'coverage':{}},'')):
            s=ReviewService(tmp,Reviewer())
            try:
                job=s.submit({});self.assertTrue(entered.wait(2));s.cancel(job['id']);release.set();s.close();self.assertEqual(s.get(job['id'])['status'],'cancelled');self.assertFalse(s.get(job['id'])['report_ready']);self.assertFalse((Path(tmp)/job['id']/'report.json').exists())
            finally:release.set();s.close()
    def test_http_and_model_api_end_to_end_without_paid_provider(self):
        provider=ThreadingHTTPServer(('127.0.0.1',0),FakeProvider);thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'ARTICHECK_API_KEY':'fixture-key-not-real'}):
            model=ModelReviewer(f'http://127.0.0.1:{provider.server_port}/v1','local-fixture');service=ReviewService(tmp,model)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(service,ROOT/'web/dist'));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            client=ReviewAPIClient(f'http://127.0.0.1:{server.server_port}')
            try:
                self.assertTrue(client.health()['configured'])
                job=client.submit(ROOT/'web/dist/samples/articheck-method-note.pdf',ROOT/'web/dist/samples/toy-artifact.zip')
                finished=client.wait(job['id'],timeout=10,interval=.02);self.assertEqual(finished['status'],'completed',finished)
                r=client.report(job['id']);self.assertEqual(r['source'],'model_api_static_review');self.assertFalse(r['execution_performed']);self.assertFalse(r['scientific_validation']);self.assertEqual(r['materials']['coverage']['total_code_files'],3);self.assertNotIn('fixture-key-not-real',json.dumps(r));self.assertGreater(FakeProvider.calls,0)
                with self.assertRaises(ValueError):client.get('../bad')
                self.assertIn('review-api-client.mjs',(ROOT/'web/dist/api-review.mjs').read_text())
            finally:server.shutdown();server.server_close();worker.join();service.close()
        provider.shutdown();provider.server_close();thread.join()
