"""Bind requirements to the actual Docker daemon and freshly built image."""
import asyncio
import hashlib
import json
import re
import shutil
from pathlib import Path
from .protocol import fingerprint


async def daemon_snapshot(docker):
    fields={key:'{{json .'+value+'}}' for key,value in {'identity':'ID','os':'OSType','architecture':'Architecture','kernel':'KernelVersion','logical_cpus':'NCPU','memory_bytes':'MemTotal'}.items()}
    argv=[docker,'info','--format','\n'.join(fields.values())]
    process=await asyncio.create_subprocess_exec(*argv,stdout=-1,stderr=-1)
    try:out,_=await asyncio.wait_for(process.communicate(),8)
    except asyncio.TimeoutError:
        process.kill();await process.communicate();return {'status':'unknown','reason':'Docker daemon inspection timed out'}
    if process.returncode or len(out)>64000:return {'status':'unknown','reason':'Docker daemon inspection unavailable'}
    try:
        values=dict(zip(fields,[json.loads(x) for x in out.decode().splitlines()]))
        if len(values)!=len(fields):raise ValueError('Incomplete daemon fields')
        identity=values.pop('identity');values['identity_sha256']=hashlib.sha256(identity.encode()).hexdigest() if identity else None
        return {'status':'observed','source':'Docker daemon info, not browser or client host',**values}
    except (ValueError,TypeError,AttributeError):return {'status':'unknown','reason':'Malformed Docker daemon inspection'}


def requirement_checks(resources,daemon,disk_free):
    required=resources.get('requirements',{});checks=[]
    for key,actual in [('cpus',resources.get('cpus',1)),('memory_bytes',resources.get('memory_bytes',2*1024**3))]:
        if required.get(key) is not None:checks.append({'key':key,'expected_minimum':required[key],'actual_limit':actual,'status':'pass' if actual>=required[key] else 'fail'})
    for key,actual in [('disk_free_bytes',disk_free),('daemon_cpus',daemon.get('logical_cpus')),('daemon_memory_bytes',daemon.get('memory_bytes'))]:
        minimum=required.get(key)
        if minimum is not None:checks.append({'key':key,'expected_minimum':minimum,'actual':actual,'status':'unknown' if actual is None else 'pass' if actual>=minimum else 'fail'})
    return checks


def compare_environment(expected,observed):
    checks=[]
    python=expected.get('python')
    if python:checks.append({'key':'python','expected':python,'actual':observed.get('python'),'status':'pass' if observed.get('python','').split('.')[:len(python.split('.'))]==python.split('.') else 'fail'})
    for name,version in expected.get('packages',{}).items():
        actual=observed.get('packages',{}).get(name)
        checks.append({'key':'package:'+name,'expected':version,'actual':actual,'status':'pass' if actual==version else 'fail'})
    if expected.get('architecture'):
        checks.append({'key':'architecture','expected':expected['architecture'],'actual':observed.get('architecture'),'status':'pass' if expected['architecture']==observed.get('architecture') else 'fail'})
    if expected.get('cuda',{}).get('required'):
        cuda=observed.get('cuda',{});passed=cuda.get('status')=='verified' and cuda.get('kernel_test') is True
        if expected['cuda'].get('runtime'):passed=passed and expected['cuda']['runtime']==cuda.get('runtime')
        checks.append({'key':'cuda_kernel_compatibility','expected':expected['cuda'],'actual':cuda,'status':'pass' if passed else 'fail'})
    if not expected:checks.append({'key':'expected_environment','status':'unknown','detail':'No version/architecture/CUDA requirements supplied'})
    return checks


async def inspect_image(executor,repo,work,expected,timeout,cancel=None):
    source=Path(__file__).with_name('environment_probe.py');target=work/'.articheck-environment-probe.py'
    shutil.copyfile(source,target);digest=fingerprint(source)['sha256']
    argv=['python3','/work/'+target.name,json.dumps(expected)] if executor.mode=='docker' else [__import__('sys').executable,str(target),json.dumps(expected)]
    result=await executor.execute(repo,work,argv,timeout=timeout,cancel=cancel,measurement=False)
    if result['status']!='completed':return {'status':'failed','probe_sha256':digest,'execution':result,'checks':[]}
    if fingerprint(target)['sha256']!=digest:raise ValueError('Environment probe changed during execution')
    try:observed=json.loads(result['stdout'])
    except ValueError:raise ValueError('Image environment probe returned invalid JSON')
    checks=compare_environment(expected,observed)
    return {'status':'failed' if any(c['status']=='fail' for c in checks) else 'verified' if checks and all(c['status']=='pass' for c in checks) else 'unknown',
            'probe_sha256':digest,'observed':observed,'checks':checks,'execution':result}
