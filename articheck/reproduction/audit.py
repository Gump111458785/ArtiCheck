from __future__ import annotations

import ast
import hashlib
import itertools
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .protocol import DIMENSIONS, fingerprint, load_json, load_plan, relative_path

SETTINGS = ('hyperparameters', 'initialization', 'augmentation', 'selection', 'stopping')


def audit_plan(path, *, workspace=None, imported=None, repo_override=None):
    """Read actual bytes only; never imports or executes artifact code."""
    plan, repo = load_plan(path, workspace)
    base = Path(path).resolve().parent
    if repo_override is not None:
        repo = Path(repo_override).resolve()
    checks = []
    def add(dimension, code, status, detail, evidence=None):
        checks.append({'dimension': dimension, 'code': code, 'status': status, 'detail': detail,
                       'evidence': evidence or {}})
    def file_check(dimension, entry, root=repo):
        name = entry.get('path', '')
        try:
            target = relative_path(root, name)
            actual = fingerprint(target)
            expected = entry.get('sha256') or entry.get('git_blob_sha')
            key = 'sha256' if entry.get('sha256') else 'git_blob_sha'
            status = 'pass' if expected and actual[key] == expected else 'fail' if expected else 'unknown'
            add(dimension, 'file:' + name, status, 'Content digest compared' if expected else 'No reference digest supplied',
                {'path': name, 'actual': actual, 'expected': {key: expected}})
            return target, actual, status
        except (OSError, ValueError) as error:
            add(dimension, 'file:' + name, 'fail', str(error))
            return None, None, 'fail'

    paper = plan['paper']
    if paper.get('path'):
        file_check('scope', {'path': paper['path'], 'sha256': paper.get('sha256')}, base)
    else:
        add('scope', 'paper_identity', 'unknown', 'Paper file and digest are required')
    pages = paper.get('pages', [])
    if paper.get('pages_path'):
        target, _, status = file_check('scope', {'path': paper['pages_path'], 'sha256': paper.get('pages_sha256')}, base)
        if target and status == 'pass':
            pages = load_json(target)
    if not isinstance(pages, list) or len(pages) > 500 or any(not isinstance(p, dict) or type(p.get('number')) is not int or not isinstance(p.get('text'), str) for p in pages):
        raise ValueError('Paper pages must contain number/text records')
    page_map = {p['number']: p['text'] for p in pages}
    if len(page_map) != len(pages):
        raise ValueError('Duplicate paper page numbers')
    candidates = {}
    for page in pages:
        for match in re.finditer(r'(?i)\b(table|figure|fig\.)\s*([0-9]+[a-z]?)\b|(?:表|图)\s*([0-9]+)', page['text']):
            kind = 'table' if (match.group(1) or '').lower() == 'table' or match.group().startswith('表') else 'figure'
            label = kind + '-' + (match.group(2) or match.group(3)).lower()
            candidates.setdefault(label, {'id': label, 'pages': []})['pages'].append(page['number'])
    inventory = paper.get('experiments', [])
    if not isinstance(inventory, list) or len(inventory) > 500:
        raise ValueError('Invalid paper experiment inventory')
    inventory_ids = [x.get('id') for x in inventory]
    if len(set(inventory_ids)) != len(inventory_ids):
        raise ValueError('Duplicate paper experiment IDs')
    for row in inventory:
        quote = row.get('quote', '')
        grounded = bool(quote and quote in page_map.get(row.get('page'), ''))
        add('scope', 'citation:' + str(row.get('id')), 'pass' if grounded else 'fail', 'Inventory citation checked against page text',
            {'page': row.get('page'), 'quote': quote})
    classified = set(itertools.chain.from_iterable(x.get('labels', []) for x in inventory)) | set(paper.get('excluded_references', {}))
    for label, item in candidates.items():
        add('scope', 'unclassified:' + label, 'pass' if label in classified else 'review_required',
            'Figure/table reference classified' if label in classified else 'Unclassified paper reference; may be a missing experiment or a citation', item)
    selected = {e.get('paper_experiment') for e in plan['experiments']}
    for row in inventory:
        if row.get('core'):
            add('scope', 'coverage:' + row['id'], 'pass' if row['id'] in selected else 'fail', 'Core experiment must have an execution plan')
    if not inventory or not paper.get('conclusions'):
        add('scope', 'inventory', 'unknown', 'Need paper-wide experiments and main conclusions')
    review = paper.get('inventory_review', {})
    add('scope', 'inventory_review', 'pass' if review.get('complete') is True and review.get('reviewer') and review.get('notes') else 'review_required',
        'Human inventory review is a declaration, not inferred from selected easy experiments', review)

    source = imported or plan['repository']
    expected_files = source.get('files', [])
    if not isinstance(expected_files, list) or len(expected_files) > 5000:
        raise ValueError('Reference snapshot must contain at most 5000 files')
    if not expected_files:
        add('code', 'snapshot', 'unknown', 'No imported content digests; a directory listing is insufficient')
    seen = set()
    for entry in expected_files:
        if entry.get('path') in seen:
            raise ValueError('Duplicate snapshot path')
        seen.add(entry.get('path'))
        file_check('code', entry)
    expected_commit = source.get('commit') or plan['repository'].get('commit')
    if expected_commit and repo_override is None:
        # Do not run git from an artifact-controlled configuration or invoke hooks.
        try:
            result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(repo), 'rev-parse', '--verify', 'HEAD'], capture_output=True, text=True, timeout=5)
            actual_commit = result.stdout.strip() if result.returncode == 0 else None
            add('code', 'commit', 'pass' if expected_commit == actual_commit else 'fail', 'Repository HEAD compared to imported revision', {'expected': expected_commit, 'actual': actual_commit})
        except (OSError, subprocess.TimeoutExpired):
            add('code', 'commit', 'unknown', 'Cannot determine local git revision')
    for component in ('method', 'preprocess', 'train', 'evaluate'):
        paths = plan['repository'].get('components', {}).get(component, [])
        if not paths:
            add('code', 'component:' + component, 'unknown', 'No method-to-file mapping supplied')
        for name in paths:
            try:
                target = relative_path(repo, name)
                if name.endswith('.py'):
                    ast.parse(target.read_text(), filename=name)
                add('code', 'component:' + component + ':' + name, 'pass', 'Declared implementation file exists and Python syntax parses', {'sha256': fingerprint(target)['sha256']})
            except (OSError, ValueError, SyntaxError) as error:
                add('code', 'component:' + component + ':' + name, 'fail', str(error))
    semantic = plan['repository'].get('method_review', {})
    add('code', 'method_correspondence', 'pass' if semantic.get('reviewer') and semantic.get('source') and semantic.get('notes') and semantic.get('verified') is True else 'review_required',
        'File existence cannot prove that a method implements the paper; explicit source-grounded review required', semantic)

    for dataset in plan['datasets']:
        did = str(dataset.get('id', 'dataset'))
        source = dataset.get('source', {})
        add('data', 'source:' + did, 'pass' if source.get('url') and source.get('version') and source.get('license') else 'unknown', 'Dataset source, version and use conditions', source)
        access = source.get('access', 'public')
        if access == 'restricted':
            add('data', 'access:' + did, 'pass' if source.get('application') and source.get('approved') is True else 'fail', 'Restricted dataset requires application conditions and approved access; no credentials are collected')
        for item in dataset.get('files', []):
            file_check('data', item)
        if not dataset.get('files'):
            add('data', 'files:' + did, 'unknown', 'No actual data files declared')
        split_ids = {}
        split_spec = dataset.get('splits', {})
        if not split_spec:
            add('data', 'splits:' + did, 'unknown', 'No split provenance supplied')
        for name, item in split_spec.items():
            if name not in ('train', 'validation', 'test'):
                raise ValueError('Unknown data split')
            try:
                target = relative_path(repo, item['path'])
                if fingerprint(target)['sha256'] != item.get('sha256'):
                    raise ValueError('Split digest does not match declared source')
                if target.stat().st_size > 32*1024**2:
                    raise ValueError('Split ID list exceeds 32 MB')
                ids = target.read_text().splitlines()
                if len(ids) != len(set(ids)) or any(not i.strip() for i in ids):
                    raise ValueError('Duplicate or blank sample IDs inside a split')
                split_ids[name] = set(ids)
                add('data', 'split:' + did + ':' + name, 'pass', 'Actual sample IDs hashed and read', {'count': len(ids), 'sha256': item['sha256'], 'source': item.get('source')})
                if not item.get('source'):
                    add('data', 'split_source:' + did + ':' + name, 'unknown', 'Split generation source is missing')
            except (OSError, ValueError, KeyError) as error:
                add('data', 'split:' + did + ':' + name, 'fail', str(error))
        for a, b in itertools.combinations(split_ids, 2):
            overlap = split_ids[a] & split_ids[b]
            add('data', 'overlap:' + did + ':' + a + ':' + b, 'fail' if overlap else 'pass', 'Sample ID overlap checked', {'overlap_count': len(overlap), 'examples': sorted(overlap)[:10]})
        lineage = dataset.get('preprocessing', [])
        if not lineage and not dataset.get('preprocessing_not_applicable'):
            add('data', 'preprocessing:' + did, 'unknown', 'Declare transformations or explain why none apply')
        for step in lineage:
            if not step.get('command') or not step.get('inputs') or not step.get('outputs'):
                add('data', 'lineage:' + did, 'unknown', 'Preprocessing needs command, inputs and outputs')
            for item in step.get('inputs', []) + step.get('outputs', []):
                file_check('data', item)

    environment = plan['environment']
    for lock in environment.get('lockfiles', []):
        target, _, matched = file_check('environment', lock)
        if target and matched == 'pass' and target.name.startswith('requirements'):
            lines = [l.strip() for l in target.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]
            pinned = all(re.fullmatch(r'[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s;]+(?:\s*;.*)?', line) for line in lines)
            add('environment', 'pinned:' + lock['path'], 'pass' if pinned else 'fail', 'Requirements must use exact versions; other lock formats require their build verifier')
    if environment.get('dockerfile'):
        file_check('environment', {'path': environment['dockerfile'], 'sha256': environment.get('dockerfile_sha256')})
    add('environment', 'clean_build', 'unknown', 'Only an actual clean build and in-image verification can establish environment reconstruction')

    for exp in plan['experiments']:
        eid = exp['id']
        try:
            cfg = exp.get('config', {})
            target, actual, matched = file_check('settings', cfg)
            settings = load_json(target) if target else {}
            expected = cfg.get('expected', {})
            for key in SETTINGS:
                present = key in expected and expected[key] is not None and expected[key] != ''
                add('settings', eid + ':' + key, 'pass' if present and settings.get(key) == expected[key] and matched == 'pass' else 'fail', 'Actual configuration compared with declared paper setting', {'expected': expected.get(key), 'actual': settings.get(key), 'source': cfg.get('source')})
            if not cfg.get('source'):
                add('settings', eid + ':source', 'unknown', 'Settings need paper/README citations')
        except (OSError, ValueError) as error:
            add('settings', eid + ':config', 'fail', str(error))
        if exp.get('paper_experiment') not in inventory_ids:
            add('scope', eid + ':inventory_link', 'fail', 'Execution plan does not link to the paper-wide inventory')
        for stage in exp['stages']:
            add('commands', eid + ':' + stage['id'], 'unknown', 'Declared command; no execution record yet', {'argv': stage['argv'], 'inputs': stage['inputs'], 'outputs': stage['outputs'], 'needs': stage.get('needs', [])})
        add('acceptance', eid, 'unknown', 'Requires actual results for every planned seed and variant', {'seeds': exp['seeds'], 'variants': [v['id'] for v in exp['variants']], 'metric': exp['metric']})
    add('resources', 'runtime_measurement', 'unknown', 'Need measured execution resources, elapsed time and declared pricing; host snapshot is insufficient')
    summary = {d: {s: sum(c['dimension'] == d and c['status'] == s for c in checks) for s in ('pass', 'fail', 'unknown', 'review_required')} for d in DIMENSIONS}
    return {'format': 'articheck-reproduction-audit-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
            'plan_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(), 'checks': checks, 'dimensions': summary,
            'paper_candidates': list(candidates.values()), 'blocking_failures': sum(c['status'] == 'fail' for c in checks),
            'limitations': ['Scope/method review are explicit reviewer declarations.', 'No artifact code executed by audit.', 'Audit alone never certifies successful reproduction.']}
