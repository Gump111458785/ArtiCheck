"""Read bounded, public citation neighborhoods from OpenAlex."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .review_api import ReviewError

WORK_ID = re.compile(r'(?:https://openalex\.org/)?(W[0-9]{1,18})\Z')
FIELDS = 'id,display_name,doi,publication_year,primary_location,primary_topic,abstract_inverted_index,related_works,authorships,referenced_works'
KINDS = {'previous', 'next', 'similar'}
LIMITS = {3, 5, 8}
CONTRIBUTION = re.compile(r'\b(?:we\s+(?:propose|introduce|present|develop|design|derive|prove|show)|this\s+(?:paper|work)\s+(?:introduces|presents|proposes)|our\s+(?:main\s+)?contribution)\b', re.I)


def work_id(value):
    match = WORK_ID.fullmatch(value) if isinstance(value, str) else None
    return match[1] if match else ''


def normalize_title(title):
    return ''.join(char for char in title.casefold() if char.isalnum())


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
    words = {}
    for token, indices in (work.get('abstract_inverted_index') or {}).items():
        for index in indices:
            if type(index) is int and 0 <= index < 600:
                words[index] = str(token)[:80]
    abstract = ' '.join(words[index] for index in sorted(words))
    url = 'https://openalex.org/' + identifier
    candidates = [part.strip() for part in re.split(r'(?<=[.!?])\s+', abstract)
                  if CONTRIBUTION.search(part) and len(part.split()) >= 7]
    contributions = [
        {'title': sentence[:260], 'summary': sentence[:420], 'source_url': url}
        for sentence in dict.fromkeys(candidates[:3])
    ]
    return {'id': identifier, 'title': title[:350], 'year': year if type(year) is int else None,
            'venue': venue, 'direction': str(topic.get('display_name') or '')[:180],
            'source_url': url, 'contributions': contributions}


class OpenAlex:
    def __init__(self, key=''):
        self.key = key

    def request(self, path='', **params):
        query = {'select': FIELDS, **params}
        if self.key:
            query['api_key'] = self.key
        try:
            with urlopen('https://api.openalex.org/works' + path + '?' + urlencode(query), timeout=8) as response:
                return json.loads(response.read(1_000_000))
        except HTTPError as error:
            if error.code == 404:
                return {}
            raise ReviewError('literature_unavailable', '公开书目暂时无法访问，请稍后重试。', 503) from error
        except (URLError, TimeoutError, ValueError) as error:
            raise ReviewError('literature_unavailable', '公开书目暂时无法访问，请稍后重试。', 503) from error

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

            def authors(row):
                return {item['author']['id'] for item in row.get('authorships', [])
                        if (item.get('author') or {}).get('id')}

            base = authors(candidate)
            # Treat a conference version and a same-title preprint as one work only
            # when the book-keeping IDs agree for most authors.
            if base and all(row is candidate or len(base & authors(row)) >= max(1, len(base) * .75) for row in exact):
                return candidate
        raise ReviewError('literature_unmatched', '未能唯一匹配公开论文。请核对论文题目或 DOI。', 404)

    def neighborhood(self, *, title, identifier='', doi='', kinds, limit):
        anchor = self.identify(title=title, identifier=identifier, doi=doi)
        metadata = work_metadata(anchor)
        if not metadata:
            raise ReviewError('literature_unmatched', '公开书目中未找到这篇论文。', 404)
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

        with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
            groups = dict(pool.map(group, sorted(kinds)))
        return metadata, groups
