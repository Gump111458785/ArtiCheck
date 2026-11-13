"""Publish a small, account-authorized snapshot of a completed review."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from time import time_ns
from uuid import uuid4

from .review_api import DIMENSIONS, ReviewError, now


def shared_case_summary(report):
    review = report.get('review') or {}
    execution = report.get('execution') or {}
    materials = report.get('materials') or {}
    metrics = execution.get('metrics') or []
    planned = (review.get('plan') or {}).get('stages') or []
    stages = execution.get('stages') or []
    criteria = review.get('criteria') or []
    required = {row['id'] for row in review.get('metrics', []) if row.get('author_method') and row.get('id')}
    required.update(row['metric_id'] for row in (review.get('plan') or {}).get('metric_patterns', []) if row.get('metric_id'))
    observed = {row.get('id') for row in metrics}
    reviewed = {row.get('dimension') for row in criteria}
    finished = {row.get('id') for row in stages}
    if (
        report.get('status') != 'completed' or report.get('terminated_at') or report.get('termination_requested')
        or execution.get('status') in {'queued', 'starting', 'running', 'cancelling', 'cancelled'} or execution.get('needs_user')
    ):
        raise ReviewError('case_not_completed', '只能分享已经完成的归档。', 409)
    failed = any(row.get('status') == 'outside_tolerance' for row in metrics) or any(
        row.get('status') == 'failed' or row.get('exit_code') not in {0, None} for row in stages
    ) or execution.get('status') in {'failed', 'expired'} or any(
        row.get('confirmed_error') and (row.get('page') or row.get('file')) for row in review.get('findings', [])
    ) or (report.get('availability') or {}).get('answer') == 'unavailable' or execution.get('user_answer') == 'unavailable'
    has_gaps = (
        not (materials.get('paper') or materials.get('code'))
        or review.get('paper_type') in {None, 'nonpaper', 'unknown'}
        or (report.get('availability') or {}).get('answer') == 'unavailable'
        or execution and (execution.get('status') != 'completed' or execution.get('needs_user'))
        or review.get('findings') or (review.get('coverage') or {}).get('gaps')
        or reviewed != set(DIMENSIONS)
        or any(row.get('status') not in {'documented', 'not_applicable'} for row in criteria)
        or materials.get('code') and not planned
        or planned and (
            not execution.get('execution_performed')
            or len(planned) != len(stages) or {row['id'] for row in planned} != finished
            or any(row.get('status') != 'completed' or row.get('exit_code') != 0 for row in stages)
        )
        or review.get('purpose') == 'reproduce_other' and review.get('paper_type') == 'empirical' and not metrics
        or execution.get('user_answer') == 'unavailable'
        or not required.issubset(observed)
        or any(row.get('status') != 'within_tolerance' or type(row.get('observed')) not in (int, float)
               or not math.isfinite(row['observed']) for row in metrics)
    )
    verdict = 'failed' if failed else 'unassessed' if has_gaps else 'passed'
    return {'materials': 'both' if materials.get('paper') and materials.get('code') else
            'paper_only' if materials.get('paper') else 'code_only',
            'stages': len(stages), 'metrics': len(metrics), 'verdict': verdict,
            'checks': [{key: row[key] for key in ('expected', 'observed', 'tolerance')
                        if type(row.get(key)) in (int, float) and math.isfinite(row[key])}
                       for row in metrics[:20]]}


class SharedCases:
    def __init__(self, store):
        self.store = store
        self.index = 'articheck:public-cases:' + store.namespace

    def list(self, before=None, *, owner=None, jobs=()):
        upper = f'({before}' if before else '+'
        rows = self.store.command('ZREVRANGEBYLEX', self.index, upper, '-', 'LIMIT', '0', '21')
        entries = [json.loads(row.split('|', 1)[1]) for row in rows[:20]]
        if owner is not None:
            identity = hashlib.sha256(owner.encode()).hexdigest()
            mine = set(self.store.command('SMEMBERS', self.index + ':owned:' + identity) or [])
            my_ids = {hashlib.sha256(f'{owner}:{job}'.encode()).hexdigest()[:32]: job for job in mine.union(jobs)}
            entries = [{**entry, 'can_delete': entry['id'] in my_ids,
                        **({'source_job': my_ids[entry['id']]} if entry['id'] in my_ids else {})} for entry in entries]
        return {'items': entries, 'next': rows[19].split('|', 1)[0] if len(rows) > 20 else None}

    def publish(self, owner, job, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ReviewError('invalid_case_title', '公开案例名称须为 1–120 个字符。')
        report = self.store.get(owner, job)
        summary = shared_case_summary(report)
        case_id = hashlib.sha256(f'{owner}:{job}'.encode()).hexdigest()[:32]
        published_at = now()
        case = {'id': case_id, 'title': title.strip(), 'published_at': published_at, **summary}
        # An immutable, sanitized snapshot. Comparing the source in the same Redis operation
        # prevents publishing a report cancelled or updated between validation and publication.
        member = f'{time_ns():020d}-{case_id}|' + json.dumps(case, ensure_ascii=False)
        script = """
        local existing = redis.call('GET', KEYS[3])
        if existing then return existing end
        if redis.call('GET', KEYS[1]) ~= ARGV[1] then return false end
        redis.call('ZADD', KEYS[2], 0, ARGV[2])
        redis.call('SET', KEYS[3], ARGV[3])
        return ARGV[3]
        """
        saved = self.store.command('EVAL', script, '3', self.store.key(owner, job), self.index,
                                   self.index + ':' + case_id, json.dumps(report, ensure_ascii=False),
                                   member, json.dumps(case, ensure_ascii=False))
        if not saved:
            raise ReviewError('case_report_changed', '审查记录已更新，请重新打开后再分享。', 409)
        return json.loads(saved)

    def get_shared(self, case_id):
        raw = self.store.command('GET', self.index + ':detail:' + case_id)
        if not raw:
            raise ReviewError('case_not_found', '该共享案例已撤回或不存在。', 404)
        return json.loads(raw)

    FILE_BLOCK = 400_000

    def file_key(self, storage, kind, index):
        return f'{self.index}:file:{storage}:{kind}:{index}'

    def read_file(self, detail, kind, chunk):
        record = detail['stored'].get(kind)
        start = chunk * 2_000_000
        if not record:
            raise ReviewError('case_not_found', '该共享文件不存在。', 404)
        if start >= record['bytes']:
            raise ReviewError('case_file_range', '请求的文件位置无效。', 416)
        end = min(start + 2_000_000, record['bytes'])
        indices = range(start // self.FILE_BLOCK, (end + self.FILE_BLOCK - 1) // self.FILE_BLOCK)
        def read(index):
            value = self.store.command('GET', self.file_key(detail['storage_owner'], kind, index))
            if not value:
                raise ReviewError('case_not_found', '共享文件已撤回或暂不可用。', 404)
            return base64.b64decode(value, validate=True)
        with ThreadPoolExecutor(max_workers=5) as pool:
            raw = b''.join(pool.map(read, indices))
        if len(raw) != end-start:
            raise ReviewError('case_file_corrupt', '共享文件完整性校验失败。', 503)
        return raw, record

    def publish_full(self, owner, job, title, publisher, report, files):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ReviewError('invalid_case_title', '公开案例名称须为 1–120 个字符。')
        summary = shared_case_summary(report)
        case_id = hashlib.sha256(f'{owner}:{job}'.encode()).hexdigest()[:32]
        storage_owner = uuid4().hex
        stored = {}
        file_keys = []
        marker = self.index + ':' + case_id
        detail_key = self.index + ':detail:' + case_id
        owner_index = self.index + ':owned:' + hashlib.sha256(owner.encode()).hexdigest()
        if self.store.command('GET', detail_key):
            raise ReviewError('case_already_shared', '该归档已分享。', 409)
        legacy = self.store.command('GET', marker)
        snapshot = {key: report[key] for key in ('status', 'review', 'materials', 'activity', 'audit', 'availability',
                    'public_paper_identifier') if key in report}
        snapshot['id'] = case_id
        if isinstance(snapshot.get('audit'), dict):
            audit = snapshot['audit']
            snapshot['audit'] = {key: audit[key] for key in ('status', 'reason', 'reviews', 'additional_metrics')
                                 if key in audit}
            snapshot['audit']['raw_findings'] = [{'title': row.get('title', '')}
                                                 for row in audit.get('raw_findings', [])]
        execution = report.get('execution')
        if execution:
            snapshot['execution'] = {key: execution[key] for key in ('status', 'execution_performed', 'stages',
                'metrics', 'started_at', 'finished_at', 'elapsed_seconds', 'runtime', 'needs_user', 'question',
                'user_answer', 'availability_verdict') if key in execution}
            allowed = ('id','title','status','exit_code','reason','timed_out','started_at','finished_at',
                       'elapsed_seconds','live_tail')
            if 'runtime' in snapshot['execution']:
                runtime = execution.get('runtime') or {}
                snapshot['execution']['runtime'] = {key: runtime[key] for key in
                    ('python', 'system', 'architecture', 'workspace_cleaned', 'auto_provisioned_packages') if key in runtime}
            snapshot['execution']['stages'] = [
                {key: stage[key] for key in allowed if key in stage} for stage in execution.get('stages', [])]
        case = {'id': case_id, 'title': title.strip(), 'publisher': publisher, 'published_at': now(),
                'verdict': summary['verdict'], 'report_available': True, 'files': {}}
        published = False
        attempted = False
        try:
            for kind, (raw, info) in files.items():
                blocks = (len(raw) + self.FILE_BLOCK - 1) // self.FILE_BLOCK
                keys = [self.file_key(storage_owner, kind, index) for index in range(blocks)]
                file_keys.extend(keys)
                stored[kind] = {**info, 'filename': info['name'], 'blocks': blocks}

                def write(index):
                    offset = index * self.FILE_BLOCK
                    encoded = base64.b64encode(raw[offset:offset+self.FILE_BLOCK]).decode()
                    if self.store.command('SET', keys[index], encoded, 'EX', '900') != 'OK':
                        raise ReviewError('case_file_save_failed', '共享文件暂未保存，请重试。', 503)

                with ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(write, range(blocks)))
            case['files'] = {kind: info['filename'] for kind, info in stored.items()}
            member = f'{time_ns():020d}-{case_id}|' + json.dumps(case, ensure_ascii=False)
            detail = {'owner': hashlib.sha256(owner.encode()).hexdigest(), 'job': job, 'member': member,
                      'case': case, 'report': snapshot, 'stored': stored, 'storage_owner': storage_owner}
            script = """
            if redis.call('EXISTS', KEYS[4])==1 then return -1 end
            if (redis.call('GET',KEYS[3]) or '')~=ARGV[4] then return -1 end
            if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
            for i=6,#KEYS do
                if redis.call('EXISTS',KEYS[i])==0 then return 0 end
            end
            if ARGV[4]~='' then
                for _,row in ipairs(redis.call('ZRANGE',KEYS[2],0,-1)) do
                    if string.sub(row,55)==ARGV[4] then redis.call('ZREM',KEYS[2],row); break end
                end
            end
            for i=6,#KEYS do redis.call('PERSIST',KEYS[i]) end
            redis.call('ZADD', KEYS[2], 0, ARGV[2])
            redis.call('SET', KEYS[3], ARGV[5])
            redis.call('SET', KEYS[4], ARGV[3])
            redis.call('SADD', KEYS[5], ARGV[6])
            return 1
            """
            attempted = True
            result = self.store.command('EVAL', script, str(5+len(file_keys)), self.store.key(owner, job), self.index, marker,
                                        detail_key, owner_index, *file_keys, json.dumps(report, ensure_ascii=False), member,
                                        json.dumps(detail, ensure_ascii=False), legacy or '',
                                        json.dumps(case, ensure_ascii=False), job)
            published = result == 1
            attempted = False
            if result == -1:
                raise ReviewError('case_already_shared', '该归档已分享。', 409)
            if not published:
                raise ReviewError('case_report_changed', '审查记录已更新，请重新打开后再分享。', 409)
            return {**case, 'can_delete': True}
        finally:
            if not published and attempted:
                try:
                    published = self.get_shared(case_id)['storage_owner'] == storage_owner
                except ReviewError as error:
                    if error.code != 'case_not_found':
                        published = True  # A lost response may have committed; never delete live bytes.
            if not published and file_keys:
                try:
                    self.store.command('DEL', *file_keys)
                except ReviewError:
                    pass  # Uncommitted blocks expire automatically.

    def retract(self, owner, case_id, job=None):
        identity = hashlib.sha256(owner.encode()).hexdigest()
        try:
            detail = self.get_shared(case_id)
        except ReviewError as error:
            if error.code != 'case_not_found' or not job or hashlib.sha256(
                    f'{owner}:{job}'.encode()).hexdigest()[:32] != case_id:
                raise
            script = """
            if redis.call('EXISTS',KEYS[3])==1 then return 0 end
            local old=redis.call('GET',KEYS[2])
            if not old then return 0 end
            for _,row in ipairs(redis.call('ZRANGE',KEYS[1],0,-1)) do
                if string.sub(row,55)==old then redis.call('ZREM',KEYS[1],row); break end
            end
            redis.call('DEL',KEYS[2])
            return 1
            """
            self.store.command('EVAL', script, '3', self.index, self.index + ':' + case_id,
                               self.index + ':detail:' + case_id)
            return {'removed': True}
        if detail['owner'] != identity:
            raise ReviewError('case_not_found', '该共享案例已撤回或不存在。', 404)
        keys = [self.file_key(detail['storage_owner'], kind, index)
                for kind, record in detail['stored'].items() for index in range(record['blocks'])]
        script = """
        local raw=redis.call('GET',KEYS[1])
        if not raw then return 0 end
        local current=cjson.decode(raw)
        if current.owner~=ARGV[1] or current.member~=ARGV[2] then return 0 end
        redis.call('ZREM',KEYS[2],ARGV[2])
        redis.call('SREM',KEYS[4],ARGV[3])
        redis.call('DEL',KEYS[1],KEYS[3])
        for i=5,#KEYS do redis.call('DEL',KEYS[i]) end
        return 1
        """
        result = self.store.command('EVAL', script, str(4 + len(keys)), self.index + ':detail:' + case_id,
                           self.index, self.index + ':' + case_id, self.index + ':owned:' + identity,
                           *keys, identity, detail['member'], detail['job'])
        if not result and self.store.command('GET', self.index + ':detail:' + case_id):
            raise ReviewError('case_changed', '共享案例已更新，请刷新后重试。', 409)
        return {'removed': True}
