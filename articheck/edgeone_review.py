"""Synchronous cloud review with durable, atomic attempt reservations.

No background workers or filesystem job state: a serverless instance may disappear
after any response. Redis stores only the reservation counter, never materials.
"""
import hmac
import json
import os
import uuid
import urllib.request

from .review_api import ModelReviewer, ReviewError, now, prepare_context

MAX_CLOUD_BODY = 5_000_000  # Includes base64 and JSON, below the platform's 6 MB limit.
MAX_PROMPT_BYTES = 200_000
MAX_ATTEMPTS = 10
RESERVATION_CNY = 1

# Increment and cap are one atomic operation. Reservations never expire or refund:
# a timeout or invalid model output may still have incurred supplier charges.
RESERVE_LUA = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then return -1 end
return redis.call('INCR', KEYS[1])
"""


class RedisBudget:
    def __init__(self, env):
        self.url = env.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
        self.token = env.get('UPSTASH_REDIS_REST_TOKEN', '')
        self.namespace = env.get('ARTICHECK_BUDGET_ID', '')

    @property
    def configured(self):
        from urllib.parse import urlparse
        u = urlparse(self.url)
        return (u.scheme == 'https' and u.hostname and not u.username and
                not u.password and not u.query and not u.fragment and
                bool(self.token) and 16 <= len(self.namespace) <= 128)

    def reserve(self):
        if not self.configured:
            raise ReviewError('budget_not_configured', 'Configure a durable budget ledger before enabling model calls', 503)
        command = ['EVAL', RESERVE_LUA, '1', 'articheck:budget:' + self.namespace, str(MAX_ATTEMPTS)]
        req = urllib.request.Request(self.url, data=json.dumps(command).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('Budget redirects are disabled')
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=8) as response:
                value = json.loads(response.read(8192))['result']
            if type(value) is not int or value < -1 or value == 0 or value > MAX_ATTEMPTS:
                raise ValueError('Invalid reservation response')
        except Exception as exc:
            raise ReviewError('budget_unavailable', 'Budget ledger unavailable; no model request was made', 503) from exc
        if value == -1:
            raise ReviewError('budget_exhausted', 'The 10 CNY trial reservation budget is exhausted', 429)
        return value


class DeepSeekReviewer(ModelReviewer):
    def __init__(self):
        # Fixed destination and model: uploads cannot redirect credentials or select costly models.
        super().__init__('https://api.deepseek.com', 'deepseek-flash')

    def post(self, body):
        body = {**body, 'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}}
        # UTF-8 bytes conservatively bound prompt tokens, with ample message overhead.
        if sum(len(m['content'].encode('utf-8')) for m in body['messages']) > MAX_PROMPT_BYTES:
            raise ReviewError('context_too_large', 'Review context exceeds the cloud input budget; narrow the materials', 413)
        return super().post(body)


def create_app(env=None, *, reviewer=None, budget=None, prepare=None):
    from flask import Flask, jsonify, request
    env = os.environ if env is None else env
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = MAX_CLOUD_BODY
    reviewer = reviewer or DeepSeekReviewer()
    budget = budget or RedisBudget(env)
    prepare = prepare or prepare_context

    def configured():
        return bool(reviewer.configured and budget.configured and len(env.get('ARTICHECK_REVIEW_TOKEN', '')) >= 24)

    @app.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(ReviewError)
    def known_error(exc):
        return jsonify(error={'code': exc.code, 'message': str(exc)}), exc.status

    @app.errorhandler(413)
    def oversized(_):
        return jsonify(error={'code': 'material_size', 'message': 'PDF + ZIP + base64 JSON must fit within 5 MB'}), 413

    @app.get('/health')
    def health():
        return jsonify(service='articheck-review-api', version=1, configured=configured(),
                mode='synchronous', auth_required=True, model='deepseek-flash',
                limits={'max_body_bytes': MAX_CLOUD_BODY, 'max_prompt_bytes': MAX_PROMPT_BYTES,
                        'max_output_tokens': 3000, 'trial_budget_cny': 10, 'max_attempts': MAX_ATTEMPTS})

    @app.post('/reviews')
    def review():
        token = env.get('ARTICHECK_REVIEW_TOKEN', '')
        if not configured():
            raise ReviewError('provider_not_configured', 'Server credentials, access token or durable budget are not configured', 503)
        if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
            raise ReviewError('unauthorized', 'Enter the site review access code, not a provider API key', 401)
        if request.headers.get('X-ArtiCheck-Client') != 'review-api':
            raise ReviewError('invalid_client', 'Expected the review-api client header', 403)
        origin = request.headers.get('Origin')
        if origin:
            # The platform can replace both scheme and Host before forwarding.
            # Use the public origin fixed by the operator, never arbitrary forwarded headers.
            expected = env.get('ARTICHECK_PUBLIC_ORIGIN') or request.host_url
            if origin.rstrip('/') != expected.rstrip('/'):
                raise ReviewError('origin_forbidden', 'Use the same-origin workbench', 403)
        if not request.is_json:
            raise ReviewError('invalid_request', 'Expected application/json', 415)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ReviewError('invalid_request', 'Expected a JSON object')
        try:
            context, scope = prepare(body)
            # Preflight the same serialization before reserving a paid attempt.
            context_bytes = len(json.dumps({'scope': scope, 'materials': {**context, 'files': context['files'][:500]}}, ensure_ascii=False).encode())
            if context_bytes > MAX_PROMPT_BYTES - 5000:
                raise ReviewError('context_too_large', 'Context exceeds the cloud budget; use a smaller source archive', 413)
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError('invalid_material', 'PDF or ZIP could not be safely parsed', 422) from exc
        attempt = budget.reserve()  # Must precede the sole supplier HTTP request.
        try:
            output = reviewer.review(context, scope)
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError('provider_failed', 'Model request failed; the attempt remains reserved. No automatic retry.', 502) from exc
        key = uuid.uuid4().hex
        job = {'id': key, 'status': 'completed', 'created_at': now(), 'stage': 'completed',
               'source': 'model_api_static_review', 'execution_performed': False,
               'scientific_validation': False, 'report_ready': True, 'error': None}
        report = {'format': 'articheck-api-static-review-v1', 'job_id': key,
                  'source': 'model_api_static_review', 'execution_performed': False,
                  'scientific_validation': False,
                  'materials': {k: context[k] for k in ('paper', 'code', 'coverage')}, **output,
                  'budget': {'reserved_attempts': attempt, 'max_attempts': MAX_ATTEMPTS,
                             'reserved_cny_per_attempt': RESERVATION_CNY},
                  'notice': 'Static model suggestions; no artifact execution. Report is stored in this browser, not on the cloud function.'}
        return jsonify(job=job, report=report)

    return app
