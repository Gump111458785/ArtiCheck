"""Read bounded, public citation neighborhoods from OpenAlex."""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
import json
from pathlib import Path
import tempfile
import time
import re
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
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
             'papers.nips.cc', 'pmc.ncbi.nlm.nih.gov', 'europepmc.org', 'www.biorxiv.org',
             'www.medrxiv.org', 'www.frontiersin.org', 'www.mdpi.com', 'www.nature.com',
             'link.springer.com', 'dl.acm.org', 'ieeexplore.ieee.org', 'hal.science', 'eprint.iacr.org',
             'www.usenix.org', 'drops.dagstuhl.de', 'pdfs.semanticscholar.org', 'www.semanticscholar.org',
             'zenodo.org', 'journals.plos.org'}
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
    sources = [item.get('source') or {} for item in [location, *(work.get('locations') or [])]
               if isinstance(item, dict)]
    source = next((item for item in sources if item.get('type') in {'journal', 'conference'}), {})
    topic = work.get('primary_topic') or {}
    year = work.get('publication_year')
    venue = str(source.get('display_name') or '')[:180] if source.get('type') in {'journal', 'conference'} else ''
    if venue and venue.count(' - ') == 1:
        left, right = venue.split(' - ')
        if left == right:
            venue = left
    url = 'https://openalex.org/' + identifier
    landing = location.get('landing_page_url')
    fallback = landing if isinstance(landing,str) and re.fullmatch(r'https://[^/@]+/[^\s]*',landing) else url
    urls = []
    names = [str((row.get('author') or {}).get('display_name') or '')[:140] for row in work.get('authorships', [])[:40]]
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
            'source_url': url, 'fallback_url': fallback, 'doi': doi, 'author_names': [name for name in names if name], 'pdf_sources': list(dict.fromkeys(sorted(urls, key=lambda url: urlsplit(url).hostname not in {'arxiv.org', 'export.arxiv.org'})))[:6], 'authors': sorted(author_ids(work))[:30]}


def allowed_pdf(value):
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in {None, 443} or url.fragment:
            return False
        if url.hostname == 'openreview.net':
            return url.path == '/pdf' and OPENREVIEW_ID.fullmatch(url.query) is not None
        if url.hostname=='journals.plos.org' and re.fullmatch(r'/[a-z]+/article/file',url.path):
            params=parse_qs(url.query)
            return (set(params)=={'id','type'} and len(params['id'])==1 and
                    re.fullmatch(r'10\.1371/journal\.[a-z]+\.[0-9]+',params['id'][0]) is not None and
                    params['type']==['printable'])
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


def fetch_method_chunks(paper, query, deadline, *, verify=False, progress=lambda phase: None, save_pdf=None):
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
                        status = 'download_failed' if verify else 'pending'
                    continue
                raw = bytes(data)
                source = response.geturl()
            requested = paper.get('requested_arxiv_id')
            if (not allowed_pdf(source) or not raw.startswith(b'%PDF-') or len(raw) > PDF_LIMIT
                    or requested and urlsplit(source).hostname in {'arxiv.org', 'export.arxiv.org'}
                    and urlsplit(source).path.removesuffix('.pdf') != '/pdf/' + requested):
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
                if save_pdf:
                    save_pdf(raw, source)
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


ARXIV_ID = re.compile(r'(?:[a-z-]+(?:\.[a-z-]+)?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?', re.I)
DOI = re.compile(r'10\.\d{4,9}/[^\s?#]+', re.I)


def paper_reference(value):
    text = value.strip()
    url = urlsplit(text) if text.startswith(('https://', 'http://')) else None
    if url and (url.username or url.password):
        raise ReviewError('invalid_paper_reference', '请填写公开论文链接。')
    if url and url.hostname in {'arxiv.org','export.arxiv.org'}:
        text = re.sub(r'^/(?:abs|pdf)/', '', url.path).removesuffix('.pdf')
    identifier = re.sub(r'^(?:arxiv:|10\.48550/arxiv\.)', '', text, flags=re.I)
    if ARXIV_ID.fullmatch(identifier):
        return 'arxiv', identifier
    if url and url.hostname == 'openalex.org' and work_id(url.path.lstrip('/')):
        return 'openalex', url.path.lstrip('/')
    doi = unquote(url.path.lstrip('/')) if url and url.hostname in {'doi.org','dx.doi.org'} else re.sub(r'^doi:', '', text, flags=re.I)
    if DOI.fullmatch(doi):
        arxiv = re.sub(r'^10\.48550/arxiv\.', '', doi, flags=re.I)
        return ('arxiv', arxiv) if ARXIV_ID.fullmatch(arxiv) else ('doi', doi)
    return ('url', value.strip()) if url else ('title', text)


class OpenPDFSources:
    def __init__(self, env):
        self.key = env.get('SEMANTIC_SCHOLAR_API_KEY', '')
        self.email = env.get('UNPAYWALL_EMAIL', '')

    @staticmethod
    def get(url, deadline, headers=None):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            return b''
        try:
            req = Request(url, headers={'User-Agent':'ArtiCheck/1.0 public paper lookup', **(headers or {})})
            with urlopen(req, timeout=min(4, remaining)) as response:
                return response.read(384_000)
        except (OSError, ValueError):
            return b''

    def json(self, url, deadline, headers=None):
        try:
            value = json.loads(self.get(url, deadline, headers))
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeError):
            return {}

    def arxiv(self, *, deadline, title='', identifier=''):
        params = {'max_results': 5}
        if identifier:
            params['id_list'] = identifier
        else:
            params['search_query'] = 'ti:"'+title.replace('"', ' ')[:280]+'"'
        raw = self.get('https://export.arxiv.org/api/query?'+urlencode(params), deadline)
        try:
            feed = ET.fromstring(raw)
        except ET.ParseError:
            return {}
        ns = {'a':'http://www.w3.org/2005/Atom','arxiv':'http://arxiv.org/schemas/atom'}
        for entry in feed.findall('a:entry', ns):
            candidate = entry.findtext('a:id', '', ns).split('/abs/')[-1]
            name = ' '.join(entry.findtext('a:title', '', ns).split())
            if not ARXIV_ID.fullmatch(candidate) or (identifier and re.sub(r'v\d+$','',candidate)!=re.sub(r'v\d+$','',identifier)):
                continue
            if not identifier and normalize_title(title)!=normalize_title(name):
                continue
            year = entry.findtext('a:published', '', ns)[:4]
            return {'arxiv_id':candidate,'title':name,'author_names':[el.text for el in entry.findall('a:author/a:name', ns)[:40] if el.text],
                    'year':int(year) if year.isdigit() else None,'doi':entry.findtext('arxiv:doi','',ns),
                    'source_url':'https://arxiv.org/abs/'+candidate}
        return {}

    def semantic(self, *, deadline, title='', reference=''):
        base = 'https://api.semanticscholar.org/graph/v1/paper/'
        fields = 'title,externalIds,openAccessPdf,authors,year,url,isOpenAccess'
        headers = {'x-api-key':self.key} if self.key else {}
        if reference:
            return self.json(base+quote(reference,safe='')+'?'+urlencode({'fields':fields}),deadline,headers)
        result = self.json(base+'search?'+urlencode({'query':title,'limit':5,'fields':fields}),deadline,headers)
        exact = [row for row in result.get('data', []) if normalize_title(row.get('title') or '')==normalize_title(title)]
        return exact[0] if len(exact)==1 else {}

    def unpaywall(self, doi, deadline):
        if not self.email or not DOI.fullmatch(doi or ''):
            return []
        data = self.json('https://api.unpaywall.org/v2/'+quote(doi,safe='/')+'?'+urlencode({'email':self.email}),deadline)
        if data.get('is_oa') is not True:
            return []
        locations = [data.get('best_oa_location'), *(data.get('oa_locations') or [])]
        return list(dict.fromkeys(row['url_for_pdf'] for row in locations if row and allowed_pdf(row.get('url_for_pdf'))))[:2]


def verify_public_fulltext(paper, provider, deadline, *, progress=lambda phase: None, sources=None, save_pdf=None):
    sources = sources or OpenPDFSources({})
    tried, status = set(), 'no_full_text'
    requested = paper.get('requested_arxiv_id', '')

    def is_arxiv(url):
        return allowed_pdf(url) and urlsplit(url).hostname in {'arxiv.org', 'export.arxiv.org'}

    def attempt(urls):
        nonlocal status
        candidates = [url for url in dict.fromkeys(urls) if allowed_pdf(url) and url not in tried
                      and (not requested or not is_arxiv(url)
                           or urlsplit(url).path.removesuffix('.pdf') == '/pdf/' + requested)]
        if not candidates:
            return []
        tried.update(candidates)
        progress('downloading')
        chunks, candidate_status = fetch_method_chunks({**paper,'pdf_sources':candidates}, paper['title'], deadline,
                                                        verify=True, progress=progress, save_pdf=save_pdf)
        if candidate_status == 'verified' or status in {'no_full_text','download_failed'}:
            status = candidate_status
        return chunks

    indexed = paper.get('pdf_sources', [])
    arxiv = [url for url in indexed if is_arxiv(url)]
    if paper.get('arxiv_id'):
        arxiv.insert(0,'https://arxiv.org/pdf/'+paper['arxiv_id'])
    chunks = attempt(arxiv)
    if status != 'verified' and not paper.get('arxiv_id'):
        edition = sources.arxiv(title=paper['title'], deadline=deadline)
        if edition:
            chunks = attempt(['https://arxiv.org/pdf/' + edition['arxiv_id']])
    if status == 'verified':
        return chunks, status
    doi = (paper.get('doi') or '').removeprefix('https://doi.org/')
    semantic = sources.semantic(title=paper['title'], reference='DOI:'+doi if DOI.fullmatch(doi) else '',deadline=deadline)
    if not semantic and doi:
        semantic = sources.semantic(title=paper['title'],deadline=deadline)
    if normalize_title(semantic.get('title') or '') == normalize_title(paper['title']):
        ext = semantic.get('externalIds') or {}
        doi = doi or ext.get('DOI') or ''
        arxiv_id = ext.get('ArXiv') or ''
        if ARXIV_ID.fullmatch(arxiv_id):
            chunks = attempt(['https://arxiv.org/pdf/'+arxiv_id])
            if status == 'verified':
                return chunks, status
    else:
        semantic = {}
    semantic_pdf = (semantic.get('openAccessPdf') or {}).get('url')
    if is_arxiv(semantic_pdf):
        chunks = attempt([semantic_pdf])
        if status == 'verified':
            return chunks, status
    alternates = []
    if paper.get('authors') and deadline-time.monotonic()>4:
        try:
            alternates = provider.find_open_editions(paper)
        except (ReviewError, OSError, ValueError):
            pass
    chunks = attempt([url for url in alternates if is_arxiv(url)])
    if status == 'verified':
        return chunks, status
    for urls in ([semantic_pdf], indexed, alternates):
        chunks = attempt(urls)
        if status == 'verified':
            return chunks, status
    chunks = attempt(sources.unpaywall(doi, deadline))
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
        return list(dict.fromkeys(sorted(sources, key=lambda url: urlsplit(url).hostname
                                         not in {'arxiv.org', 'export.arxiv.org'})))[:2]

    def identify(self, *, title, identifier='', doi=''):
        doi = (doi or '').removeprefix('https://doi.org/').lower()
        if work_id(identifier):
            return self.request('/' + work_id(identifier))
        if re.fullmatch(r'10\.\d{4,9}/[-._;()/:a-z0-9]+', doi or '', re.I):
            hits = self.request(filter='doi:https://doi.org/' + doi, per_page=3).get('results', [])
            if len(hits) == 1:
                hit = hits[0]
                if not doi.startswith('10.48550/arxiv.') or (work_metadata(hit) or {}).get('venue'):
                    return hit
                try:
                    published = self.identify(title=hit.get('display_name') or '')
                except ReviewError:
                    return hit
                if matching_edition(hit, published) and work_metadata(published).get('venue'):
                    return {**published, 'locations': [*(published.get('locations') or []), *(hit.get('locations') or [])]}
                return hit
        title_key = normalize_title(title)
        hits = self.request(search=title[:300], per_page=8).get('results', []) if title_key else []
        exact = [row for row in hits if normalize_title(row.get('display_name') or '') == title_key]
        if len(exact) == 1:
            return exact[0]
        published = [row for row in exact if (work_metadata(row) or {}).get('venue')]
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
