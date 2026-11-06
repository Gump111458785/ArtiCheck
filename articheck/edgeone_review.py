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
MAX_ATTEMPTS = 100000
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
        try:
            self.max_attempts = int(env.get('ARTICHECK_MODEL_ATTEMPTS', str(MAX_ATTEMPTS)))
        except (TypeError, ValueError):
            self.max_attempts = 0

    @property
    def configured(self):
        from urllib.parse import urlparse
        u = urlparse(self.url)
        return (u.scheme == 'https' and u.hostname and not u.username and
                not u.password and not u.query and not u.fragment and
                bool(self.token) and 16 <= len(self.namespace) <= 128 and 1 <= self.max_attempts <= 10_000_000)

    def reserve(self):
        if not self.configured:
            raise ReviewError('budget_not_configured', 'Configure a durable budget ledger before enabling model calls', 503)
        command = ['EVAL', RESERVE_LUA, '1', 'articheck:budget:' + self.namespace, str(self.max_attempts)]
        req = urllib.request.Request(self.url, data=json.dumps(command).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('Budget redirects are disabled')
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=8) as response:
                value = json.loads(response.read(8192))['result']
            if type(value) is not int or value < -1 or value == 0 or value > self.max_attempts:
                raise ValueError('Invalid reservation response')
        except Exception as exc:
            raise ReviewError('budget_unavailable', 'Budget ledger unavailable; no model request was made', 503) from exc
        if value == -1:
            raise ReviewError('budget_exhausted', '本轮模型调用额度已用完，可继续查看和导出已有报告。', 429)
        return value


class DeepSeekReviewer(ModelReviewer):
    def __init__(self):
        # Fixed destination and model: uploads cannot redirect credentials or select costly models.
        super().__init__('https://api.deepseek.com', 'deepseek-flash')

    def post(self, body):
        body = {**body, 'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}}
        # UTF-8 bytes conservatively bound prompt tokens, with ample message overhead.
        text_bytes=0;image_bytes=0;image_count=0
        for message in body['messages']:
            content=message['content']
            if isinstance(content,str):
                text_bytes+=len(content.encode())
                continue
            for block in content:
                if block.get('type')=='text':text_bytes+=len(block['text'].encode())
                elif block.get('type')=='image_url':
                    url=block['image_url']['url']
                    if message['role']!='user' or not url.startswith('data:image/jpeg;base64,'):
                        raise ReviewError('invalid_image_context','Only rendered PDF images are accepted',400)
                    image_count+=1;image_bytes+=len(url)
        if text_bytes > MAX_PROMPT_BYTES or image_count>24 or image_bytes>16_100_000:
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
    from .hosted_api import register
    register(app, env, reviewer, budget)

    def configured():
        return bool(reviewer.configured and budget.configured)

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
                        'max_output_tokens': 3000, 'trial_budget_cny': getattr(budget,'max_attempts',MAX_ATTEMPTS), 'max_attempts': getattr(budget,'max_attempts',MAX_ATTEMPTS)})

    @app.post('/reviews')
    def review():
        if not configured():
            raise ReviewError('provider_not_configured','模型与费用计数尚未配置。',503)
        app.extensions['articheck_authorize'](session=False)
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
                  'budget': {'reserved_attempts': attempt, 'max_attempts': getattr(budget,'max_attempts',MAX_ATTEMPTS),
                             'reserved_cny_per_attempt': RESERVATION_CNY},
                  'notice': 'Static model suggestions; no artifact execution. Report is stored in this browser, not on the cloud function.'}
        return jsonify(job=job, report=report)

    return app
