import base64
import copy
import json
from pathlib import Path
import tempfile
import time
import io
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from articheck.hosted_api import register as register_api
from articheck.hosted_gpu import OwnedGPUExecutor, HybridExecutor
from articheck.gpu_worker import GPUWorker, validate_source_url
from articheck.hosted_review import prepare_assessment as prepare_visual_assessment, validate_assessment, assess
from articheck.hosted_runner import run_plan
from articheck.hosted_store import HostedStore
from articheck.hosted_github import repository
from articheck.hosted_sources import public_identifier,lookup
from articheck.hosted_audit import cross_audit
from articheck.review_api import DIMENSIONS, ReviewError

def register(app,env,*args,**kwargs):
    # These tests isolate workflow semantics using the explicitly configured legacy client.
    return register_api(app,{**env,'ARTICHECK_AUTH_MODE':'legacy'},*args,**kwargs)

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
    def test_graph_uses_owned_report_and_does_not_invent_evidence(self):
        store = MemoryStore()
        store.namespace = 'test'
        app = Flask(__name__)
        app.register_error_handler(ReviewError, lambda error: (jsonify(error=str(error)), error.status))
        register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), Budget(),
                 store=store, executor=Executor())
        job = 'c' * 32
        store.save(OWNER, {
            'id': job, 'status': 'completed',
            'review': {'task': 'self_review', 'paper_title': 'Original paper', 'paper_contributions': ['Shared benchmark contribution'],
                       'metrics': [{'id': 'target', 'metric': 'accuracy', 'value': 50}]},
            'execution': {'status': 'completed', 'scientific_validation': False,
                          'metrics': [{'id': 'other', 'metric': 'accuracy', 'observed': 50,
                                       'status': 'within_tolerance'}]},
        })
        client = app.test_client()
        payload = {'assessment_id': job, 'report': {'review': {'paper_title': 'Forged title'}}}
        other = {**HEADERS, 'X-ArtiCheck-Session': 'b' * 64}
        self.assertEqual(client.post('/kg/ingest', json=payload, headers=other).status_code, 404)
        response = client.post('/kg/ingest', json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        nodes = response.json['nodes']
        paper = next(n for n in nodes if n['full_title'] == 'Original paper')
        self.assertIsNone(paper['year'])
        self.assertEqual({n['node_type'] for n in nodes}, {'Paper'})
        self.assertEqual(paper['method_status'], 'unavailable')
        self.assertTrue(paper['read'])
        self.assertNotIn('accuracy', json.dumps(response.json))
        self.assertEqual(client.get('/kg/graph', headers=other).json['papers'], [])
        for scope in ('GLOBAL', 'COMBINED'):
            self.assertEqual(client.get('/kg/graph?scope=' + scope, headers=HEADERS).status_code, 400)
        for route in ('visibility', 'import-external', 'verify-conflict'):
            self.assertEqual(client.post('/kg/' + route, json={}, headers=HEADERS).status_code, 404)
        self.assertEqual(client.get('/kg/graph?paper_id=' + paper['id'], headers=other).json['focus_paper_id'], '')

        comparison_job = 'd' * 32
        store.save(OWNER, {'id': comparison_job, 'status': 'completed',
                           'review': {'task': 'self_review', 'paper_title': 'Second paper',
                                      'paper_contributions': ['Shared benchmark contribution']}})
        client.post('/kg/ingest', json={'assessment_id': comparison_job}, headers=HEADERS)
        url = '/kg/assessments/' + job + '/conflicts'
        self.assertEqual(client.get(url, headers=other).status_code, 404)
        items = client.get(url, headers=HEADERS).json['items']
        candidate = next(item for item in items if item['source_title'] == item['target_title'])
        self.assertFalse(candidate['user_verified'])
        self.assertEqual(client.post(url, json={'comparison_id': 'foreign', 'decision': 'confirm'}, headers=HEADERS).status_code, 404)
        self.assertEqual(client.post(url, json={'comparison_id': candidate['id'], 'decision': 'confirm'}, headers=HEADERS).status_code, 200)
        self.assertTrue(next(item for item in client.get(url, headers=HEADERS).json['items'] if item['id'] == candidate['id'])['user_verified'])

    def test_retired_shared_and_external_entries_cannot_enter_personal_graph(self):
        from articheck.kg_service import KnowledgeGraphService, extract_paper_graph_entry
        store = MemoryStore()
        store.namespace = 'test'
        graph = KnowledgeGraphService({}, store)
        own = extract_paper_graph_entry({'title': 'Own upload'}, graph._owner_hash(OWNER))
        own['visibility'] = 'GLOBAL'
        external = extract_paper_graph_entry({'title': 'Old manual reference', 'source_type': 'MANUAL_REFERENCE'}, graph._owner_hash(OWNER))
        foreign = extract_paper_graph_entry({'title': 'Another account'}, graph._owner_hash('b' * 64))
        graph.save_private_papers(OWNER, [own, external, foreign])
        graph.save_layout(OWNER, {'pinned': [external['id'], foreign['id']]})
        result = graph.build_graph_response(OWNER, focus_paper_id=foreign['id'])
        self.assertEqual([item['title'] for item in result['papers']], ['Own upload'])
        self.assertEqual(result['papers'][0]['visibility'], 'PRIVATE')
        self.assertEqual(result['focus_paper_id'], own['id'])
        self.assertEqual(result['layout']['pinned'], [])

    def test_literature_second_hop_relationships_and_choices_are_account_scoped(self):
        store = MemoryStore()
        store.namespace = 'test'
        app = Flask(__name__)
        app.register_error_handler(ReviewError, lambda error: (jsonify(error=str(error)), error.status))
        with patch('articheck.kg_service.OpenAlex') as provider:
            register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), Budget(),
                     store=store, executor=Executor())
        job = 'e' * 32
        evidence = {'title': 'Residual shortcut connections', 'local_id': 'c1', 'page': 3,
                    'quote': 'Residual shortcut connections stabilize gradient propagation', 'section': '3. Residual Learning',
                    'method_grounded': True, 'details': [{'title': 'Identity shortcuts', 'page': 3,
                    'quote': 'Identity shortcuts preserve gradients', 'section': '3.1 Shortcut Mapping'}]}
        store.save(OWNER, {'id': job, 'status': 'completed', 'review': {
            'task': 'self_review', 'paper_title': 'Owned paper', 'method_graph': [evidence]}})
        client = app.test_client()
        other = {**HEADERS, 'X-ArtiCheck-Session': 'b' * 64}
        graph = client.post('/kg/ingest', json={'assessment_id': job}, headers=HEADERS).json
        root = graph['focus_paper_id']
        public = lambda ident, title, year: {'id': ident, 'title': title, 'year': year, 'venue': 'CVPR',
            'direction': 'Computer vision', 'source_url': 'https://openalex.org/' + ident,
            'contributions': [{'title': 'A legacy abstract sentence must never be shown'}]}
        original, past, future = public('W11', 'Owned paper', 2016), public('W22', 'Earlier work', 2014), public('W33', 'Later work', 2017)
        provider.return_value.neighborhood.side_effect = [(original, {'previous': [past], 'next': [future]}),
                                                           (future, {'previous': [original, past]})]
        expand = '/kg/literature/expand'
        choice = '/kg/literature/paper'
        payload = {'paper_id': root, 'kinds': ['previous', 'next'], 'limit': 3}
        self.assertEqual(client.post(expand, json=payload, headers=other).status_code, 404)
        from articheck.kg_methods import method_key
        public_evidence = {**evidence, 'title': 'Skip-connected architecture', 'source_url': 'https://arxiv.org/pdf/1611.05431', 'details': []}
        relation = {'left_paper': 'W11', 'left_id': method_key(evidence),
                    'right_paper': 'W33', 'right_id': method_key(public_evidence),
                    'description': '两项架构都使用恒等捷径直接传递输入特征。'}
        with patch('articheck.kg_service.synthesize', return_value=({'W33': [public_evidence]}, [relation])):
            graph = client.post(expand, json=payload, headers=HEADERS).json
        by_id = {row['id']: row for row in graph['nodes']}
        self.assertEqual(by_id[root]['metadata']['year']['source'], 'OpenAlex')
        self.assertEqual([n['label'] for n in graph['nodes'] if n['node_type'] == 'Detail'], ['Identity shortcuts'])
        self.assertNotIn('Claim', {n['node_type'] for n in graph['nodes']})
        pairs = {(edge['source'], edge['target']) for edge in graph['edges'] if edge['edge_type'] == 'CITED_BY'}
        self.assertEqual(pairs, {('W22', root), (root, 'W33')})
        self.assertTrue(any(edge['edge_type'] == 'SIMILAR_CONTRIBUTION'
                            and by_id[edge['source']]['node_type'] != 'Paper'
                            and edge['source_url'] for edge in graph['edges']))
        self.assertTrue(by_id[root]['read'])
        self.assertFalse(by_id['W33']['read'])
        self.assertEqual(by_id['W22']['method_status'], 'unavailable')
        self.assertNotIn('legacy abstract', json.dumps(graph))
        edge = next(edge for edge in graph['edges'] if edge['edge_type'] == 'SIMILAR_CONTRIBUTION')
        self.assertEqual(edge['evidence'][0]['section'], '3. Residual Learning')
        node_id = edge['target']
        self.assertEqual(client.post('/kg/layout', json={'change': {'id': node_id, 'x': 22, 'y': 44, 'pinned': True}}, headers=HEADERS).status_code, 200)
        self.assertEqual(client.get('/kg/graph', headers=HEADERS).json['layout']['positions'][node_id]['x'], 22)
        self.assertEqual(client.post('/kg/nodes/delete', json={'node_id': node_id}, headers=other).status_code, 404)
        for action in ('read', 'hide'):
            graph = client.post(choice, json={'paper_id': 'W33', 'action': action}, headers=HEADERS).json
        hidden = next(row for row in graph['papers'] if row['paper_id'] == 'W33')
        self.assertTrue(hidden['read'] and hidden['hidden'])
        with patch('articheck.kg_service.synthesize', return_value=({}, [])):
            graph = client.post(expand, json={'paper_id': 'W33', 'kinds': ['previous'], 'limit': 3}, headers=HEADERS).json
        self.assertEqual(provider.return_value.neighborhood.call_args.kwargs['identifier'], 'W33')
        self.assertEqual({row['paper_id'] for row in graph['papers']}, {root, 'W22', 'W33'})
        self.assertEqual(client.post(choice, json={'paper_id': 'W33', 'action': 'show'}, headers=other).status_code, 404)
        graph = client.post(choice, json={'paper_id': 'W33', 'action': 'show'}, headers=HEADERS).json
        self.assertFalse(next(row for row in graph['papers'] if row['paper_id'] == 'W33')['hidden'])
        graph = client.post(choice, json={'paper_id': 'W22', 'action': 'remove'}, headers=HEADERS).json
        self.assertFalse(any('W22' in (edge['source'], edge['target']) for edge in graph['edges']))
        deleted = client.post('/kg/nodes/delete', json={'node_id': node_id}, headers=HEADERS).json
        self.assertFalse(any(node['id'] == node_id for node in deleted['nodes']))
        self.assertFalse(any(node_id in (edge['source'], edge['target']) for edge in deleted['edges']))
        self.assertEqual(store.get(OWNER, job)['review']['method_graph'][0], evidence)
        self.assertEqual(client.get('/kg/graph', headers=other).json['papers'], [])

    def test_graph_relations_survive_new_service_and_manual_removal(self):
        from articheck.kg_service import KnowledgeGraphService

        class RedisFixture:
            namespace = 'relation-durability'
            url = token = 'test'

            def __init__(self):
                self.values = {}
                self.expiries = set()

            def command(self, command, *args):
                if command == 'GET':
                    return self.values.get(args[0])
                if command == 'PERSIST':
                    self.expiries.discard(args[0])
                    return 1
                if command == 'SET':
                    self.values[args[0]] = args[1]
                    if len(args) > 2:
                        self.expiries.add(args[0])
                    return 'OK'
                if command == 'EVAL':
                    _, _, key, expected, value = args
                    if self.values.get(key, '') != expected:
                        return 0
                    self.values[key] = value
                    self.expiries.discard(key)
                    return 1
                raise AssertionError(command)

        store = RedisFixture()
        svc = KnowledgeGraphService({}, store, reviewer=Reviewer(), budget=Budget())
        evidence = {
            'local_id': 'method', 'title': 'Residual shortcut normalization', 'section': 'Methods',
            'quote': 'Residual shortcut normalization stabilizes model training across layers.',
            'page': 3, 'method_grounded': True,
        }
        ids = []
        for title in ('Study A', 'Study B'):
            graph = svc.ingest_project(OWNER, {'project_id': title, 'report': {
                'review': {'paper_title': title, 'method_graph': [evidence]}}})
            ids.append(graph['focus_paper_id'])
        left, right = ids
        def grounded(_reviewer, _budget, papers, pairs):
            methods = {paper['id']: paper['existing'][0]['local_id'] for paper in papers}
            return {}, [{'left_paper': a, 'right_paper': b, 'left_id': methods[a],
                         'right_id': methods[b], 'description': 'Both methods normalize residual shortcuts.'}
                        for a, b in pairs]

        with patch('articheck.kg_service.synthesize', side_effect=grounded) as verify:
            graph = svc.verify_related(OWNER, left)
            restarted = KnowledgeGraphService({}, store, reviewer=Reviewer(), budget=Budget())
            restarted.verify_related(OWNER, left)
            self.assertEqual(verify.call_count, 1)
            relation = next(edge for edge in graph['edges'] if edge['edge_type'] == 'SIMILAR_CONTRIBUTION')
            self.assertEqual(relation['excerpts'], [evidence['quote'], evidence['quote']])
            self.assertTrue(any(edge['id'] == relation['id'] for edge in restarted.build_graph_response(OWNER)['edges']))
            self.assertFalse(store.expiries)
            self.assertFalse(restarted.build_graph_response('another-account')['nodes'])
            contribution_pair = (relation['source'], relation['target'])
            restarted.edit_relation(OWNER, *contribution_pair, 'remove')
            self.assertFalse(any(edge['id'] == relation['id'] for edge in restarted.verify_related(OWNER, left)['edges']))
            coordinates = {n['id']: (n['x'], n['y']) for n in graph['nodes'] if n['node_type'] == 'Paper'}
            restarted.edit_relation(OWNER, left, right, 'add', 'Uses the same shortcut', 'Method extension')
            reopened = svc.build_graph_response(OWNER, focus_paper_id=right)
            manual = next(edge for edge in reopened['edges'] if edge['edge_type'] == 'MANUAL_RELATION')
            self.assertEqual((manual['label'], manual['description']), ('Method extension', 'Uses the same shortcut'))
            self.assertEqual({n['id']: (n['x'], n['y']) for n in reopened['nodes'] if n['node_type'] == 'Paper'},
                             coordinates)
            restarted.edit_relation(OWNER, left, right, 'remove')
            restarted.edit_relation(OWNER, *contribution_pair, 'add')
            self.assertEqual(sum(edge['edge_type'] == 'MANUAL_RELATION'
                                 for edge in svc.build_graph_response(OWNER)['edges']), 1)
            restarted.edit_relation(OWNER, *contribution_pair, 'remove')
            self.assertFalse(any(edge['edge_type'] in ('MANUAL_RELATION', 'SIMILAR_CONTRIBUTION')
                                 for edge in restarted.verify_related(OWNER, left)['edges']))
            self.assertEqual(verify.call_count, 1)

    def test_manual_public_read_status_survives_merging_into_owned_paper(self):
        from articheck.kg_service import KnowledgeGraphService
        store = MemoryStore()
        store.namespace = 'read-merge'
        graph = KnowledgeGraphService({}, store)
        graph.update_literature(OWNER, lambda state: state['papers'].update(
            W99={'id': 'W99', 'title': 'Same title', 'source_url': 'https://openalex.org/W99'}))
        graph.update_paper_choice(OWNER, 'W99', 'unread')
        result = graph.ingest_project(OWNER, {'project_id': 'project', 'report': {
            'id': 'a'*32, 'review': {'paper_title': 'Same title'}}})
        self.assertEqual(len(result['papers']), 1)
        self.assertEqual(result['papers'][0]['source_type'], 'USER_UPLOAD')
        self.assertFalse(result['papers'][0]['read'])
        deleted = graph.delete_node(OWNER, result['focus_paper_id'])
        self.assertEqual(deleted['nodes'], [])
        self.assertEqual(len(graph.owned_papers(OWNER)), 1)

    def test_method_retrieval_and_grounded_model_output(self):
        from articheck.kg_methods import retrieve_methods, synthesize
        quote = 'The routing layer groups related patches into learned windows.'
        methods = retrieve_methods([
            {'number': 1, 'text': '1. Introduction\n' + 'The introduction describes the objective. '*8},
            {'number': 3, 'text': '4. Architecture\n' + quote*3 + '\n5. Experiments\n' + 'The benchmark reports results. '*8}
        ], query='routing')
        self.assertEqual([row['page'] for row in methods], [3])
        self.assertEqual(methods[0]['section'], '4. Architecture')
        self.assertNotIn('benchmark', methods[0]['text'])
        reviewer = Reviewer()
        budget = Budget()
        good = {'id': 'c1', 'title': 'Patch routing layer', 'chunk_id': 'M1', 'quote': quote}
        rows = [
            {**good, 'paper_id': 'W1'}, {**good, 'paper_id': 'W2', 'title': 'Learned routing windows'},
            {**good, 'paper_id': 'W1', 'id': 'fake', 'title': 'Synthetic graph', 'quote': 'This passage is missing from the paper.'}
        ]
        relation = {'left_paper': 'W1', 'right_paper': 'W2', 'left_id': 'c1', 'right_id': 'c1',
                    'description': '两项方法均使用窗口组织图块，但关注不同路由粒度。'}
        data = {'contributions': rows, 'relations': [relation, {**relation, 'right_id': 'missing'}]}
        with patch.object(reviewer, 'post', return_value={'choices': [{'message': {'content': json.dumps(data)}}]}) as post:
            graph, edges = synthesize(reviewer, budget, [
                {'id': 'W1', 'title': 'First', 'chunks': methods, 'existing': []},
                {'id': 'W2', 'title': 'Second', 'chunks': methods, 'existing': []}], [['W1', 'W2']])
        self.assertEqual(budget.calls, 1)
        self.assertIn(quote, post.call_args.args[0]['messages'][1]['content'])
        self.assertEqual([row['title'] for row in graph['W1']], ['Patch routing layer'])
        self.assertEqual(len(edges), 1)

    def test_terminated_assessment_cannot_reopen_or_resume_execution(self):
        store = MemoryStore()
        store.namespace = 'test'
        app = Flask(__name__)
        app.register_error_handler(ReviewError, lambda error: (jsonify(error=str(error)), error.status))
        register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), Budget(),
                 store=store, executor=Executor())
        job = 'c' * 32
        evidence = [{'id': 'S1', 'status': 'failed', 'stdout': 'existing evidence'}]
        store.save(OWNER, {'id': job, 'status': 'completed', 'review': {'task': 'reproduction'},
                           'execution': {'status': 'failed', 'stages': evidence}})
        client = app.test_client()
        base = '/assessments/' + job
        first = client.post(base + '/terminate', json={}, headers=HEADERS).json
        second = client.post(base + '/terminate', json={}, headers=HEADERS).json
        self.assertEqual(first['terminated_at'], second['terminated_at'])
        self.assertEqual(first['execution']['stages'], evidence)
        self.assertEqual(client.post(base + '/execute', json={}, headers=HEADERS).status_code, 409)
        self.assertEqual(client.post(base + '/feedback', json={'answer': 'can_provide'}, headers=HEADERS).status_code, 409)
        self.assertEqual(store.reservations, 0)

    def test_subcontribution_shortens_architecture_and_excludes_evaluation_details(self):
        from articheck.hosted_review import subcontribution_phrase
        self.assertEqual(subcontribution_phrase('我们提出了残差路由模块，准确率提升 5%'), '残差路由模块')
        self.assertEqual(subcontribution_phrase('我们在测试集做了消融实验，F1 为 89%'), '')
        self.assertEqual(subcontribution_phrase('We introduce identity shortcut connections for training, improving accuracy.'), 'identity shortcut connections for training')
        self.assertLessEqual(len(subcontribution_phrase('并行缓存模块用于批量调度与异步回收以及长期性能优化与模型工程适配')), 24)

    def test_decimal_ratio_with_unsubstantiated_percent_is_not_an_acceptance_target(self):
        context,_=prepare_assessment(materials())
        context['paper_excerpts']=[{'page':1,'text':'Table 1. Ours 0.8338'}]
        answer=output(context)
        answer['metrics']=[{'id':'M1','reference':'Table 1','page':1,'quote':'Ours 0.8338',
            'value':0.8338,'unit':'%','metric':'accuracy','model':'Ours','dataset':'test'}]
        answer['plan']['metric_patterns']=[{'metric_id':'M1','stage_id':'S1','pattern':'acc: ([0-9.]+)','tolerance':0.01}]
        result=validate_assessment(answer,context)
        self.assertEqual(result['metrics'][0]['value'],0.8338)
        self.assertEqual(result['metrics'][0]['unit'],'')
        self.assertTrue(result['metrics'][0]['unit_uncertain'])
        self.assertEqual(result['plan']['metric_patterns'],[])
        context['paper_excerpts'][0]['text']='Table 1. Ours 0.8338 %'
        answer['metrics'][0]['quote']='Ours 0.8338 %'
        result=validate_assessment(answer,context)
        self.assertEqual(result['metrics'][0]['unit'],'%')
        self.assertEqual(len(result['plan']['metric_patterns']),1)

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
        report['review']['metrics']=[{'id':'M1','reference':'Table 1','page':1,'dataset':'test','metric':'mAP','unit':'',
             'protocol':'','model':'baseline','author_method':True,'quote':'baseline 0.7','value':0.7}]
        answer={'reviews':[{'index':0,'decision':'remove','reason':'10³ 为数量级表述，不是 103 层。'}],
            'additional_tables':[{'reference':'Table 1','page':1,'dataset':'test','metric_prefix':'AP','unit':'','protocol':'',
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

    def test_disposable_cpu_tasks_remove_environment_and_keep_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, results, venv = (base / name for name in ('artifact', 'results', 'venv'))
            for code, status in ((0, 'completed'), (7, 'failed')):
                with self.subTest(status=status):
                    root.mkdir()
                    results.mkdir(exist_ok=True)
                    (root / 'experiment-venv').mkdir()
                    (venv / 'bin').mkdir(parents=True)
                    plan = {'max_seconds': 30, 'stages': [{
                        'id': 'S1', 'title': 'workspace cleanup', 'file': 'test.sh',
                        'command': f': > experiment-venv/installed; : > .cache/task-cache; : > .pydeps/installed; echo retained; exit {code}',
                    }]}
                    report = run_plan(plan, root, results, run_as=None, disposable=True, venv=venv)
                    self.assertEqual(report['status'], status)
                    self.assertTrue(report['runtime']['workspace_cleaned'])
                    self.assertFalse(root.exists())
                    self.assertFalse(venv.exists())
                    self.assertIn('retained', (results / 'S1.log').read_text())

    def test_cpu_supervisor_retries_transient_interruptions_three_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / 'results'
            results.mkdir()
            plan = {'max_seconds': 30, 'stages': [
                {'id': 'S1', 'title': 'recover', 'file': 'probe.sh',
                 'command': "if test -f recovered; then echo score:1; else : > recovered; echo 'connection reset'; exit 1; fi"},
                {'id': 'S2', 'title': 'fail', 'file': 'probe.sh',
                 'command': "echo try >> attempts; echo 'connection timed out'; exit 1"},
                {'id': 'S3', 'title': 'dependent', 'file': 'probe.sh', 'command': 'exit 0'}]}
            report = run_plan(plan, root, results, run_as=None)
            self.assertEqual([row['status'] for row in report['stages']], ['completed', 'failed', 'skipped'])
            self.assertEqual([row.get('retry_count') for row in report['stages']], [1, 3, None])
            self.assertEqual(report['stages'][0]['live_tail'], ['score:1'])
            self.assertEqual(len((root / 'attempts').read_text().splitlines()), 4)
            self.assertIn('重试 3 次', report['stages'][1]['reason'])
            self.assertEqual([ev['retry'] for ev in report['events'] if ev['kind'] == 'stage_retry'], [1, 1, 2, 3])
            self.assertEqual(json.loads((results / 'status.json').read_text())['status'], 'failed')

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

    def test_reviewing_assessment_can_be_cancelled_and_a_late_result_never_overwrites_it(self):
        app=Flask(__name__);store=MemoryStore();executor=Executor();budget=Budget()
        register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), budget, store=store, executor=executor)
        client=app.test_client();job='e'*32
        # Unclaimed request: cancel succeeds without touching the store.
        early=client.post('/assessments/'+job+'/cancel',json={},headers=HEADERS)
        self.assertEqual(early.status_code,200);self.assertEqual(early.json['status'],'cancelled')
        real_assess=__import__('articheck.hosted_api',fromlist=['assess']).assess
        def cancel_mid_review(*args,**kwargs):
            stopped=client.post('/assessments/'+job+'/cancel',json={},headers=HEADERS).json
            self.assertEqual(stopped['status'],'cancelled')
            self.assertEqual(stopped['activity'][-1]['title'],'审查已手动中止')
            return real_assess(*args,**kwargs)
        with patch('articheck.hosted_api.assess',side_effect=cancel_mid_review):
            late=client.post('/assessments',json={**materials(),'request_id':job},headers=HEADERS)
        self.assertEqual(late.json['status'],'cancelled')
        self.assertEqual(client.get('/assessments/'+job,headers=HEADERS).json['status'],'cancelled')
        self.assertEqual(executor.launches,0)

    def test_unverifiable_citations_and_paper_only_stages_degrade_instead_of_failing(self):
        context,_=prepare_assessment({'paper':materials()['paper']})
        answer=output(context)
        answer['criteria'][1]['page']=999
        answer['criteria'][0]['file']='train.py'
        answer['plan']['stages']=[{'title':'训练','command':'python train.py','file':'train.py'}]
        review=validate_assessment(answer,context)
        self.assertIsNone(review['criteria'][0]['file'])
        self.assertEqual(review['plan']['stages'],[])
        self.assertTrue(any('论文页面' in g for g in review['coverage']['gaps']))

    def test_owned_gpu_executor_hybrid_routing_and_worker_lifecycle(self):
        class FakeRedisStore(MemoryStore):
            def __init__(self):
                super().__init__()
                self.kv = {}
                self.queues = {}
            def command(self, op, *args):
                if op == 'GET':
                    return self.kv.get(args[0])
                if op == 'SET':
                    self.kv[args[0]] = args[1]
                    return 'OK'
                if op == 'LPOP':
                    q = self.queues.setdefault(args[0], [])
                    return q.pop(0) if q else None
                if op == 'LREM':
                    q = self.queues.setdefault(args[0], [])
                    count = q.count(args[2])
                    q[:] = [job for job in q if job != args[2]]
                    return count
                if op == 'EVAL' and 'RPUSH' in args[0]:
                    job_key, queue_key, record_json, job_id = args[2], args[3], args[4], args[5]
                    if job_key in self.kv:
                        return 0
                    self.kv[job_key] = record_json
                    self.queues.setdefault(queue_key, []).append(job_id)
                    return 1
                raise AssertionError('Unexpected Redis op: ' + str((op, args)))

        import hashlib
        ctx, _ = prepare_assessment(materials())
        raw_out = output(ctx)
        raw_out['plan']['hardware'] = 'GPU'
        # Without GPU capacity in execution_environment, hardware falls back to CPU
        cpu_validated = validate_assessment(copy.deepcopy(raw_out), ctx)
        self.assertEqual(cpu_validated['plan']['hardware'], 'CPU')
        # With GPU capacity enabled, hardware is preserved as GPU
        ctx['execution_environment'] = {'provider': 'owned_gpu', 'cpu_count': 8, 'memory_mb': 16384, 'gpu': True, 'gpu_name': 'NVIDIA GeForce RTX 4090'}
        gpu_validated = validate_assessment(copy.deepcopy(raw_out), ctx)
        self.assertEqual(gpu_validated['plan']['hardware'], 'GPU')

        store = FakeRedisStore()
        env = {'ARTICHECK_BUDGET_ID': 'test-budget', 'ARTICHECK_GPU_ENABLED': '1', 'E2B_API_KEY': 'e2b-test-key'}
        zip_bytes = (ROOT / 'web/dist/samples/toy-artifact.zip').read_bytes()
        code_sha = hashlib.sha256(zip_bytes).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            worker = GPUWorker(env, store=store,
                               fetcher=lambda url, size, sha: (validate_source_url(url), zip_bytes)[1],
                               runtime='/usr', run_as=None, work_root=tmp)
            worker.capacity = {'provider': 'owned_gpu', 'cpu_count': 8, 'memory_mb': 16384,
                               'gpu': True, 'gpu_name': 'NVIDIA GeForce RTX 4090', 'gpu_memory_mb': 24564}
            worker.send_heartbeat(force=True)
            hybrid = HybridExecutor(env, store)
            self.assertTrue(hybrid.configured)
            self.assertTrue(hybrid.capacity['gpu'])
            self.assertEqual(hybrid.capacity['gpu_name'], 'NVIDIA GeForce RTX 4090')

            class FakeStageSandbox:
                sandbox_id = 'sbx-stage-1'
                def __init__(self):
                    self.files = self
                def write(self, path, data, user='root'):
                    self.written = data
                def download_url(self, path, user='root', use_signature_expiration=120):
                    return 'https://8080-sbx-stage-1.e2b.app/gpu-source.zip'
                def kill(self):
                    pass
                @staticmethod
                def kill(sandbox_id, api_key=None):
                    pass

            assessment = {'id': 'f' * 32, 'materials': {'code': code_sha},
                          'review': gpu_validated, 'execution': {'attempt_id': 'a1'}}
            with patch('e2b.Sandbox.create', return_value=FakeStageSandbox()), \
                 patch('e2b.Sandbox.kill', return_value=None):
                launched = hybrid.launch(assessment, {'code': materials()['code']})
                self.assertEqual(launched['status'], 'queued')
                self.assertEqual(launched['provider'], 'owned_gpu')
                # Replace bwrap execution with direct local shell in test tmpdir
                def local_stage(work_dir, log_path, command, deadline, job_id):
                    import subprocess
                    with log_path.open('wb') as log:
                        proc = subprocess.run(['/bin/bash', '-c', command], cwd=work_dir, stdout=log, stderr=subprocess.STDOUT, timeout=10)
                    return proc.returncode, False, False
                from articheck.gpu_worker import bwrap_args, bwrap_env
                worker.run_stage_command = local_stage
                bwrap_cmd = bwrap_args(Path(tmp), 'echo ok', runtime='/usr')
                self.assertIn('--share-net', bwrap_cmd)
                self.assertEqual(bwrap_env('/usr')['PYTHONUSERBASE'], '/work/.pydeps')
                self.assertEqual(bwrap_env('/usr')['TORCH_HOME'], '/work/.cache/torch')
                self.assertEqual(bwrap_env('/usr')['SSL_CERT_FILE'], '/etc/ssl/certs/ca-certificates.crt')
                processed = worker.poll_once()
                self.assertEqual(processed['status'], 'completed')
                self.assertIsNone(processed['source_url'])
                self.assertTrue(processed['result']['runtime'].get('workspace_cleaned'))
                self.assertEqual(list(Path(tmp).iterdir()), [])
                polled = hybrid.poll(launched)
                self.assertEqual(polled['status'], 'completed')
                self.assertTrue(polled['execution_performed'])
                self.assertEqual(polled['stages'][0]['status'], 'completed')

                # Fifth-batch: cancelling a queued GPU job immediately sets status='cancelled' and does not revert on poll
                launched2 = hybrid.launch(assessment, {'code': materials()['code']})
                self.assertEqual(launched2['status'], 'queued')
                stopped_ok = hybrid.stop(launched2)
                self.assertTrue(stopped_ok)
                polled_cancelled = hybrid.poll(launched2)
                self.assertEqual(polled_cancelled['status'], 'cancelled')

                # Transient stage errors replay in the same GPU workspace, with a hard cap.
                launched3 = hybrid.launch(assessment, {'code': materials()['code']})
                key = worker.job_key(launched3['gpu_job_id'])
                record = json.loads(store.kv[key])
                record['plan']['stages'][0]['command'] = "echo 'connection reset'; exit 1"
                worker.save_record(record)
                failed = worker.poll_once()
                self.assertEqual(failed['status'], 'failed')
                self.assertTrue(failed['result']['runtime']['workspace_cleaned'])
                self.assertEqual(list(Path(tmp).iterdir()), [])
                self.assertEqual(failed['result']['stages'][0]['retry_count'], 3)
                self.assertEqual([ev['retry'] for ev in failed['result']['events'] if ev['kind'] == 'stage_retry'], [1, 2, 3])

                active = hybrid.launch(assessment, {'code': materials()['code']})
                def cancel_during_stage(work_dir, log_path, command, deadline, job_id):
                    (work_dir / '.pydeps' / 'task_only').touch()
                    self.assertFalse(hybrid.stop(active))
                    self.assertEqual(hybrid.poll(active)['status'], 'cancelling')
                    self.assertTrue(work_dir.exists())
                    log_path.write_text('retained progress')
                    return -9, False, True
                worker.run_stage_command = cancel_during_stage
                cancelled = worker.poll_once()
                self.assertEqual(cancelled['status'], 'cancelled')
                self.assertTrue(cancelled['result']['runtime']['workspace_cleaned'])
                self.assertIn('retained progress', cancelled['result']['stages'][0]['output'])
                self.assertEqual(list(Path(tmp).iterdir()), [])
                self.assertEqual(hybrid.poll(active)['status'], 'cancelled')
                worker.run_stage_command = local_stage

                launched4 = hybrid.launch(assessment, {'code': materials()['code']})
                key = worker.job_key(launched4['gpu_job_id'])
                record = json.loads(store.kv[key])
                record['plan']['stages'][0]['command'] = 'pip install -r requirements.txt'
                worker.save_record(record)
                calls = []

                def install_stage(work_dir, log_path, command, deadline, job_id):
                    self.assertEqual(deadline, float('inf'))
                    calls.append(command)
                    running = json.loads(store.kv[key])
                    running['deadline'] = time.time() - 1
                    store.kv[key] = json.dumps(running)
                    self.assertEqual(hybrid.poll(launched4)['status'], 'running')
                    self.assertFalse(worker.is_cancelled(job_id))
                    return 0, False, False

                with patch('articheck.gpu_worker.infer_project_dependencies',
                           return_value={'sklearn': 'scikit-learn'}), \
                     patch.object(worker, 'run_stage_command', side_effect=install_stage):
                    result = worker.poll_once()
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(calls, ['pip install -r requirements.txt'])

                # Fifth-batch: AST/regex import dependency analysis and ModuleNotFoundError parser
                from articheck.gpu_worker import infer_project_dependencies, parse_missing_modules_from_log
                dep_dir = Path(tmp) / 'dep_check'
                dep_dir.mkdir(parents=True, exist_ok=True)
                (dep_dir / 'local_helper.py').write_text('def helper(): return 1\n')
                (dep_dir / 'train.py').write_text('import os, sys, json\nimport local_helper\nimport cv2\nfrom sklearn.metrics import f1_score\nimport yaml\n')
                inferred = infer_project_dependencies(dep_dir)
                self.assertEqual(inferred.get('cv2'), 'opencv-python-headless')
                self.assertEqual(inferred.get('sklearn'), 'scikit-learn')
                self.assertEqual(inferred.get('yaml'), 'PyYAML')
                self.assertNotIn('os', inferred)
                self.assertNotIn('local_helper', inferred)
                parsed_missing = parse_missing_modules_from_log("Traceback:\nModuleNotFoundError: No module named 'bs4'\nImportError: No module named skimage.io\n")
                self.assertEqual(parsed_missing.get('bs4'), 'beautifulsoup4')
                self.assertEqual(parsed_missing.get('skimage'), 'scikit-image')

                # Sixth-batch: collapse_cr_lines, extract_live_tail, core_code_snippets, and fail_fast
                from articheck.gpu_worker import collapse_cr_lines, extract_live_tail
                from articheck.hosted_review import extract_core_code_snippets
                cr_text = "Epoch 1: 10%\rEpoch 1: 50%\rEpoch 1: 100%\nLoss: 0.25\nAccuracy: 94.2%\nDone\n"
                self.assertIn("Epoch 1: 100%", collapse_cr_lines(cr_text))
                self.assertNotIn("Epoch 1: 10%", collapse_cr_lines(cr_text))
                tail_lines = extract_live_tail(cr_text, max_lines=3)
                self.assertEqual(len(tail_lines), 3)
                self.assertEqual(tail_lines[-1], "Done")
                self.assertTrue(gpu_validated['plan'].get('fail_fast'))
                self.assertTrue(isinstance(gpu_validated.get('core_code_snippets'), list))
                snippets = extract_core_code_snippets({}, {'code_excerpts': [{'file': 'trainer.py', 'text': 'class ResNet:\n    def forward(self, x):\n        return x\n'}]}, gpu_validated['plan']['stages'], gpu_validated['criteria'], gpu_validated.get('findings') or [])
                self.assertGreaterEqual(len(snippets), 1)
                self.assertEqual(snippets[0]['file'], 'trainer.py')


if __name__ == '__main__':
    unittest.main()

