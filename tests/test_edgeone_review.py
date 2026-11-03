import base64
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from articheck.edgeone_review import create_app, DeepSeekReviewer, RedisBudget, MAX_CLOUD_BODY
from articheck.review_api import DIMENSIONS, ModelReviewer, ReviewError

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'test-access-code-not-a-secret-1234'
HEADERS = {'Authorization': 'Bearer ' + TOKEN, 'X-ArtiCheck-Client': 'review-api'}


class Budget:
    configured = True
    def __init__(self):
        self.attempts = 0
        self.lock = threading.Lock()
    def reserve(self):
        with self.lock:
            if self.attempts >= 10:
                raise ReviewError('budget_exhausted', 'Trial exhausted', 429)
            self.attempts += 1
            return self.attempts


class Provider(BaseHTTPRequestHandler):
    requests = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(body)
        review = {'summary': '需要核对实验设置', 'criteria': [
            {'dimension': d, 'status': 'needs_review', 'note': '静态建议', 'page': 1, 'file': None}
            for d in DIMENSIONS], 'findings': []}
        raw = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(review)}}],
                          'usage': {'prompt_tokens': 1000, 'completion_tokens': 800}}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def materials():
    return {k: {'name': f, 'content_base64': base64.b64encode((ROOT/'web/dist/samples'/f).read_bytes()).decode()}
            for k, f in [('paper', 'articheck-method-note.pdf'), ('code', 'toy-artifact.zip')]}


class CloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import flask
        except ImportError:
            raise unittest.SkipTest('Install articheck[cloud] to test the cloud adapter')

    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.key = patch.dict(os.environ, ARTICHECK_API_KEY='test-key')
        self.key.start()
        self.reviewer = DeepSeekReviewer()
        # Only the test fixture changes destination. The deployed class locks it to DeepSeek.
        self.reviewer.base_url = f'http://127.0.0.1:{self.server.server_port}'
        self.budget = Budget()
        self.app = create_app({'ARTICHECK_REVIEW_TOKEN': TOKEN}, reviewer=self.reviewer, budget=self.budget)
        self.client = self.app.test_client()
        Provider.requests = []

    def tearDown(self):
        self.key.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_actual_pdf_zip_to_http_model_returns_report_without_queue(self):
        response = self.client.post('/reviews', json=materials(), headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.json)
        value = response.json
        self.assertEqual(value['job']['id'], value['report']['job_id'])
        self.assertEqual(value['job']['status'], 'completed')
        self.assertFalse(value['report']['execution_performed'])
        self.assertEqual(value['report']['budget']['reserved_attempts'], 1)
        self.assertEqual(len(value['report']['review']['criteria']), 8)
        self.assertEqual(value['report']['materials']['coverage']['code_files_in_context'], 3)
        request = Provider.requests[0]
        self.assertEqual(request['model'], 'deepseek-flash')
        self.assertEqual(request['thinking'], {'type': 'disabled'})
        self.assertEqual(request['max_tokens'], 3000)
        self.assertEqual(request['response_format'], {'type': 'json_object'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_unauthorized_wrong_origin_and_oversize_never_reserve_or_call(self):
        self.assertEqual(self.client.post('/reviews', json=materials()).status_code, 401)
        h = {**HEADERS, 'Origin': 'https://other.example'}
        self.assertEqual(self.client.post('/reviews', json=materials(), headers=h).status_code, 403)
        self.assertEqual(self.client.post('/reviews', data=b'x'*(MAX_CLOUD_BODY+1), content_type='application/json', headers=HEADERS).status_code, 413)
        self.assertEqual(self.budget.attempts, 0)
        self.assertEqual(Provider.requests, [])

    def test_parse_failures_and_excessive_context_do_not_consume_budget(self):
        self.assertEqual(self.client.post('/reviews', json={}, headers=HEADERS).status_code, 400)
        context = {'files': [], 'paper_excerpts': [{'text': '字'*100000}]}
        app = create_app({'ARTICHECK_REVIEW_TOKEN': TOKEN}, reviewer=self.reviewer,
                         budget=self.budget, prepare=lambda _: (context, ''))
        self.assertEqual(app.test_client().post('/reviews', json={}, headers=HEADERS).status_code, 413)
        self.assertEqual(self.budget.attempts, 0)

    def test_provider_failure_is_reserved_once_and_does_not_retry(self):
        with patch.object(self.reviewer, 'post', side_effect=TimeoutError) as post:
            response = self.client.post('/reviews', json=materials(), headers=HEADERS)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.budget.attempts, 1)

    def test_ledger_failure_or_exhaustion_blocks_supplier(self):
        with patch.object(self.budget, 'reserve', side_effect=ReviewError('budget_unavailable', 'Unavailable', 503)):
            self.assertEqual(self.client.post('/reviews', json=materials(), headers=HEADERS).status_code, 503)
        self.budget.attempts = 10
        self.assertEqual(self.client.post('/reviews', json=materials(), headers=HEADERS).status_code, 429)
        self.assertEqual(Provider.requests, [])

    def test_missing_durable_store_stays_disabled(self):
        app = create_app({'ARTICHECK_REVIEW_TOKEN': TOKEN}, reviewer=self.reviewer)
        client = app.test_client()
        self.assertFalse(client.get('/health').json['configured'])
        self.assertEqual(client.post('/reviews', json=materials(), headers=HEADERS).status_code, 503)

    def test_public_origin_survives_internal_proxy_host(self):
        app = create_app({'ARTICHECK_REVIEW_TOKEN': TOKEN, 'ARTICHECK_PUBLIC_ORIGIN': 'https://review.example'},
                         reviewer=self.reviewer, budget=self.budget)
        client = app.test_client()
        h = {**HEADERS, 'Origin': 'https://review.example'}
        response = client.post('/reviews', json=materials(), headers=h, base_url='http://internal-function.local')
        self.assertEqual(response.status_code, 200, response.json)
        h['Origin'] = 'https://untrusted.example'
        self.assertEqual(client.post('/reviews', json=materials(), headers=h, base_url='http://internal-function.local').status_code, 403)


class LedgerTests(unittest.TestCase):
    def test_ledger_is_one_atomic_eval_without_expiry_or_refund(self):
        ledger = RedisBudget({'UPSTASH_REDIS_REST_URL': 'https://example.upstash.io',
                             'UPSTASH_REDIS_REST_TOKEN': 'secret', 'ARTICHECK_BUDGET_ID': 'fixed-test-budget-0001'})
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, n): return b'{"result": 10}'
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = Response()
            self.assertEqual(ledger.reserve(), 10)
            request = factory.return_value.open.call_args.args[0]
            command = json.loads(request.data)
            self.assertEqual(command[0], 'EVAL')
            self.assertIn("redis.call('INCR'", command[1])
            self.assertNotIn('EXPIRE', command[1])
            self.assertNotIn('secret', request.full_url)
            self.assertEqual(command[-1], '10')
