import time
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from articheck.kg_service import KnowledgeGraphService
from articheck.review_api import ReviewError
from test_hosted_review import Budget, Executor, HEADERS, MemoryStore, Reviewer, TOKEN, materials, register


class LifecycleRaces(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.budget = Budget()
        self.executor = Executor()
        app = Flask(__name__)
        app.register_error_handler(ReviewError, lambda error: (jsonify(error=error.code), error.status))
        register(app, {'ARTICHECK_REVIEW_TOKEN': TOKEN}, Reviewer(), self.budget,
                 store=self.store, executor=self.executor)
        self.client = app.test_client()

    def test_cancel_before_claim_is_durable(self):
        job = '1' * 32
        path = '/assessments/' + job
        self.assertEqual(self.client.post(path + '/cancel', json={}, headers=HEADERS).json['status'], 'cancelled')
        with patch('articheck.hosted_api.prepare_assessment') as prepare:
            late = self.client.post('/assessments', json={**materials(), 'request_id': job}, headers=HEADERS)
        prepare.assert_not_called()
        self.assertEqual(late.json['status'], 'cancelled')
        self.assertEqual(self.budget.calls, 0)

    def test_cancel_during_material_parse_prevents_model_dispatch(self):
        from articheck.hosted_api import prepare_assessment
        job = '3' * 32
        path = '/assessments/' + job

        def parse(*args, **kwargs):
            reply = self.client.post(path + '/cancel', headers=HEADERS, json={'terminate': True})
            self.assertEqual(reply.json['status'], 'cancelled')
            return prepare_assessment(*args, **kwargs)

        with patch('articheck.hosted_api.prepare_assessment', side_effect=parse), patch('articheck.hosted_api.assess') as model:
            result = self.client.post('/assessments', headers=HEADERS, json={**materials(), 'request_id': job})
        model.assert_not_called()
        self.assertEqual(result.json['status'], 'cancelled')
        self.assertIn('terminated_at', result.json)
        self.assertEqual(self.budget.calls, 0)

    def test_cancel_after_model_dispatch_cannot_publish_late_result(self):
        from articheck.hosted_api import assess
        job = '2' * 32
        path = '/assessments/' + job

        def complete_after_cancel(*args, **kwargs):
            cancelled = self.client.post(path + '/cancel', json={}, headers=HEADERS).json
            self.assertEqual(cancelled['status'], 'cancelled')
            return assess(*args, **kwargs)

        with patch('articheck.hosted_api.assess', side_effect=complete_after_cancel) as reviewer:
            late = self.client.post('/assessments', json={**materials(), 'request_id': job}, headers=HEADERS)
        reviewer.assert_called_once()
        self.assertEqual(late.json['status'], 'cancelled')
        self.assertEqual(self.client.get(path, headers=HEADERS).json['status'], 'cancelled')
        self.assertEqual(self.executor.launches, 0)

    def test_terminate_while_starting_stops_the_late_instance(self):
        report = self.client.post('/assessments', json=materials(), headers=HEADERS).json
        path = '/assessments/' + report['id']
        original_launch = self.executor.launch

        def launch(value, payload):
            waiting = self.client.post(path + '/cancel', json={'terminate': True}, headers=HEADERS).json
            self.assertEqual(waiting['execution']['status'], 'cancelling')
            self.assertEqual(self.client.get(path, headers=HEADERS).json['execution']['status'], 'cancelling')
            return original_launch(value, payload)

        self.executor.launch = launch
        self.executor.poll = lambda ex: {**ex, 'status': 'running'}
        payload = {'code': materials()['code'], 'plan_sha256': report['review']['plan_sha256']}
        finished = self.client.post(path + '/execute', json=payload, headers=HEADERS).json
        self.assertEqual(finished['execution']['status'], 'cancelled')
        self.assertIn('terminated_at', finished)
        self.assertEqual((self.executor.launches, self.executor.stops, self.store.reservations), (1, 1, 1))
        self.assertEqual(self.client.post(path + '/execute', json=payload, headers=HEADERS).status_code, 409)

    def test_unavailable_execution_logs_do_not_prevent_stop(self):
        report = self.client.post('/assessments', json=materials(), headers=HEADERS).json
        path = '/assessments/' + report['id']
        self.client.post(path + '/execute', json={
            'code': materials()['code'], 'plan_sha256': report['review']['plan_sha256']}, headers=HEADERS)
        with patch.object(self.executor, 'poll', side_effect=OSError('log unavailable')):
            stopped = self.client.post(path + '/cancel', json={}, headers=HEADERS)
        self.assertEqual(stopped.json['execution']['status'], 'cancelled')
        self.assertEqual(self.executor.stops, 1)

    def test_cancel_before_execute_prevents_a_late_launch(self):
        report = self.client.post('/assessments', json=materials(), headers=HEADERS).json
        path = '/assessments/' + report['id']
        reply = self.client.post(path + '/cancel', json={'execution_request': True}, headers=HEADERS)
        self.assertEqual(reply.json['execution']['status'], 'cancelled')
        late = self.client.post(path + '/execute', headers=HEADERS,
                                json={'code': materials()['code'], 'plan_sha256': report['review']['plan_sha256']})
        self.assertEqual(late.json['execution']['status'], 'cancelled')
        self.assertEqual(self.executor.launches, 0)
        self.assertEqual(self.store.reservations, 0)


class GraphTraversal(unittest.TestCase):
    def setUp(self):
        store = MemoryStore()
        store.namespace = 'batch-four'
        self.graph = KnowledgeGraphService({}, store, reviewer=None, budget=None)

    def test_graph_expands_three_levels_and_keeps_edge_origins(self):
        paper = lambda pid: {'id': pid, 'title': pid}
        graph = {'B': ['A', 'C'], 'C': ['B', 'D', 'E'], 'D': ['A']}
        self.graph.literature.neighborhood = lambda identifier, **kw: (paper(identifier), {
            'next': [paper(pid) for pid in graph[identifier]]
        })
        papers, links = self.graph.discover_literature(paper('A'), {'next': [paper('B')]}, kinds=['next'],
            depth=3, total=3, state={'choices': {}}, deadline=time.monotonic() + 5)
        self.assertEqual(list(papers), ['B', 'C', 'D'])
        self.assertIn(('C', 'next', 'D'), links)
        self.assertIn(('B', 'next', 'A'), links)
        self.assertNotIn(('A', 'next', 'D'), links)

    def test_initial_layout_brings_neighbors_close_and_preserves_drag(self):
        papers = [{'id': pid} for pid in ('A', 'B', 'C')]
        links = {'previous': {'source': 'A', 'target': 'B', 'kind': 'citation'},
                 'next': {'source': 'B', 'target': 'C', 'kind': 'citation'}}
        points = self.graph.initial_paper_positions(papers, 'B', {}, links, {'B': {'x': 720, 'y': 350}})
        self.assertEqual(points['B'], (720, 350))
        self.assertLess(points['A'][0], points['B'][0])
        self.assertLess(points['B'][0], points['C'][0])
        self.assertLess(sum(abs(points[pid][0] - points['B'][0]) for pid in ('A', 'C')), 540)

    def test_cancelled_graph_operation_cannot_persist_late_graph(self):
        operation_id = 'a' * 32
        key = self.graph.graph_operation_key('first', operation_id)
        self.assertEqual(self.graph.cancel_graph_operation('first', operation_id)['status'], 'cancelled')
        with self.assertRaisesRegex(ReviewError, '已停止或已处理'):
            self.graph.update_literature('first', lambda state: state['papers'].update(A={}), operation_key=key)
        self.assertEqual(self.graph.literature_state('first')[1]['papers'], {})
        other_key = self.graph.graph_operation_key('second', operation_id)
        self.graph.update_literature('second', lambda state: state['papers'].update(A={}), operation_key=other_key)
        self.assertEqual(self.graph.cancel_graph_operation('second', operation_id)['status'], 'completed')

    def test_graph_concurrency_caps_accounts_and_releases_lease(self):
        from contextlib import ExitStack
        with ExitStack() as slots:
            for owner in ('first', 'second', 'third'):
                for _ in range(3):
                    slots.enter_context(self.graph.public_work_slot(owner))
                if owner == 'first':
                    with self.assertRaises(ReviewError):
                        with self.graph.public_work_slot('first'):
                            self.fail('per-account limit exceeded')
            with self.assertRaises(ReviewError):
                with self.graph.public_work_slot('fourth'):
                    self.fail('global limit exceeded')
        with self.graph.public_work_slot('fourth'):
            pass
