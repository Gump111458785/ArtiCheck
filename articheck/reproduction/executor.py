from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import signal
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .protocol import finite, relative_path
from .monitor import ExternalMonitor


class StageExecutor:
    """Writable per-run output, readonly artifact, no network or host credentials."""
    def __init__(self, mode='docker', image=None, *, memory_bytes=2*1024**3, cpus=1, gpu_devices=None, disk_limit_bytes=None, allow_local_trusted=False):
        if mode not in ('docker', 'local') or mode == 'local' and not allow_local_trusted:
            raise ValueError('Local execution requires explicit allow_local_trusted for your own fixtures')
        if mode == 'docker' and os.getuid() == 0:
            raise ValueError('Run ArtiCheck as a non-root user for artifact containers')
        self.mode, self.image = mode, image
        self.memory = int(finite(memory_bytes, minimum=64*1024**2))
        self.cpus = finite(cpus, minimum=.1)
        self.disk_limit=disk_limit_bytes
        self.gpu_devices = gpu_devices or []
        if any(type(i) is not int or i < 0 for i in self.gpu_devices):
            raise ValueError('GPU devices must be integer indices')
        self.docker = shutil.which('docker')
        if mode == 'docker' and not self.docker:
            raise RuntimeError('Docker unavailable; no local fallback for imported artifacts')

    async def execute(self, repo, work, argv, *, timeout=300, environment=None, measurement=True, cancel=None):
        name = 'articheck-repro-' + uuid.uuid4().hex
        helper = Path(__file__).with_name('measure.py')
        measurement_path = work / ('.measurement-' + uuid.uuid4().hex + '.json')
        effective = list(argv)
        local_env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', **(environment or {})}
        if self.mode == 'docker':
            inner = ['python3', '/articheck-measure.py', '/work/'+measurement_path.name, *effective] if measurement else effective
            command = [self.docker, 'run', '--rm', '--name', name, '--network=none', '--read-only',
                       '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=256',
                       '--memory='+str(self.memory), '--memory-swap='+str(self.memory), '--cpus='+str(self.cpus),
                       '--user='+str(os.getuid())+':'+str(os.getgid()), '--init',
                       '--tmpfs=/tmp:rw,nosuid,size=256m', '--workdir=/work',
                       '--mount', 'type=bind,source='+str(repo)+',target=/artifact,readonly',
                       '--mount', 'type=bind,source='+str(work)+',target=/work',
                       '--mount', 'type=bind,source='+str(helper)+',target=/articheck-measure.py,readonly']
            if self.gpu_devices:
                command += ['--gpus', '"device='+','.join(map(str, self.gpu_devices))+'"']
            for key, value in {**local_env, 'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'ARTICHECK_ISOLATED_CONTAINER': '1'}.items():
                command += ['-e', key+'='+str(value)]
            command += [self.image, *inner]
            env = None  # Docker client needs its configured daemon; no secrets forwarded.
        else:
            command = [sys.executable, str(helper), str(measurement_path), *effective] if measurement else effective
            env = local_env
        started = time.monotonic()
        timeout_hit = overflow = cancelled = False
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = await asyncio.create_subprocess_exec(*command, cwd=work, env=env, stdout=out, stderr=err, start_new_session=True)
            monitor=ExternalMonitor(work,self.docker if self.mode=='docker' else None,name,self.disk_limit)
            monitor_task=asyncio.create_task(monitor.run())
            try:
                while process.returncode is None:
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    if time.monotonic()-started > timeout:
                        timeout_hit = True
                        break
                    if monitor.report['disk_limit_exceeded']:
                        break
                    if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 2_000_000:
                        overflow = True
                        break
                    try:
                        await asyncio.wait_for(process.wait(), .05)
                    except asyncio.TimeoutError:
                        pass
            finally:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
                if self.mode == 'docker':
                    cleanup = await asyncio.create_subprocess_exec(self.docker, 'rm', '-f', name, stdout=-3, stderr=-3)
                    try:
                        await asyncio.wait_for(cleanup.wait(), 10)
                    except asyncio.TimeoutError:
                        cleanup.kill()
                        await cleanup.wait()
                monitor.finished=True
                monitor.stop.set()
                await monitor_task
            overflow |= os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 2_000_000
            out.seek(0); err.seek(0)
            stdout, stderr = out.read(2_000_000).decode(errors='replace'), err.read(2_000_000).decode(errors='replace')
        measured = None
        if measurement_path.is_file() and not measurement_path.is_symlink() and measurement_path.stat().st_size <= 100000:
            try:
                measured = json.loads(measurement_path.read_text())
                numeric=('elapsed_seconds','child_peak_rss_bytes','child_user_cpu_seconds','child_system_cpu_seconds','cgroup_peak_memory_bytes','gpu_peak_memory_bytes')
                if not isinstance(measured,dict) or any(measured.get(k) is not None and (type(measured[k]) not in (int,float) or not math.isfinite(measured[k]) or measured[k]<0) for k in numeric):
                    measured=None
            except ValueError:
                pass
        return {'status': 'cancelled' if cancelled else 'completed' if process.returncode == 0 and not timeout_hit and not overflow and not monitor.report['disk_limit_exceeded'] else 'failed',
                'returncode': process.returncode, 'timed_out': timeout_hit, 'output_overflow': overflow,
                'stdout': stdout, 'stderr': stderr, 'elapsed_seconds': time.monotonic()-started,
                'resources': measured, 'measurement_scope': 'child getrusage and isolated cgroup when available; GPU unmeasured',
                'external_resources':monitor.report,
                'isolation': 'docker_no_network' if self.mode == 'docker' else 'local_explicitly_trusted'}
