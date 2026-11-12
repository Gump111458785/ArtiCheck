import base64
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from articheck.kg_literature import OpenAlex, allowed_pdf, pdf_text_status, retrieve_public_methods
from articheck.kg_methods import grounded_contributions, method_key, retrieve_methods
from articheck.kg_service import KnowledgeGraphService
from articheck.review_api import ReviewError


RELATED_QUOTE = 'Earlier architectures use a fixed neighbourhood to aggregate each patch.'
METHOD_QUOTE = 'We use learned patch routes to select which tokens can exchange features.'
DETAIL_QUOTE = 'Each routing layer independently predicts a sparse window assignment for all tokens.'
PAGES = [
    {'number': 2, 'text': '2. Related Work\n2.1. Existing Architecture\n' + RELATED_QUOTE +
                          ' Previous work uses a shared convolution kernel for every image.'},
    {'number': 3, 'text': '3. Proposed Model\n' + METHOD_QUOTE + ' ' + DETAIL_QUOTE},
    {'number': 4, 'text': '4. Experiments\n4.1. Architecture Comparison\n' +
                          'The proposed model is benchmarked against older models on a new dataset. ' * 2},
]


class ContributionExtractionTests(unittest.TestCase):
    def test_related_work_cannot_be_submitted_as_contribution_evidence(self):
        chunks = retrieve_methods(PAGES, 'patch routes')
        self.assertEqual([(row['kind'], row['page']) for row in chunks], [('method', 3), ('related_work', 2)])
        contributions = grounded_contributions([
            {'title': 'Learned patch routes', 'chunk_id': 'M1', 'quote': METHOD_QUOTE, 'details': [
                {'title': 'Sparse window assignment', 'chunk_id': 'M1', 'quote': DETAIL_QUOTE},
                {'title': 'Fixed neighbourhood', 'chunk_id': 'R1', 'quote': RELATED_QUOTE},
            ]},
            {'title': 'Existing architecture', 'chunk_id': 'R1', 'quote': RELATED_QUOTE},
        ], chunks)
        self.assertEqual([row['title'] for row in contributions], ['Learned patch routes'])
        self.assertEqual([row['title'] for row in contributions[0]['details']], ['Sparse window assignment'])

    def test_dedicated_extraction_enriches_a_private_node_with_the_same_pdf(self):
        owner = 'a' * 64
        raw = b'%PDF-test original'
        material = {'name': 'original.pdf', 'content_base64': base64.b64encode(raw).decode()}
        existing = {'title': 'Learned patch routes', 'local_id': 'c1', 'quote': METHOD_QUOTE, 'page': 3,
                    'section': '3. Proposed Model', 'method_grounded': True, 'details': []}
        result = {'contributions': [{'title': existing['title'], 'existing_id': method_key(existing),
                                     'summary': 'Routes let selected tokens exchange features.',
                                     'chunk_id': 'M1', 'quote': METHOD_QUOTE, 'details': [
                                         {'title': 'Sparse window assignment', 'summary': 'Assigns windows in each layer.',
                                          'chunk_id': 'M1', 'quote': DETAIL_QUOTE}]}]}
        def model(request):
            self.assertIn('related_work', request['messages'][0]['content'])
            self.assertIn(RELATED_QUOTE, request['messages'][1]['content'])
            return {'choices': [{'message': {'content': json.dumps(result)}}]}
        budget_calls = []
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='test'),
            reviewer=SimpleNamespace(configured=True, model='test', post=model),
            budget=SimpleNamespace(reserve=lambda: budget_calls.append('reserved')))
        ingested = graph.ingest_project(owner, {'project_id': 'project', 'report': {
            'materials': {'paper': hashlib.sha256(raw).hexdigest()},
            'review': {'paper_title': 'Test paper', 'method_graph': [existing]}}})
        paper = ingested['focus_paper_id']
        root_before = next(node for node in ingested['nodes'] if node['node_type'] == 'Contribution')
        self.assertEqual(ingested['papers'][0]['method_detail_status'], 'pending')
        unavailable = graph.retry_contributions(owner, paper)
        self.assertEqual(unavailable['papers'][0]['method_detail_status'], 'no_full_text')
        self.assertIn('原始 PDF', unavailable['method_notice'])
        with self.assertRaises(ReviewError) as error:
            graph.retry_contributions('b' * 64, paper, material)
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ReviewError) as error:
            graph.retry_contributions(owner, paper, {**material, 'content_base64': base64.b64encode(b'%PDF-other').decode()})
        self.assertEqual(error.exception.code, 'paper_changed')
        with patch('articheck.kg_service.extract_paper', return_value=(PAGES, {})):
            graph.retry_contributions(owner, paper, material)
        self.assertEqual(budget_calls, ['reserved'])
        reread = graph.build_graph_response(owner, focus_paper_id=paper)
        self.assertEqual(reread['papers'][0]['method_detail_status'], 'grounded')
        self.assertEqual(reread['papers'][0]['detail_count'], 1)
        child = next(node for node in reread['nodes'] if node['node_type'] == 'Detail')
        self.assertEqual((child['parent_id'], child['page'], child['section'], child['quote']),
                         (root_before['id'], 3, '3. Proposed Model', DETAIL_QUOTE))
        self.assertEqual(child['summary'], 'Assigns windows in each layer.')

    def test_retrieval_explains_body_with_insufficient_method_evidence(self):
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='test'))
        owner = 'a' * 64
        graph.update_literature(owner, lambda data: data['papers'].update({'W1': {'id': 'W1', 'title': 'Public paper'}}))
        with patch('articheck.kg_service.verify_public_fulltext', return_value=([], 'verified')):
            result = graph.retry_contributions(owner, 'W1')
        self.assertEqual(result['papers'][0]['method_status'], 'insufficient_evidence')
        self.assertIn('正文片段不足', result['papers'][0]['method_reason'])

    def test_fulltext_verification_rejects_scans_and_wrong_papers(self):
        self.assertEqual(pdf_text_status([{'text': ''}], 'Routing'), 'unreadable_pdf')
        body = 'Each layer dynamically selects a sparse route. ' * 15
        self.assertEqual(pdf_text_status([{'text': 'A Different Paper\n' + body}], 'Routing'), 'identity_mismatch')
        self.assertEqual(pdf_text_status([{'text': 'Routing\n' + body}], 'Routing'), 'verified')

    def test_multilevel_expansion_fetches_only_verified_neighborhoods(self):
        owner = 'a' * 64
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='test'))
        records = {
            number: {'id': f'https://openalex.org/W{number}', 'display_name': title,
                     'referenced_works': [f'https://openalex.org/W{ref}' for ref in refs]}
            for number, title, refs in [(1, 'Root', [2, 3]), (2, 'Book record', [4]),
                                         (3, 'Verified paper', [5]), (4, 'Never fetched', []),
                                         (5, 'Leaf', [])]
        }
        events = []
        graph.literature = OpenAlex()
        def identify(*, title, identifier='', doi=''):
            return next(row for row in records.values() if row['display_name'] == title)
        def request(path='', **params):
            ids = params['filter'].split(':')[1]
            events.append(('relations', ids))
            return {'results': [records[int(key[1:])] for key in ids.split('|')]}
        def verify(paper, provider, deadline, **kwargs):
            events.append(('verify', paper['id']))
            return [], 'no_full_text' if paper['id'] == 'W2' else 'verified'
        graph.literature.identify = identify
        graph.literature.request = request
        graph.update_literature(owner, lambda state: state['papers'].update({'W1': {'id': 'W1', 'title': 'Root'}}))
        with patch('articheck.kg_service.verify_public_fulltext', side_effect=verify):
            result = graph.expand_literature(owner, 'W1', kinds=['previous'], limit=5, depth=2, total=6)
        self.assertLess(events.index(('verify', 'W1')), events.index(('relations', 'W2|W3')))
        self.assertLess(events.index(('verify', 'W3')), events.index(('relations', 'W5')))
        self.assertNotIn(('relations', 'W4'), events)
        self.assertEqual(next(row for row in result['papers'] if row['paper_id'] == 'W2')['fulltext_status'], 'no_full_text')
        self.assertIn('W5', {row['paper_id'] for row in result['papers']})

    def test_public_retrieval_tries_attributed_open_edition_after_unusable_link(self):
        source = 'https://arxiv.org/pdf/1512.03385'
        alternate = 'https://openreview.net/pdf?id=Paper_1'
        self.assertTrue(allowed_pdf(alternate))
        self.assertFalse(allowed_pdf(alternate + '&redirect=https://example.test'))
        self.assertFalse(allowed_pdf('https://openreview.net/forum?id=Paper_1'))
        chunks = retrieve_methods(PAGES)
        paper = {'id': 'W1', 'title': 'Routing', 'authors': ['A1'], 'pdf_sources': [source]}
        provider = SimpleNamespace(find_open_editions=lambda value: [source, alternate])
        with patch('articheck.kg_literature.fetch_method_chunks', side_effect=[([], 'no_full_text'), (chunks, 'pending')]) as fetch:
            self.assertEqual(retrieve_public_methods([paper], 'routing', provider, include_status=True),
                             {'W1': (chunks, 'pending')})
        self.assertEqual(fetch.call_args.args[0]['pdf_sources'], [alternate])


if __name__ == '__main__':
    unittest.main()
