"""Independently bind cited text to paper bytes, including CLI plans."""
import importlib.metadata
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from .protocol import fingerprint,load_json


def extract_paper(path, *, layout=False):
    path=Path(path)
    with path.open('rb') as stream:signature=stream.read(5)
    if signature==b'%PDF-' or path.suffix.lower()=='.pdf':
        if path.stat().st_size>20*1024**2:raise ValueError('Paper PDF exceeds 20 MiB')
        worker=Path(__file__).with_name('pdf_extract.py');before=fingerprint(path)['sha256']
        with tempfile.TemporaryDirectory(prefix='articheck-paper-') as tmp:
            output=Path(tmp)/'pages.json'
            try:
                # Serverless vendors install dependencies beside the function and
                # expose them through PYTHONPATH. Forward only the trusted parser
                # package directory; never forward model keys or the full environment.
                parser_spec=importlib.util.find_spec('pypdf')
                worker_env={'PATH':os.defpath,'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
                if parser_spec and parser_spec.origin:
                    worker_env['PYTHONPATH']=str(Path(parser_spec.origin).resolve().parent.parent)
                result=subprocess.run([sys.executable,str(worker),str(path),str(output)]+(['--layout'] if layout else []),env=worker_env,capture_output=True,timeout=20)
            except subprocess.TimeoutExpired as error:raise ValueError('Independent PDF extraction timed out') from error
            if result.returncode:raise ValueError('Independent PDF extraction failed: '+result.stderr.decode(errors='replace')[:300])
            pages=load_json(output)
        if fingerprint(path)['sha256']!=before:raise ValueError('Paper changed during independent extraction')
        return pages,{'engine':'pypdf','version':importlib.metadata.version('pypdf'),'source_pdf_sha256':before,'worker_sha256':fingerprint(worker)['sha256']}
    if path.suffix.lower() in ('.txt','.md'):
        if path.stat().st_size>2_000_000:raise ValueError('Plain-text paper exceeds 2 MB')
        return [{'number':1,'text':path.read_text()}],{'engine':'literal_plain_text','scope':'Text document, not a PDF layout verification'}
    return None,{'engine':'unsupported','scope':'Paper text origin not independently verified'}
