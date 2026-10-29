"""Frozen paired percentile bootstrap; missing/failed runs are never silently dropped."""
from __future__ import annotations

import math
import random
import statistics

from .protocol import finite


def distribution(values):
    if not values:
        return {'n': 0, 'mean': None, 'sample_std': None, 'min': None, 'max': None}
    return {'n': len(values), 'mean': statistics.mean(values),
            'sample_std': statistics.stdev(values) if len(values) > 1 else None,
            'min': min(values), 'max': max(values)}


def quantile(values, q):
    pos = (len(values)-1)*q
    low = math.floor(pos)
    return values[low] + (values[math.ceil(pos)]-values[low])*(pos-low)


def paired_interval(deltas, confidence=.95, resamples=5000, seed=20261029):
    if len(deltas) < 2:
        return None
    finite(confidence)
    if not 0 < confidence < 1 or not 1000 <= resamples <= 20000:
        raise ValueError('Invalid bootstrap confidence/resample budget')
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(resamples))
    alpha = 1-confidence
    return [quantile(means, alpha/2), quantile(means, 1-alpha/2)]


def evaluate_experiment(experiment, rows):
    seeds = experiment['seeds']
    variants = {v['id']: v for v in experiment['variants']}
    by_key, invalid = {}, []
    for row in rows:
        key = (row.get('variant'), row.get('seed'))
        if key in by_key:
            raise ValueError('Duplicate run for variant and seed')
        if key[0] not in variants or key[1] not in seeds or type(key[1]) is not int:
            raise ValueError('Unexpected variant/seed result')
        by_key[key] = row
        value = row.get('metric')
        try:
            finite(value)
        except ValueError:
            invalid.append(key)
        if row.get('status') != 'completed' and key not in invalid:
            invalid.append(key)
    expected = {(v, s) for v in variants for s in seeds}
    missing = sorted(expected-set(by_key))
    good = {key: row['metric'] for key, row in by_key.items() if key not in invalid}
    aggregates = {}
    metric = experiment['metric']
    for vid, variant in variants.items():
        values = [good[(vid, s)] for s in seeds if (vid, s) in good]
        stats = distribution(values)
        complete = len(values) == len(seeds)
        reference = None
        if variant['role'] == 'method' and 'reference' in metric:
            reference = {'expected': metric['reference'], 'absolute_tolerance': metric['absolute_tolerance'],
                         'status': 'inconclusive' if not complete else 'within_tolerance' if abs(stats['mean']-metric['reference']) <= metric['absolute_tolerance'] else 'outside_tolerance'}
        aggregates[vid] = {**stats, 'complete': complete, 'reference_comparison': reference}
    comparisons = []
    planned = experiment.get('comparisons', [])
    # Family-wise alpha adjustment for all comparisons declared before execution.
    family_confidence = float(experiment.get('confidence', .95))
    if not 0 < family_confidence < 1:
        raise ValueError('Confidence must lie strictly between zero and one')
    confidence = 1-(1-family_confidence)/max(1, len(planned))
    minimum_runs = experiment.get('minimum_runs', 5)
    if type(minimum_runs) is not int or minimum_runs < 5:
        raise ValueError('Statistical acceptance requires at least five paired runs')
    sign = 1 if metric['direction'] == 'higher' else -1
    for spec in planned:
        method, other = spec['method'], spec['other']
        pairs = [s for s in seeds if (method, s) in good and (other, s) in good]
        deltas = [sign*(good[method, s]-good[other, s]) for s in pairs]
        full = len(pairs) == len(seeds) and len(pairs) >= minimum_runs
        interval = paired_interval(deltas, confidence=confidence) if full else None
        effect = spec.get('minimum_effect', 0)
        status = 'inconclusive' if interval is None else 'supported' if interval[0] > effect else 'not_supported' if interval[1] <= effect else 'inconclusive'
        comparisons.append({'method': method, 'other': other, 'paired_seeds': pairs,
                            'minimum_effect': effect, 'direction_adjusted_difference': distribution(deltas),
                            'confidence_interval': interval, 'per_comparison_confidence': confidence,
                            'family_confidence': family_confidence, 'methodology': 'paired percentile bootstrap; Bonferroni family adjustment; 5000 resamples; RNG seed 20261029',
                            'status': status, 'reason': 'All planned pairs required; at least five seeds' if not full else 'Interval compared to preregistered minimum effect'})
    all_complete = not missing and not invalid
    reference_failed = any(a['reference_comparison'] and a['reference_comparison']['status'] == 'outside_tolerance' for a in aggregates.values())
    status = 'inconclusive' if not all_complete else 'not_supported' if reference_failed or any(c['status'] == 'not_supported' for c in comparisons) else 'supported' if comparisons and all(c['status'] == 'supported' for c in comparisons) else 'inconclusive'
    return {'experiment_id': experiment['id'], 'status': status, 'variants': aggregates,
            'missing_runs': missing, 'invalid_runs': invalid, 'comparisons': comparisons,
            'reference_alignment_only': all_complete and any(a['reference_comparison'] for a in aggregates.values()) and not reference_failed,
            'limitations': ['Statistical support is conditional on this frozen protocol and declared population.', 'Reference alignment without baseline/ablation evidence does not establish main conclusions.']}
