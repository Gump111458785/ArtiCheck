"""Read bounded, public citation neighborhoods from OpenAlex."""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
import json
from pathlib import Path
import tempfile
import time
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen, build_opener, HTTPRedirectHandler, Request

from .kg_methods import retrieve_methods
from .reproduction.paper_text import extract_paper
from .review_api import ReviewError

WORK_ID = re.compile(r'(?:https://openalex\.org/)?(W[0-9]{1,18})\Z')
FIELDS = 'id,display_name,doi,publication_year,primary_location,primary_topic,best_oa_location,locations,related_works,authorships,referenced_works'
KINDS = {'previous', 'next', 'similar'}
LIMITS = {3, 5, 8}
PDF_HOSTS = {'arxiv.org', 'export.arxiv.org', 'openaccess.thecvf.com', 'aclanthology.org',
             'proceedings.mlr.press', 'jmlr.org', 'www.jmlr.org', 'proceedings.neurips.cc',
             'papers.nips.cc', 'pmc.ncbi.nlm.nih.gov'}
OPENREVIEW_ID = re.compile(r'id=[A-Za-z0-9_-]{1,64}\Z')
PDF_LIMIT = 12 * 1024**2



def work_id(value):
    match = WORK_ID.fullmatch(value) if isinstance(value, str) else None
    return match[1] if match else ''


def normalize_title(title):
    return ''.join(char for char in title.casefold() if char.isalnum())


def author_ids(work):
    return {item['author']['id'] for item in work.get('authorships', [])
            if (item.get('author') or {}).get('id')}


def matching_edition(work, candidate):
    authors = author_ids(work)
    return (normalize_title(work.get('display_name') or '') == normalize_title(candidate.get('display_name') or '')
            and bool(authors) and len(authors & author_ids(candidate)) >= max(1, len(authors) * .75))


def work_metadata(work):
    identifier = work_id(work.get('id'))
    title = work.get('display_name')
    if not identifier or not isinstance(title, str) or not title.strip():
        return None
    location = work.get('primary_location') or {}
    source = location.get('source') or {}
    topic = work.get('primary_topic') or {}
    year = work.get('publication_year')
    venue = str(source.get('display_name') or '')[:180] if source.get('type') in {'journal', 'conference'} else ''
    if venue and venue.count(' - ') == 1:
        left, right = venue.split(' - ')
        if left == right:
            venue = left
    url = 'https://openalex.org/' + identifier
    urls = []
    for location in [work.get('best_oa_location'), *(work.get('locations') or [])[:24]]:
        if not isinstance(location, dict) or not location.get('is_oa'):
            continue
        pdf, landing = location.get('pdf_url'), location.get('landing_page_url')
        if allowed_pdf(pdf):
            urls.append(pdf)
        if isinstance(landing, str) and re.fullmatch(r'https://arxiv\.org/abs/(?:[a-z-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?', landing):
            urls.append(landing.replace('/abs/', '/pdf/', 1))
        if isinstance(landing, str) and landing.startswith('https://openreview.net/forum?'):
            candidate = landing.replace('/forum?', '/pdf?', 1)
            if allowed_pdf(candidate):
                urls.append(candidate)
    doi = work.get('doi') or ''
    preprint = re.fullmatch(r'https://doi\.org/10\.48550/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?', doi, re.I)
    if preprint:
        urls.append('https://arxiv.org/pdf/' + preprint[1])
    return {'id': identifier, 'title': title[:350], 'year': year if type(year) is int else None,
            'venue': venue, 'direction': str(topic.get('display_name') or '')[:180],
            'source_url': url, 'pdf_sources': list(dict.fromkeys(urls))[:2], 'authors': sorted(author_ids(work))[:30]}


def allowed_pdf(value):
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in {None, 443} or url.fragment:
            return False
        if url.hostname == 'openreview.net':
            return url.path == '/pdf' and OPENREVIEW_ID.fullmatch(url.query) is not None
        return (url.hostname in PDF_HOSTS and not url.query and bool(url.path)
                and (url.path.endswith('.pdf') or url.hostname == 'aclanthology.org'
                     or url.hostname in {'arxiv.org','export.arxiv.org'} and url.path.startswith('/pdf/')))
    except ValueError:
        return False


def pdf_text_status(pages, title):
    first_page = pages[0].get('text', '')[:5000] if pages else ''
    body_length = sum(len(normalize_title(page.get('text', ''))) for page in pages[:3])
    if body_length < 240:
        return 'unreadable_pdf'
    title = normalize_title(title)
    return 'verified' if title and title in normalize_title(first_page) else 'identity_mismatch'


def fetch_method_chunks(paper, query, deadline, *, verify=False, progress=lambda phase: None):
    class PublicPDFRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allowed_pdf(newurl):
                raise URLError('Redirect outside public PDF allowlist')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    status = 'no_full_text'
    for url in paper.get('pdf_sources', []):
        remaining = deadline - time.monotonic()
        if not allowed_pdf(url):
            continue
        if remaining < 2:
            return [], ('download_failed' if status == 'no_full_text' else status) if verify else (status if status == 'insufficient_evidence' else 'pending')
        try:
            request = Request(url, headers={'User-Agent': 'ArtiCheck/1.0 public research methods', 'Accept': 'application/pdf'})
            with build_opener(PublicPDFRedirects()).open(request, timeout=min(6, remaining/2)) as response:
                data = bytearray()
                while len(data) <= PDF_LIMIT and deadline - time.monotonic() > 1:
                    block = response.read1(256 * 1024)
                    if not block:
                        break
                    data.extend(block)
                else:
                    if deadline - time.monotonic() <= 1 and status != 'insufficient_evidence':
                        status = 'pending'
                    continue
                raw = bytes(data)
                source = response.geturl()
            if not allowed_pdf(source) or not raw.startswith(b'%PDF-') or len(raw) > PDF_LIMIT:
                continue
            status = 'unreadable_pdf' if verify else 'insufficient_evidence'
            if verify:
                progress('reading')
            with tempfile.TemporaryDirectory(prefix='articheck-oa-') as directory:
                path = Path(directory) / 'paper.pdf'
                path.write_bytes(raw)
                pages, _ = extract_paper(path, timeout=max(1, min(10, deadline - time.monotonic())))
            if verify:
                status = pdf_text_status(pages, paper['title'])
                if status != 'verified':
                    continue
            chunks = retrieve_methods(pages, query=query, limit=4)
            if verify:
                return [{**chunk, 'source_url': source} for chunk in chunks], 'verified'
            if chunks:
                return [{**chunk, 'source_url': source} for chunk in chunks], 'pending'
        except HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                if status == 'no_full_text':
                    status = 'download_failed' if verify else 'pending'
        except (URLError, TimeoutError):
            if status == 'no_full_text':
                status = 'download_failed' if verify else 'pending'
        except (OSError, ValueError):
            continue
    if verify and status == 'no_full_text' and paper.get('pdf_sources'):
        status = 'download_failed'
    return [], status


def verify_public_fulltext(paper, provider, deadline, *, progress=lambda phase: None):
    progress('downloading')
    chunks, status = fetch_method_chunks(paper, paper['title'], deadline, verify=True, progress=progress)
    if status == 'verified' or not paper.get('authors') or deadline - time.monotonic() < 4:
        return chunks, status
    try:
        tried = set(paper.get('pdf_sources', []))
        sources = [url for url in provider.find_open_editions(paper) if url not in tried]
    except (ReviewError, OSError, ValueError):
        return chunks, status
    if sources:
        progress('downloading')
        alternate, alternate_status = fetch_method_chunks({**paper, 'pdf_sources': sources}, paper['title'], deadline,
                                                           verify=True, progress=progress)
        if alternate_status == 'verified' or status == 'no_full_text':
            return alternate, alternate_status
    return chunks, status


def retrieve_public_methods(papers, query, provider=None, *, include_status=False, check=lambda: None):
    if not papers:
        return {}
    deadline = time.monotonic() + 28
    def retrieve(paper):
        check()
        chunks, status = fetch_method_chunks(paper, query, deadline)
        if not chunks and provider and paper.get('authors') and deadline - time.monotonic() > 7:
            check()
            try:
                tried = set(paper.get('pdf_sources', []))
                sources = [url for url in provider.find_open_editions(paper) if url not in tried]
            except (ReviewError, OSError, ValueError):
                sources = []
                if status == 'no_full_text':
                    status = 'pending'
            if sources:
                chunks, alternate = fetch_method_chunks({**paper, 'pdf_sources': sources}, query, deadline)
                if chunks or alternate == 'insufficient_evidence' or status == 'no_full_text':
                    status = alternate
        return (chunks, status) if include_status else chunks

    with ThreadPoolExecutor(max_workers=min(4, len(papers))) as pool:
        return dict(zip((paper['id'] for paper in papers), pool.map(retrieve, papers)))


class OpenAlex:
    def __init__(self, key=''):
        self.key = key
        self.request_slots = BoundedSemaphore(3)

    def request(self, path='', **params):
        query = {'select': FIELDS, **params}
        if self.key:
            query['api_key'] = self.key
        try:
            with self.request_slots, urlopen('https://api.openalex.org/works' + path + '?' + urlencode(query), timeout=8) as response:
                return json.loads(response.read(1_000_000))
        except HTTPError as error:
            if error.code == 404:
                return {}
            raise ReviewError('literature_unavailable', '公开书目暂时无法访问，请稍后重试。', 503) from error
        except (URLError, TimeoutError, ValueError) as error:
            raise ReviewError('literature_unavailable', '公开书目暂时无法访问，请稍后重试。', 503) from error

    def find_open_editions(self, paper):
        author_set = set(paper['authors'])
        hits = self.request(search=paper['title'][:300], per_page=5).get('results', [])
        sources = []
        for hit in hits:
            if (normalize_title(hit.get('display_name') or '') == normalize_title(paper['title'])
                    and len(author_set & author_ids(hit)) >= max(1, len(author_set) * .75)):
                metadata = work_metadata(hit)
                if metadata:
                    sources.extend(metadata['pdf_sources'])
        return list(dict.fromkeys(sources))[:2]

    def identify(self, *, title, identifier='', doi=''):
        if work_id(identifier):
            return self.request('/' + work_id(identifier))
        if re.fullmatch(r'10\.\d{4,9}/[-._;()/:a-z0-9]+', doi or '', re.I):
            hits = self.request(filter='doi:https://doi.org/' + doi, per_page=3).get('results', [])
            if len(hits) == 1:
                return hits[0]
        title_key = normalize_title(title)
        hits = self.request(search=title[:300], per_page=8).get('results', []) if title_key else []
        exact = [row for row in hits if normalize_title(row.get('display_name') or '') == title_key]
        if len(exact) == 1:
            return exact[0]
        published = [row for row in exact if ((row.get('primary_location') or {}).get('source') or {}).get('type') in {'journal', 'conference'}]
        if len(published) == 1:
            candidate = published[0]

            if all(row is candidate or matching_edition(candidate, row) for row in exact):
                locations = [location for row in exact if row is not candidate for location in row.get('locations', [])]
                return {**candidate, 'locations': [*(candidate.get('locations') or []), *locations]}
        raise ReviewError('literature_unmatched', '未能唯一匹配公开论文。请核对论文题目或 DOI。', 404)

    def neighborhood(self, *, title, identifier='', doi='', kinds, limit, before_relations=None):
        anchor = self.identify(title=title, identifier=identifier, doi=doi)
        metadata = work_metadata(anchor)
        if not metadata:
            raise ReviewError('literature_unmatched', '公开书目中未找到这篇论文。', 404)
        if before_relations:
            before_relations(metadata)
        anchor_id = metadata['id']

        references = [identifier for value in anchor.get('referenced_works', [])
                      if (identifier := work_id(value)) and identifier != anchor_id]

        def group(kind):
            if kind == 'next':
                rows = self.request(filter='cites:' + anchor_id, per_page=limit*3).get('results', [])
                rows = [row for row in rows if work_id(row.get('id')) not in references
                        and anchor_id in {work_id(value) for value in row.get('referenced_works', [])}]
            else:
                ids = references[:limit*4] if kind == 'previous' else [
                    identifier for value in anchor.get('related_works', [])
                    if (identifier := work_id(value)) and identifier != anchor_id
                ][:limit*2]
                ids = list(dict.fromkeys(ids))
                if not ids:
                    return kind, []
                rows = self.request(filter='openalex_id:' + '|'.join(ids), per_page=len(ids)).get('results', [])
                rows = [row for row in rows if work_id(row.get('id')) in ids]
            papers = [paper for row in rows if (paper := work_metadata(row)) and paper['id'] != anchor_id]
            year = metadata['year']
            if kind == 'previous' and year:
                papers = [paper for paper in papers if not paper['year'] or paper['year'] <= year]
            elif kind == 'next' and year:
                papers = [paper for paper in papers if not paper['year'] or paper['year'] >= year]
            return kind, papers[:limit]

        if not kinds:
            return metadata, {}
        with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
            groups = dict(pool.map(group, sorted(kinds)))
        return metadata, groups
