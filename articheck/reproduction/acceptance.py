"""Evidence-derived milestones and scientific gates; no success from a score alone."""
from __future__ import annotations
import json
from .protocol import fingerprint, load_json, relative_path, same_json
from .verification import verify_splits, recompute_metric


def verify_selection(repo,work,experiment,stage,configuration,models,elapsed):
    policy=experiment.get('fairness',{})
    if policy.get('selection_protocol')!='validation_only':return None
    budget=policy.get('tuning_budget',{});space=policy.get('search_space',{});spec=policy.get('validation_metric',{})
    record_path=experiment.get('training_evidence',{}).get('selection_record_path')
    if not record_path or record_path not in stage['outputs']:raise ValueError('Validation selection needs a declared training search-record output')
    if not budget.get('max_trials') or not budget.get('max_seconds') or not space:raise ValueError('Validation selection requires a frozen search space and trial/time budget')
    if elapsed>budget['max_seconds'] or stage.get('timeout_seconds',300)>budget['max_seconds']:raise ValueError('Actual search stage or timeout exceeds frozen tuning budget')
    split=experiment.get('split_ids',{}).get('validation',{})
    if not split or spec.get('ids_path')!=split.get('path'):raise ValueError('Selection must use the independently verified validation split')
    record=load_json(relative_path(work,record_path))
    if not isinstance(record,dict) or record.get('protocol')!='validation_only' or type(record.get('seed')) is not int or record.get('seed')!=configuration['seed']:raise ValueError('Search record protocol/seed does not match frozen run')
    trials=record.get('trials',[])
    if not isinstance(trials,list) or not 1<=len(trials)<=budget['max_trials'] or any(not isinstance(t,dict) for t in trials):raise ValueError('Invalid trial count or search trace')
    ids=set();proof=[]
    for trial in trials:
        tid=trial.get('id');settings=trial.get('settings')
        if not isinstance(tid,str) or not tid or tid in ids:raise ValueError('Trial IDs must be unique text')
        ids.add(tid)
        if not isinstance(settings,dict) or set(settings)!=set(space) or any(not any(same_json(settings[k],candidate) for candidate in space[k]) for k in space):raise ValueError('Trial settings are outside the preregistered search space')
        predictions=trial.get('records_path');model=trial.get('model_path')
        if predictions not in stage['outputs'] or model not in stage['outputs']:raise ValueError('Trial predictions and model must be declared training outputs')
        metric=recompute_metric(repo,work,{**spec,'records_path':predictions})
        proof.append({'id':tid,'settings':settings,'metric':metric,'model':fingerprint(relative_path(work,model))})
    selected=next((t for t in proof if t['id']==record.get('selected_trial_id')),None)
    if selected is None:raise ValueError('Selected trial is absent from verified search trace')
    values=[t['metric']['value'] for t in proof];best=(min if spec.get('direction')=='lower' else max)(values)
    if selected['metric']['value']!=best:raise ValueError('Selected trial does not optimize the frozen validation metric')
    if len(models)!=1 or next(iter(models.values()))!=selected['model']:raise ValueError('Final model differs from the selected validation-trial model')
    return {'status':'verified','budget':budget,'actual_trials':len(proof),'actual_stage_seconds':elapsed,'selected_trial_id':selected['id'],
            'validation_ids_sha256':fingerprint(relative_path(work,split['path']))['sha256'],'trials':proof,
            'scope':'Recorded trials independently scored on frozen validation labels; source review must establish that the record covers the actual search and that test data was not used'}


def verify_training(work, experiment, stage, configuration, prior_models=None, *, repo=None, elapsed=0):
    spec=experiment.get('training_evidence')
    if not spec or spec.get('stage_id')!=stage['id']:return None
    if stage.get('kind')!='train':raise ValueError('Training evidence must reference a typed training stage')
    if spec['used_config_path'] not in stage['outputs'] or spec['used_config_path']=='config.json':raise ValueError('Used-configuration record must be a distinct declared training output')
    used_path=relative_path(work,spec['used_config_path'])
    if not same_json(load_json(used_path),configuration):raise ValueError('Program-reported used configuration differs from frozen run configuration')
    models={}
    if not spec.get('model_outputs'):raise ValueError('Training proof needs model outputs')
    for name in spec['model_outputs']:
        if name not in stage['outputs']:raise ValueError('Model must be a declared output of the training stage')
        models[name]=fingerprint(relative_path(work,name))
        if prior_models and prior_models.get(name)==models[name]:raise ValueError('Model output did not change; retraining was not established')
        if models[name]['bytes']==0:raise ValueError('Training model output is empty')
    selection=verify_selection(repo,work,experiment,stage,configuration,models,elapsed)
    return {'status':'verified','stage_id':stage['id'],'model_fingerprints':models,'selection':selection,
            'used_config_sha256':fingerprint(used_path)['sha256'],
            'scope':'Declared training command produced models and matching configuration; source/method correspondence is reviewed separately'}


def verify_fairness(experiment, rows):
    policy=experiment.get('fairness',{})
    reasons=[]
    if not policy.get('source') or policy.get('selection_protocol') not in ('none','validation_only'):
        reasons.append('Declare a source-grounded model-selection protocol; test-set tuning is not accepted')
    if policy.get('selection_protocol')=='validation_only' and (not policy.get('tuning_budget') or not policy.get('validation_metric')):
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
                if not same_json(a.get(key),b.get(key)):reasons.append('Uncontrolled configuration difference: '+key)
            av=a.get('variant',{}).get('settings',{});bv=b.get('variant',{}).get('settings',{})
            differing={k for k in set(av)|set(bv) if not same_json(av.get(k),bv.get(k))}
            if not differing.issubset(allowed):reasons.append('Variant settings differ beyond preregistered factors')
            la=left.get('split_verification');lb=right.get('split_verification')
            if not la or not lb:reasons.append('Actual generated split verification is missing');continue
            for name in set(la['splits'])|set(lb['splits']):
                if la['splits'].get(name,{}).get('fingerprint')!=lb['splits'].get(name,{}).get('fingerprint'):
                    reasons.append('Control uses different sample IDs: '+name)
            if policy.get('selection_protocol')=='validation_only' and 'validation' not in la['splits']:
                reasons.append('Validation split not independently verified')
            if policy.get('selection_protocol')=='validation_only' and any((row.get('training_evidence',{}).get('selection') or {}).get('status')!='verified' for row in (left,right)):
                reasons.append('Search traces, selected models and actual tuning budgets were not verified')
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
        if check['dimension']=='scope' and (check['code'] in ('paper_identity','paper_text_origin') or check['code'].startswith('file:')) and check['status']!='pass':training_reasons.append('Paper identity/text is not verified: '+check['code'])
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
