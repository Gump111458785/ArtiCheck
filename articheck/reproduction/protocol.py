from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

FORMAT = 'articheck-reproduction-plan-v1'
DIMENSIONS = ('scope', 'code', 'data', 'environment', 'settings', 'commands', 'resources', 'acceptance')
MAX_PLAN_BYTES = 2_000_000


def read_json_bytes(path, max_bytes=MAX_PLAN_BYTES):
    with Path(path).open('rb') as source:
        raw=source.read(max_bytes+1)
    if len(raw)>max_bytes:raise ValueError('JSON document exceeds its size limit')
    return raw


def decode_json(raw):
    return json.loads(raw.decode('utf-8'),parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def load_json(path, *, max_bytes=MAX_PLAN_BYTES):
    return decode_json(read_json_bytes(path,max_bytes))


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


def object_value(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object')
    return value


def object_rows(value, label, maximum=5000):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(x, dict) for x in value):
        raise ValueError(label + ' must be a bounded list of objects')
    return value


def text_paths(value, label, maximum=100):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(x, str) or not x or '\\' in x or '\x00' in x for x in value):
        raise ValueError(label + ' must contain relative path strings')
    for name in value:
        name = name[5:] if name.startswith('repo:') else name
        pure = PurePosixPath(name)
        if pure.is_absolute() or '..' in pure.parts or re.match(r'^[A-Za-z]:', name):
            raise ValueError(label + ' contains a path outside the declared root')
    return value


def validate_files(value, label='files'):
    rows = object_rows(value, label)
    names = set()
    for row in rows:
        text_paths([row.get('path')], label)
        if row['path'] in names:
            raise ValueError('Duplicate file reference: ' + row['path'])
        names.add(row['path'])
        for key, lengths in [('sha256', (64,)), ('git_blob_sha', (40,64))]:
            digest = row.get(key)
            if digest is not None and (not isinstance(digest,str) or len(digest) not in lengths or not re.fullmatch('[0-9a-f]+',digest)):
                raise ValueError('Invalid reference ' + key)
    return rows


def validate_snapshot(value):
    object_value(value, 'imported snapshot')
    validate_files(value.get('files', []), 'snapshot files')
    commit = value.get('commit')
    if commit is not None and (not isinstance(commit,str) or not re.fullmatch(r'[0-9a-f]{40,64}',commit)):
        raise ValueError('Invalid imported commit')
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
    validate_snapshot(plan['repository'])
    components = object_value(plan['repository'].get('components', {}), 'code components')
    for name, paths in components.items():
        text_paths(paths, 'component ' + name)
    for key in ('experiments','conclusions'):
        object_rows(plan['paper'].get(key, []), 'paper '+key, 500)
        for row in plan['paper'].get(key,[]):identifier(row.get('id'))
    exclusions=object_value(plan['paper'].get('excluded_references',{}),'excluded paper references')
    if any(not isinstance(v,str) for v in exclusions.values()):raise ValueError('Excluded references require text reasons')
    for row in plan['paper'].get('experiments',[]):
        if not isinstance(row.get('labels',[]),list) or any(not isinstance(v,str) for v in row.get('labels',[])):raise ValueError('Experiment labels must be text lists')
        if not isinstance(row.get('conclusion_ids',[]),list) or any(not isinstance(v,str) for v in row.get('conclusion_ids',[])):raise ValueError('Conclusion links must be text lists')
        if row.get('core') is not None and type(row['core']) is not bool:raise ValueError('Core flag must be boolean')
    for key in ('inventory_review',):
        object_value(plan['paper'].get(key, {}), key)
    object_value(plan['repository'].get('method_review', {}), 'method review')
    validate_files(plan['environment'].get('lockfiles', []), 'lockfiles')
    verifies = plan['environment'].get('verify', [])
    if not isinstance(verifies,list) or len(verifies)>100:
        raise ValueError('Environment verification must be a list of argv arrays')
    for argv in verifies:
        if not isinstance(argv,list) or not argv or any(not isinstance(x,str) or not x or '\x00' in x for x in argv):
            raise ValueError('Invalid environment verification command')
    dataset_ids=set()
    for dataset in object_rows(plan['datasets'], 'datasets', 100):
        did=identifier(dataset.get('id'))
        if did in dataset_ids:raise ValueError('Duplicate dataset ID')
        dataset_ids.add(did)
        object_value(dataset.get('source', {}), 'dataset source')
        validate_files(dataset.get('files', []), 'dataset files')
        for name, item in object_value(dataset.get('splits', {}), 'dataset splits').items():
            object_value(item, 'split '+name)
            validate_files([item], 'split files')
        for step in object_rows(dataset.get('preprocessing', []), 'preprocessing', 100):
            validate_files(step.get('inputs', []), 'preprocess inputs')
            validate_files(step.get('outputs', []), 'preprocess outputs')
    object_rows(plan['experiments'], 'experiments', 100)
    all_ids = set()
    for exp in plan['experiments']:
        eid = identifier(exp.get('id'))
        if eid in all_ids:
            raise ValueError('Duplicate experiment ID')
        all_ids.add(eid)
        object_value(exp.get('config', {}), 'experiment config')
        object_value(exp.get('config', {}).get('expected', {}), 'expected configuration')
        object_value(exp.get('fairness', {}), 'fairness protocol')
        object_value(exp.get('training_evidence', {}), 'training evidence')
        object_value(exp.get('split_ids', {}), 'generated split definitions')
        for name,item in exp.get('split_ids',{}).items():
            object_value(item,'generated split')
            text_paths([item.get('path')],'generated split path')
            if name not in ('train','validation','test'):raise ValueError('Unknown generated split')
            if item.get('count') is not None and (type(item['count']) is not int or item['count']<1):raise ValueError('Invalid split count')
        training=exp.get('training_evidence',{})
        if training:
            identifier(training.get('stage_id'))
            text_paths([training.get('used_config_path')],'used configuration output')
            text_paths(training.get('model_outputs'),'model output paths')
        differences=object_value(exp.get('fairness',{}).get('allowed_variant_differences',{}),'allowed variant factors')
        for names in differences.values():
            if not isinstance(names,list) or any(not isinstance(n,str) for n in names):raise ValueError('Variant factor names must be lists of text')
        confidence=finite(exp.get('confidence',.95))
        if not 0<confidence<1:raise ValueError('Confidence must be between zero and one')
        if type(exp.get('minimum_runs',5)) is not int or exp.get('minimum_runs',5)<5:raise ValueError('At least five paired runs are required for statistical acceptance')
        object_value(exp.get('metric', {}), 'experiment metric')
        seeds = exp.get('seeds', [])
        if not isinstance(seeds,list):raise ValueError('Seeds must be a list')
        if not 1 <= len(seeds) <= 100 or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError('Provide 1–100 distinct integer seeds')
        variants = object_rows(exp.get('variants', []), 'variants', 20)
        if not 1 <= len(variants) <= 20 or len({identifier(v.get('id')) for v in variants}) != len(variants):
            raise ValueError('Provide 1–20 unique variants')
        for variant in variants:object_value(variant.get('settings', {}), 'variant settings')
        if any(v.get('role') not in ('method', 'baseline', 'ablation') for v in variants):
            raise ValueError('Unknown variant role')
        stages = object_rows(exp.get('stages', []), 'stages', 30)
        stage_ids = set()
        if not 1 <= len(stages) <= 30:
            raise ValueError('Provide 1–30 ordered stages')
        for stage in stages:
            if stage.get('kind') is not None and stage['kind'] not in ('prepare','preprocess','train','evaluate','summarize'):
                raise ValueError('Unknown stage kind')
            sid = identifier(stage.get('id'))
            needs = stage.get('needs', [])
            if not isinstance(needs,list) or any(not isinstance(x,str) for x in needs):raise ValueError('Stage needs must be an ID list')
            if sid in stage_ids or not set(stage.get('needs', [])).issubset(stage_ids):
                raise ValueError('Stage dependency must name an earlier unique stage')
            stage_ids.add(sid)
            argv = stage.get('argv')
            if not isinstance(argv, list) or not 1 <= len(argv) <= 128 or any(not isinstance(s, str) or not s or len(s) > 4096 or '\0' in s for s in argv):
                raise ValueError('Stages require nonempty argv arrays, never shell text')
            for key in ('inputs', 'outputs'):
                text_paths(stage.get(key), 'stage '+key)
            finite(stage.get('timeout_seconds', 300), minimum=1)
            if stage.get('timeout_seconds', 300) > 86400:
                raise ValueError('Stage timeout exceeds one day')
        metric = exp.get('metric', {})
        if not isinstance(metric.get('key'), str) or metric.get('direction') not in ('higher', 'lower'):
            raise ValueError('Metric needs a key and higher/lower direction')
        if 'reference' in metric:
            finite(metric['reference'])
            finite(metric.get('absolute_tolerance'), minimum=0)
        for comparison in object_rows(exp.get('comparisons', []), 'comparisons', 100):
            if comparison.get('method') not in {v['id'] for v in variants} or comparison.get('other') not in {v['id'] for v in variants} or comparison['method'] == comparison['other']:
                raise ValueError('Comparison must name two different variants')
            finite(comparison.get('minimum_effect', 0), minimum=0)
    for key, minimum in [('memory_bytes',1),('cpus',.1),('price_per_hour_usd',0)]:
        if plan['resources'].get(key) is not None:finite(plan['resources'][key],minimum=minimum)
    finite(plan['resources'].get('max_seconds', 3600), minimum=1)
    if plan['resources'].get('max_seconds', 3600) > 7*86400:
        raise ValueError('Total budget exceeds seven days')
    return plan


def load_plan(path, workspace=None, *, with_digest=False):
    path = Path(path).resolve()
    if workspace is not None and not path.is_relative_to(Path(workspace).resolve()):
        raise ValueError('Plan must be inside the configured workspace')
    raw=read_json_bytes(path)
    plan=validate_plan(decode_json(raw))
    repo = relative_path(path.parent, plan['repository'].get('path', '.'))
    if not repo.is_dir():
        raise ValueError('Repository path must be a directory')
    if workspace is not None and not repo.is_relative_to(Path(workspace).resolve()):
        raise ValueError('Repository must be inside the configured workspace')
    return (plan,repo,hashlib.sha256(raw).hexdigest()) if with_digest else (plan,repo)
