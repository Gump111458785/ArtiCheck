"""Bounded public-source lookup using the same server-side DeepSeek account."""
import hashlib
import json
import os
import re
from urllib.parse import urlparse
import urllib.request

from .review_api import ReviewError


def public_identifier(context):
    if not context.get('paper'):
        return None
    for identifier in context.get('public_paper_ids',[]):
        if re.fullmatch(r'\d{4}\.\d{4,5}',identifier):return 'arXiv:'+identifier
    first=context['paper_excerpts'][0]['text'] if context['paper_excerpts'] else ''
    arxiv=re.search(r'arxiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?',first,re.I)
    if arxiv:return 'arXiv:'+arxiv.group(1)
    name=re.fullmatch(r'(\d{4}\.\d{4,5})(?:v\d+)?\.pdf',context['paper']['name'],re.I)
    if name:return 'arXiv:'+name.group(1)
    doi=re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+',first)
    return doi.group(0)[:100] if doi else None


def prepare_sources(context,sources,identifier):
    header=''.join(re.findall('[a-z]+',(context['paper_excerpts'][0]['text'][:2500] if context['paper_excerpts'] else '').lower()))
    primary=[];secondary=[];links=[]
    for source in sources:
        url=urlparse(source['url']);parts=url.path.strip('/').split('/')
        author_repo=(url.hostname=='github.com' and len(parts)>=2 and len(parts[0])>=6 and re.sub('[^a-z]','',parts[0].lower()) in header)
        original_paper=(url.hostname in {'arxiv.org','www.arxiv.org'} and identifier.removeprefix('arXiv:') in url.path)
        publisher=url.hostname in {'openaccess.thecvf.com','openreview.net','jmlr.org','www.jmlr.org','proceedings.mlr.press','aclanthology.org'}
        (primary if author_repo or original_paper or publisher else secondary).append({**source,'source_kind':'primary' if author_repo or original_paper or publisher else 'secondary'})
        for match in re.finditer(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',source.get('content','')+' '+source.get('summary','')):
            owner=match.group(1)
            if len(owner)>=6 and re.sub('[^a-z]','',owner.lower()) in header:
                links.append({'url':match.group(0).removesuffix('.git').rstrip('.'),'source_url':source['url']})
    context['discovered_code_links']=list({item['url']:item for item in links}.values())[:5]
    selected=(primary+secondary)[:5]
    # Keep page excerpts within the text-token budget. Full responses stay out
    # of the model prompt and never turn a mirror into independent validation.
    for source in selected:
        source['content']=source.get('content','')[:2000]
        source['summary']=source.get('summary','')[:500]
    return selected


def provider_tool(kind, body, *, key=None):
    if kind not in {'search','fetch'}:
        raise ValueError('Unsupported provider tool')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            raise ValueError('Redirect disabled')
    request=urllib.request.Request('https://api.deepseek.com/v1/tools/'+kind,
        data=json.dumps(body).encode(),headers={'Content-Type':'application/json',
          'Authorization':'Bearer '+(key or os.environ.get('ARTICHECK_API_KEY',''))})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=12) as response:
            raw=response.read(1_000_001)
        if len(raw)>1_000_000:raise ValueError('Source response too large')
        return json.loads(raw)
    except Exception as exc:
        raise ReviewError('external_lookup_failed','公开资料检索暂不可用；本次保留论文与代码内部核对。',502) from exc


def lookup(context,budget,store):
    identifier=public_identifier(context)
    if not identifier:
        context['source_lookup']={'status':'not_requested','reason':'未识别到论文自身的公开 arXiv / DOI 标识，仅核对已提供材料。'}
        context['web_sources']=[]
        return
    cache_key='articheck:public-sources:v2:'+hashlib.sha256(identifier.encode()).hexdigest()
    try:
        cached=store.command('GET',cache_key)
    except (ReviewError,AttributeError):
        cached=None
    if cached:
        sources=json.loads(cached)
        context['web_sources']=prepare_sources(context,sources,identifier)
        context['source_lookup']={'status':'completed','identifier':identifier,'cached':True}
        return
    budget.reserve()  # Search is separately billable and shares the same cap.
    try:
        result=provider_tool('search',{'query':'"'+identifier.removeprefix('arXiv:')+'" official paper implementation github','count':8,'need_content':True})
    except ReviewError as exc:
        context['web_sources']=[]
        context['source_lookup']={'status':'failed','identifier':identifier,'reason':str(exc)}
        return
    sources=[]
    for item in (result.get('results') or [])[:8]:
        if not isinstance(item,dict):continue
        u=urlparse(str(item.get('url','')))
        if u.scheme not in {'http','https'} or not u.hostname or u.username or u.password:continue
        sources.append({'url':u.geturl(),'title':str(item.get('title',''))[:300],
                        'summary':str(item.get('summary') or item.get('snippet') or '')[:1000],
                        'content':str(item.get('content') or '')[:4000]})
    context['web_sources']=prepare_sources(context,sources,identifier)
    context['source_lookup']={'status':'completed' if sources else 'no_results','identifier':identifier,'cached':False}
    try:
        store.command('SET',cache_key,json.dumps(sources,ensure_ascii=False),'EX','3600')
    except (ReviewError,AttributeError):
        pass
