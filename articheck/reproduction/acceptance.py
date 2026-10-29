"""Evidence-derived milestones and scientific gates; no success from a score alone."""
from __future__ import annotations
import json
from .protocol import fingerprint, load_json, relative_path
from .verification import verify_splits


def verify_training(work, experiment, stage, configuration, prior_models=None):
    spec=experiment.get('training_evidence')
    if not spec or spec.get('stage_id')!=stage['id']:return None
    if stage.get('kind')!='train':raise ValueError('Training evidence must reference a typed training stage')
    if spec['used_config_path'] not in stage['outputs'] or spec['used_config_path']=='config.json':raise ValueError('Used-configuration record must be a distinct declared training output')
    used_path=relative_path(work,spec['used_config_path'])
    if load_json(used_path)!=configuration:raise ValueError('Program-reported used configuration differs from frozen run configuration')
    models={}
    if not spec.get('model_outputs'):raise ValueError('Training proof needs model outputs')
    for name in spec['model_outputs']:
        if name not in stage['outputs']:raise ValueError('Model must be a declared output of the training stage')
        models[name]=fingerprint(relative_path(work,name))
        if prior_models and prior_models.get(name)==models[name]:raise ValueError('Model output did not change; retraining was not established')
        if models[name]['bytes']==0:raise ValueError('Training model output is empty')
    return {'status':'verified','stage_id':stage['id'],'model_fingerprints':models,
            'used_config_sha256':fingerprint(used_path)['sha256'],
            'scope':'Declared training command produced models and matching configuration; source/method correspondence is reviewed separately'}


def verify_fairness(experiment, rows):
    policy=experiment.get('fairness',{})
    reasons=[]
    if not policy.get('source') or policy.get('selection_protocol') not in ('none','validation_only'):
        reasons.append('Declare a source-grounded model-selection protocol; test-set tuning is not accepted')
    if policy.get('selection_protocol')=='validation_only' and (not policy.get('tuning_budget') or not policy.get('validation_ids')):
        reasons.append('Validation selection needs a frozen validation split and matching tuning budgets')
    mapping={(row['variant'],row['seed']):row for row in rows}
    for comparison in experiment.get('comparisons',[]):
        allowed=set(policy.get('allowed_variant_differences',{}).get(comparison['other'],[]))
        for seed in experiment['seeds']:
            left=mapping.get((comparison['method'],seed));right=mapping.get((comparison['other'],seed))
            if not left or not right or left['status']!='completed' or right['status']!='completed':
                reasons.append('Missing or failed control pair');continue
            a=left.get('configuration',{});b=right.get('configuration',{})
            if not a or not b:reasons.append('Actual configuration snapshots are missing');continue
            for key in (set(a)|set(b))-{'variant','seed'}:
                if a.get(key)!=b.get(key):reasons.append('Uncontrolled configuration difference: '+key)
            av=a.get('variant',{}).get('settings',{});bv=b.get('variant',{}).get('settings',{})
            differing={k for k in set(av)|set(bv) if av.get(k)!=bv.get(k)}
            if not differing.issubset(allowed):reasons.append('Variant settings differ beyond preregistered factors')
            la=left.get('split_verification');lb=right.get('split_verification')
            if not la or not lb:reasons.append('Actual generated split verification is missing');continue
            for name in set(la['splits'])|set(lb['splits']):
                if la['splits'].get(name,{}).get('fingerprint')!=lb['splits'].get(name,{}).get('fingerprint'):
                    reasons.append('Control uses different sample IDs: '+name)
            if policy.get('selection_protocol')=='validation_only' and 'validation' not in la['splits']:
                reasons.append('Validation split not independently verified')
            input_a=left.get('training_inputs');input_b=right.get('training_inputs')
            if not input_a or not input_b:reasons.append('Actual training input fingerprints are missing')
            else:
                allowed_inputs=set(policy.get('allowed_input_differences',[]))
                for name in (set(input_a)|set(input_b))-allowed_inputs:
                    if input_a.get(name)!=input_b.get(name):reasons.append('Control consumed different training input: '+name)
            if left.get('execution_limits')!=right.get('execution_limits'):
                reasons.append('Execution resource or stage budgets differ')
    return {'status':'verified' if not reasons else 'unverified','reasons':sorted(set(reasons)),
            'protocol':policy,'scope':'Equality checks are relative to preregistered factors, splits and budgets; optimality of a baseline is not inferred'}


def evaluate_levels(plan, audit, environment, rows, results, status):
    run=status=='completed' and bool(rows) and all(row['status']=='completed' for row in rows)
    rebuilt=bool(environment and environment.get('status')=='built' and environment.get('verification')=='passed' and environment.get('compatibility',{}).get('status')=='verified')
    training_reasons=[];conclusion_reasons=[]
    if not run:training_reasons.append('Not all planned runs completed')
    if not rebuilt:training_reasons.append('Clean environment reconstruction was not verified')
    for experiment in plan['experiments']:
        for row in [r for r in rows if r['experiment']==experiment['id']]:
            if row.get('training_evidence',{}).get('status')!='verified':training_reasons.append('Missing validated training/model/configuration evidence')
            if not row.get('independent_metric'):training_reasons.append('Evaluation metric was not independently recomputed')
            if not row.get('split_verification'):training_reasons.append('Actual data splits were not verified')
        expected=len(experiment['seeds'])*len(experiment['variants'])
        if len([r for r in rows if r['experiment']==experiment['id']])!=expected:training_reasons.append('Run matrix is incomplete')
        if experiment.get('deviations'):training_reasons.append('Declared protocol deviations prevent claiming original-paper training reproduction')
    for check in audit.get('checks',[]):
        if check['dimension'] in ('code','settings') and check['status']!='pass':training_reasons.append('Unresolved method/configuration correspondence: '+check['code'])
        if check['dimension']=='environment' and check['code']!='clean_build' and check['status']!='pass':training_reasons.append('Unresolved environment/lock correspondence: '+check['code'])
    training=not training_reasons
    # Main conclusions depend on actual coverage and source-grounded reviews as well as outcomes.
    for check in audit.get('checks',[]):
        if check['dimension'] in ('scope','code','settings') and check['status']!='pass':
            conclusion_reasons.append('Unresolved '+check['dimension']+' check: '+check['code'])
        if check['dimension']=='data' and check['status']!='pass':
            runtime_splits=check['code'].startswith('splits:') and rows and all(r.get('split_verification') for r in rows)
            if not runtime_splits:conclusion_reasons.append('Unresolved data provenance: '+check['code'])
    inventory=plan['paper'].get('experiments',[])
    if not inventory or not plan['paper'].get('conclusions'):conclusion_reasons.append('Paper-wide inventory or main conclusions are missing')
    for claim in plan['paper'].get('conclusions',[]):
        supporting=[x for x in inventory if x.get('core') and claim.get('id') in x.get('conclusion_ids',[])]
        if not supporting:conclusion_reasons.append('Main conclusion has no mapped core experiment: '+str(claim.get('id')))
    if not training:conclusion_reasons.append('Training reproduction gate is not satisfied')
    if len(results)!=len(plan['experiments']):conclusion_reasons.append('Experiment acceptance is incomplete')
    for result in results:
        if result.get('status')!='supported':conclusion_reasons.append('Comparison/reference acceptance not supported: '+result['experiment_id'])
        if result.get('fairness',{}).get('status')!='verified':conclusion_reasons.append('Control fairness is not verified')
    for experiment in plan['experiments']:
        roles={v['role'] for v in experiment['variants']}
        if 'baseline' not in roles:conclusion_reasons.append('No actual baseline comparison')
        if 'ablation' not in roles and not experiment.get('ablation_not_applicable',{}).get('source'):
            conclusion_reasons.append('Ablation evidence or source-grounded non-applicability is missing')
        compared={c['other'] for c in experiment.get('comparisons',[])}
        if any(v['role'] in ('baseline','ablation') and v['id'] not in compared for v in experiment['variants']):
            conclusion_reasons.append('A declared control has no preregistered comparison')
    reasons={'training':sorted(set(training_reasons)),'conclusion':sorted(set(conclusion_reasons))}
    return {'run':run,'environment_rebuilt':rebuilt,'training':training,'conclusion':not conclusion_reasons}, reasons
