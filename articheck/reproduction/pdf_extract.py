"""Bounded PDF parsing in a fresh trusted process, never artifact Python."""
import json
import logging
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
    for number,page in enumerate(reader.pages,1):
        text=page.extract_text() or ''
        if len(text)>60000:raise ValueError('Page text exceeds limit; no partial inventory is certified')
        total+=len(text)
        if total>1_500_000:raise ValueError('Extracted PDF text exceeds limit')
        pages.append({'number':number,'text':text})
    raw=(json.dumps(pages,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if len(raw)>2_000_000:raise ValueError('Extracted PDF text exceeds 2 MB')
    Path(sys.argv[2]).write_bytes(raw)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__+': '+str(error)[:1000],file=sys.stderr)
        raise SystemExit(2)
