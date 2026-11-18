"""Synchronous cloud review adapter."""
import json
import os
import uuid

from .review_api import ModelReviewer, ReviewError, now, prepare_context

MAX_CLOUD_BODY = 5_000_000  # Includes base64 and JSON, below the platform's 6 MB limit.
MAX_PROMPT_BYTES = 200_000


class DeepSeekReviewer(ModelReviewer):
    def __init__(self):
        # Fixed destination and model: uploads cannot redirect credentials or select costly models.
        super().__init__('https://api.deepseek.com', 'deepseek-flash')

    def post(self, body):
        extra = {'thinking': {'type': 'disabled'}}
        if 'tools' not in body:
            extra['response_format'] = {'type': 'json_object'}
        body = {**body, **extra}
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


def create_app(env=None, *, reviewer=None, prepare=None):
    from flask import Flask, jsonify, request
    env = os.environ if env is None else env
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = MAX_CLOUD_BODY
    reviewer = reviewer or DeepSeekReviewer()
    prepare = prepare or prepare_context
    from .hosted_api import register
    register(app, env, reviewer)

    @app.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(ReviewError)
    def known_error(exc):
        status = exc.status
        # EdgeOne replaces function 5xx bodies with its own HTML page, which hides the
        # actual reason from the workbench. Keep v1 /reviews semantics; v2 routes return
        # 424 with the original status in a header so the JSON reason reaches the user.
        if status >= 500 and not request.path.startswith('/reviews'):
            response = jsonify(error={'code': exc.code, 'message': str(exc), 'upstream_status': status})
            response.headers['X-ArtiCheck-Upstream-Status'] = str(status)
            return response, 424
        return jsonify(error={'code': exc.code, 'message': str(exc)}), status

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error={'code': 'http_error', 'message': exc.description or exc.name}), exc.code
        app.logger.exception('Unhandled workbench error')
        return jsonify(error={'code': 'internal_error', 'message': '服务处理未完成，请重试；已有材料与记录保留。', 'upstream_status': 500}), 424

    @app.errorhandler(413)
    def oversized(_):
        return jsonify(error={'code': 'material_size', 'message': 'PDF + ZIP + base64 JSON must fit within 5 MB'}), 413

    @app.get('/health')
    def health():
        return jsonify(service='articheck-review-api', version=1, configured=bool(reviewer.configured),
                mode='synchronous', auth_required=True, model='deepseek-flash',
                limits={'max_body_bytes': MAX_CLOUD_BODY, 'max_prompt_bytes': MAX_PROMPT_BYTES,
                        'max_output_tokens': 3000})

    @app.post('/reviews')
    def review():
        app.extensions['articheck_authorize'](session=False)
        if not reviewer.configured:
            raise ReviewError('provider_not_configured','模型服务尚未配置。',503)
        if not request.is_json:
            raise ReviewError('invalid_request', 'Expected application/json', 415)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ReviewError('invalid_request', 'Expected a JSON object')
        try:
            context, scope = prepare(body)
            # Preflight the same serialization before calling the provider.
            context_bytes = len(json.dumps({'scope': scope, 'materials': {**context, 'files': context['files'][:500]}}, ensure_ascii=False).encode())
            if context_bytes > MAX_PROMPT_BYTES - 5000:
                raise ReviewError('context_too_large', 'Context exceeds the cloud budget; use a smaller source archive', 413)
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError('invalid_material', 'PDF or ZIP could not be safely parsed', 422) from exc
        try:
            output = reviewer.review(context, scope)
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError('provider_failed', 'Model request failed. No automatic retry.', 502) from exc
        key = uuid.uuid4().hex
        job = {'id': key, 'status': 'completed', 'created_at': now(), 'stage': 'completed',
               'source': 'model_api_static_review', 'execution_performed': False,
               'scientific_validation': False, 'report_ready': True, 'error': None}
        report = {'format': 'articheck-api-static-review-v1', 'job_id': key,
                  'source': 'model_api_static_review', 'execution_performed': False,
                  'scientific_validation': False,
                  'materials': {k: context[k] for k in ('paper', 'code', 'coverage')}, **output,
                  'notice': 'Static model suggestions; no artifact execution. Report is stored in this browser, not on the cloud function.'}
        return jsonify(job=job, report=report)

    return app
