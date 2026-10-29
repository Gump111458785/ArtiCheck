from __future__ import annotations
import copy
import hashlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from articheck.reproduction.audit import audit_plan
from articheck.reproduction.materials import MaterialStore
from articheck.reproduction.protocol import validate_plan, fingerprint
from test_reproduction import fixture

ROOT=Path(__file__).resolve().parents[1]


def make_zip(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files:z.writestr(name,value)
    return stream.getvalue()


class MaterialImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path,self.plan,self.repo=fixture(self.root)
        self.pdf=(ROOT/'web/dist/samples/articheck-method-note.pdf').read_bytes()
        self.plan['paper']['sha256']=hashlib.sha256(self.pdf).hexdigest()
        self.zip=make_zip([('package/'+p.name,p.read_bytes()) for p in self.repo.iterdir()])
        self.store=MaterialStore(self.root)
        self.bundle=self.store.create({'project_id':'test-paper','paper_sha256':hashlib.sha256(self.pdf).hexdigest(),'archive_sha256':hashlib.sha256(self.zip).hexdigest()})
    def tearDown(self):self.tmp.cleanup()
    def upload(self,kind,raw):return self.store.upload(self.bundle['id'],kind,io.BytesIO(raw),len(raw))
    def ready(self):
        self.upload('paper',self.pdf);self.upload('archive',self.zip);self.upload('plan',json.dumps(self.plan).encode())
        return self.store.bind(self.bundle['id'],{'code_root':'package'})
    def test_actual_pdf_zip_plan_binding_keeps_original_and_bound_fingerprints(self):
        receipt=self.ready();self.assertEqual(receipt['status'],'bound')
        root=self.store.directory(receipt['id']);plan=json.loads((root/'bound-plan.json').read_text())
        self.assertEqual(plan['repository']['path'],'artifact/package')
        self.assertEqual(plan['paper']['sha256'],hashlib.sha256(self.pdf).hexdigest())
        self.assertEqual(receipt['imported_snapshot']['files'][0]['archive_path'].split('/')[0],'package')
        self.assertNotEqual(receipt['binding']['source_plan_sha256'],receipt['binding']['bound_plan_sha256'])
        self.assertEqual(receipt['files']['paper']['extraction']['engine'],'pypdf')
        self.assertEqual(fingerprint(root/'artifact/package/experiment.py')['sha256'],fingerprint(self.repo/'experiment.py')['sha256'])
        self.assertEqual(len(json.loads((root/'paper-pages.json').read_text())),2)
    def test_wrong_pdf_or_archive_bytes_are_rejected_without_receipt(self):
        with self.assertRaises(ValueError):self.upload('paper',self.pdf+b'changed')
        with self.assertRaises(ValueError):self.upload('archive',self.zip+b'changed')
        self.assertEqual(self.store.get(self.bundle['id'])['files'],{})
    def test_uploaded_plan_reference_is_not_silently_replaced_by_uploaded_code(self):
        self.plan['repository']['files'][0]['sha256']='0'*64
        receipt=self.ready();result=audit_plan(self.root/receipt['plan_path'],workspace=self.root,imported=receipt['imported_snapshot'])
        self.assertTrue(any(c['dimension']=='code' and c['status']=='fail' and c['code']=='file:experiment.py' for c in result['checks']))
    def test_uploads_are_immutable_and_wrong_paper_binding_is_rejected(self):
        self.upload('paper',self.pdf)
        with self.assertRaises(ValueError):self.upload('paper',self.pdf)
        self.upload('archive',self.zip);self.plan['paper']['sha256']='0'*64
        self.upload('plan',json.dumps(self.plan).encode())
        with self.assertRaises(ValueError):self.store.bind(self.bundle['id'],{})
    def test_modified_extracted_text_and_root_escape_do_not_bind(self):
        self.upload('paper',self.pdf);self.upload('archive',self.zip);self.upload('plan',json.dumps(self.plan).encode())
        with self.assertRaises(ValueError):self.store.bind(self.bundle['id'],{'code_root':'../../outside'})
        (self.store.directory(self.bundle['id'])/'paper-pages.json').write_text('[]')
        with self.assertRaises(ValueError):self.store.bind(self.bundle['id'],{})
    def test_zip_rejects_traversal_case_collision_links_and_git_metadata(self):
        for files in [[('../escape',b'x')],[('A/x.py',b'1'),('a/y.py',b'2')],[('.git/config',b'1')],[('a.py',b'1'),('a.py',b'2')]]:
            with tempfile.TemporaryDirectory() as tmp:
                source=Path(tmp)/'bad.zip';source.write_bytes(make_zip(files))
                with self.assertRaises((ValueError,OSError)):self.store.extract_zip(source,Path(tmp)/'dest')
                self.assertFalse((Path(tmp)/'dest').exists())
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            link=zipfile.ZipInfo('link');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(link,'../secret')
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'links.zip';source.write_bytes(data.getvalue())
            with self.assertRaises(ValueError):self.store.extract_zip(source,Path(tmp)/'dest')
    def test_malformed_nested_plans_and_imported_snapshots_raise_validation_errors(self):
        for change in [lambda p:p.update(experiments=[None]),lambda p:p['experiments'][0].update(variants=[1]),lambda p:p['repository'].update(files=[None]),lambda p:p['datasets'][0].update(source=[]),lambda p:p['experiments'][0]['stages'][0].update(needs=[{}])]:
            plan=copy.deepcopy(self.plan);change(plan)
            with self.assertRaises(ValueError):validate_plan(plan)
        for snapshot in [True,[],{'files':[None]}]:
            with self.assertRaises(ValueError):audit_plan(self.path,imported=snapshot)
    def test_extra_untracked_source_cannot_pass_file_matching(self):
        (self.repo/'untracked.py').write_text('print("unreviewed")')
        result=audit_plan(self.path)
        extra=next(c for c in result['checks'] if c['code']=='undeclared_source_files')
        self.assertEqual(extra['status'],'fail');self.assertIn('untracked.py',extra['evidence']['extra_files'])
