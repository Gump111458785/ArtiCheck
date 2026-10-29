"""Explicit public HTTPS retrieval with pinned addresses, checksums and bounded writes.

No credentials, archive execution, automatic restricted-data acquisition, or ambient proxies.
"""
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,urljoin
from .protocol import fingerprint,relative_path,load_plan
from ..schema import dump


def public_endpoint(url):
    if not isinstance(url,str) or len(url)>2048:raise ValueError('Invalid public data URL')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Only public HTTPS port 443 without credentials or fragments is supported')
    host=parsed.hostname.encode('idna').decode('ascii')
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Dataset URL resolves to a private, reserved or local address')
    return parsed,host,addresses[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):
        super().__init__(host,timeout=timeout,context=ssl.create_default_context());self.address=address
    def connect(self):
        family,kind,proto,_,address=self.address
        raw=socket.socket(family,kind,proto);raw.settimeout(self.timeout)
        try:
            raw.connect(address);self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:
            raw.close();raise


def fetch_public(destination,url,sha256,max_bytes,*,timeout_seconds=120):
    destination=Path(destination)
    if not isinstance(sha256,str) or not re.fullmatch('[0-9a-f]{64}',sha256):raise ValueError('A reference SHA256 is required before downloading')
    if type(max_bytes) is not int or not 1<=max_bytes<=512*1024**2:raise ValueError('Download budget must be 1 byte to 512 MiB')
    started=time.monotonic()
    if destination.exists():
        if destination.is_symlink() or fingerprint(destination,limit=max_bytes)['sha256']!=sha256:raise ValueError('Existing data contradicts reference; files are never overwritten')
        return {'status':'verified_cache','sha256':sha256,'bytes':destination.stat().st_size,'elapsed_seconds':time.monotonic()-started}
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.parent.is_symlink():raise ValueError('Download destination must not be symbolic')
    import shutil,uuid
    if shutil.disk_usage(destination.parent).free<max_bytes+32*1024**2:raise ValueError('Insufficient free disk for declared download budget')
    temporary=destination.with_name('.download-'+uuid.uuid4().hex)
    current=url;redirects=0;connection=None;total=0;digest=hashlib.sha256()
    try:
        while True:
            remaining=timeout_seconds-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError('Dataset acquisition exceeded total time budget')
            parsed,host,address=public_endpoint(current)
            connection=PinnedHTTPS(host,address,min(20,remaining))
            connection.request('GET',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),headers={'User-Agent':'ArtiCheck/0.1 public-data-fetch','Accept-Encoding':'identity'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                redirects+=1
                if redirects>3 or not response.getheader('Location'):raise ValueError('Dataset redirect limit exceeded')
                current=urljoin(current,response.getheader('Location'));connection.close();continue
            if response.status!=200:raise ValueError('Dataset server returned HTTP '+str(response.status))
            if response.getheader('Content-Encoding') not in (None,'identity'):raise ValueError('Encoded HTTP transfer is not supported; reference bytes must be explicit')
            length=response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length)>max_bytes):raise ValueError('Declared dataset download exceeds size budget')
            with temporary.open('xb') as out:
                while True:
                    remaining=timeout_seconds-(time.monotonic()-started)
                    if remaining<=0:raise TimeoutError('Dataset acquisition exceeded total time budget')
                    if connection.sock is not None:connection.sock.settimeout(min(20,remaining))
                    chunk=response.read(min(1024*1024,max_bytes-total+1))
                    if not chunk:break
                    total+=len(chunk)
                    if total>max_bytes:raise ValueError('Downloaded dataset exceeds size budget')
                    digest.update(chunk);out.write(chunk)
            break
        if digest.hexdigest()!=sha256:raise ValueError('Downloaded data SHA256 differs from frozen reference')
        # Atomic no-clobber publication; a concurrent acquisition cannot replace prior bytes.
        os.link(temporary,destination);temporary.unlink()
        return {'status':'downloaded_verified','sha256':sha256,'bytes':total,'elapsed_seconds':time.monotonic()-started,
                'transport':'HTTPS with pinned public address and verified TLS; no credentials or proxies','redirects':redirects}
    finally:
        if connection is not None:connection.close()
        if temporary.exists():temporary.unlink()


def acquire_plan_data(plan_path,output):
    plan,repo,plan_sha=load_plan(plan_path,with_digest=True)
    receipt={'format':'articheck-data-acquisition-v1','plan_sha256':plan_sha,'created_at':datetime.now(timezone.utc).isoformat(),'files':[],'status':'completed'}
    try:
        for dataset in plan['datasets']:
            source=dataset.get('source',{})
            jobs=dataset.get('acquisition',[])
            if jobs and (source.get('access','public')!='public'):
                raise ValueError('Restricted data must be obtained through its documented application process; automatic acquisition disabled')
            references={x['path']:x.get('sha256') for x in dataset.get('files',[])}
            for item in jobs:
                if references.get(item['path'])!=item['sha256']:raise ValueError('Acquisition must match a frozen dataset file reference')
                destination=relative_path(repo,item['path'],exists=False)
                proof=fetch_public(destination,item['url'],item['sha256'],item['max_bytes'])
                receipt['files'].append({'dataset':dataset['id'],'path':item['path'],**proof})
    except Exception as error:
        receipt.update(status='failed',error=type(error).__name__+': '+str(error));dump(output,receipt);raise
    dump(output,receipt);return receipt
