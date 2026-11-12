"""Account-scoped PDF storage for paper nodes and Markdown index export."""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import re
import unicodedata

from .review_api import ReviewError

BLOCK = 600_000


def filename(paper):
    first = next(iter(paper.get('author_names') or []), '作者未知')
    value = f"{paper.get('year') or '年份未知'}_{first}_{paper['title']}"
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', unicodedata.normalize('NFKC', value))
    return clean.encode('utf-8')[:220].decode('utf-8','ignore').strip(' .') + '.pdf'


class PaperPDFs:
    def __init__(self, store):
        self.store = store
        self.memory = {}

    def key(self, owner, sha):
        return f'articheck:kg:pdf:{self.store.namespace}:{owner}:{sha}'

    def save(self, owner, raw, paper, source=''):
        sha = hashlib.sha256(raw).hexdigest()
        key = self.key(owner, sha)
        if getattr(self.store,'url','') and getattr(self.store,'token',''):
            payload = base64.b64encode(raw).decode()
            if self.store.command('GET', key+':ready') != str(len(payload)):
                offsets = range(0, len(payload), BLOCK)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda offset: self.store.command('SETRANGE', key, offset, payload[offset:offset+BLOCK]), offsets))
                self.store.command('SET', key+':ready', len(payload))
        else:
            self.memory[key] = raw
        return {'sha256':sha,'bytes':len(raw),'filename':filename(paper),'source':source}

    def read(self, owner, record, *, offset=0, size=None):
        key = self.key(owner, record['sha256'])
        end = record['bytes'] if size is None else min(record['bytes'],offset+size)
        if offset<0 or offset>=end:
            raise ReviewError('paper_range_invalid','请求的 PDF 位置无效。',416)
        if getattr(self.store,'url','') and getattr(self.store,'token',''):
            length = int(self.store.command('GET', key+':ready') or 0)
            expected = ((record['bytes']+2)//3)*4
            if length != expected:
                raise ReviewError('paper_file_missing','PDF 存储暂不可用，可重新插入论文。',404)
            start64, end64 = offset//3*4, ((end+2)//3)*4
            with ThreadPoolExecutor(max_workers=4) as pool:
                parts = pool.map(lambda start: self.store.command('GETRANGE',key,start,min(end64,start+BLOCK)-1),
                                 range(start64,end64,BLOCK))
                try:
                    decoded=base64.b64decode(''.join(parts),validate=True)
                    raw=decoded[offset%3:offset%3+end-offset]
                except (ValueError, TypeError) as exc:
                    raise ReviewError('paper_file_missing','PDF 存储暂不可用，可重新插入论文。',404) from exc
        else:
            raw = self.memory.get(key,b'')[offset:end]
        if len(raw)!=end-offset or offset==0 and end==record['bytes'] and hashlib.sha256(raw).hexdigest()!=record['sha256']:
            raise ReviewError('paper_file_missing','PDF 存储暂不可用，可重新插入论文。',404)
        return raw


def markdown_index(papers):
    def cell(value):
        return str(value or '—').replace('\\','\\\\').replace('|','\\|').replace('\n',' ').replace('\r',' ').replace('<','&lt;').replace('>','&gt;')
    lines = ['# 论文下载索引','','| 标题 | 作者 | 年份 | 来源链接 | 下载状态 | 文件 |','| --- | --- | --- | --- | --- | --- |']
    for paper, status, file in papers:
        fields = (paper.get('title'), '、'.join(paper.get('author_names') or []), paper.get('year'),
                  (file or {}).get('source') or paper.get('source_url'), status, (file or {}).get('filename'))
        lines.append('| '+' | '.join(cell(value) for value in fields)+' |')
    return '\n'.join(lines)+'\n'
