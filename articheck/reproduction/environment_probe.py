"""Trusted in-container probe. Never reads credentials, hostnames or artifact imports."""
import importlib.metadata
import json
import platform
import sys
import csv
import io
import subprocess
import shutil
import hashlib
from pathlib import Path


def main():
    request=json.loads(sys.argv[1]);packages={}
    for name in request.get('packages',{}):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]=None
    cuda={'status':'not_requested','available':None,'runtime':None,'kernel_test':None}
    if request.get('cuda',{}).get('required'):
        cuda['status']='unavailable'
        try:
            import torch
            cuda.update(framework='torch',framework_version=torch.__version__,runtime=torch.version.cuda,available=torch.cuda.is_available())
            if cuda['available']:
                x=torch.ones((2,2),device='cuda');result=(x@x).sum().item();torch.cuda.synchronize()
                cuda.update(status='verified' if result==8 else 'failed',kernel_test=result==8,device_name=torch.cuda.get_device_name(0))
        except (ImportError,RuntimeError,AssertionError) as error:cuda['error']=type(error).__name__+': '+str(error)[:500]
    devices=[];boot=None
    try:boot=hashlib.sha256(Path('/proc/sys/kernel/random/boot_id').read_bytes()).hexdigest()
    except OSError:pass
    smi=shutil.which('nvidia-smi')
    if smi:
        try:
            result=subprocess.run([smi,'--query-gpu=uuid,driver_version','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=4)
            if result.returncode==0 and len(result.stdout)<64000:
                devices=[{'uuid':row[0].strip(),'driver':row[1].strip()} for row in csv.reader(io.StringIO(result.stdout)) if len(row)==2]
        except (OSError,subprocess.TimeoutExpired):pass
    print(json.dumps({'python':platform.python_version(),'architecture':platform.machine(),'os':platform.system(),'packages':packages,'cuda':cuda,'nvidia_devices':devices,'kernel_identity_sha256':boot},allow_nan=False))


if __name__=='__main__':main()
