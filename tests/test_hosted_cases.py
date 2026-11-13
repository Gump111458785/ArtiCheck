import json
import unittest

from flask import Flask, jsonify

from articheck.hosted_api import register as register_accounts
from articheck.review_api import DIMENSIONS, ReviewError
from test_hosted_auth import RedisMemory
from test_hosted_review import Budget, Executor, HEADERS, OWNER, Reviewer, register


class CaseStore(RedisMemory):
    namespace = 'cases-test'

    def __init__(self):
        super().__init__()
        self.public = {}
        self.published = {}
        self.change_before_publish = False

    def key(self, owner, job):
        return owner, job

    def command(self, name, *args):
        if name == 'EVAL' and "redis.call('ZADD'" in args[0]:
            _, key_count, source, _, marker, expected, member, snapshot = args
            assert key_count == '3'
            if marker in self.published:
                return self.published[marker]
            if self.change_before_publish or json.dumps(self.records.get(source), ensure_ascii=False) != expected:
                return None
            self.public[member] = 0
            self.published[marker] = snapshot
            return snapshot
        if name == 'ZREVRANGEBYLEX':
            _, upper, _, _, _, count = args
            return [key for key in sorted(self.public, reverse=True)
                    if upper == '+' or key < upper[1:]][:int(count)]
        return super().command(name, *args)


class SharedCaseTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_error_handler(ReviewError, lambda e: (jsonify(error={'code': e.code}), e.status))
        self.store = CaseStore()
        register(app, {'ARTICHECK_REVIEW_TOKEN': HEADERS['Authorization'].split()[1]},
                 Reviewer(), Budget(), store=self.store, executor=Executor())
        self.client = app.test_client()
        self.other = {**HEADERS, 'X-ArtiCheck-Session': 'b' * 64}
        self.report = {'id': 'c' * 32, 'status': 'completed', 'materials': {'paper': 'private-sha', 'code': 'private-code'},
                       'review': {'purpose': 'reproduce_other', 'paper_type': 'empirical',
                                  'paper_title': 'private title',
                                  'criteria': [{'dimension': key, 'status': 'documented'} for key in DIMENSIONS],
                                  'findings': [], 'coverage': {'gaps': []},
                                  'metrics': [{'id': 'M1', 'author_method': True}],
                                  'plan': {'stages': [{'id': 'S1', 'command': 'private command'}]}},
                       'execution': {'status': 'completed', 'execution_performed': True,
                                     'stages': [{'id': 'S1', 'status': 'completed', 'exit_code': 0, 'output': 'private output'}],
                                     'metrics': [{'id': 'M1', 'expected': 1, 'observed': 1, 'tolerance': 0.01, 'status': 'within_tolerance'}]}}

    def publish(self, headers=HEADERS, title='公开案例'):
        return self.client.post('/cases', headers=headers,
                                json={'assessment_id': self.report['id'], 'title': title, 'verdict': 'passed'})

    def test_only_owner_can_publish_and_others_can_read_sanitized_snapshot(self):
        self.store.save(OWNER, self.report)
        self.assertEqual(self.client.get('/cases', headers=self.other).json['items'], [])
        self.assertEqual(self.client.get('/cases').status_code, 401)
        self.assertEqual(self.publish(self.other).status_code, 404)
        result = self.publish()
        self.assertEqual(result.status_code, 200)
        case = result.json
        self.assertEqual(case['verdict'], 'passed')
        self.assertEqual(case['checks'], [{'expected': 1, 'observed': 1, 'tolerance': 0.01}])
        self.assertNotIn('private', json.dumps(case))
        self.assertEqual(self.publish(title='重复提交').json, case)
        self.store.records.clear()
        self.assertEqual(self.client.get('/cases', headers=self.other).json['items'], [case])

    def test_finished_failures_publish_but_active_and_terminated_records_do_not(self):
        for overrides in ({'status': 'reviewing'}, {'terminated_at': 'now'},
                          {'execution': {'status': 'running'}}, {'execution': {'needs_user': True}}):
            with self.subTest(overrides=overrides):
                self.store.save(OWNER, {**self.report, **overrides})
                self.assertEqual(self.publish().json['error']['code'], 'case_not_completed')
        self.store.save(OWNER, self.report)
        self.store.change_before_publish = True
        self.assertEqual(self.publish().json['error']['code'], 'case_report_changed')
        self.assertEqual(self.client.get('/cases', headers=self.other).json['items'], [])
        self.store.change_before_publish = False
        execution = {**self.report['execution'], 'metrics': [{
            'id': 'M1', 'expected': 1, 'observed': 0.5, 'tolerance': 0.01, 'status': 'outside_tolerance'}]}
        self.store.save(OWNER, {**self.report, 'execution': execution})
        self.assertEqual(self.publish().json['verdict'], 'failed')

    def test_shared_cases_paginate_without_repeating_the_boundary(self):
        for number in range(24):
            self.report['id'] = f'{number:032x}'
            self.store.save(OWNER, self.report)
            self.assertEqual(self.publish(title=f'案例 {number}').status_code, 200)
        first = self.client.get('/cases', headers=self.other).json
        second = self.client.get('/cases', headers=self.other, query_string={'before': first['next']}).json
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(len(second['items']), 4)
        self.assertIsNone(second['next'])
        self.assertEqual(len({entry['id'] for entry in first['items'] + second['items']}), 24)

    def test_separate_invited_accounts_see_only_the_public_snapshot(self):
        app = Flask('case-accounts')
        app.register_error_handler(ReviewError, lambda e: (jsonify(error={'code': e.code}), e.status))
        register_accounts(app, {}, Reviewer(), Budget(), store=self.store, executor=Executor())
        accounts = app.extensions['articheck_accounts']
        clients = []
        headers = {'X-ArtiCheck-Client': 'review-api'}
        for name in ('publisher', 'reader'):
            user = accounts.create_user(name, 'test-password-for-cases', name)
            client = app.test_client()
            self.assertEqual(client.post('/auth/login', headers=headers,
                                         json={'username': name, 'password': 'test-password-for-cases'}).status_code, 200)
            clients.append(client)
            if name == 'publisher':
                record = accounts.read('user', user['id'])
                self.store.save(record['report_owner'], self.report)
        publish = {'assessment_id': self.report['id'], 'title': '邀请账户分享的案例'}
        self.assertEqual(clients[1].get('/cases', headers=headers).json['items'], [])
        self.assertEqual(clients[1].post('/cases', headers=headers, json=publish).status_code, 404)
        shared = clients[0].post('/cases', headers=headers, json=publish)
        self.assertEqual(shared.status_code, 200)
        self.assertEqual(clients[1].get('/cases', headers=headers).json['items'], [shared.json])
        self.assertEqual(clients[1].get('/assessments/' + self.report['id'], headers=headers).status_code, 404)
