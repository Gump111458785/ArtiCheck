import base64
import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch,MagicMock

from articheck.hosted_uploads import HostedUploads
from articheck.hosted_github import import_repository,resolve_repository,read,MAX_ZIP
from articheck.hosted_review import prepare_assessment
from articheck.review_api import ReviewError,MAX_CODE_BYTES
from test_hosted_review import MemoryStore,OWNER


class LargeMaterialTests(unittest.TestCase):
    def test_large_repository_returns_reference_and_resolves_identical_bytes(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('repo/README.md','Run python main.py')
            archive.writestr('repo/main.py','print(1)')
            archive.writestr('repo/asset.bin',b'\0'*3_000_000)
        raw=buffer.getvalue();commit='a'*40
        import_repository.cache_clear()
        try:
            with patch('articheck.hosted_github.read',side_effect=[json.dumps([{'sha':commit}]).encode(),raw]):
                value=import_repository('example/large-material',0)
            self.assertNotIn('content_base64',value['material'])
            self.assertLess(len(json.dumps(value)),2000)
            with patch('articheck.hosted_github.read',return_value=raw):
                material=resolve_repository(value['material'])
            context,_=prepare_assessment({'code':material},images=False)
            self.assertEqual(context['code']['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(len(context['files']),3)
            self.assertIn('print(1)',str(context['code_excerpts']))
            with patch('articheck.hosted_github.read',return_value=raw+b'changed'):
                with self.assertRaises(ReviewError) as caught:resolve_repository(value['material'])
            self.assertEqual(caught.exception.code,'material_changed')
        finally:import_repository.cache_clear()

    def test_repository_over_100_mb_is_rejected_before_reading_body(self):
        response=MagicMock();response.headers={'Content-Length':str(MAX_CODE_BYTES+1)}
        response.__enter__.return_value=response
        opener=MagicMock();opener.open.return_value=response
        with patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaises(ReviewError) as caught:read('https://codeload.github.com/example/repo/zip/'+'a'*40,MAX_ZIP)
        self.assertEqual(caught.exception.code,'repository_size')
        response.read.assert_not_called()

    def test_invalid_upload_does_not_reserve_an_instance(self):
        store=MemoryStore();uploads=HostedUploads({'E2B_API_KEY':'test'},store)
        for kind,name,size in [('code','source.zip',MAX_CODE_BYTES+1),('paper','paper.pdf',20*1024**2+1),('code','bad.exe',100)]:
            with self.assertRaises(ReviewError):uploads.create(OWNER,{'request_id':'1'*32,'files':[{'kind':kind,'name':name,'bytes':size,'sha256':'a'*64}]})
        self.assertEqual(store.reservations,0)
        item={'kind':'code','name':'source.zip','bytes':100,'sha256':'a'*64}
        store.save(OWNER,{'id':'1'*32,'type':'material_upload','status':'starting','deadline':9999999999,
                          'files':{'code':{k:item[k] for k in ('name','bytes','sha256')}}})
        with self.assertRaises(ReviewError) as caught:uploads.create(OWNER,{'request_id':'1'*32,'files':[item]})
        self.assertEqual(caught.exception.code,'upload_starting')
        self.assertEqual(store.reservations,0)
        with self.assertRaises(ReviewError):uploads.resolve(OWNER,{'upload_id':[]},'code')
        with self.assertRaises(ReviewError):resolve_repository({'repository':'example/project','commit':[],'sha256':'f'*64})

    def test_upload_bytes_are_owner_scoped_and_fingerprint_checked(self):
        raw=b'test-source';store=MemoryStore();uploads=HostedUploads({'E2B_API_KEY':'test'},store)
        record={'id':'2'*32,'type':'material_upload','status':'ready','deadline':9999999999,
                'files':{'code':{'name':'source.zip','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}}
        store.save(OWNER,record);ref={'name':'source.zip','upload_id':record['id'],'kind':'code'}
        sandbox=MagicMock();sandbox.download_url.return_value='https://sandbox.e2b.app/files'
        class Response(io.BytesIO):
            headers={}
        opener=MagicMock();opener.open.side_effect=lambda *a,**kw:Response(raw)
        with patch.object(uploads,'connect',return_value=sandbox),patch('urllib.request.build_opener',return_value=opener):
            self.assertEqual(uploads.resolve(OWNER,ref,'code')['_raw_bytes'],raw)
            with self.assertRaises(ReviewError):uploads.resolve('b'*64,ref,'code')
            record['files']['code']['sha256']='f'*64;store.save(OWNER,record)
            with self.assertRaises(ReviewError) as caught:uploads.resolve(OWNER,ref,'code')
            self.assertEqual(caught.exception.code,'material_changed')
