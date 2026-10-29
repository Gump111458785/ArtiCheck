"""Optional NVIDIA sampling. Container attribution requires matching kernel identity."""
import asyncio
import csv
import hashlib
import io
import math
import re
import shutil
from pathlib import Path


def kernel_identity():
    try:return hashlib.sha256(Path('/proc/sys/kernel/random/boot_id').read_bytes()).hexdigest()
    except OSError:return None


async def bounded_command(argv):
    process=await asyncio.create_subprocess_exec(*argv,stdout=-1,stderr=-1)
    try:out,_=await asyncio.wait_for(process.communicate(),3)
    except asyncio.TimeoutError:
        process.kill();await process.communicate();return None
    if process.returncode or len(out)>128000:return None
    return out.decode(errors='replace')


def parse_devices(text,uuids):
    result={}
    for row in csv.reader(io.StringIO(text)):
        if len(row)!=2:return None
        uuid,memory=[x.strip() for x in row]
        if uuid not in uuids:continue
        try:value=float(memory)*1024**2
        except ValueError:return None
        if not math.isfinite(value) or value<0:return None
        result[uuid]=int(value)
    return result if set(result)==set(uuids) else None


def parse_processes(text,uuids,pids):
    result={key:0 for key in uuids}
    for row in csv.reader(io.StringIO(text)):
        if len(row)!=3:return None
        uuid,pid,memory=[x.strip() for x in row]
        if uuid not in result or not pid.isdigit() or int(pid) not in pids:continue
        try:value=float(memory)*1024**2
        except ValueError:return None
        if not math.isfinite(value) or value<0:return None
        result[uuid]+=int(value)
    return result


async def sample_gpu(docker,name,uuids,same_kernel):
    smi=shutil.which('nvidia-smi')
    if not smi or not uuids or any(not re.fullmatch(r'GPU-[0-9a-fA-F-]{8,80}',key) for key in uuids):return None
    selection='--id='+','.join(uuids)
    text=await bounded_command([smi,selection,'--query-gpu=uuid,memory.used','--format=csv,noheader,nounits'])
    devices=parse_devices(text,uuids) if text is not None else None
    if devices is None:return None
    processes=None
    if same_kernel:
        top=await bounded_command([docker,'top',name,'-eo','pid'])
        pids={int(line.strip()) for line in (top or '').splitlines() if line.strip().isdigit()}
        if pids:
            rows=await bounded_command([smi,selection,'--query-compute-apps=gpu_uuid,pid,used_memory','--format=csv,noheader,nounits'])
            if rows is not None:processes=parse_processes(rows,uuids,pids)
    return {'device_memory_bytes':devices,'container_process_memory_bytes':processes,
            'attribution':'same kernel boot-id digest + Docker top PIDs + selected GPU UUIDs' if processes is not None else 'whole selected device only; job attribution unavailable'}
