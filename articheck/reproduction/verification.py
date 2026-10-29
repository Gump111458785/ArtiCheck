"""Independent output verification; artifact-reported scores are compared, not trusted."""
from __future__ import annotations
import itertools
import json
import math
from pathlib import Path

from .protocol import finite, fingerprint, relative_path


def ids_from_file(root, path):
    target=relative_path(root,path)
    if target.stat().st_size > 32*1024**2:
        raise ValueError('Sample ID file exceeds 32 MB')
    ids=target.read_text().splitlines()
    if not ids or len(ids)!=len(set(ids)) or any(not x.strip() for x in ids):
        raise ValueError('Expected nonempty unique sample IDs')
    return ids


def verify_splits(root, spec):
    results={};sets={}
    for name,item in spec.items():
        if name not in ('train','validation','test'):
            raise ValueError('Unknown split')
        ids=ids_from_file(root,item['path']);sets[name]=set(ids)
        if item.get('count') is not None and len(ids)!=item['count']:
            raise ValueError('Split size does not match frozen protocol: '+name)
        results[name]={'count':len(ids),'fingerprint':fingerprint(relative_path(root,item['path']))}
    for a,b in itertools.combinations(sets,2):
        if sets[a]&sets[b]:
            raise ValueError('Actual generated splits overlap: '+a+'/'+b)
    return {'status':'verified','splits':results,'pairwise_overlap':0}


def jsonl_records(path, limit=1_000_000):
    if Path(path).stat().st_size > 128*1024**2:
        raise ValueError('Evaluation records exceed 128 MB')
    values={}
    with Path(path).open() as stream:
        for index,line in enumerate(stream):
            if index >= limit:raise ValueError('Too many evaluation records')
            row=json.loads(line,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite record')))
            key=row.get('id')
            if not isinstance(key,str) or not key or key in values:
                raise ValueError('Duplicate or invalid evaluation sample ID')
            values[key]=row
    if not values:raise ValueError('No evaluation records')
    return values


def recompute_metric(repo, work, spec):
    name=spec['implementation']
    if name not in ('accuracy','macro_f1','mse','mae'):
        raise ValueError('Unsupported independent metric implementation')
    predictions_path=relative_path(work,spec['records_path'])
    targets_path=relative_path(repo,spec['targets_path'])
    if fingerprint(targets_path)['sha256']!=spec.get('targets_sha256'):
        raise ValueError('Reference target content changed')
    predictions=jsonl_records(predictions_path);targets=jsonl_records(targets_path)
    expected_ids=set(ids_from_file(work,spec['ids_path']))
    if set(predictions)!=expected_ids:
        raise ValueError('Prediction IDs do not exactly cover the declared evaluation split')
    if not expected_ids.issubset(targets):
        raise ValueError('Evaluation split IDs are absent from frozen targets')
    pairs=[]
    for key in sorted(expected_ids):
        target=targets[key]['target'];prediction=predictions[key]['prediction']
        # The artifact may include targets for convenience, but cannot redefine truth.
        if 'target' in predictions[key] and predictions[key]['target']!=target:
            raise ValueError('Artifact changed reference target labels')
        if name in ('mse','mae'):
            finite(target);finite(prediction)
        else:
            for item in (target,prediction):
                if isinstance(item,bool) or not isinstance(item,(str,int,float)) or isinstance(item,float) and not math.isfinite(item):
                    raise ValueError('Invalid class label')
        pairs.append((target,prediction))
    if name=='accuracy':value=sum(a==b for a,b in pairs)/len(pairs)
    elif name in ('mse','mae'):
        value=sum((a-b)**2 if name=='mse' else abs(a-b) for a,b in pairs)/len(pairs)
    else:
        labels={x for pair in pairs for x in pair};scores=[]
        for label in labels:
            tp=sum(a==label and b==label for a,b in pairs)
            fp=sum(a!=label and b==label for a,b in pairs)
            fn=sum(a==label and b!=label for a,b in pairs)
            scores.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
        value=sum(scores)/len(scores)
    finite(value)
    return {'implementation':name,'value':value,'n':len(pairs),'records_sha256':fingerprint(predictions_path)['sha256'],
            'reference_targets_sha256':spec['targets_sha256'],'source':'ArtiCheck independent metric over frozen target labels and exact split IDs'}
