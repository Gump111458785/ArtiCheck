"""Publish a small, account-authorized snapshot of a passed review."""
import hashlib
import json
import math
from time import time_ns

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
        or not (materials.get('paper') or materials.get('code'))
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
    ):
        raise ReviewError('case_not_passed', '只能分享服务端已判定通过的归档。', 409)
    return {'materials': 'both' if materials.get('paper') and materials.get('code') else
            'paper_only' if materials.get('paper') else 'code_only',
            'stages': len(stages), 'metrics': len(metrics), 'verdict': 'passed',
            'checks': [{key: row[key] for key in ('expected', 'observed', 'tolerance')
                        if type(row.get(key)) in (int, float) and math.isfinite(row[key])}
                       for row in metrics[:20]]}


class SharedCases:
    def __init__(self, store):
        self.store = store
        self.index = 'articheck:public-cases:' + store.namespace

    def list(self, before=None):
        upper = f'({before}' if before else '+'
        rows = self.store.command('ZREVRANGEBYLEX', self.index, upper, '-', 'LIMIT', '0', '21')
        entries = [json.loads(row.split('|', 1)[1]) for row in rows[:20]]
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
