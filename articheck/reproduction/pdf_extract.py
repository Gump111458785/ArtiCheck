"""Bounded PDF parsing in a fresh trusted process, never artifact Python."""
import json
import logging
import re
import resource
import sys
from pathlib import Path


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    logging.getLogger('pypdf').setLevel(logging.CRITICAL)
    from pypdf import PdfReader
    reader=PdfReader(sys.argv[1],strict=False)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 150:
        raise ValueError('PDF must be unencrypted and contain 1–150 pages')
    pages=[];total=0
    layout = '--layout' in sys.argv
    method_context = '--method-context' in sys.argv
    method_pages, method_chars = [], 0
    for number,page in enumerate(reader.pages,1):
        has_contents = '/Contents' in page
        ordinary = (page.extract_text() or '') if has_contents and (not layout or number == 1 or method_context) else ''
        text = (page.extract_text(extraction_mode='layout') or ordinary) if has_contents and layout else ordinary
        if len(text)>60000:raise ValueError('Page text exceeds limit; no partial inventory is certified')
        total+=len(text)
        if total>1_500_000:raise ValueError('Extracted PDF text exceeds limit')
        item={'number':number,'text':text}
        if method_context and ordinary and method_chars < 400_000:
            method_text = ordinary[:min(60_000, 400_000 - method_chars)]
            method_pages.append({'number': number, 'text': method_text})
            method_chars += len(method_text)
        if number == 1 and '--bibliography' in sys.argv:
            metadata = reader.metadata
            title = metadata.title if metadata else None
            if isinstance(title, str):
                item['document_title'] = title[:350]
        if layout:
            if number == 1:
                # Layout extraction drops rotated arXiv margin identifiers.
                # Read only the first page header in ordinary extraction mode.
                header=ordinary[:2500]
                item['public_ids']=re.findall(r'arxiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?',header,re.I)
            links=[]
            for annotation in list(page.get('/Annots', []))[:100]:
                try:
                    uri=annotation.get_object().get('/A', {}).get('/URI')
                    if isinstance(uri,str) and uri.startswith(('http://','https://')) and len(uri)<=2000:
                        links.append(uri)
                except (AttributeError,ValueError,TypeError):
                    continue
            item['links']=links
        pages.append(item)
    raw=(json.dumps(pages,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if len(raw)>2_000_000:raise ValueError('Extracted PDF text exceeds 2 MB')
    Path(sys.argv[2]).write_bytes(raw)
    if method_context:
        Path(sys.argv[2]).with_suffix('.methods.json').write_text(json.dumps(method_pages, ensure_ascii=False), encoding='utf-8')

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__+': '+str(error)[:1000],file=sys.stderr)
        raise SystemExit(2)
