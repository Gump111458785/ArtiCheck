"""Trusted in-container probe. Never reads credentials, hostnames or artifact imports."""
import importlib.metadata
import json
import platform
import sys


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
    print(json.dumps({'python':platform.python_version(),'architecture':platform.machine(),'os':platform.system(),'packages':packages,'cuda':cuda},allow_nan=False))


if __name__=='__main__':main()
