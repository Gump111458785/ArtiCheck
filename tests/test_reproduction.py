from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from articheck.reproduction.audit import audit_plan
from articheck.reproduction.engine import reproduce
from articheck.reproduction.executor import StageExecutor
from articheck.reproduction.protocol import FORMAT, fingerprint, relative_path, validate_plan
from articheck.reproduction.statistics import evaluate_experiment


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) if not isinstance(value, str) else value)
    return path


def fixture(root):
    repo = root/'artifact';repo.mkdir()
    paper = write(root/'paper.txt', 'A synthetic test document. Figure 1 compares prediction error. Figure 2 is another core experiment.')
    code = write(repo/'experiment.py', '''import json, sys, random
from pathlib import Path
stage, cfg_path = sys.argv[1:]
cfg=json.loads(Path(cfg_path).read_text()); seed=cfg['seed'];variant=cfg['variant']['id']
if stage=='prepare':
    Path('prepared.json').write_text(Path(sys.argv[0]).with_name('data.json').read_text())
elif stage=='train':
    data=json.loads(Path('prepared.json').read_text());rng=random.Random(seed)
    rows=rng.choices(data['train'],k=len(data['train']))
    xs=[x for x,y in rows];ys=[y for x,y in rows];mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    slope=sum((x-mx)*(y-my) for x,y in rows)/sum((x-mx)**2 for x in xs) if variant!='baseline' else 0
    intercept=my-slope*mx if variant!='ablation' else 0
    Path('model.json').write_text(json.dumps({'slope':slope,'intercept':intercept}))
    Path('used-config.json').write_text(Path(cfg_path).read_text())
elif stage=='evaluate':
    model=json.loads(Path('model.json').read_text());data=json.loads(Path('prepared.json').read_text())
    error=sum((model['slope']*x+model['intercept']-y)**2 for x,y in data['test'])/len(data['test'])
    Path('metrics.json').write_text(json.dumps({'mse':error}))
''')
    data=write(repo/'data.json',{'train':[[x,2*x+5+((x%3)-1)*.1] for x in range(-10,11)],'test':[[x+.5,2*(x+.5)+5] for x in range(-5,5)]})
    write(repo/'train.ids','\n'.join('train-'+str(x) for x in range(21)))
    write(repo/'test.ids','\n'.join('test-'+str(x) for x in range(10)))
    settings={'hyperparameters':{'fit':'least_squares'},'initialization':'closed_form','augmentation':'none','selection':'all training examples','stopping':'closed form solution'}
    cfg=write(repo/'settings.json',settings)
    def entry(name):return {'path':name,'sha256':fingerprint(repo/name)['sha256']}
    plan={'format':FORMAT,'paper':{'path':'paper.txt','sha256':fingerprint(paper)['sha256'],'version':'synthetic v1',
         'pages':[{'number':1,'text':paper.read_text()}],'conclusions':[{'id':'C1','text':'Test conclusion'}],
         'experiments':[{'id':'E1','labels':['figure-1'],'page':1,'quote':'Figure 1 compares prediction error.','core':True}],
         'inventory_review':{'complete':False}},
         'repository':{'path':'artifact','files':[entry('experiment.py'),entry('data.json')],
                       'components':{k:['experiment.py'] for k in ('method','preprocess','train','evaluate')}},
         'datasets':[{'id':'synthetic','source':{'url':'generated:test','version':'v1','license':'self-owned'},'files':[entry('data.json')],
                      'splits':{n:{**entry(n+'.ids'),'source':'disjoint generated IDs'} for n in ('train','test')},'preprocessing_not_applicable':'Generated fixture is already numeric'}],
         'environment':{},'resources':{'max_seconds':60,'cpus':1,'memory_bytes':1024**3,'price_per_hour_usd':0},
         'experiments':[{'id':'regression','paper_experiment':'E1','seeds':[11,22,33,44,55],
                        'config':{**entry('settings.json'),'expected':settings,'source':'synthetic test protocol'},
                        'variants':[{'id':'method','role':'method'},{'id':'baseline','role':'baseline'},{'id':'ablation','role':'ablation'}],
                        'stages':[{'id':'prepare','argv':[sys.executable,'{repo}/experiment.py','prepare','{config}'],'needs':[], 'inputs':['repo:data.json','config.json'],'outputs':['prepared.json']},
                                  {'id':'train','argv':[sys.executable,'{repo}/experiment.py','train','{config}'],'needs':['prepare'],'inputs':['prepared.json','config.json'],'outputs':['model.json','used-config.json']},
                                  {'id':'evaluate','argv':[sys.executable,'{repo}/experiment.py','evaluate','{config}'],'needs':['train'],'inputs':['model.json','prepared.json'],'outputs':['metrics.json']}],
                        'metric':{'path':'metrics.json','key':'mse','direction':'lower'},
                        'comparisons':[{'method':'method','other':'baseline'},{'method':'method','other':'ablation'}]}]}
    path=write(root/'plan.json',plan)
    return path,plan,repo


class ReproductionAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path,self.plan,self.repo=fixture(self.root)
    def tearDown(self):self.tmp.cleanup()
    def run_audit(self):
        write(self.path,self.plan)
        return audit_plan(self.path,workspace=self.root)
    def test_unknown_figure_and_unreviewed_inventory_are_not_full_coverage(self):
        result=self.run_audit()
        self.assertTrue(any(c['code']=='unclassified:figure-2' and c['status']=='review_required' for c in result['checks']))
        self.assertTrue(any(c['code']=='method_correspondence' and c['status']=='review_required' for c in result['checks']))
        self.assertFalse(any(c['status']=='fail' for c in result['checks']))
    def test_file_content_changes_fail_even_when_directory_and_names_match(self):
        (self.repo/'experiment.py').write_text('print("changed")')
        result=self.run_audit()
        self.assertTrue(any(c['code']=='file:experiment.py' and c['status']=='fail' for c in result['checks']))
    def test_hash_and_actual_split_intersections_are_checked(self):
        (self.repo/'test.ids').write_text('train-1\ntest-2')
        self.plan['datasets'][0]['splits']['test']['sha256']=fingerprint(self.repo/'test.ids')['sha256']
        result=self.run_audit()
        overlap=next(c for c in result['checks'] if c['code']=='overlap:synthetic:train:test')
        self.assertEqual(overlap['status'],'fail');self.assertEqual(overlap['evidence']['overlap_count'],1)
        self.plan['datasets'][0]['splits']['test']['sha256']='0'*64
        self.assertTrue(any(c['code']=='split:synthetic:test' and c['status']=='fail' for c in self.run_audit()['checks']))
    def test_settings_are_compared_to_file_values_instead_of_field_presence(self):
        self.plan['experiments'][0]['config']['expected']['augmentation']='unreported augmentation'
        result=self.run_audit()
        self.assertEqual(next(c for c in result['checks'] if c['code']=='regression:augmentation')['status'],'fail')
    def test_missing_core_experiment_and_restricted_data_access_are_blockers(self):
        self.plan['paper']['experiments'].append({'id':'E2','labels':['figure-2'],'page':1,'quote':'Figure 2 is another core experiment.','core':True})
        self.plan['datasets'][0]['source'].update(access='restricted',application='Apply through owner',approved=False)
        result=self.run_audit()
        self.assertEqual(next(c for c in result['checks'] if c['code']=='coverage:E2')['status'],'fail')
        self.assertEqual(next(c for c in result['checks'] if c['code']=='access:synthetic')['status'],'fail')
    def test_path_escape_symlinks_and_unordered_dependencies_are_rejected(self):
        for value in ('../outside','/tmp/file','C:/private','a/../../file'):
            with self.assertRaises(ValueError):relative_path(self.repo,value,exists=False)
        (self.repo/'link').symlink_to(self.repo/'data.json')
        with self.assertRaises(ValueError):relative_path(self.repo,'link')
        self.plan['experiments'][0]['stages'][0]['needs']=['train']
        with self.assertRaises(ValueError):validate_plan(self.plan)
    def test_digest_is_git_blob_identity_and_sha256(self):
        result=fingerprint(self.repo/'data.json');raw=(self.repo/'data.json').read_bytes()
        self.assertEqual(result['git_blob_sha'],hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
    def test_snapshot_audit_rechecks_copied_bytes(self):
        shadow=self.root/'shadow';shadow.mkdir();(shadow/'experiment.py').write_text('tampered')
        result=audit_plan(self.path,repo_override=shadow)
        self.assertGreater(result['blocking_failures'],0)


class ReproductionStatisticsTests(unittest.TestCase):
    def experiment(self):
        return {'id':'E','seeds':list(range(5)),'variants':[{'id':'method','role':'method'},{'id':'baseline','role':'baseline'}],
                'metric':{'direction':'higher','key':'accuracy'},'comparisons':[{'method':'method','other':'baseline'}]}
    def rows(self):return [{'variant':v,'seed':s,'metric':(.9+s*.001 if v=='method' else .5+s*.001),'status':'completed'} for v in ('method','baseline') for s in range(5)]
    def test_effect_is_paired_and_confidence_interval_supports_preregistered_claim(self):
        result=evaluate_experiment(self.experiment(),self.rows())
        self.assertEqual(result['status'],'supported');self.assertGreater(result['comparisons'][0]['confidence_interval'][0],.39)
    def test_missing_failed_nonfinite_runs_and_duplicates_cannot_be_dropped(self):
        for change in ('missing','failed','nonfinite'):
            rows=self.rows()
            if change=='missing':rows.pop()
            elif change=='failed':rows[0]['status']='failed'
            else:rows[0]['metric']=float('nan')
            self.assertEqual(evaluate_experiment(self.experiment(),rows)['status'],'inconclusive')
        with self.assertRaises(ValueError):evaluate_experiment(self.experiment(),self.rows()+[self.rows()[0]])
    def test_small_improvement_inside_variation_is_inconclusive(self):
        rows=self.rows()
        for row in rows:row['metric']=.5+((-.1,.1,-.1,.1,.01)[row['seed']] if row['variant']=='method' else 0)
        self.assertEqual(evaluate_experiment(self.experiment(),rows)['status'],'inconclusive')
    def test_reference_match_without_controls_does_not_prove_main_conclusion(self):
        exp=self.experiment();exp['comparisons']=[];exp['metric'].update(reference=.902,absolute_tolerance=.01)
        result=evaluate_experiment(exp,self.rows());self.assertEqual(result['status'],'inconclusive');self.assertTrue(result['reference_alignment_only'])


class ReproductionExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_prepare_train_evaluate_matrix_and_resource_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,plan,repo=fixture(root)
            result=await reproduce(path,root/'run',mode='local',allow_local_trusted=True)
            self.assertEqual(result['status'],'completed',result['errors'])
            self.assertEqual(len(result['runs']),15)
            self.assertEqual(result['experiments'][0]['status'],'supported')
            self.assertGreater(result['measurement']['max_child_rss_bytes'],0)
            self.assertEqual(result['measurement']['stage_count'],45)
            self.assertEqual(result['cost']['compute_estimate_usd'],0)
            self.assertFalse(result['levels']['environment_rebuilt']);self.assertFalse(result['levels']['conclusion'])
            self.assertTrue((root/'run/source-files.json').is_file())
            train=result['runs'][0]['stages'][1]
            self.assertIn('model.json',train['output_fingerprints'])
    async def test_material_mismatch_stops_before_any_artifact_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,plan,repo=fixture(root);(repo/'data.json').write_text('{}')
            result=await reproduce(path,root/'run',mode='local',allow_local_trusted=True)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['runs'],[])
    async def test_nonzero_exit_timeout_and_output_overflow_are_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);executor=StageExecutor('local',allow_local_trusted=True)
            result=await executor.execute(root,root,[sys.executable,'-c','import time;time.sleep(5)'],timeout=.1)
            self.assertTrue(result['timed_out']);self.assertEqual(result['status'],'failed')
            result=await executor.execute(root,root,[sys.executable,'-c','raise SystemExit(7)'])
            self.assertEqual(result['returncode'],7);self.assertEqual(result['status'],'failed')
            result=await executor.execute(root,root,[sys.executable,'-c','print("x"*3000000)'])
            self.assertTrue(result['output_overflow']);self.assertEqual(result['status'],'failed')
    async def test_local_trust_is_explicit_and_source_output_cannot_overlap(self):
        with self.assertRaises(ValueError):StageExecutor('local')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,plan,repo=fixture(root)
            with self.assertRaises(ValueError):await reproduce(path,repo/'run',mode='local',allow_local_trusted=True)


@unittest.skipUnless(os.environ.get('ARTICHECK_TEST_DOCKER') == '1', 'Explicit Docker integration run only')
class ReproductionDockerTests(unittest.IsolatedAsyncioTestCase):
    async def test_clean_build_image_verification_and_full_matrix_in_containers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,plan,repo=fixture(root)
            dockerfile=write(repo/'Dockerfile','FROM python:3.11-slim\n')
            plan['environment']={'dockerfile':'Dockerfile','dockerfile_sha256':fingerprint(dockerfile)['sha256'],
                                 'verify':[['python3','-c','import sys; assert sys.version_info[:2] == (3,11)']]}
            plan['resources']['max_seconds']=240
            for stage in plan['experiments'][0]['stages']:stage['argv'][0]='python3'
            write(path,plan)
            result=await reproduce(path,root/'docker-run')
            self.assertEqual(result['status'],'completed',result['errors'])
            self.assertTrue(result['levels']['environment_rebuilt'])
            self.assertTrue(result['environment']['image'].startswith('sha256:'))
            self.assertEqual(result['environment']['network'],'none')
            self.assertEqual(len(result['runs']),15)
            self.assertEqual(result['experiments'][0]['status'],'supported')


if __name__=='__main__':unittest.main()
