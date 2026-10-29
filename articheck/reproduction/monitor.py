"""Client-side sampling, separate from artifact-writable instrumentation files."""
import asyncio
import json
import os
import re
import time
from .gpu_monitor import sample_gpu


def quantity(value):
    match=re.fullmatch(r'\s*([0-9]+(?:\.[0-9]+)?)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*',value)
    if not match:raise ValueError('Unknown Docker quantity')
    number,unit=match.groups();power={'B':0,'kB':1,'KB':1,'MB':2,'GB':3,'TB':4,'KiB':1,'MiB':2,'GiB':3,'TiB':4}[unit]
    return int(float(number)*(1024 if 'iB' in unit else 1000)**power)


def occupancy(root,maximum_files=100000):
    size=count=0
    for directory,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if not (root.__class__(directory)/d).is_symlink()]
        for name in files:
            path=root.__class__(directory)/name
            if path.is_symlink():continue
            try:size+=path.stat().st_size
            except FileNotFoundError:continue
            count+=1
            if count>maximum_files:raise ValueError('Output file count exceeds monitoring budget')
    return size


async def docker_sample(docker,name):
    process=await asyncio.create_subprocess_exec(docker,'stats','--no-stream','--format','{{json .}}',name,stdout=-1,stderr=-1)
    try:out,_=await asyncio.wait_for(process.communicate(),3)
    except asyncio.TimeoutError:
        process.kill();await process.communicate();return None
    if process.returncode or len(out)>64000:return None
    try:
        raw=json.loads(out);memory=quantity(raw['MemUsage'].split('/')[0]);cpu=float(raw['CPUPerc'].rstrip('%'))
        if not raw.get('ID') or memory<0 or not 0<=cpu<=100000:return None
        return {'container_id':raw['ID'],'memory_bytes':memory,'cpu_percent':cpu}
    except (ValueError,KeyError,TypeError):return None


class ExternalMonitor:
    def __init__(self,work,docker=None,name=None,disk_limit=None,gpu_uuids=(),same_kernel=False):
        self.work=work;self.docker=docker;self.name=name;self.disk_limit=disk_limit;self.started=time.monotonic();self.finished=False;self.stop=asyncio.Event()
        self.report={'source':'ArtiCheck client-side sampler, outside artifact container','samples':0,'container_samples':0,
            'sampled_peak_output_bytes':None,'sampled_peak_container_memory_bytes':None,'sampled_peak_container_cpu_percent':None,
            'container_ids':[],'disk_limit_exceeded':False,'errors':[],
            'limitations':['Sampled peaks can miss short spikes; Docker memory excludes cache according to daemon semantics.',
                           'Output occupancy is file size, not disk I/O or filesystem-wide peak; GPU sampling has separate attribution and coverage.']}
        self.gpu_uuids=list(gpu_uuids);self.same_kernel=same_kernel
        self.report.update(gpu_samples=0,gpu_process_samples=0,sampled_peak_gpu_device_bytes=None,sampled_peak_gpu_process_bytes=None,sampled_peak_gpu_process_total_bytes=None,
                gpu_scope='Device memory includes other tasks. Container process memory requires matching kernel identity and Docker PIDs. Sampled peaks can miss short allocations; unsupported NVIDIA/MIG/WDDM data remains unknown.')
    def sample_disk(self):
        try:
            size=occupancy(self.work);self.report['samples']+=1
            self.report['sampled_peak_output_bytes']=max(size,self.report['sampled_peak_output_bytes'] or 0)
            if self.disk_limit is not None and size>self.disk_limit:self.report['disk_limit_exceeded']=True
        except (OSError,ValueError) as error:
            message=str(error)
            if message not in self.report['errors']:self.report['errors'].append(message)
    async def run(self):
        self.sample_disk()
        while not self.finished:
            if self.docker:
                value=await docker_sample(self.docker,self.name)
                if value:
                    self.report['container_samples']+=1
                    if value['container_id'] not in self.report['container_ids']:self.report['container_ids'].append(value['container_id'])
                    for source,target in [('memory_bytes','sampled_peak_container_memory_bytes'),('cpu_percent','sampled_peak_container_cpu_percent')]:
                        self.report[target]=max(value[source],self.report[target] or 0)
                if self.gpu_uuids:
                    gpu=await sample_gpu(self.docker,self.name,self.gpu_uuids,self.same_kernel)
                    if gpu:
                        self.report['gpu_samples']+=1
                        for field,target in [('device_memory_bytes','sampled_peak_gpu_device_bytes'),('container_process_memory_bytes','sampled_peak_gpu_process_bytes')]:
                            if gpu[field] is not None:
                                peaks=self.report[target] or {}
                                for uuid,size in gpu[field].items():peaks[uuid]=max(size,peaks.get(uuid,0))
                                self.report[target]=peaks
                        if gpu['container_process_memory_bytes'] is not None:
                            self.report['gpu_process_samples']+=1
                            total=sum(gpu['container_process_memory_bytes'].values())
                            self.report['sampled_peak_gpu_process_total_bytes']=max(total,self.report['sampled_peak_gpu_process_total_bytes'] or 0)
            self.sample_disk()
            try:await asyncio.wait_for(self.stop.wait(),.25)
            except asyncio.TimeoutError:pass
        self.sample_disk();self.report['elapsed_seconds']=time.monotonic()-self.started
