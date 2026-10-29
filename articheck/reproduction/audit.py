from __future__ import annotations

import ast
import hashlib
import itertools
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .protocol import DIMENSIONS, fingerprint, load_json, load_plan, relative_path, validate_snapshot, object_value, same_json
from .paper_text import extract_paper

SETTINGS = ('hyperparameters', 'initialization', 'augmentation', 'selection', 'stopping')


def audit_plan(path, *, workspace=None, imported=None, repo_override=None):
    """Read actual bytes only; never imports or executes artifact code."""
    plan, repo, plan_sha = load_plan(path, workspace, with_digest=True)
    base = Path(path).resolve().parent
    if repo_override is not None:
        repo = Path(repo_override).resolve()
    checks = []
    def add(dimension, code, status, detail, evidence=None):
        checks.append({'dimension': dimension, 'code': code, 'status': status, 'detail': detail,
                       'evidence': evidence or {}})
    def file_check(dimension, entry, root=repo, origin=None):
        name = entry.get('path', '')
        try:
            target = relative_path(root, name)
            actual = fingerprint(target)
            expected = entry.get('sha256') or entry.get('git_blob_sha')
            key = 'sha256' if entry.get('sha256') else 'git_blob_sha'
            status = 'pass' if expected and actual[key] == expected else 'fail' if expected else 'unknown'
            add(dimension, 'file:' + name, status, 'Content digest compared' if expected else 'No reference digest supplied',
                {'path': name, 'actual': actual, 'expected': {key: expected}, 'reference_source': origin or 'declared_manifest'})
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
    if paper.get('path'):
        try:
            actual_pages,origin=extract_paper(relative_path(base,paper['path']))
            if actual_pages is not None:
                matches=same_json([{'number':p['number'],'text':p['text']} for p in pages],actual_pages)
                add('scope','paper_text_origin','pass' if matches else 'fail','Citations use independently extracted paper text; supplied text mismatch remains a contradiction',origin)
                pages=actual_pages
            else:
                add('scope','paper_text_origin','unknown','Paper text extraction format is unsupported',origin);pages=[]
        except (OSError,ValueError) as error:
            add('scope','paper_text_origin','fail',str(error));pages=[]
    else:pages=[]
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
    exclusions=paper.get('excluded_references',{})
    classified = set(itertools.chain.from_iterable(x.get('labels', []) for x in inventory))
    for label,reason in exclusions.items():
        valid=isinstance(reason,str) and bool(reason.strip())
        add('scope','excluded:'+label,'pass' if valid else 'review_required','Excluded figure/table needs an explicit reason',{'reason':reason})
        if valid:classified.add(label)
    for label, item in candidates.items():
        add('scope', 'unclassified:' + label, 'pass' if label in classified else 'review_required',
            'Figure/table reference classified' if label in classified else 'Unclassified paper reference; may be a missing experiment or a citation', item)
    for claim in paper.get('conclusions',[]):
        quote=claim.get('quote','')
        add('scope','conclusion_source:'+str(claim.get('id')),
            'pass' if isinstance(quote,str) and quote and quote in page_map.get(claim.get('page'),'') else 'review_required',
            'Main conclusion requires a grounded paper-page citation',{'page':claim.get('page'),'quote':quote})
    selected = {e.get('paper_experiment') for e in plan['experiments']}
    for row in inventory:
        if row.get('core'):
            add('scope', 'coverage:' + row['id'], 'pass' if row['id'] in selected else 'fail', 'Core experiment must have an execution plan')
    if not inventory or not paper.get('conclusions'):
        add('scope', 'inventory', 'unknown', 'Need paper-wide experiments and main conclusions')
    review = paper.get('inventory_review', {})
    add('scope', 'inventory_review', 'pass' if review.get('complete') is True and review.get('reviewer') and review.get('notes') else 'review_required',
        'Human inventory review is a declaration, not inferred from selected easy experiments', review)

    source = validate_snapshot(imported) if imported is not None else plan['repository']
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
        file_check('code', entry, origin='imported_snapshot' if imported is not None else 'plan_reference')
    if imported is not None:
        # The selected upload and the paper-plan reference are independent constraints.
        # Never replace a bad paper reference with a newly hashed upload.
        for entry in plan['repository'].get('files', []):
            file_check('code', entry, origin='plan_reference')
            seen.add(entry['path'])
    declared=set(seen)
    for exp in plan['experiments']:
        if exp.get('config',{}).get('path'):declared.add(exp['config']['path'])
    for lock in plan['environment'].get('lockfiles',[]):declared.add(lock['path'])
    if plan['environment'].get('dockerfile'):declared.add(plan['environment']['dockerfile'])
    if not plan['datasets']:
        add('data','dataset_provenance','unknown','Declare actual data provenance or a source-grounded generator protocol')
    for dataset in plan['datasets']:
        declared.update(x['path'] for x in dataset.get('files',[]))
        declared.update(x['path'] for x in dataset.get('splits',{}).values())
        for step in dataset.get('preprocessing',[]):
            declared.update(x['path'] for x in step.get('inputs',[])+step.get('outputs',[]))
    extras=[];inventory_count=0
    for directory,dirs,files in os.walk(repo,followlinks=False):
        dirs[:]=[d for d in dirs if d not in {'.git','.venv','node_modules','__pycache__'}]
        for name in dirs+files:
            item=Path(directory)/name
            if item.is_symlink():add('code','source_symlink','fail','Source contains a symlink',{'path':item.relative_to(repo).as_posix()})
        for name in files:
            rel=(Path(directory)/name).relative_to(repo).as_posix();inventory_count+=1
            if inventory_count>10000:raise ValueError('Source inventory exceeds 10000 files')
            if rel not in declared:extras.append(rel)
    add('code','undeclared_source_files','fail' if extras else 'pass','Actual source inventory compared with imported and explicitly declared inputs',{'extra_files':extras[:100],'extra_count':len(extras)})
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
    semantic_grounded=bool(semantic.get('citations'))
    for index,citation in enumerate(semantic.get('citations',[])):
        grounded=citation['quote'] in page_map.get(citation['page'],'') and bool(citation['paths']);files={}
        for name in citation['paths']:
            try:files[name]=fingerprint(relative_path(repo,name))
            except (OSError,ValueError):grounded=False
        semantic_grounded=semantic_grounded and grounded
        add('code','method_source:'+str(index),'pass' if grounded else 'fail','Method mapping quote checked against PDF text and actual source files',{'citation':citation,'files':files})
    add('code', 'method_correspondence', 'pass' if semantic_grounded and semantic.get('reviewer') and semantic.get('source') and semantic.get('notes') and semantic.get('verified') is True else 'review_required',
        'File existence cannot prove method semantics; requires a named review with actual page/quote/file mappings', semantic)

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
    expected_packages=environment.get('expected',{}).get('packages',{})
    normalized_packages={re.sub(r'[-_.]+','-',k).lower():v for k,v in expected_packages.items()}
    dockerfile_text=''
    if environment.get('dockerfile'):
        try:dockerfile_text=relative_path(repo,environment['dockerfile']).read_text()
        except (OSError,ValueError):pass
    bases=re.findall(r'^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)',dockerfile_text,re.M|re.I)
    immutable=bool(bases) and all(re.fullmatch(r'\S+@sha256:[0-9a-f]{64}',x) for x in bases)
    add('environment','immutable_base','pass' if immutable else 'unknown','Every external FROM image needs an immutable digest for repeatable reconstruction',{'from_images':bases})
    for lock in environment.get('lockfiles', []):
        target, _, matched = file_check('environment', lock)
        if target and matched == 'pass' and target.name.startswith('requirements'):
            lines = [l.strip() for l in target.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]
            pinned = all(re.fullmatch(r'[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s;]+(?:\s*;.*)?', line) for line in lines)
            add('environment', 'pinned:' + lock['path'], 'pass' if pinned else 'fail', 'Requirements must use exact versions; other lock formats require their build verifier')
            plain=[re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)',line) for line in lines]
            matches=pinned and all(m and normalized_packages.get(re.sub(r'[-_.]+','-',m[1]).lower())==m[2] for m in plain)
            add('environment','lock_snapshot:'+lock['path'],'pass' if matches else 'unknown','Every simple locked package must have a matching observed-version expectation; markers/extras require a project verifier')
        elif target and matched=='pass':
            try:
                custom=load_json(target)
                valid=isinstance(custom,dict) and custom.get('base_image') in bases and bool(custom.get('dependencies')) and immutable
            except (ValueError,OSError):valid=False
            add('environment','lock_snapshot:'+lock['path'],'pass' if valid else 'unknown','Custom source-build lock must bind its immutable base and describe bundled dependencies; unsupported lock formats remain unresolved')
    if environment.get('dockerfile'):
        file_check('environment', {'path': environment['dockerfile'], 'sha256': environment.get('dockerfile_sha256')})
    add('environment', 'clean_build', 'unknown', 'Only an actual clean build and in-image verification can establish environment reconstruction')

    for exp in plan['experiments']:
        eid = exp['id']
        try:
            cfg = exp.get('config', {})
            target, actual, matched = file_check('settings', cfg)
            settings = object_value(load_json(target),'configuration file') if target else {}
            expected = object_value(cfg.get('expected', {}),'expected configuration')
            for key in SETTINGS:
                present = key in expected and expected[key] is not None and expected[key] != ''
                add('settings', eid + ':' + key, 'pass' if present and same_json(settings.get(key),expected[key]) and matched == 'pass' else 'fail', 'Actual configuration compared with declared paper setting', {'expected': expected.get(key), 'actual': settings.get(key), 'source': cfg.get('source')})
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
            'plan_sha256': plan_sha, 'imported_material': {k:imported[k] for k in ('kind','archive_sha256','commit') if imported and k in imported}, 'checks': checks, 'dimensions': summary,
            'paper_candidates': list(candidates.values()), 'blocking_failures': sum(c['status'] == 'fail' for c in checks),
            'coverage':{'inventory_review':review,'method_review':semantic,'conclusions':paper.get('conclusions',[]),
                        'excluded_references':exclusions,'experiments':[{**item,'execution_ids':[e['id'] for e in plan['experiments'] if e.get('paper_experiment')==item['id']]} for item in inventory]},
            'limitations': ['Scope/method review are explicit reviewer declarations.', 'No artifact code executed by audit.', 'Audit alone never certifies successful reproduction.']}
