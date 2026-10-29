"""Workspace-local immutable uploads; binary content is never a host executable."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import unicodedata
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from ..schema import dump
from .protocol import fingerprint, load_json, relative_path, validate_plan

LIMITS={'paper':20*1024**2,'archive':50*1024**2,'plan':2_000_000}
NAMES={'paper':'paper.pdf','archive':'repository.zip','plan':'source-plan.json'}


class MaterialStore:
    def __init__(self,workspace):
        self.workspace=Path(workspace).resolve();self.lock=threading.RLock()
    @property
    def workspace(self):return self._workspace
    @workspace.setter
    def workspace(self,value):self._workspace=Path(value).resolve()
    @property
    def root(self):
        root=self.workspace/'.articheck-inputs'
        if root.is_symlink():raise ValueError('Material root must not be a symlink')
        return root
    def directory(self,bundle_id):
        if not isinstance(bundle_id,str) or not re.fullmatch('[0-9a-f]{32}',bundle_id):raise ValueError('Invalid material bundle ID')
        return relative_path(self.root,bundle_id)
    def get(self,bundle_id):
        with self.lock:return self._get(bundle_id)
    def _get(self,bundle_id):
        root=self.directory(bundle_id);meta=load_json(root/'materials.json',max_bytes=8_000_000)
        return {**meta,'workspace_path':root.relative_to(self.workspace).as_posix()}
    def create(self,body):
        project=body.get('project_id')
        if not isinstance(project,str) or not 1<=len(project)<=200:raise ValueError('project_id is required')
        expected={}
        for kind,key in [('paper','paper_sha256'),('archive','archive_sha256')]:
            digest=body.get(key)
            if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError(key+' must be SHA256')
            expected[kind]=digest
        bundle_id=uuid.uuid4().hex;root=self.root/bundle_id;root.mkdir(parents=True,mode=0o700);self.root.chmod(0o700)
        dump(root/'materials.json',{'id':bundle_id,'project_id':project,'expected':expected,'files':{},'status':'collecting'})
        return self.get(bundle_id)
    def upload(self,bundle_id,kind,stream,length):
        with self.lock:return self._upload(bundle_id,kind,stream,length)
    def _upload(self,bundle_id,kind,stream,length):
        if kind not in LIMITS or not 1<=length<=LIMITS[kind]:raise ValueError('Unsupported upload or file exceeds limit')
        root=self.directory(bundle_id);meta=load_json(root/'materials.json',max_bytes=8_000_000)
        if kind in meta['files'] or meta['status']=='bound':raise ValueError('Uploads are immutable; create a new material bundle')
        part=root/('.upload-'+uuid.uuid4().hex);target=root/NAMES[kind]
        try:
            remaining=length;sha=hashlib.sha256()
            with part.open('xb') as out:
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:raise ValueError('Upload ended before declared length')
                    remaining-=len(chunk);sha.update(chunk);out.write(chunk)
            actual=sha.hexdigest()
            if meta['expected'].get(kind) and actual!=meta['expected'][kind]:raise ValueError('Upload differs from the project material fingerprint')
            if kind=='paper':
                with part.open('rb') as source:
                    if source.read(5)!=b'%PDF-':raise ValueError('Paper content is not PDF')
                parser=Path(__file__).with_name('pdf_extract.py')
                try:
                    result=subprocess.run([sys.executable,str(parser),str(part),str(root/'paper-pages.json')],
                            env={'PATH':os.defpath,'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,timeout=20)
                except subprocess.TimeoutExpired as error:
                    raise ValueError('PDF text extraction exceeded 20 seconds') from error
                if result.returncode:raise ValueError('PDF extraction failed; use an unencrypted, text-readable PDF within the documented limits')
            elif kind=='archive':
                try:manifest=self.extract_zip(part,root/'artifact')
                except (zipfile.BadZipFile,RuntimeError,NotImplementedError,zlib.error) as error:
                    raise ValueError('Invalid or unsupported ZIP content') from error
                meta['archive_files']=manifest
                parents={PurePosixPath(f['path']).parts[0] for f in manifest}
                common=next(iter(parents)) if len(parents)==1 and all(len(PurePosixPath(f['path']).parts)>1 for f in manifest) else '.'
                meta['suggested_root']=common
            else:
                validate_plan(load_json(part))
            part.replace(target)
            meta['files'][kind]={'sha256':actual,'bytes':length,'name':NAMES[kind]}
            if kind=='paper':
                meta['files'][kind]['pages_sha256']=fingerprint(root/'paper-pages.json')['sha256']
                meta['files'][kind]['extraction']={'engine':'pypdf','version':importlib.metadata.version('pypdf'),'source_pdf_sha256':actual,'worker_sha256':fingerprint(parser)['sha256']}
            dump(root/'materials.json',meta)
        finally:
            if part.exists():part.unlink()
        return self.get(bundle_id)
    @staticmethod
    def extract_zip(path,destination):
        if destination.exists():raise ValueError('Extraction destination already exists')
        temporary=destination.with_name('.extract-'+uuid.uuid4().hex);temporary.mkdir()
        manifest=[];names=set();prefixes={}
        try:
            with zipfile.ZipFile(path) as archive:
                entries=archive.infolist()
                total=sum(i.file_size for i in entries)
                if not entries or len(entries)>5000 or total>500*1024**2 or total>shutil.disk_usage(temporary).free-32*1024**2:
                    raise ValueError('Archive exceeds file count, expanded size or free disk budget')
                total_path_characters=0
                for item in entries:
                    name=item.orig_filename
                    total_path_characters+=len(name)
                    if len(name)>512 or total_path_characters>1_000_000:raise ValueError('Archive path metadata exceeds limit')
                    pure=PurePosixPath(name)
                    if not name or '\\' in name or '\0' in name or pure.is_absolute() or '..' in pure.parts or re.match(r'^[A-Za-z]:',name) or '.git' in pure.parts:
                        raise ValueError('Unsafe archive path')
                    mode=(item.external_attr>>16)&0o170000
                    if item.flag_bits&1 or mode not in (0,stat.S_IFREG,stat.S_IFDIR) or item.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
                        raise ValueError('Encrypted, linked, special or unsupported archive entry')
                    normalized=unicodedata.normalize('NFC',pure.as_posix()).casefold()
                    if normalized in names:raise ValueError('Duplicate or case-colliding archive path')
                    names.add(normalized)
                    for index in range(1,len(pure.parts)+1):
                        prefix='/'.join(pure.parts[:index]);key=unicodedata.normalize('NFC',prefix).casefold()
                        if key in prefixes and prefixes[key]!=prefix:raise ValueError('Ambiguous archive directory casing')
                        prefixes[key]=prefix
                    target=relative_path(temporary,pure.as_posix(),exists=False)
                    if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                    if item.file_size>128*1024**2:raise ValueError('Archive member exceeds 128 MiB')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    written=0
                    with archive.open(item) as source,target.open('xb') as out:
                        while chunk:=source.read(1024*1024):
                            written+=len(chunk)
                            if written>item.file_size:raise ValueError('Archive expanded beyond declared member size')
                            out.write(chunk)
                    target.chmod(0o755 if (item.external_attr>>16)&0o111 else 0o644)
                    manifest.append({'path':pure.as_posix(),**fingerprint(target)})
            if not manifest:raise ValueError('Archive has no regular files')
            temporary.replace(destination)
            return manifest
        except Exception:
            shutil.rmtree(temporary,ignore_errors=True)
            raise
    def bind(self,bundle_id,body):
        with self.lock:return self._bind(bundle_id,body)
    def _bind(self,bundle_id,body):
        root=self.directory(bundle_id);meta=load_json(root/'materials.json',max_bytes=8_000_000)
        if meta['status']=='bound':return self.get(bundle_id)
        if not all(k in meta['files'] for k in ('paper','archive','plan')):raise ValueError('Upload PDF, source ZIP and experiment plan before binding')
        selected=body.get('code_root',meta.get('suggested_root','.'))
        code_root=relative_path(root/'artifact',selected)
        if not code_root.is_dir():raise ValueError('Selected code root must be a directory')
        reference=[]
        for item in meta['archive_files']:
            path=relative_path(root/'artifact',item['path'])
            if path.is_relative_to(code_root):reference.append({**item,'archive_path':item['path'],'path':path.relative_to(code_root).as_posix()})
        if not reference:raise ValueError('No source files in selected code root')
        # Recheck the uploaded bytes, rather than trusting a stale receipt.
        for kind,item in meta['files'].items():
            if fingerprint(root/item['name'])['sha256']!=item['sha256']:raise ValueError('Stored upload changed: '+kind)
        if fingerprint(root/'paper-pages.json')['sha256']!=meta['files']['paper']['pages_sha256']:
            raise ValueError('Extracted PDF text changed; import the PDF again')
        plan=validate_plan(load_json(root/'source-plan.json'))
        actual_paper=meta['files']['paper']['sha256']
        if plan['paper'].get('sha256') and plan['paper']['sha256']!=actual_paper:raise ValueError('Plan refers to a different paper PDF')
        original={'repository_path':plan['repository'].get('path'),'paper_path':plan['paper'].get('path')}
        plan['repository']['path']=code_root.relative_to(root).as_posix()
        plan['paper'].update(path='paper.pdf',sha256=actual_paper,pages_path='paper-pages.json',pages_sha256=fingerprint(root/'paper-pages.json')['sha256'])
        plan['paper'].pop('pages',None)
        dump(root/'bound-plan.json',plan)
        meta.update(status='bound',code_root=selected,imported_snapshot={'kind':'zip','archive_sha256':meta['files']['archive']['sha256'],'files':reference},
                    binding={'original':original,'source_plan_sha256':meta['files']['plan']['sha256'],'bound_plan_sha256':fingerprint(root/'bound-plan.json')['sha256']},
                    plan_path=(root/'bound-plan.json').relative_to(self.workspace).as_posix())
        dump(root/'materials.json',meta)
        return self.get(bundle_id)
