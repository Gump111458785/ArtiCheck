import base64
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from articheck.kg_literature import OpenAlex, allowed_pdf, paper_reference, pdf_text_status, retrieve_public_methods, verify_public_fulltext
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
        with patch.object(graph.literature, 'identify', side_effect=ReviewError('literature_unmatched', '未匹配')), \
                patch.object(graph, 'acquire_paper_pdf', return_value=([], 'no_full_text', None)):
            unavailable = graph.retry_contributions(owner, paper)
        self.assertEqual(unavailable['papers'][0]['method_detail_status'], 'no_full_text')
        self.assertIn('未取得可读开放原文', unavailable['method_notice'])
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

    def test_multilevel_expansion_follows_metadata_without_downloading_pdfs(self):
        owner = 'a' * 64
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='test'))
        records = {
            number: {'id': f'https://openalex.org/W{number}', 'display_name': title,
                     'referenced_works': [f'https://openalex.org/W{ref}' for ref in refs]}
            for number, title, refs in [(1, 'Root', [2, 3]), (2, 'Book record', [4]),
                                         (3, 'Verified paper', [5]), (4, 'Book reference', []),
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
        graph.literature.identify = identify
        graph.literature.request = request
        graph.update_literature(owner, lambda state: state['papers'].update({'W1': {'id': 'W1', 'title': 'Root'}}))
        with patch.object(graph, 'acquire_paper_pdf') as acquire:
            result = graph.expand_literature(owner, 'W1', kinds=['previous'], limit=5, depth=2, total=6)
        acquire.assert_not_called()
        self.assertIn(('relations', 'W4'), events)
        self.assertIn(('relations', 'W5'), events)
        self.assertEqual({row['paper_id'] for row in result['papers']}, {'W1', 'W2', 'W3', 'W4', 'W5'})
        self.assertTrue(all(not row['pdf_available'] for row in result['papers']))

    def test_find_pdf_for_discovered_paper_without_changing_graph(self):
        owner = 'a' * 64
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='test'))
        graph.literature = OpenAlex()
        paper = {'id': 'W2', 'title': 'Public paper', 'fallback_url': 'https://arxiv.org/abs/1706.03762'}
        graph.update_literature(owner, lambda state: state['papers'].update({'W2': paper}))
        with patch.object(graph, 'acquire_paper_pdf', return_value=([], 'no_full_text', None)):
            result = graph.retry_contributions(owner, 'W2')
        self.assertEqual(result['papers'][0]['fallback_url'], paper['fallback_url'])
        self.assertFalse(result['papers'][0]['pdf_available'])
        raw = (Path(__file__).resolve().parents[1] / 'web/dist/samples/articheck-method-note.pdf').read_bytes()
        record = graph.pdfs.save(graph._owner_hash(owner), raw, paper, 'https://arxiv.org/pdf/1706.03762')
        with patch.object(graph, 'acquire_paper_pdf', return_value=([], 'verified', record)):
            result = graph.retry_contributions(owner, 'W2')
        self.assertTrue(result['papers'][0]['pdf_available'])
        self.assertEqual(graph.paper_file(owner, 'W2')[0], raw)
        self.assertIn('已下载', graph.paper_index(owner))

    def test_download_source_order_and_identifiers(self):
        self.assertEqual(paper_reference('https://arxiv.org/pdf/1706.03762v2.pdf'), ('arxiv','1706.03762v2'))
        self.assertEqual(paper_reference('https://doi.org/10.1000/example'), ('doi','10.1000/example'))
        self.assertEqual(paper_reference('Learning residual routes'), ('title','Learning residual routes'))
        self.assertEqual(paper_reference('https://example.org/paper'), ('url','https://example.org/paper'))
        urls = ['https://arxiv.org/pdf/1706.03762','https://pdfs.semanticscholar.org/sample.pdf',
                'https://openaccess.thecvf.com/routing.pdf','https://aclanthology.org/routing.pdf']
        sources = SimpleNamespace(arxiv=lambda **kw:{'arxiv_id':'1706.03762'},
            semantic=lambda **kw:{'title':'Routing','openAccessPdf':{'url':urls[1]}},
            unpaywall=lambda doi, deadline:[urls[3]])
        paper = {'title':'Routing','doi':'10.1000/example','pdf_sources':[urls[2]]}
        seen = []
        def try_pdf(record, query, deadline, **kwargs):
            seen.extend(record['pdf_sources'])
            return ([], 'verified' if seen[-1]==urls[3] else 'download_failed')
        with patch('articheck.kg_literature.fetch_method_chunks',side_effect=try_pdf):
            self.assertEqual(verify_public_fulltext(paper,OpenAlex(),time.monotonic()+30,sources=sources),([], 'verified'))
        self.assertEqual(seen,urls)

    def test_pdf_attachment_is_account_scoped_and_indexed(self):
        graph = KnowledgeGraphService({},SimpleNamespace(namespace='test'))
        owner = 'a'*64
        raw = (Path(__file__).resolve().parents[1]/'web/dist/samples/articheck-method-note.pdf').read_bytes()
        paper = {'id':'W1','title':'A Routing Study','author_names':['Alice Example'],'year':2026,'source_url':'https://openalex.org/W1'}
        graph.update_literature(owner,lambda state:state['papers'].update({'W1':paper}))
        material = {'name':'sample.pdf','content_base64':base64.b64encode(raw).decode()}
        pages = [{'number':1,'text':paper['title']+'\n'+METHOD_QUOTE*8}]
        with patch('articheck.kg_service.extract_paper',return_value=(pages,{})):
            result = graph.retry_contributions(owner,'W1',material)
        self.assertTrue(result['papers'][0]['pdf_available'])
        self.assertEqual(graph.paper_file(owner,'W1')[0],raw)
        self.assertEqual(graph.paper_file(owner,'W1',offset=17,size=501)[0],raw[17:518])
        self.assertIn('2026_Alice Example_A Routing Study.pdf',graph.paper_index(owner))
        self.assertIn('已插入',graph.paper_index(owner))
        with self.assertRaises(ReviewError):
            graph.paper_file('b'*64,'W1')

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


    def test_imports_reuse_paper_and_keep_published_venue_and_arxiv_version(self):
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='import-test'))
        owner = 'a' * 64
        title = 'ArtiCheck: Artifact Evaluation Fixture'
        sample = Path(__file__).resolve().parents[1] / 'web/dist/samples/articheck-method-note.pdf'
        raw = sample.read_bytes()
        material = {'name': sample.name, 'content_base64': base64.b64encode(raw).decode()}
        work = {'id': 'https://openalex.org/W42', 'display_name': title, 'doi': 'https://doi.org/10.1000/demo',
                'primary_location': {'source': {'type': 'repository'}},
                'locations': [{'source': {'type': 'conference', 'display_name': 'Test Conference'}}]}
        arxiv_url = 'https://arxiv.org/pdf/1706.03762v2'
        graph.literature = SimpleNamespace(identify=lambda **kwargs: work)
        graph.open_pdf_sources = SimpleNamespace(
            arxiv=lambda **kwargs: {'title': title, 'arxiv_id': '1706.03762v2'},
            semantic=lambda **kwargs: {'title': title, 'externalIds': {'DOI': '10.1000/demo'}})
        fetches = []

        def acquire(account, paper, _deadline, **kwargs):
            fetches.append(paper.get('arxiv_id'))
            return [], 'verified', graph.pdfs.save(graph._owner_hash(account), raw, paper, arxiv_url)

        with patch.object(graph, 'acquire_paper_pdf', side_effect=acquire):
            first = graph.import_public_paper(owner, title)
            second = graph.import_public_paper(owner, 'https://doi.org/10.1000/demo')
            third = graph.import_public_paper(owner, 'https://arxiv.org/abs/1706.03762v2')
            uploaded = graph.import_public_paper(owner, material=material)
        self.assertEqual(fetches, [None])
        for result in (first, second, third, uploaded):
            self.assertEqual(result['focus_paper_id'], 'W42')
            self.assertEqual(result['stats']['paper_count'], 1)
            self.assertEqual(result['timeline'][0]['venue'], 'Test Conference')
            self.assertEqual(result['nodes'][0]['metadata']['venue']['source'], 'OpenAlex')
        self.assertEqual(third['papers'][0]['fallback_url'], 'https://arxiv.org/abs/1706.03762v2')
        self.assertEqual(graph.paper_file(owner, 'W42')[0], raw)

    def test_all_bibliography_inputs_try_arxiv_before_other_pdf_hosts(self):
        title = 'A Routing Study'
        for reference in (title, '10.1000/routing', 'https://example.org/routing',
                          'https://arxiv.org/abs/1706.03762v2'):
            with self.subTest(reference=reference):
                graph = KnowledgeGraphService({}, SimpleNamespace(namespace='priority-test'))
                graph.literature = SimpleNamespace(identify=lambda **kwargs: {
                    'id': 'https://openalex.org/W42', 'display_name': title, 'locations': [
                        {'is_oa': True, 'pdf_url': 'https://openaccess.thecvf.com/routing.pdf'}]})
                graph.open_pdf_sources = SimpleNamespace(
                    arxiv=lambda **kwargs: {'title': title, 'arxiv_id': kwargs.get('identifier', '1706.03762')},
                    semantic=lambda **kwargs: {'title': title, 'externalIds': {'DOI': '10.1000/routing',
                                                                              'ArXiv': '1706.03762'},
                                               'openAccessPdf': {'url': 'https://pdfs.semanticscholar.org/routing.pdf'}})
                attempts = []

                def download(record, *args, **kwargs):
                    url = record['pdf_sources'][0]
                    attempts.append(url)
                    if 'arxiv.org' in url:
                        return [], 'download_failed'
                    kwargs['save_pdf'](b'%PDF-test', url)
                    return [], 'verified'

                with patch('articheck.kg_literature.fetch_method_chunks', side_effect=download):
                    result = graph.import_public_paper('a' * 64, reference)
                suffix = '1706.03762v2' if 'arxiv.org' in reference else '1706.03762'
                self.assertEqual(attempts, ['https://arxiv.org/pdf/' + suffix,
                                            'https://pdfs.semanticscholar.org/routing.pdf'])
                self.assertTrue(result['papers'][0]['pdf_available'])

    def test_auto_expansion_reuses_existing_nodes_and_caps_new_papers_across_two_hops(self):
        graph = KnowledgeGraphService({}, SimpleNamespace(namespace='expansion-test'))
        owner = 'a' * 64
        record = lambda i: {'id': f'W{i}', 'title': f'Paper {i}'}
        graph.update_literature(owner, lambda state: state['papers'].update(
            {key: value for key, value in [('W1', record(1)), ('W8', record(8))]}))
        visited = []

        def neighborhood(*, identifier, **kwargs):
            visited.append(identifier)
            if identifier == 'W1':
                return record(1), {'previous': [record(i) for i in (2, 3, 4, 8)]}
            number = int(identifier[1:])
            return record(number), {'previous': [record(i) for i in (10, 11, 12, 13)]}

        graph.literature = SimpleNamespace(neighborhood=neighborhood)
        expanded = graph.expand_literature(owner, 'W1', kinds=['previous'], limit=5, depth=2, total=5)
        self.assertEqual(expanded['stats']['paper_count'], 7)
        self.assertIn('W8', visited[1:])
        self.assertNotIn('W10', visited)
        edges = {(edge['source'], edge['target']) for edge in expanded['edges']}
        self.assertIn(('W8', 'W1'), edges)
        self.assertIn(('W10', 'W8'), edges)


if __name__ == '__main__':
    unittest.main()
