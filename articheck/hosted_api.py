"""Hosted v2 routes. v1 remains available for existing API clients."""
import hmac
import json
import re
import time
import uuid
import copy

from .hosted_github import import_repository, repository, resolve_repository
from .hosted_uploads import HostedUploads
from .hosted_review import assess, material_identity, prepare_assessment, digest
from .hosted_gpu import HybridExecutor
from .hosted_store import HostedStore
from .hosted_images import text_materials
from .hosted_sources import lookup, public_identifier
from .hosted_audit import cross_audit
from .kg_service import KnowledgeGraphService
from .review_api import ReviewError, now


def register(app, env, reviewer, budget, *, store=None, executor=None):
    from flask import jsonify, request
    store = store or HostedStore(env)
    executor = executor or HybridExecutor(env,store)
    uploads = HostedUploads(env,store)
    kg = KnowledgeGraphService(env, store, reviewer, budget)
    from .hosted_auth import Accounts
    accounts = Accounts(app,env,store)

    def authorize(*, session=True):
        if env.get('ARTICHECK_AUTH_MODE')=='legacy':
            token=env.get('ARTICHECK_REVIEW_TOKEN','')
            if len(token)<24 or not hmac.compare_digest(request.headers.get('Authorization','').encode(),('Bearer '+token).encode()):
                raise ReviewError('unauthorized','请登录后提交审查。',401)
            accounts.guard()
            owner=request.headers.get('X-ArtiCheck-Session','')
            if session and not re.fullmatch(r'[a-f0-9]{64}',owner):raise ReviewError('invalid_session','会话无效。',401)
            return accounts.owner() or owner
        accounts.require()
        return accounts.owner()

    app.extensions['articheck_accounts']=accounts
    app.extensions['articheck_authorize']=authorize

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ReviewError('invalid_request', '请提交有效的材料对象。')
        return value

    def material_body(payload):
        payload=dict(payload)
        for kind in ('paper','code'):
            material=payload.get(kind)
            if not isinstance(material,dict):continue
            if material.get('upload_id'):
                payload[kind]=uploads.resolve(authorize(),material,kind)
            elif kind=='code' and material.get('repository'):
                payload[kind]=resolve_repository(material)
        return payload

    @app.post('/uploads')
    def create_upload():
        owner=authorize()
        return jsonify(uploads.create(owner,body()))

    @app.post('/uploads/<job>/cancel')
    def cancel_upload(job):
        return jsonify(uploads.cancel(authorize(),job))

    @app.get('/capabilities')
    def capabilities():
        if env.get('ARTICHECK_AUTH_MODE')!='legacy':authorize()
        return jsonify(version=2, service='articheck-online', model=reviewer.model,
                       review_configured=reviewer.configured and budget.configured,
                       sandbox_configured=executor.configured, auth_required=True,
                       accounts={'registration':False,'invitation_only':True,'session_days':30,'method':'username_password'},
                       compute={'capacity':getattr(executor,'capacity',{'provider':'e2b','cpu_count':2,'memory_mb':512,'gpu':False}),
                                'gpu':{'status':'ready' if getattr(executor,'capacity',{}).get('gpu') else 'not_configured','provider':'owned_server'}},
                       limits={'max_body_bytes': 5_000_000, 'max_zip_bytes':100*1024**2,
                               'max_unpacked_bytes':500*1024**2,'max_pdf_bytes':20*1024**2,
                               'large_upload_transport':'signed_direct_upload','max_seconds': 600,
                               'default_seconds': 300, 'report_retention_days': 7,
                               'compute_reservation_cny': 1, 'compute_attempts': getattr(store, 'max_compute_attempts', 100000)})

    @app.post('/repositories')
    def import_code():
        owner=authorize()
        payload=body()
        name=repository(payload.get('url'))
        assessment=store.get(owner,payload['assessment_id']) if payload.get('assessment_id') else None
        prior_assessment = copy.deepcopy(assessment)
        if assessment and (assessment.get('terminated_at') or assessment.get('termination_requested')):
            raise ReviewError('assessment_terminated', '本次审查已终止。', 409)
        if assessment and assessment['review'].get('repository_hint')!='https://github.com/'+name:
            raise ReviewError('source_mismatch','自动获取的仓库必须对应本次报告中的来源线索。',409)
        cached=None
        if not payload.get('refresh'):
            try:cached=store.repository_ref(name)
            except ReviewError:pass
        try:
            result=import_repository(name,int(time.time()//300),env.get('ARTICHECK_GITHUB_TOKEN',''),
                                     cached.get('commit') if cached else None)
        except ReviewError as exc:
            if assessment:
                assessment['source_discovery']={'status':'failed','url':'https://github.com/'+name,
                                                'error':exc.code,'reason':str(exc),'attempted_at':now()}
                store.replace(owner, prior_assessment, assessment)
            raise
        fetched_at=cached.get('fetched_at') if cached else time.time()
        if not cached:
            try:store.repository_ref(name,{'commit':result['commit'],'fetched_at':fetched_at})
            except ReviewError:pass
        if assessment:
            assessment['source_discovery']={'status':'downloaded','url':result['url'],
                                            'commit':result['commit'],'sha256':result['sha256'],'attempted_at':now()}
            if not store.replace(owner, prior_assessment, assessment):
                assessment = store.get(owner, assessment['id'])
        return jsonify({**result,'cached_reference':bool(cached),'fetched_at':fetched_at,
                        **({'assessment':assessment} if assessment else {})})

    @app.post('/assessments')
    def create_assessment():
        started=time.monotonic()
        owner = authorize()
        payload = body()
        job = payload.get('request_id') or uuid.uuid4().hex
        if not isinstance(job, str) or not re.fullmatch(r'[a-f0-9]{32}', job):
            raise ReviewError('invalid_request_id', '请求编号无效。')
        try:
            existing = store.get(owner, job)
        except ReviewError as exc:
            if exc.code != 'not_found':
                raise
        else:
            if existing.get('status') == 'cancelled':
                return jsonify(existing)
        payload = material_body(payload)
        try:
            context, scope = prepare_assessment(payload)
            context['execution_environment']=getattr(executor,'capacity',context['execution_environment'])
        except ReviewError:
            raise
        except Exception as exc:
            raise ReviewError('invalid_material','论文或代码包无法安全解析，请检查文件是否完整、加密或损坏。',422) from exc
        while context.get('method_chunks') and len(json.dumps(text_materials(context), ensure_ascii=False).encode()) > 175_000:
            context['method_chunks'].pop()
        if len(json.dumps(text_materials(context), ensure_ascii=False).encode()) > 175_000:
            raise ReviewError('context_too_large', '材料解析后的内容过大，请缩小代码包或论文范围。', 413)
        identity = digest({'materials': material_identity(context), 'task': context['task'],
                           'scope': scope, 'max_seconds': context['max_seconds'],'supplement':context['supplement'],
                           **({'purpose': context['purpose']} if context.get('purpose') else {})})
        pending = {'id': job, 'status': 'reviewing', 'created_at': now(), 'started_at': time.time(),
                   'format': 'articheck-online-assessment-v2', 'source': 'model_api_review',
                   'materials': material_identity(context), 'input_sha256': identity, 'review': None,
                   'execution': None, 'execution_performed': False, 'scientific_validation': False}
        if not store.claim(owner, pending):
            existing = store.get(owner, job)
            if existing.get('status') != 'cancelled' and existing.get('input_sha256') != identity:
                raise ReviewError('request_changed', '同一请求编号不能替换材料或审查范围。', 409)
            return jsonify(existing)
        published = copy.deepcopy(pending)
        pending['activity'] = []

        def stopped():
            return store.get(owner, job).get('status') != 'reviewing'

        def publish(value):
            nonlocal published
            if not store.replace(owner, published, value):
                return False
            published = copy.deepcopy(value)
            return True

        def activity(title, roles, detail='', status='running'):
            for event in pending['activity']:
                if event['status']=='running':event['status']='failed' if status in {'failed','skipped'} else 'completed'
            pending['activity'].append({'title':title,'roles':roles,'detail':detail,
                                        'status':status,'time':time.time()})
            return publish(pending)
        activity('材料解析完成',[role for role,present in [('literature_reader',context.get('paper')),('code_inspector',context.get('code'))] if present],
                 '论文与源码已按输入预算解析；仅处理实际提供的材料。','completed')
        # Material parsing and the durable idempotency claim precede reservation.
        try:
            if stopped():
                return jsonify(store.get(owner, job))
            activity('核对公开来源',['literature_reader' if context.get('paper') else 'code_inspector'],'正在识别可核对的公开出处；无有效标识时仅核对导入材料。')
            lookup(context,budget,store)
            if stopped():
                return jsonify(store.get(owner, job))
            while len(json.dumps(text_materials(context),ensure_ascii=False).encode())>175_000 and context.get('web_sources'):
                sources=context['web_sources']
                if any(s.get('content') for s in sources):
                    for source in sources:source['content']=source.get('content','')[:len(source.get('content',''))//2]
                elif any(s.get('summary') for s in sources):
                    for source in sources:source['summary']=''
                else:sources.pop()
                context['source_lookup']['context_truncated']=True
            has_code = bool(context.get('code'))
            activity('联合审阅与计划编排' if has_code else '论文审阅与指标核查',
                     [role for role,present in [('literature_reader',context.get('paper')),('code_inspector',has_code),('planner',has_code and context.get('task')!='self_review')] if present],
                     '主审模型正在核对图表、实现与实验条件，并生成结构化建议和执行计划。' if has_code else '主审模型正在深度核对论文图表、指标出处与论证一致性。')
            if stopped():
                return jsonify(store.get(owner, job))
            attempt = budget.reserve()
            if stopped():
                return jsonify(store.get(owner, job))
            value = assess(reviewer, context, scope, request_timeout=max(5,min(80,108-(time.monotonic()-started))))
        except Exception as exc:
            if stopped():
                return jsonify(store.get(owner, job))
            activity('主审请求未完成',['reporter'],'保留已取得的活动记录，不自动重试。','failed')
            pending.update(status='failed', error=exc.code if isinstance(exc, ReviewError) else 'provider_failed',
                           error_message=str(exc)[:300] if isinstance(exc, ReviewError) else f'模型请求未完成（{type(exc).__name__}），请稍后重试。')
            if not publish(pending):
                return jsonify(store.get(owner, job))
            if isinstance(exc, ReviewError):
                raise
            raise ReviewError('provider_failed', '模型请求失败，调用额度已预留；未自动重试。', 502) from exc
        if stopped():
            return jsonify(store.get(owner, job))
        return_roles = [role for role,present in [('literature_reader',context.get('paper')),('code_inspector',context.get('code')),('planner',bool(context.get('code') and value['review']['plan']['stages']))] if present] or ['literature_reader']
        activity('主审结果已返回',return_roles,'图表与代码核查结果、执行计划已完成结构化校验。' if context.get('code') else '论文图表与材料核查结果已完成结构化校验。','completed')
        remaining=108-(time.monotonic()-started)
        if context['paper'] and value['review']['paper_type'] in {'empirical','diagnostic','survey'} and (value['review']['findings'] or value['review']['metrics']):
            if remaining>=8:
                try:
                    if not activity('交叉核查依据',['cross_auditor'],'独立复核建议与图表数字，撤回依据不足的条目。'):
                        return jsonify(store.get(owner, job))
                    attempt=budget.reserve()
                    if stopped():
                        return jsonify(store.get(owner, job))
                    value=cross_audit(reviewer,context,value,request_timeout=min(25,remaining))
                except Exception as exc:
                    value['audit']={'status':'not_completed','reason':exc.code if isinstance(exc,ReviewError) else 'cross_audit_failed'}
            else:
                value['audit']={'status':'not_completed','reason':'request_deadline'}
        if context.get('purpose') == 'reproduce_other':
            for row in value['review'].get('findings', []) + value.get('audit', {}).get('raw_findings', []):
                row['suggestion'] = ''
        if value.get('audit',{}).get('status')!='completed':
            activity('交叉复核未执行或未完成',['cross_auditor'],
                     '本次不适用、请求时限不足或复核请求未成功；以报告标记为准。','skipped')
        activity('汇总审查报告',['reporter'],'建议、图表出处、覆盖缺口与执行计划已整理。','completed')
        value['activity']=pending['activity']
        value.update(id=job, status='completed', input_sha256=identity)
        if identifier := public_identifier(context):
            value['public_paper_identifier'] = identifier
        value['budget'] = {'model_reserved_attempts': attempt, 'model_max_attempts': getattr(budget,'max_attempts',10)}
        if not publish(value):
            return jsonify(store.get(owner, job))
        return jsonify(value)

    @app.get('/assessments/<job>')
    def get_assessment(job):
        owner = authorize()
        value = store.get(owner, job)
        previous = copy.deepcopy(value)
        if value.get('terminated_at'):
            return jsonify(value)
        if value.get('status') == 'reviewing' and time.time() - value['started_at'] > 125:
            value.update(status='failed', error='review_response_unavailable')
            if not store.replace(owner, previous, value):
                return jsonify(store.get(owner, job))
        execution = value.get('execution')
        if execution and (execution['status'] == 'starting' or execution.get('awaiting_launch')):
            if time.time() > execution.get('deadline', float('inf')):
                value['execution'] = {**execution, 'status': 'expired', 'notice': '未能确认实例启动结果，保留未验收状态。'}
                value['execution'].pop('awaiting_launch', None)
                complete_termination(value)
                store.replace(owner, previous, value)
                value = store.get(owner, job)
            return jsonify(value)
        if execution and execution['status'] in {'queued', 'running', 'cancelling'}:
            try:
                value['execution'] = executor.poll(execution)
                if execution['status'] == 'cancelling' and value['execution']['status'] in {'queued', 'running'}:
                    value['execution']['status'] = 'cancelling'
                complete_termination(value)
            except ReviewError:
                raise
            except Exception as exc:
                raise ReviewError('sandbox_poll_failed', '暂时无法获取执行状态，可稍后刷新；不会重新启动任务。', 502) from exc
            if not store.replace(owner, previous, value):
                return jsonify(store.get(owner, job))
            if value['execution']['status'] in {'completed', 'failed'}:
                try:
                    executor.stop(value['execution'])
                except Exception:
                    pass  # Provider hard deadline is the final billing bound.
        return jsonify(value)

    @app.post('/assessments/<job>/execute')
    def execute(job):
        owner = authorize()
        value = store.get(owner, job)
        if value.get('terminated_at') or value.get('termination_requested'):
            raise ReviewError('assessment_terminated', '本次审查已终止。', 409)
        payload = body()
        if not value.get('review'):
            raise ReviewError('review_not_ready', '请等待材料审查完成后再执行。', 409)
        if payload.get('plan_sha256') != value['review']['plan_sha256']:
            raise ReviewError('plan_changed', '执行计划已变化，请刷新后再提交。', 409)
        previous_execution=value.get('execution')
        retry=payload.get('retry_of')
        if previous_execution and not retry:
            return jsonify(value)  # Idempotent across repeated clicks/requests.
        history=value.get('execution_history',[])
        if retry and (not previous_execution or previous_execution['status'] not in {'failed','expired','cancelled'} or
                      previous_execution.get('attempt_id')!=retry or len(history)>=2):
            raise ReviewError('retry_changed','该执行不能按此版本重试，请刷新状态；每份计划最多执行三次。',409)
        attempt_number=len(history)+2 if retry else 1
        if not executor.configured:
            raise ReviewError('sandbox_not_configured', '云端执行服务尚未配置，未消耗执行额度。', 503)
        if not value['review']['plan']['stages']:
            raise ReviewError('no_executable_plan', value['review']['plan']['blocked_reason'] or '当前材料未提供可执行代码。请先补充代码或查看论文自查结果。', 422)
        # Revalidate bytes and fingerprint before acquiring a paid launch latch.
        payload = material_body(payload)
        from .review_api import decode_material, prepare_context
        context, _ = prepare_context({'code': payload.get('code')}, partial=True)
        if material_identity(context)['code'] != value['materials']['code']:
            raise ReviewError('material_changed', '代码版本已变化，请重新审查。', 409)
        if not store.lock(owner, job,attempt_number):
            raise ReviewError('execution_already_requested', '这份计划已提交过执行。请刷新状态；不会重复启动或扣费。', 409)
        previous = copy.deepcopy(value)
        if retry:
            value['execution_history'] = history + [previous_execution]
        attempt_id = uuid.uuid4().hex
        value['execution'] = {'status': 'starting', 'execution_performed': False, 'attempt_id': attempt_id,
                              'scientific_validation': False,
                              'deadline': time.time() + value['review']['plan']['max_seconds'] + 60}
        if not store.replace(owner, previous, value):
            store.unlock_before_launch(owner, job, attempt_number)
            raise ReviewError('execution_changed', '任务状态已更新，请刷新。', 409)
        starting = copy.deepcopy(value)
        try:
            if store.get(owner, job) != starting:
                return jsonify(finish_unlaunched_cancel(owner, job, attempt_id))
            attempt = store.reserve_compute()
        except ReviewError:
            store.replace(owner, starting, previous)
            store.unlock_before_launch(owner, job, attempt_number)
            raise
        if store.get(owner, job) != starting:
            return jsonify(finish_unlaunched_cancel(owner, job, attempt_id))
        try:
            launched = {**executor.launch(value, payload), 'reserved_attempt': attempt, 'attempt_id': attempt_id}
        except Exception as exc:
            value['execution'] = {**starting['execution'], 'reserved_attempt': attempt, 'status': 'failed',
                                  'notice': '云端实例启动失败，本次预留保留；请联系管理员，避免反复提交。'}
            if not store.replace(owner, starting, value):
                return jsonify(finish_unlaunched_cancel(owner, job, attempt_id))
            if isinstance(exc, ReviewError):
                raise
            raise ReviewError('sandbox_launch_failed', value['execution']['notice'], 502) from exc
        value['execution'] = launched
        if store.replace(owner, starting, value):
            return jsonify(value)
        current = store.get(owner, job)
        if (current.get('execution') or {}).get('attempt_id') == attempt_id:
            # Expose the handle before stopping, so a transient stop failure can be retried.
            updated = {**current, 'execution': {**launched, 'status': 'cancelling'}}
            if store.replace(owner, current, updated):
                return jsonify(stop_execution(owner, job, updated))
        executor.stop(launched)
        return jsonify(store.get(owner, job))

    def finish_unlaunched_cancel(owner, job, attempt_id):
        current = store.get(owner, job)
        execution = current.get('execution') or {}
        if execution.get('attempt_id') == attempt_id and execution.get('awaiting_launch'):
            updated = {**current, 'execution': {**execution, 'status': 'cancelled'}}
            updated['execution'].pop('awaiting_launch')
            complete_termination(updated)
            if store.replace(owner, current, updated):
                return updated
        return store.get(owner, job)

    def complete_termination(value):
        if value.get('termination_requested') and (value.get('execution') or {}).get('status') not in {
            'queued', 'starting', 'running', 'cancelling'
        } and value.get('status') != 'reviewing':
            value['terminated_at'] = now()
            value['notice'] = '本次审查已终止，已取得的证据保留。'

    def stop_execution(owner, job, current):
        execution = current['execution']
        try:
            snapshot = executor.poll(execution)
        except Exception:
            # A log retrieval failure must not prevent a stop request.
            snapshot = copy.deepcopy(execution)
        if snapshot['status'] not in {'expired', 'cancelled'}:
            try:
                stopped = executor.stop(execution)
            except Exception as exc:
                raise ReviewError('cancel_pending', '暂时无法确认停止，请点击重试停止。', 502) from exc
            if snapshot['status'] not in {'completed', 'failed'}:
                if stopped is False:
                    snapshot = {**snapshot, 'status': 'cancelling', 'notice': '已请求停止，正在等待执行器确认。'}
                else:
                    for stage in snapshot.get('stages', []):
                        if stage.get('status') == 'running':
                            stage.update(status='skipped', reason='任务已按请求停止。')
                    snapshot = {**snapshot, 'status': 'cancelled', 'notice': '用户停止执行，保留已产生的证据。'}
        for _ in range(6):
            updated = {**current, 'execution': snapshot}
            complete_termination(updated)
            if store.replace(owner, current, updated):
                return updated
            current = store.get(owner, job)
            live = current.get('execution') or {}
            if live.get('attempt_id') != execution.get('attempt_id') or live.get('status') != 'cancelling':
                return current
        raise ReviewError('cancel_pending', '任务状态正在更新，请重试中断。', 409)

    @app.post('/assessments/<job>/cancel')
    def cancel(job):
        owner = authorize()
        payload = body() if request.is_json else {}
        for _ in range(6):
            try:
                value = store.get(owner, job)
            except ReviewError as exc:
                if exc.code != 'not_found':
                    raise
                tombstone = {'id': job, 'status': 'cancelled', 'review': None, 'execution': None,
                             'format': 'articheck-online-assessment-v2', 'source': 'model_api_review',
                             'execution_performed': False, 'scientific_validation': False,
                             'notice': '审查已按请求中止。', 'activity': []}
                if payload.get('terminate') is True:
                    tombstone['termination_requested'] = True
                    complete_termination(tombstone)
                if store.claim(owner, tombstone):
                    return jsonify(tombstone)
                continue
            previous = copy.deepcopy(value)
            if value.get('status') == 'reviewing':
                for event in value.get('activity') or []:
                    if event.get('status') == 'running':
                        event['status'] = 'skipped'
                value.setdefault('activity', []).append({'title': '审查已手动中止', 'roles': ['reporter'],
                                                         'status': 'completed', 'time': time.time()})
                value.update(status='cancelled', error='user_cancelled', notice='用户已主动中止本次审查。')
            elif (execution := value.get('execution')) and execution['status'] in {'starting', 'queued', 'running', 'cancelling'}:
                value['execution'] = {**execution, 'status': 'cancelling'}
                if execution['status'] == 'starting':
                    value['execution']['awaiting_launch'] = True
            elif value.get('review') and payload.get('execution_request') is True and (
                not execution or execution.get('attempt_id') == payload.get('retry_of')
            ):
                if execution:
                    value['execution_history'] = [*value.get('execution_history', []), execution]
                value['execution'] = {'status': 'cancelled', 'attempt_id': uuid.uuid4().hex,
                                      'execution_performed': False, 'scientific_validation': False,
                                      'notice': '已取消启动实验。'}
            else:
                return jsonify(value)
            if payload.get('terminate') is True:
                value['termination_requested'] = True
            complete_termination(value)
            if not store.replace(owner, previous, value):
                continue
            current_execution = value.get('execution') or {}
            if current_execution.get('status') == 'cancelling' and not current_execution.get('awaiting_launch'):
                value = stop_execution(owner, job, value)
            return jsonify(value)
        raise ReviewError('cancel_pending', '任务状态正在更新，请重试中断。', 409)

    @app.post('/assessments/<job>/terminate')
    def terminate(job):
        owner = authorize()
        value = store.get(owner, job)
        if value.get('terminated_at'):
            return jsonify(value)
        execution = value.get('execution') or {}
        review = value.get('review') or {}
        status = execution.get('status')
        if value.get('status') == 'reviewing' or status in {'queued', 'starting', 'running', 'cancelling'}:
            raise ReviewError('assessment_active', '请先中断运行，再终止本次审查。', 409)
        blocked = (status in {'failed', 'expired', 'cancelled'} or value.get('status') in {'failed', 'cancelled'}
                   or any(stage.get('status') == 'failed' for stage in execution.get('stages', []))
                   or (not execution and ((review.get('resource_preflight') or {}).get('needs_user')
                       or (review.get('task') == 'reproduction' and not (value.get('materials') or {}).get('code')))))
        if not blocked:
            raise ReviewError('assessment_not_interrupted', '只有中断或等待资源的审查可以终止。', 409)
        updated = {**value, 'terminated_at': now(), 'notice': '本次审查已终止，已取得的证据保留。'}
        if not store.replace(owner, value, updated):
            raise ReviewError('assessment_changed', '任务状态已更新，请刷新。', 409)
        return jsonify(updated)

    @app.post('/assessments/<job>/feedback')
    def answer_blocker(job):
        owner = authorize()
        value = store.get(owner, job)
        if value.get('terminated_at'):
            raise ReviewError('assessment_terminated', '本次审查已终止。', 409)
        previous = copy.deepcopy(value)

        def save_answer():
            if not store.replace(owner, previous, value):
                raise ReviewError('assessment_changed', '任务状态已更新，请刷新。', 409)
            return jsonify(value)

        execution = value.get('execution') or {}
        answer = body().get('answer')
        preflight=(value.get('review') or {}).get('resource_preflight') or {}
        if not execution and preflight.get('needs_user'):
            if answer not in {'unavailable','can_provide'}:
                raise ReviewError('invalid_feedback','请选择能否提供所需计算条件。')
            value['availability']={'resource':'compute_capacity','answer':answer,'confirmed_at':now(),
                'verdict':'当前托管 CPU 条件不足，受影响实验未复现。' if answer=='unavailable' else '可选择本地工作台提供所需资源；当前云端未启动实验。',
                'scientific_validation':False}
            return save_answer()
        if not execution and value.get('review',{}).get('task')=='reproduction' and not value['materials']['code']:
            if answer not in {'unavailable','can_provide'}:
                raise ReviewError('invalid_feedback','请选择能否补充代码来源。')
            discovery=value.get('source_discovery',{})
            if value['review'].get('repository_hint') and not discovery:
                raise ReviewError('source_not_attempted','已定位到代码线索，请先尝试自动获取。',409)
            value['availability']={'resource':'source_code','answer':answer,'confirmed_at':now(),
                 'verdict':'当前条件下无法取得代码，代码执行保留为未复现。' if answer=='unavailable' else '等待补充 GitHub 地址或代码 ZIP 后重新审查。',
                 'scientific_validation':False}
            return save_answer()
        if not execution.get('needs_user') or answer not in {'unavailable', 'can_provide'}:
            raise ReviewError('invalid_feedback', '只有实际执行遇到材料阻碍后，才需要确认补充情况。')
        execution['user_answer'] = answer
        execution['availability_verdict'] = '当前条件下无法复现受阻实验' if answer == 'unavailable' else '等待补充材料后重新生成计划'
        # A skip cannot become a scientific pass, including after user feedback.
        execution['scientific_validation'] = False
        value['execution'] = execution
        return save_answer()

    @app.get('/kg/graph')
    def get_kg_graph():
        owner = authorize()
        if request.args.get('scope', 'PRIVATE').upper() != 'PRIVATE':
            raise ReviewError('invalid_graph_scope', '知识图谱仅限当前账号。')
        focus_paper_id = request.args.get('paper_id', '')
        return jsonify(kg.build_graph_response(owner, focus_paper_id=focus_paper_id))

    @app.post('/kg/ingest')
    def ingest_kg_project():
        owner = authorize()
        payload = body()
        job = str(payload.get('assessment_id') or '')
        if not re.fullmatch(r'[a-f0-9]{32}', job):
            raise ReviewError('invalid_assessment', '请从已完成的在线审查报告打开图谱。')
        report = store.get(owner, job)
        review = report.get('review')
        if not review:
            raise ReviewError('report_not_ready', '审查报告尚未生成。', 409)
        if review.get('paper_type') in {'code_only', 'nonpaper'}:
            raise ReviewError('paper_required', '只有论文审查报告可以加入图谱。', 422)
        return jsonify(kg.ingest_project(owner, {
            'project_id': str(payload.get('project_id') or '')[:100],
            'title': str(payload.get('title') or '')[:300],
            'report': report,
        }))

    def self_review_report(owner, job):
        report = store.get(owner, job)
        if (report.get('review') or {}).get('task') != 'self_review':
            raise ReviewError('report_type', '只有论文自查报告提供潜在冲突核对。', 404)
        return report

    @app.get('/kg/assessments/<job>/conflicts')
    def get_kg_conflicts(job):
        owner = authorize()
        return jsonify(items=kg.report_conflicts(owner, self_review_report(owner, job)))

    @app.post('/kg/assessments/<job>/conflicts')
    def verify_kg_conflict(job):
        owner = authorize()
        report = self_review_report(owner, job)
        payload = body()
        cmp_id = str(payload.get('comparison_id') or '')
        if not any(item['id'] == cmp_id for item in kg.report_conflicts(owner, report)):
            raise ReviewError('comparison_not_found', '当前报告没有这项候选冲突。', 404)
        return jsonify(kg.save_verification(owner, cmp_id, payload.get('decision'), payload.get('note', '')))

    @app.post('/kg/relations/verify')
    def verify_kg_relations():
        owner = authorize()
        with kg.public_work_slot(owner):
            return jsonify(kg.verify_related(owner, str(body().get('paper_id') or '')))

    @app.post('/kg/relations/edit')
    def edit_kg_relation():
        owner = authorize()
        payload = body()
        return jsonify(kg.edit_relation(owner, str(payload.get('source') or ''),
                                        str(payload.get('target') or ''), payload.get('action'),
                                        payload.get('note', ''), payload.get('label', '')))

    @app.post('/kg/literature/expand')
    def expand_kg_literature():
        owner = authorize()
        payload = body()
        with kg.public_work_slot(owner):
            return jsonify(kg.expand_literature(owner, str(payload.get('paper_id') or ''),
                kinds=payload.get('kinds'), limit=payload.get('limit', 5),
                depth=payload.get('depth', 1), total=payload.get('max_total'), operation_id=payload.get('operation_id')))

    @app.post('/kg/literature/paper')
    def update_kg_paper():
        owner = authorize()
        payload = body()
        return jsonify(kg.update_paper_choice(owner, str(payload.get('paper_id') or ''),
                                             str(payload.get('action') or '')))

    @app.post('/kg/contributions/extract')
    def extract_kg_contributions():
        owner = authorize()
        payload = body()
        material = material_body({'paper': payload['paper']})['paper'] if payload.get('paper') else None
        with kg.public_work_slot(owner):
            return jsonify(kg.retry_contributions(owner, str(payload.get('paper_id') or ''), material, operation_id=payload.get('operation_id')))

    @app.get('/kg/operations/<operation_id>/progress')
    def kg_operation_progress(operation_id):
        owner = authorize()
        return jsonify(kg.graph_progress(kg.graph_operation_key(owner, operation_id)))

    @app.post('/kg/operations/<operation_id>/cancel')
    def cancel_kg_operation(operation_id):
        return jsonify(kg.cancel_graph_operation(authorize(), operation_id))

    @app.post('/kg/nodes/delete')
    def delete_kg_node():
        owner = authorize()
        return jsonify(kg.delete_node(owner, str(body().get('node_id') or '')))

    @app.post('/kg/layout')
    def save_kg_layout():
        owner = authorize()
        return jsonify(kg.save_layout(owner, body()))
