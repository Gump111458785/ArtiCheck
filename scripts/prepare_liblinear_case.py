"""Download fixed public author artifacts and create a CPU reproduction plan. No author code executed."""
from __future__ import annotations
import argparse
import bz2
import hashlib
import json
import re
import shutil
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

from articheck.reproduction.protocol import FORMAT, fingerprint

REVISION = '491c9f1188b97ba70847c70a68be363d186ddf9d'
FILES = {
 'source.tar.gz': ('https://codeload.github.com/cjlin1/liblinear/tar.gz/'+REVISION, 'ad9c824a631e48fd57fe21ab23e87e9de0413cf0558d0fa9dd89685aec76c185'),
 'paper.pdf': ('https://www.jmlr.org/papers/volume9/fan08a/fan08a.pdf', '86b3b03c8ff30d9a633884daa00159add25d04d99b64d4010f4894a087127d0a'),
 'news20.binary.bz2': ('https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/binary/news20.binary.bz2', '2659afadb07f109afb57a7fc1ebc13b12581284fadab05b986a25c7d00690b69')}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def download(destination, url, sha):
    from articheck.reproduction.acquisition import fetch_public
    return fetch_public(destination,url,sha,200*1024**2,timeout_seconds=180)


def prepare(destination, base_image):
    if not re.fullmatch(r'(?:docker.io/library/)?python@sha256:[0-9a-f]{64}', base_image):
        raise ValueError('Supply the immutable RepoDigest of official python:3.11-bookworm')
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError('Install optional dependencies: pip install -e ".[reproduction]"') from error
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archives = destination/'downloads';archives.mkdir(exist_ok=True)
    receipts={name:download(archives/name,url,sha) for name,(url,sha) in FILES.items()}
    write(destination/'acquisition-receipt.json',{'format':'articheck-data-acquisition-v1','files':receipts,'scope':'public source, paper and data before experiment timer'})
    artifact = destination/'artifact'
    if artifact.exists():
        raise ValueError('Artifact output already exists; use a new destination or keep the frozen prior plan')
    artifact.mkdir()
    with tarfile.open(archives/'source.tar.gz') as source:
        members = source.getmembers()
        if len(members) > 1000 or sum(m.size for m in members) > 10*1024**2:
            raise ValueError('Source archive exceeds expected bounds')
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != 'liblinear-'+REVISION or '..' in parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError('Unsupported source archive entry')
            target = artifact.joinpath(*parts[1:])
            if member.isdir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with source.extractfile(member) as stream, target.open('wb') as out:shutil.copyfileobj(stream,out)
    shutil.copyfile(archives/'news20.binary.bz2',artifact/'news20.binary.bz2')
    shutil.copyfile(Path(__file__).resolve().parents[1]/'examples/liblinear_case/adapter.py',artifact/'articheck_adapter.py')
    (artifact/'Dockerfile').write_text('FROM '+base_image+'\nCOPY . /opt/liblinear\nWORKDIR /opt/liblinear\nRUN make -j2\nWORKDIR /work\n')
    lock = {'base_image':base_image,'author_archive_sha256':FILES['source.tar.gz'][1], 'dependencies':'Python standard library + bundled BLAS, compiled by base-image toolchain; no pip/network install'}
    write(artifact/'environment-lock.json',lock)
    with bz2.open(artifact/'news20.binary.bz2','rt') as raw, (artifact/'targets.jsonl').open('w') as out:
        for index,line in enumerate(raw):
            out.write(json.dumps({'id':str(index),'target':float(line.split()[0])})+'\n')
    settings = {'hyperparameters':{'epsilon':.1,'C':1,'solver':1},'initialization':'LIBLINEAR solver defaults at fixed revision',
                'augmentation':'none; publisher-provided unit-normalized features','selection':'C fixed at 1 for Section 3.1; no test-set selection',
                'stopping':'epsilon 0.1; other solver defaults at pinned revision'}
    write(artifact/'settings.json',settings)
    pages=[{'number':i+1,'text':page.extract_text()} for i,page in enumerate(PdfReader(archives/'paper.pdf').pages)]
    write(destination/'paper-pages.json',pages)
    def entry(name):return {'path':name,'sha256':fingerprint(artifact/name)['sha256']}
    inventory=[{'id':'practical-news20','labels':[],'page':2,'quote':'3.1 Practical Usage','core':True,'conclusion_ids':['C1']},
               {'id':'comparison-news20','labels':['figure-1'],'page':4,'quote':'(a) news20','core':True,'conclusion_ids':['C2']},
               {'id':'comparison-rcv1','labels':['figure-1'],'page':4,'quote':'(b) rcv1','core':True,'conclusion_ids':['C2']}]
    plan={'format':FORMAT,'paper':{'path':'downloads/paper.pdf','sha256':FILES['paper.pdf'][1],'version':'JMLR 9(61), 2008 final',
           'pages_path':'paper-pages.json','pages_sha256':fingerprint(destination/'paper-pages.json')['sha256'],
           'conclusions':[{'id':'C1','text':'Public training/prediction workflow for linear classification'},
                          {'id':'C2','text':'Efficiency comparisons with other solvers on news20 and rcv1'}],
           'experiments':inventory,'inventory_review':{'complete':False,'notes':'Three visible experiment groups registered; independent reviewer confirmation still required'}},
          'repository':{'path':'artifact','source_revision':REVISION,'source_url':'https://github.com/cjlin1/liblinear',
                        'files':[entry(p.relative_to(artifact).as_posix()) for p in sorted(artifact.rglob('*')) if p.is_file()],
                        'components':{'method':['linear.cpp','newton.cpp'],'preprocess':['articheck_adapter.py'], 'train':['train.c'],'evaluate':['predict.c','articheck_adapter.py']},
                        'method_review':{'source':'Paper Sections 2–3.3; source linear.cpp/train.c/predict.c','verified':False}},
          'datasets':[{'id':'news20','source':{'url':FILES['news20.binary.bz2'][0],'version':'frozen SHA256 '+FILES['news20.binary.bz2'][1],
                      'license':'Public LIBSVM Tools distribution; original dataset terms apply','access':'public'},'files':[entry('news20.binary.bz2'),entry('targets.jsonl')],
                      'preprocessing_not_applicable':'No feature transformation of the publisher-normalized input; generated split IDs/lineage are stage outputs'}],
          'environment':{'dockerfile':'Dockerfile','dockerfile_sha256':fingerprint(artifact/'Dockerfile')['sha256'],
                         'lockfiles':[entry('environment-lock.json')], 'expected':{'python':'3.11','packages':{}}, 'verify':[['python3','-c','import sys; assert sys.version_info[:2] == (3,11)'],['/bin/sh','-c','test -x /opt/liblinear/train && test -x /opt/liblinear/predict']]},
          'resources':{'max_seconds':1800,'memory_bytes':2*1024**3,'cpus':2,'gpu_devices':[],'price_per_hour_usd':None},
          'experiments':[{'id':'news20-section-3-1','paper_experiment':'practical-news20','seeds':[11,22,33,44,55],
              'config':{**entry('settings.json'),'expected':settings,'source':'Paper p2 Section 3.1; pinned author README defaults; deviations explicitly listed'},
              'variants':[{'id':'l2-svm','role':'method','settings':{'solver':1,'C':1}},
                          {'id':'logistic-control','role':'baseline','settings':{'solver':0,'C':1}},
                          {'id':'regularization-control','role':'ablation','settings':{'solver':1,'C':.001}}],
              'training_evidence':{'stage_id':'train','used_config_path':'used-config.json','model_outputs':['model.txt']},
              'fairness':{'source':'Section 3.1 C=1; ArtiCheck additional fixed controls, without tuning',
                          'selection_protocol':'none','allowed_variant_differences':{'logistic-control':['solver'],'regularization-control':['C']}},
              'stages':[{'id':kind,'kind':kind,'argv':['python3','{repo}/articheck_adapter.py',kind,'{config}'],
                         'needs':[] if i==0 else [previous], 'inputs':inputs, 'outputs':outputs,'timeout_seconds':180}
                        for i,(kind,previous,inputs,outputs) in enumerate([
                            ('prepare','', ['repo:news20.binary.bz2','config.json'], ['train.svm','test.svm','train.ids','test.ids','split-provenance.json']),
                            ('train','prepare',['train.svm','config.json'],['model.txt','used-config.json','training-command.json']),
                            ('evaluate','train',['model.txt','test.svm','test.ids'],['predictions.txt','metrics.json','evaluation-records.jsonl']),
                            ('summarize','evaluate',['metrics.json'],['summary.json'])])],
              'split_ids':{'train':{'path':'train.ids','count':15996},'test':{'path':'test.ids','count':4000}},
              'metric':{'implementation':'accuracy','records_path':'evaluation-records.jsonl','targets_path':'targets.jsonl','targets_sha256':fingerprint(artifact/'targets.jsonl')['sha256'],'ids_path':'test.ids','path':'metrics.json','key':'accuracy','direction':'higher','reference':.96575,'absolute_tolerance':.01},
              'comparisons':[{'method':'l2-svm','other':'logistic-control'},{'method':'l2-svm','other':'regularization-control'}],
              'deviations':['Modern author revision is not the unpublished 2008 code state.', 'Original 80/20 row IDs and seed unavailable; our seeded split is explicitly different.',
                            'Controls are added by ArtiCheck, not the Figure 1 Pegasos/SVMperf baselines.', 'Figure 1 comparisons, rcv1, tuning and historical timing are not reproduced.']} ]}
    write(destination/'plan.json',plan)
    print(json.dumps({'plan':str(destination/'plan.json'),'author_revision':REVISION,'scope':'Section 3.1 reconstruction only; full-paper coverage remains incomplete'}))
    return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--base-image',required=True)
    args=parser.parse_args();prepare(args.output,args.base_image)

if __name__=='__main__':main()
