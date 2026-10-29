from __future__ import annotations
import copy
import json
import tempfile
import unittest
from pathlib import Path
from articheck.reproduction.engine import reproduce
from articheck.reproduction.acceptance import evaluate_levels
from articheck.reproduction.protocol import fingerprint
from test_reproduction import fixture,write


class AcceptanceEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, transform=None, complete=True):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);path,plan,repo=fixture(root,complete=complete)
        if transform:transform(plan,repo)
        for item in plan['repository']['files']:
            item['sha256']=fingerprint(repo/item['path'])['sha256']
        write(path,plan)
        report=await reproduce(path,root/'run',mode='local',allow_local_trusted=True)
        return plan,report,root
    async def test_successful_models_used_configs_independent_metrics_and_fair_controls(self):
        plan,r,root=await self.scenario()
        self.assertEqual(r['status'],'completed',r['errors'])
        self.assertEqual(r['experiments'][0]['fairness']['status'],'verified')
        self.assertTrue(all(row['training_evidence']['status']=='verified' and row['independent_metric'] for row in r['runs']))
        self.assertFalse(r['levels']['training']) # Local mode never invents a rebuilt environment.
        proof_audit={**r['audit'],'checks':[c for c in r['audit']['checks'] if c['dimension']!='environment']}
        levels,reasons=evaluate_levels(plan,proof_audit,{'status':'built','verification':'passed','compatibility':{'status':'verified'}},r['runs'],r['experiments'],r['status'])
        self.assertTrue(levels['training'],reasons);self.assertTrue(levels['conclusion'],reasons)
        # The actual positive environment proof is exercised in the Docker CI integration.
    async def test_wrong_used_configuration_fails_before_evaluation(self):
        def bad(plan,repo):
            plan['experiments'][0]['seeds']=[11]
            code=(repo/'experiment.py').read_text().replace("Path('used-config.json').write_text(Path(cfg_path).read_text())","Path('used-config.json').write_text('{}')")
            (repo/'experiment.py').write_text(code)
        plan,r,root=await self.scenario(bad)
        self.assertEqual(r['status'],'failed');self.assertFalse(r['levels']['training'])
        self.assertTrue(all(len(row['stages'])==2 for row in r['runs']))
        self.assertTrue(any('configuration differs' in stage.get('output_error','') for row in r['runs'] for stage in row['stages']))
    async def test_actual_generated_overlap_stops_before_training(self):
        def bad(plan,repo):
            plan['experiments'][0]['seeds']=[11]
            injection="    Path('train.ids').write_text(chr(10).join(['test-0']+['train-'+str(i) for i in range(20)]))\n"
            code=(repo/'experiment.py').read_text().replace("elif stage=='train':",injection+"elif stage=='train':")
            (repo/'experiment.py').write_text(code)
        plan,r,root=await self.scenario(bad)
        self.assertEqual(r['status'],'failed');self.assertTrue(all(len(row['stages'])==1 for row in r['runs']))
        self.assertTrue(any('overlap' in stage.get('output_error','') for row in r['runs'] for stage in row['stages']))
    async def test_different_control_data_is_not_accepted_despite_completed_commands(self):
        def bad(plan,repo):
            injection="    if cfg['variant']['id']=='baseline':\n        data=json.loads(Path('prepared.json').read_text());data['train'][0][1]+=100;Path('prepared.json').write_text(json.dumps(data))\n"
            (repo/'experiment.py').write_text((repo/'experiment.py').read_text().replace("elif stage=='train':",injection+"elif stage=='train':"))
        plan,r,root=await self.scenario(bad)
        self.assertEqual(r['status'],'completed',r['errors'])
        self.assertEqual(r['experiments'][0]['status'],'inconclusive')
        self.assertTrue(any('different training input' in reason for reason in r['experiments'][0]['fairness']['reasons']))
        self.assertFalse(r['levels']['conclusion'])
    async def test_replacing_model_after_training_prevents_acceptance(self):
        def bad(plan,repo):
            plan['experiments'][0]['seeds']=[11]
            code=(repo/'experiment.py').read_text().replace("model=json.loads(Path('model.json').read_text());data=", "model=json.loads(Path('model.json').read_text());Path('model.json').write_text('{}');data=")
            (repo/'experiment.py').write_text(code)
        plan,r,root=await self.scenario(bad)
        self.assertEqual(r['status'],'failed');self.assertFalse(r['levels']['training'])
        self.assertTrue(any('model.json' in stage.get('output_error','') for row in r['runs'] for stage in row['stages']))
    async def test_uncovered_core_experiment_and_protocol_deviations_keep_main_gate_closed(self):
        plan,r,root=await self.scenario(complete=False)
        proof_audit={**r['audit'],'checks':[c for c in r['audit']['checks'] if c['dimension']!='environment']}
        levels,reasons=evaluate_levels(plan,proof_audit,{'status':'built','verification':'passed','compatibility':{'status':'verified'}},r['runs'],r['experiments'],r['status'])
        self.assertFalse(levels['conclusion']);self.assertTrue(any('scope' in reason for reason in reasons['conclusion']))
        plan['experiments'][0]['deviations']=['Different author split']
        proof_audit={**r['audit'],'checks':[c for c in r['audit']['checks'] if c['dimension']!='environment']}
        levels,reasons=evaluate_levels(plan,proof_audit,{'status':'built','verification':'passed','compatibility':{'status':'verified'}},r['runs'],r['experiments'],r['status'])
        self.assertFalse(levels['training']);self.assertTrue(any('deviations' in reason for reason in reasons['training']))

    async def test_validation_search_is_independently_scored_and_model_selection_verified(self):
        def configure(plan,repo):
            exp=plan['experiments'][0];exp['seeds']=[11]
            code=(repo/'experiment.py').read_text()
            code=code.replace("elif stage=='train':","    Path('validation.ids').write_text('val-0\\nval-1\\n')\n"+"elif stage=='train':")
            addition="""    model=json.loads(Path('model.json').read_text())
    for name,wrong in [('trial-1',False),('trial-2',True)]:
        predictions=[100,100] if wrong else [model['slope']*x+model['intercept'] for x in [1.5,2.5]]
        Path(name+'.jsonl').write_text(''.join(json.dumps({'id':'val-'+str(i),'prediction':v})+'\\n' for i,v in enumerate(predictions)))
        Path(name+'-model.json').write_text('{}' if wrong else Path('model.json').read_text())
    trace={'protocol':'validation_only','seed':seed,'selected_trial_id':'trial-1','trials':[{'id':name,'settings':{'candidate':i},'records_path':name+'.jsonl','model_path':name+'-model.json'} for i,name in enumerate(['trial-1','trial-2'])]}
    Path('selection.json').write_text(json.dumps(trace))
"""
            code=code.replace("elif stage=='evaluate':",addition+"elif stage=='evaluate':")
            (repo/'experiment.py').write_text(code)
            with (repo/'targets.jsonl').open('a') as out:
                out.write(''.join(json.dumps({'id':'val-'+str(i),'target':v})+'\n' for i,v in enumerate([8,10])))
            sha=fingerprint(repo/'targets.jsonl')['sha256'];exp['metric']['targets_sha256']=sha
            for item in plan['datasets'][0]['files']:
                if item['path']=='targets.jsonl':item['sha256']=sha
            exp['split_ids']['validation']={'path':'validation.ids','count':2};exp['stages'][0]['outputs'].append('validation.ids')
            train=exp['stages'][1];train['timeout_seconds']=30;train['inputs'].append('validation.ids')
            train['outputs']+=['trial-1.jsonl','trial-2.jsonl','trial-1-model.json','trial-2-model.json','selection.json']
            exp['training_evidence']['selection_record_path']='selection.json'
            exp['fairness'].update(selection_protocol='validation_only',tuning_budget={'max_trials':2,'max_seconds':30},search_space={'candidate':[0,1]},validation_metric={'implementation':'mse','direction':'lower','targets_path':'targets.jsonl','targets_sha256':sha,'ids_path':'validation.ids'})
        plan,r,root=await self.scenario(configure)
        self.assertEqual(r['status'],'completed',r['errors'])
        self.assertTrue(all(x['training_evidence']['selection']['status']=='verified' for x in r['runs']))
        self.assertEqual(r['experiments'][0]['fairness']['status'],'verified')
        # Reuse frozen materials with a changed selection choice; test evaluation must never run.
        def bad(plan,repo):
            configure(plan,repo)
            (repo/'experiment.py').write_text((repo/'experiment.py').read_text().replace("'selected_trial_id':'trial-1'","'selected_trial_id':'trial-2'"))
        plan,r,root=await self.scenario(bad)
        self.assertEqual(r['status'],'failed')
        self.assertTrue(all(len(x['stages'])==2 for x in r['runs']))
        self.assertTrue(any('does not optimize' in s.get('output_error','') for row in r['runs'] for s in row['stages']))
