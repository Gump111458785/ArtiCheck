"""Fixed-host public repository import. No user URLs are fetched directly."""
import base64
import json
import re
import time
import urllib.error
import urllib.request
from functools import lru_cache

from .review_api import ReviewError, decode_material, prepare_context, MAX_CODE_BYTES

MAX_ZIP = MAX_CODE_BYTES
INLINE_ZIP = 2_500_000


def repository(value):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?(?:\?[^#]*)?', value or '')
    if not match or any(s in {'.', '..'} for s in match.groups()):
        raise ReviewError('invalid_repository', '请填写公开 GitHub 仓库首页地址，例如 https://github.com/作者/仓库。')
    return '/'.join(match.groups())


def read(url, limit, headers=None):
    # Hosts are constructed internally; redirects may only remain at GitHub's
    # archive hosts, and credentials are only ever attached to api.github.com.
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            from urllib.parse import urlparse
            if urlparse(newurl).hostname not in {'api.github.com', 'codeload.github.com'}:
                raise ReviewError('repository_redirect', 'GitHub 返回了不支持的下载地址。', 502)
            redirected = super().redirect_request(req, fp, code, msg, hdrs, newurl)
            redirected.remove_header('Authorization')
            return redirected
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ArtiCheck', **(headers or {})})
        with urllib.request.build_opener(SafeRedirect()).open(req, timeout=60 if limit==MAX_ZIP else 25) as response:
            if int(response.headers.get('Content-Length','0'))>limit:
                raise ReviewError('repository_size','仓库源码包超过 100 MB，请缩小范围或导入实验代码 ZIP。',413)
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ReviewError('repository_size', '仓库源码包超过 100 MB，请缩小范围或导入实验代码 ZIP；不会因此判定无法复现。', 413)
        return raw
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            delay = exc.headers.get('Retry-After')
            if not delay:
                try:
                    delay = str(max(1, int(exc.headers.get('X-RateLimit-Reset', '0')) - int(time.time())))
                except ValueError:
                    delay = None
            raise ReviewError('github_rate_limited', 'GitHub 暂时限制请求。' + (f'约 {delay} 秒后可重试。' if delay else '请稍后重试。') + '也可上传代码 ZIP；这不代表代码无法复现。', 429) from exc
        if exc.code == 404:
            raise ReviewError('repository_not_found', '仓库不存在或未公开，请检查地址或导入 ZIP。', 404) from exc
        raise ReviewError('github_unavailable', 'GitHub 暂时无法访问，请重试或上传 ZIP。', 502) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise ReviewError('github_unavailable', 'GitHub 连接超时，请重试或上传 ZIP。', 502) from exc


@lru_cache(maxsize=8)
def import_repository(name, cache_period, github_token='', cached_commit=None):
    headers = {'Accept': 'application/vnd.github+json'}
    if github_token:
        headers['Authorization'] = 'Bearer ' + github_token
    if cached_commit and re.fullmatch(r'[a-f0-9]{40}',cached_commit):
        commit=cached_commit
    else:
        meta = json.loads(read('https://api.github.com/repos/' + name + '/commits?per_page=1', 100_000, headers))
        if not isinstance(meta, list) or not meta or not re.fullmatch(r'[a-f0-9]{40}', meta[0].get('sha', '')):
            raise ReviewError('repository_empty', '仓库没有可读取的提交。', 422)
        commit = meta[0]['sha']
    raw = read('https://codeload.github.com/' + name + '/zip/' + commit, MAX_ZIP)
    filename=name.split('/')[-1]+'.zip'
    context, _ = prepare_context({'code': {'name':filename,'_raw_bytes':raw}}, partial=True)
    material=({'name':filename,'content_base64':base64.b64encode(raw).decode()} if len(raw)<=INLINE_ZIP else
              {'name':filename,'repository':name,'commit':commit,'sha256':context['code']['sha256'],'bytes':len(raw)})
    return {'name': name, 'url': 'https://github.com/' + name, 'commit': commit,
            'sha256': context['code']['sha256'], 'files': [{'path': path} for path in context['files']],
            'material': material}


def resolve_repository(material):
    """Resolve an immutable public reference without a large client JSON body."""
    name=repository('https://github.com/'+str(material.get('repository','')))
    commit=material.get('commit','');sha=material.get('sha256','')
    if not isinstance(commit,str) or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{40}',commit) or not re.fullmatch(r'[a-f0-9]{64}',sha):
        raise ReviewError('invalid_repository_ref','代码版本引用无效，请重新读取仓库。')
    raw=read('https://codeload.github.com/'+name+'/zip/'+commit,MAX_ZIP)
    import hashlib
    if hashlib.sha256(raw).hexdigest()!=sha:
        raise ReviewError('material_changed','仓库源码指纹不符，请重新读取仓库。',409)
    return {'name':name.split('/')[-1]+'.zip','_raw_bytes':raw}
