import base64
import copy
import json
from pathlib import Path
import tempfile
import io
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from articheck.hosted_api import register
from articheck.hosted_review import prepare_assessment as prepare_visual_assessment, validate_assessment, assess
from articheck.hosted_runner import run_plan
from articheck.hosted_store import HostedStore
from articheck.hosted_github import repository
from articheck.hosted_sources import public_identifier,lookup
from articheck.hosted_audit import cross_audit
from articheck.review_api import DIMENSIONS, ReviewError

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'test-site-code-not-provider-secret'
OWNER = 'a' * 64
HEADERS = {'Authorization': 'Bearer ' + TOKEN, 'X-ArtiCheck-Client': 'review-api', 'X-ArtiCheck-Session': OWNER}


def prepare_assessment(body):
    return prepare_visual_assessment(body,images=False)

def materials():
    return {k: {'name': f, 'content_base64': base64.b64encode((ROOT/'web/dist/samples'/f).read_bytes()).decode()}
            for k, f in [('paper', 'articheck-method-note.pdf'), ('code', 'toy-artifact.zip')]}


def output(context):
    file = context['code_excerpts'][0]['file'] if context['code'] else None
    return {'summary': '核对已提供的材料', 'paper_type': 'empirical' if context['paper'] else 'code_only',
            'task': 'reproduction' if context['paper'] else 'code_review', 'classification_reason': '按提供材料选择',
            'criteria': [{'dimension': d, 'status': 'needs_review', 'note': '待执行证据', 'page': None, 'file': file}
                         for d in DIMENSIONS], 'findings': [], 'metrics': [],
            'coverage': {'gaps': ['图中曲线未读取'], 'note': '有限上下文'},
            'plan': {'purpose': '检查实际 Python 环境', 'blocked_reason': '' if file else '没有代码',
                     'stages': [{'id': 'S1', 'title': '版本检查', 'command': 'python3 --version', 'file': file}] if file else [],
                     'needs': [], 'metric_patterns': []}}


class Reviewer:
    model = 'test-fixture'
    configured = True
    def post(self, body):
        content=body['messages'][1]['content']
        context = json.loads(content[0]['text'] if isinstance(content,list) else content)['materials']
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output(context))}}]}


class MemoryStore:
    def __init__(self):
        self.records = {}; self.locks = set(); self.reservations = 0
    def get(self, owner, job):
        if (owner, job) not in self.records:
            raise ReviewError('not_found', 'Missing', 404)
        return copy.deepcopy(self.records[owner, job])
    def save(self, owner, value):
        self.records[owner, value['id']] = copy.deepcopy(value)
    def replace(self, owner, previous, value):
        if self.records.get((owner, value['id'])) != previous: return False
        self.save(owner, value); return True
    def claim(self, owner, value):
        if (owner, value['id']) in self.records: return False
        self.save(owner, value); return True
    def lock(self, owner, job, attempt=1):
        key = (owner, job, attempt)
        if key in self.locks:
            return False
        self.locks.add(key); return True
    def reserve_compute(self):
        self.reservations += 1; return self.reservations
    def repository_ref(self,name,value=None):
        return None
    def unlock_before_launch(self,owner,job,attempt=1):
        self.locks.discard((owner,job,attempt))


class Executor:
    configured = True
    def __init__(self):
        self.launches = 0; self.stops = 0
    def launch(self, value, body):
        self.launches += 1
        return {'status': 'running', 'execution_performed': False, 'scientific_validation': False}
    def poll(self, execution):
        return {**execution, 'status': 'failed', 'needs_user': True, 'stages': [{'exit_code': 1}],
                'execution_performed': True, 'scientific_validation': False}
    def stop(self, execution):
        self.stops += 1


class Budget:
    configured = True
    def __init__(self):
        self.calls = 0
    def reserve(self):
        self.calls += 1; return self.calls


class HostedReviewTests(unittest.TestCase):
    def test_valid_blank_pdf_is_not_rejected_as_corrupt(self):
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(612,792);buffer=io.BytesIO();writer.write(buffer)
        context,_=prepare_assessment({'paper':{'name':'blank.pdf','content_base64':base64.b64encode(buffer.getvalue()).decode()}})
        self.assertEqual(context['paper_pages'],1)
        self.assertEqual(context['paper_excerpts'][0]['text'],'')

    def test_numeric_outputs_are_not_mistaken_for_http_rate_limits(self):
        cases=[("printf 'accuracy 0.429 and 403 samples\\n'",None,False),
               ("printf 'score 429\\n'; exit 1",'execution_blocked',False),
               ("printf 'HTTP Error 429: Too Many Requests\\n'; exit 1",'transient_service',False),
               ("printf 'dataset file not found\\n'; exit 1",'execution_blocked',True)]
        for command,category,needs_user in cases:
            with self.subTest(command=command),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);dest=root/'result';dest.mkdir()
                value=run_plan({'max_seconds':30,'stages':[{'id':'S1','title':'Check','command':command,'file':'check.sh'}],
                                'metrics':[],'metric_patterns':[]},root,dest,run_as=None)
                self.assertEqual(value['failure_category'],category)
                self.assertEqual(value['needs_user'],needs_user)

    def test_insufficient_compute_can_be_confirmed_without_pretending_to_execute(self):
        context,_=prepare_assessment(materials());answer=output(context)
        answer['plan'].update(stages=[],blocked_reason='训练需要 CUDA GPU，当前仅有 CPU',
            needs=[{'name':'CUDA GPU','source':'论文训练设置','required':True}])
        review=validate_assessment(answer,context)
        self.assertFalse(review['resource_preflight']['capacity']['gpu'])
        store=MemoryStore();executor=Executor();app=Flask(__name__)
        register(app,{'ARTICHECK_REVIEW_TOKEN':TOKEN},Reviewer(),Budget(),store=store,executor=executor)
        record={'id':'9'*32,'review':review,'execution':None,'scientific_validation':False}
        store.save(OWNER,record)
        response=app.test_client().post('/assessments/'+record['id']+'/feedback',
            json={'answer':'unavailable'},headers=HEADERS)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['availability']['resource'],'compute_capacity')
        self.assertFalse(response.json['availability']['scientific_validation'])
        self.assertIsNone(response.json['execution'])
        self.assertEqual(executor.launches,0)
        self.assertEqual(store.reservations,0)

    def test_long_paper_keeps_late_result_tables_within_context_budget(self):
        pages=[{'number':n,'text':('Introduction text ' * 500)+f'\nTable {n}. Results\nOurs 92.3 %\n',
                **({'public_ids':['1911.02685']} if n==1 else {})} for n in range(1,32)]
        with patch('articheck.review_api.extract_paper',return_value=(pages,{})):
            context,_=prepare_assessment({'paper':materials()['paper']})
        self.assertEqual(len(context['paper_excerpts']),31)
        self.assertIn('Ours 92.3 %',context['paper_excerpts'][-1]['text'])
        self.assertLessEqual(sum(len(p['text'].encode()) for p in context['paper_excerpts']),90000)
        self.assertEqual(public_identifier(context),'arXiv:1911.02685')
        self.assertTrue(context['coverage']['paper_text_truncated'])

    def test_nonexperimental_academic_analysis_keeps_self_review_task(self):
        context,_=prepare_assessment({'paper':materials()['paper']})
        answer=output(context);answer.update(paper_type='diagnostic',task='self_review')
        result=validate_assessment(answer,context)
        self.assertEqual(result['paper_type'],'diagnostic')
        self.assertEqual(result['task'],'self_review')
        self.assertEqual(result['plan']['stages'],[])

    def test_pdf_only_and_code_only_and_empty_material(self):
        for key in ('paper', 'code'):
            context, _ = prepare_assessment({key: materials()[key]})
            self.assertIsNotNone(context[key])
            other = 'paper' if key == 'code' else 'code'
            self.assertIsNone(context[other])
            report = assess(Reviewer(), context, '')
            self.assertFalse(report['execution_performed'])
            self.assertFalse(report['scientific_validation'])
            if key == 'paper':
                self.assertEqual(report['review']['plan']['stages'], [])
        with self.assertRaises(ReviewError):
            prepare_assessment({})

    def test_actual_pdf_images_are_bounded_and_never_embedded_in_saved_report(self):
        context,_=prepare_visual_assessment(materials())
        self.assertEqual(len(context['paper_images']),2)
        self.assertTrue(all(max(i['width'],i['height'])<=1601 for i in context['paper_images']))
        image=context['paper_images'][0]
        self.assertTrue(base64.b64decode(image['image_url'].split(',',1)[1]).startswith(b'\xff\xd8'))
        report=assess(Reviewer(),context,'')
        self.assertEqual(len(report['page_images']),2)
        self.assertNotIn('base64',json.dumps(report))

    def test_curve_estimates_never_become_exact_targets(self):
        context,_=prepare_assessment(materials())
        context['paper_images']=[{'page':1}]
        answer=output(context)
        answer['metrics']=[{'id':'M1','reference':'Figure 1','page':1,'quote':'about 3.5',
                            'value':3.5,'unit':'%','metric':'error','precision':'estimated'}]
        result=validate_assessment(answer,context)
        self.assertEqual(result['metrics'],[])
        self.assertEqual(result['visual_observations'][0]['precision'],'estimated')

    def test_code_review_does_not_treat_missing_paper_as_a_defect(self):
        context,_=prepare_assessment({'code':materials()['code']})
        answer=output(context)
        answer['findings']=[{'title':'缺少论文无法核对','severity':'high','detail':'没有论文','suggestion':'上传论文','page':None,'file':None}]
        value=validate_assessment(answer,context)
        self.assertEqual(value['findings'],[])
        self.assertEqual(next(r for r in value['criteria'] if r['dimension']=='results')['status'],'not_applicable')

    def test_cross_audit_preserves_original_and_does_not_merge_baseline_plus_variants(self):
        context,_=prepare_assessment(materials())
        context['paper_excerpts']=[{'page':1,'text':'Table 1. baseline 0.7 baseline+++ 0.9'}]
        report=assess(Reviewer(),context,'')
        report['review']['findings']=[{'title':'103层疑点','detail':'待核对','suggestion':'对照排版','severity':'high','page':1,'file':None}]
        report['review']['metrics']=[{'id':'M1','reference':'Table 1','page':1,'dataset':'test','metric':'mAP','unit':'%',
             'protocol':'','model':'baseline','author_method':True,'quote':'baseline 0.7','value':0.7}]
        answer={'reviews':[{'index':0,'decision':'remove','reason':'10³ 为数量级表述，不是 103 层。'}],
            'additional_tables':[{'reference':'Table 1','page':1,'dataset':'test','metric_prefix':'AP','unit':'%','protocol':'',
                'columns':['mAP'],'rows':[{'model':'baseline','author_method':True,'values':[0.7],'quote':'baseline 0.7'},
                                        {'model':'baseline+++','author_method':True,'values':[0.9],'quote':'baseline+++ 0.9'}]}],
            'visual_notes':[]}
        reviewer=Reviewer()
        reviewer.post=lambda body:{'choices':[{'message':{'content':json.dumps(answer)}}]}
        result=cross_audit(reviewer,context,report)
        self.assertEqual(result['audit']['withdrawn'],1)
        self.assertEqual(result['audit']['additional_metrics'],1)
        self.assertEqual({m['model'] for m in result['review']['metrics']},{'baseline','baseline+++'})
        self.assertEqual(len(report['review']['findings']),1)
        self.assertEqual(len(result['review']['findings']),0)

    def test_lookup_uses_public_identifiers_and_counts_the_paid_search_once(self):
        context,_=prepare_assessment({'paper':materials()['paper']})
        budget=Budget();store=MemoryStore()
        lookup(context,budget,store)
        self.assertEqual(budget.calls,0)
        context['paper']['name']='1512.03385v1.pdf'
        self.assertEqual(public_identifier(context),'arXiv:1512.03385')
        with patch('articheck.hosted_sources.provider_tool',return_value={'results':[{'url':'https://arxiv.org/abs/1512.03385','title':'ResNet','content':'Paper abstract'}]}) as provider:
            lookup(context,budget,store)
        self.assertEqual(budget.calls,1)
        self.assertEqual(provider.call_args.args[0],'search')
        self.assertEqual(context['source_lookup']['status'],'completed')

    def test_time_limits_are_server_enforced_and_empty_uses_default(self):
        for n in (-1, 0, 29, 601, '300', True):
            with self.assertRaises(ReviewError):
                prepare_assessment({**materials(), 'max_seconds': n})
        context, _ = prepare_assessment({**materials(), 'max_seconds': ''})
        self.assertEqual(context['max_seconds'], 300)

    def test_metrics_require_real_cited_table_quote_not_body_fragment(self):
        context, _ = prepare_assessment(materials())
        context['paper_excerpts'] = [{'page': 1, 'text': 'Table 1. Ours 92.3 %\nBody says accuracy is good.'}]
        answer = output(context)
        metric = {'id': 'M1', 'reference': 'Table 1', 'model': 'Ours', 'dataset': 'test', 'metric': 'accuracy',
                  'value': 92.3, 'unit': '%', 'protocol': 'test split', 'page': 1,
                  'quote': 'Ours 92.3 %', 'author_method': True}
        answer['metrics'] = [metric]
        self.assertEqual(len(validate_assessment(answer, context)['metrics']), 1)
        for changed in ({'page': 9}, {'quote': 'invented 95.0'}, {'reference': 'Body paragraph'}):
            answer['metrics'] = [{**metric, **changed}]
            clean = validate_assessment(answer, context)
            self.assertEqual(clean['metrics'], [])
            self.assertGreater(len(clean['coverage']['gaps']), 1)

    def test_nonpaper_has_no_executable_plan_and_no_scientific_pass(self):
        context, _ = prepare_assessment(materials())
        answer = output(context); answer['paper_type'] = 'nonpaper'
        self.assertEqual(validate_assessment(answer, context)['plan']['stages'], [])
        answer['criteria'][0]['status'] = 'passed'
        with self.assertRaises(ReviewError):
            validate_assessment(answer, context)

    def test_repository_relative_citation_prefers_the_actual_archive_root(self):
        context,_=prepare_assessment(materials())
        context['files']=['repo/Makefile','repo/blas/Makefile']
        context['code_excerpts']=[{'file':'repo/Makefile','text':'all: train'}, {'file':'repo/blas/Makefile','text':'all: blas'}]
        answer=output(context)
        answer['criteria'][0]['file']='Makefile'
        answer['plan']['stages'][0]['file']='Makefile'
        result=validate_assessment(answer,context)
        self.assertEqual(result['criteria'][0]['file'],'repo/Makefile')
        self.assertEqual(result['plan']['stages'][0]['file'],'repo/Makefile')

    def test_repository_parser_accepts_only_github_home_urls(self):
        self.assertEqual(repository('https://github.com/owner/repo.git?utm_source=test'), 'owner/repo')
        for u in ('http://github.com/a/b', 'https://evil.test/a/b', 'https://github.com/a/b/tree/main',
                  'https://github.com/a/..', 'https://github.com@127.0.0.1/a/b'):
            with self.assertRaises(ReviewError): repository(u)

    def test_store_keys_are_owner_scoped_and_reject_untrusted_ids(self):
        s = HostedStore({})
        self.assertNotEqual(s.key('a'*64, 'b'*32), s.key('c'*64, 'b'*32))
        for bad in ('../secrets', '*', 'a'*1000):
            with self.assertRaises(ReviewError): s.key(OWNER, bad)

    def test_real_cpu_supervisor_records_failure_and_never_converts_skip_to_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); result = root/'results'; result.mkdir()
            plan = {'max_seconds': 30, 'stages': [
                {'id': 'S1', 'title': 'actual stdout', 'file': 'test.py', 'command': "printf 'score: 0.75\\n'"},
                {'id': 'S2', 'title': 'actual failure', 'file': 'test.py', 'command': 'exit 7'},
                {'id': 'S3', 'title': 'dependent step', 'file': 'test.py', 'command': 'exit 0'}],
                'metrics': [{'id': 'M1', 'metric': 'score', 'value': 0.8, 'unit': ''}],
                'metric_patterns': [{'metric_id': 'M1', 'stage_id':'S1', 'pattern': 'score: ([0-9.]+)', 'tolerance': 0.01}]}
            value = run_plan(plan, root, result, run_as=None)
            self.assertEqual(value['stages'][1]['exit_code'], 7)
            self.assertEqual(value['stages'][2]['status'], 'skipped')
            self.assertEqual(value['metrics'][0]['observed'], 0.75)
            self.assertEqual(value['metrics'][0]['status'], 'outside_tolerance')
            self.assertFalse(value['scientific_validation'])
            self.assertEqual(json.loads((result/'status.json').read_text())['status'], 'failed')

    def test_independent_experiment_continues_and_numeric_outputs_are_stage_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);results=root/'results';results.mkdir()
            plan={'max_seconds':30,'stages':[
                {'id':'S1','title':'missing data','file':'a.py','command':"printf 'FileNotFoundError: dataset\\n'; exit 1",'depends_on':[]},
                {'id':'S2','title':'dependent','file':'a.py','command':"printf 'score: 99\\n'",'depends_on':['S1']},
                {'id':'S3','title':'independent','file':'b.py','command':"printf 'score: 0.6\\nscore: 0.8\\n'",'depends_on':[]}],
                'metrics':[{'id':'M1','metric':'score','value':0.7,'unit':''}],
                'metric_patterns':[{'metric_id':'M1','stage_id':'S3','pattern':'score: ([0-9.]+)','tolerance':0.001,'aggregation':'mean'}]}
            value=run_plan(plan,root,results,run_as=None)
            self.assertEqual([s['status'] for s in value['stages']],['failed','skipped','completed'])
            self.assertTrue(value['needs_user'])
            self.assertEqual(value['metrics'][0]['n'],2)
            self.assertAlmostEqual(value['metrics'][0]['observed'],0.7)
            self.assertFalse(value['scientific_validation'])

    def test_routes_enforce_identity_fingerprints_idempotent_launch_and_real_blocker_answer(self):
        app = Flask(__name__); store = MemoryStore(); executor = Executor(); budget = Budget()
        app.config['TESTING'] = True
        @app.errorhandler(ReviewError)
        def handle(error):
            return jsonify(error={'code': error.code, 'message': str(error)}), error.status
        register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), budget, store=store, executor=executor)
        client = app.test_client()
        self.assertEqual(client.post('/assessments', json=materials()).status_code, 401)
        self.assertEqual(budget.calls, 0)
        submission = {**materials(), 'request_id': 'd'*32}
        created = client.post('/assessments', json=submission, headers=HEADERS)
        self.assertEqual(created.status_code, 200, created.json)
        value = created.json; path = '/assessments/' + value['id']
        repeated = client.post('/assessments', json=submission, headers=HEADERS)
        self.assertEqual(repeated.json['id'], value['id'])
        self.assertEqual(budget.calls, 1)
        self.assertEqual(client.post('/assessments', json={**submission, 'task': 'self_review'}, headers=HEADERS).status_code, 409)
        different = {**HEADERS, 'X-ArtiCheck-Session': 'b'*64}
        self.assertEqual(client.get(path, headers=different).status_code, 404)
        body = {'code': materials()['code'], 'plan_sha256': value['review']['plan_sha256']}
        changed = {**body, 'plan_sha256': 'wrong'}
        self.assertEqual(client.post(path+'/execute', json=changed, headers=HEADERS).status_code, 409)
        self.assertEqual(executor.launches, 0)
        for _ in range(2):
            self.assertEqual(client.post(path+'/execute', json=body, headers=HEADERS).status_code, 200)
        self.assertEqual(executor.launches, 1)
        self.assertEqual(store.reservations, 1)
        self.assertEqual(client.post(path+'/feedback', json={'answer': 'unavailable'}, headers=HEADERS).status_code, 400)
        polled = client.get(path, headers=HEADERS)
        self.assertTrue(polled.json['execution']['needs_user'])
        answer = client.post(path+'/feedback', json={'answer': 'unavailable'}, headers=HEADERS).json
        self.assertIn('无法复现', answer['execution']['availability_verdict'])
        self.assertFalse(answer['execution']['scientific_validation'])
        retry_id=answer['execution']['attempt_id']
        retried=client.post(path+'/execute',json={**body,'retry_of':retry_id},headers=HEADERS)
        self.assertEqual(retried.status_code,200,retried.json)
        self.assertEqual(len(retried.json['execution_history']),1)
        self.assertEqual(executor.launches,2)
        stale=client.post(path+'/execute',json={**body,'retry_of':retry_id},headers=HEADERS)
        self.assertEqual(stale.status_code,409)
        self.assertEqual(executor.launches,2)
        self.assertEqual(budget.calls,1)

    def test_source_unavailable_requires_a_real_acquisition_attempt_when_a_hint_exists(self):
        app=Flask(__name__);store=MemoryStore();executor=Executor();budget=Budget()
        @app.errorhandler(ReviewError)
        def error(exc):return jsonify(error={'code':exc.code}),exc.status
        register(app,{'ARTICHECK_REVIEW_TOKEN':TOKEN},Reviewer(),budget,store=store,executor=executor)
        client=app.test_client()
        value=client.post('/assessments',json={'paper':materials()['paper']},headers=HEADERS).json
        value['review']['repository_hint']='https://github.com/cjlin1/liblinear'
        store.save(OWNER,value)
        path='/assessments/'+value['id']
        self.assertEqual(client.post(path+'/feedback',json={'answer':'unavailable'},headers=HEADERS).status_code,409)
        with patch('articheck.hosted_api.import_repository',side_effect=ReviewError('github_rate_limited','temporary limit',429)):
            response=client.post('/repositories',json={'url':'https://github.com/cjlin1/liblinear','assessment_id':value['id']},headers=HEADERS)
        self.assertEqual(response.status_code,429)
        stored=client.get(path,headers=HEADERS).json
        self.assertEqual(stored['source_discovery']['status'],'failed')
        answer=client.post(path+'/feedback',json={'answer':'unavailable'},headers=HEADERS).json
        self.assertIn('当前条件',answer['availability']['verdict'])
        self.assertIsNone(answer['execution'])
        self.assertEqual(executor.launches,0)

    def test_a_late_poll_cannot_replace_a_cancellation(self):
        app=Flask(__name__);store=MemoryStore();executor=Executor();budget=Budget()
        register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), budget, store=store, executor=executor)
        client=app.test_client()
        value=client.post('/assessments', json=materials(), headers=HEADERS).json
        path='/assessments/'+value['id']
        client.post(path+'/execute', json={'code':materials()['code'], 'plan_sha256':value['review']['plan_sha256']}, headers=HEADERS)
        def delayed_poll(execution):
            newer=store.get(OWNER,value['id']);newer['execution']['status']='cancelled';store.save(OWNER,newer)
            return {**execution,'status':'completed'}
        executor.poll=delayed_poll
        self.assertEqual(client.get(path,headers=HEADERS).json['execution']['status'],'cancelled')
