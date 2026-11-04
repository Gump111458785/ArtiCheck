"""Render actual PDF pages for multimodal review; images never enter Redis."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def render_paper(pdf, pages):
    # Include the title and every page for typical short papers. On longer
    # documents, prioritize chart/table pages and state any omitted images.
    ordered=[1]+[p['page'] for p in pages if re.search(r'(table|figure|fig\.|表|图)\s*\d',p['text'],re.I)]
    ordered+= [p['page'] for p in pages]
    selected=list(dict.fromkeys(ordered))[:24]
    with tempfile.TemporaryDirectory(prefix='articheck-vision-') as folder:
        folder=Path(folder);source=folder/'paper.pdf';source.write_bytes(pdf)
        env={'PATH':os.defpath,'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
        roots=[]
        for name in ('pypdfium2','PIL'):
            spec=importlib.util.find_spec(name)
            if spec and spec.origin:
                roots.append(str(Path(spec.origin).resolve().parent.parent))
        env['PYTHONPATH']=os.pathsep.join(dict.fromkeys(roots))
        worker=Path(__file__).with_name('reproduction')/'pdf_render.py'
        result=subprocess.run([sys.executable,str(worker),str(source),str(folder),json.dumps(selected)],
                              env=env,capture_output=True,timeout=18)
        if result.returncode:
            raise ValueError('PDF page rendering failed')
        images=[]
        for item in json.loads((folder/'images.json').read_text()):
            raw=(folder/item.pop('file')).read_bytes()
            images.append({**item,'sha256':hashlib.sha256(raw).hexdigest(),
                           'image_url':'data:image/jpeg;base64,'+base64.b64encode(raw).decode()})
        return images


def text_materials(context):
    return {**context,'files':context['files'][:500],
            'paper_images':[{k:v for k,v in image.items() if k!='image_url'} for image in context.get('paper_images',[])]}
