from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

FORMAT = 'articheck-reproduction-plan-v1'
DIMENSIONS = ('scope', 'code', 'data', 'environment', 'settings', 'commands', 'resources', 'acceptance')
MAX_PLAN_BYTES = 2_000_000


def load_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_PLAN_BYTES:
        raise ValueError('JSON document exceeds 2 MB')
    return json.loads(path.read_text(), parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def relative_path(root, value, *, exists=True):
    if not isinstance(value, str) or not value or '\\' in value or '\0' in value:
        raise ValueError('Expected a relative POSIX file path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or re.match(r'^[A-Za-z]:', value):
        raise ValueError('Path must stay inside its declared root')
    root = Path(root).resolve()
    target = root.joinpath(*p.parts)
    # Reject symlinks even when they currently point inside the root (TOCTOU/input ambiguity).
    current = root
    for part in p.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Symlinks are not accepted as evidence inputs')
    target = target.resolve()
    if not target.is_relative_to(root) or (exists and not target.exists()):
        raise ValueError('Missing file or path outside declared root: ' + value)
    return target


def fingerprint(path, *, limit=512 * 1024**2):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('Evidence file missing, symbolic, or exceeds size limit')
    sha = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(path.stat().st_size).encode() + b'\0')
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            size += len(chunk)
            if size > limit:
                raise ValueError('Evidence file grew beyond size limit')
            sha.update(chunk)
            blob.update(chunk)
    return {'sha256': sha.hexdigest(), 'git_blob_sha': blob.hexdigest(), 'bytes': size}


def finite(value, *, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or minimum is not None and value < minimum:
        raise ValueError('Expected a finite number within range')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value):
        raise ValueError('Invalid identifier')
    return value


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('format') != FORMAT:
        raise ValueError('Expected ' + FORMAT)
    for key in ('paper', 'repository', 'environment', 'resources'):
        if not isinstance(plan.get(key), dict):
            raise ValueError('Missing object: ' + key)
    for key in ('datasets', 'experiments'):
        if not isinstance(plan.get(key), list) or len(plan[key]) > 100:
            raise ValueError('Expected at most 100 ' + key)
    if not plan['experiments']:
        raise ValueError('At least one experiment is required')
    all_ids = set()
    for exp in plan['experiments']:
        eid = identifier(exp.get('id'))
        if eid in all_ids:
            raise ValueError('Duplicate experiment ID')
        all_ids.add(eid)
        seeds = exp.get('seeds', [])
        if not 1 <= len(seeds) <= 100 or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError('Provide 1–100 distinct integer seeds')
        variants = exp.get('variants', [])
        if not 1 <= len(variants) <= 20 or len({identifier(v.get('id')) for v in variants}) != len(variants):
            raise ValueError('Provide 1–20 unique variants')
        if any(v.get('role') not in ('method', 'baseline', 'ablation') for v in variants):
            raise ValueError('Unknown variant role')
        stages = exp.get('stages', [])
        stage_ids = set()
        if not 1 <= len(stages) <= 30:
            raise ValueError('Provide 1–30 ordered stages')
        for stage in stages:
            sid = identifier(stage.get('id'))
            if sid in stage_ids or not set(stage.get('needs', [])).issubset(stage_ids):
                raise ValueError('Stage dependency must name an earlier unique stage')
            stage_ids.add(sid)
            argv = stage.get('argv')
            if not isinstance(argv, list) or not 1 <= len(argv) <= 128 or any(not isinstance(s, str) or not s or len(s) > 4096 or '\0' in s for s in argv):
                raise ValueError('Stages require nonempty argv arrays, never shell text')
            for key in ('inputs', 'outputs'):
                if not isinstance(stage.get(key), list) or len(stage[key]) > 100:
                    raise ValueError('Declare stage inputs and outputs')
            finite(stage.get('timeout_seconds', 300), minimum=1)
            if stage.get('timeout_seconds', 300) > 86400:
                raise ValueError('Stage timeout exceeds one day')
        metric = exp.get('metric', {})
        if not isinstance(metric.get('key'), str) or metric.get('direction') not in ('higher', 'lower'):
            raise ValueError('Metric needs a key and higher/lower direction')
        if 'reference' in metric:
            finite(metric['reference'])
            finite(metric.get('absolute_tolerance'), minimum=0)
        for comparison in exp.get('comparisons', []):
            if comparison.get('method') not in {v['id'] for v in variants} or comparison.get('other') not in {v['id'] for v in variants} or comparison['method'] == comparison['other']:
                raise ValueError('Comparison must name two different variants')
            finite(comparison.get('minimum_effect', 0), minimum=0)
    finite(plan['resources'].get('max_seconds', 3600), minimum=1)
    if plan['resources'].get('max_seconds', 3600) > 7*86400:
        raise ValueError('Total budget exceeds seven days')
    return plan


def load_plan(path, workspace=None):
    path = Path(path).resolve()
    if workspace is not None and not path.is_relative_to(Path(workspace).resolve()):
        raise ValueError('Plan must be inside the configured workspace')
    plan = validate_plan(load_json(path))
    repo = relative_path(path.parent, plan['repository'].get('path', '.'))
    if not repo.is_dir():
        raise ValueError('Repository path must be a directory')
    if workspace is not None and not repo.is_relative_to(Path(workspace).resolve()):
        raise ValueError('Repository must be inside the configured workspace')
    return plan, repo
