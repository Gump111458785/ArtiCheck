import hashlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from articheck.reproduction.acquisition import public_endpoint,fetch_public,acquire_plan_data
from test_reproduction import fixture,write

PUBLIC=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]

class AcquisitionTests(unittest.TestCase):
    def test_private_addresses_credentials_and_non_https_rejected(self):
        for url in ['http://example.org/data','https://u:p@example.org/data','https://example.org:444/data','https://example.org/a#fragment']:
            with self.assertRaises(ValueError):public_endpoint(url)
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1']:
            with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
                with self.assertRaises(ValueError):public_endpoint('https://example.org/data')
    def test_public_socket_address_is_frozen_for_the_tls_connection(self):
        with patch('socket.getaddrinfo',return_value=PUBLIC):
            parsed,host,address=public_endpoint('https://example.org/data')
        self.assertEqual(host,'example.org');self.assertEqual(address[4][0],'8.8.8.8')
    def test_bounded_download_hash_cache_and_no_overwrite(self):
        raw=b'known public bytes';sha=hashlib.sha256(raw).hexdigest()
        class Response(io.BytesIO):
            status=200
            def getheader(self,key):return str(len(raw)) if key=='Content-Length' else None
        class Connection:
            sock=None
            def __init__(self,*args):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):return Response(raw)
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp,patch('socket.getaddrinfo',return_value=PUBLIC),patch('articheck.reproduction.acquisition.PinnedHTTPS',Connection):
            dest=Path(tmp)/'data.bin'
            result=fetch_public(dest,'https://example.org/data',sha,100)
            self.assertEqual(result['status'],'downloaded_verified');self.assertEqual(dest.read_bytes(),raw)
            self.assertEqual(fetch_public(dest,'https://example.org/data',sha,100)['status'],'verified_cache')
            with self.assertRaises(ValueError):fetch_public(dest,'https://example.org/data','0'*64,100)
            self.assertEqual(dest.read_bytes(),raw)
            for limit,expected in [(2,sha),(100,'0'*64)]:
                target=Path(tmp)/('bad-'+str(limit))
                with self.assertRaises(ValueError):fetch_public(target,'https://example.org/data',expected,limit)
                self.assertFalse(target.exists())
            self.assertFalse(list(Path(tmp).glob('.download-*')))
    def test_restricted_data_and_reference_disagreement_have_failed_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,plan,repo=fixture(root)
            plan['datasets'][0]['acquisition']=[{'path':'data.json','sha256':'0'*64,'url':'https://example.org/data','max_bytes':100}]
            write(path,plan)
            with self.assertRaises(ValueError):acquire_plan_data(path,root/'receipt.json')
            self.assertEqual(json.loads((root/'receipt.json').read_text())['status'],'failed')
            plan['datasets'][0]['source']['access']='restricted';write(path,plan)
            with patch('articheck.reproduction.acquisition.fetch_public') as download:
                with self.assertRaises(ValueError):acquire_plan_data(path,root/'restricted.json')
                download.assert_not_called()
