"""Read-only, dependency-free host snapshot. No hostname, credentials or processes."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=4)
        return result.stdout[:64000] if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def memory_snapshot():
    total = available = None
    if platform.system() == "Linux":
        try:
            values = dict((k, int(v.strip().split()[0]) * 1024) for k, v in
                          (line.split(":", 1) for line in Path('/proc/meminfo').read_text().splitlines()))
            total, available = values.get('MemTotal'), values.get('MemAvailable')
            limit = Path('/sys/fs/cgroup/memory.max').read_text().strip()
            used = int(Path('/sys/fs/cgroup/memory.current').read_text())
            if limit.isdigit():
                total = min(total, int(limit)) if total else int(limit)
                available = min(available, max(0, int(limit)-used)) if available is not None else max(0, int(limit)-used)
        except (OSError, ValueError):
            pass
    elif platform.system() == "Darwin":
        text = command(['/usr/sbin/sysctl', '-n', 'hw.memsize'])
        if text and text.strip().isdigit():
            total = int(text.strip())
        # Keep available unknown: total RAM does not establish allocatable RAM.
    return {'total_bytes': total, 'available_bytes': available}


def collect_environment(disk_path=Path.cwd()):
    gpu_rows = None
    smi = shutil.which('nvidia-smi')
    if smi:
        output = command([smi, '--query-gpu=index,name,memory.total,memory.free,driver_version', '--format=csv,noheader,nounits'])
        if output is not None:
            try:
                gpu_rows = []
                for row in csv.reader(io.StringIO(output)):
                    if len(row) != 5:
                        raise ValueError('Invalid GPU record')
                    index, name, total, free, driver = [v.strip() for v in row]
                    gpu_rows.append({'index': int(index), 'name': name[:160], 'total_memory_bytes': int(float(total)*1024**2),
                                     'free_memory_bytes': int(float(free)*1024**2), 'driver': driver[:64]})
            except (ValueError, OverflowError):
                gpu_rows = None
    disk = shutil.disk_usage(disk_path)
    cores = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count()
    return {'format': 'articheck-environment-v1', 'collected_at': datetime.now(timezone.utc).isoformat(),
            'collector': 'articheck-readonly-v1', 'system': {'os': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version()},
            'cpu': {'logical_cores': cores}, 'memory': memory_snapshot(),
            'disk': {'total_bytes': disk.total, 'free_bytes': disk.free, 'scope': 'selected_workspace_filesystem'},
            'gpus': gpu_rows, 'gpu_probe': 'nvidia-smi' if gpu_rows is not None else 'unavailable_or_unsupported',
            'limitations': ['Snapshot only; free resources can change.', 'GPU probe covers NVIDIA only.',
                            'Does not verify CUDA framework compatibility or reserve resources.',
                            'Disk describes the selected filesystem, not every mount.']}


def main():
    parser = argparse.ArgumentParser(description='Read-only ArtiCheck host report; run on the intended execution server.')
    parser.add_argument('--disk-path', type=Path, default=Path.cwd(), help='Filesystem where experiment data and outputs reside')
    parser.add_argument('--output', type=Path, help='Save the JSON report to this file; otherwise print it')
    args = parser.parse_args()
    report = json.dumps(collect_environment(args.disk_path), indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(report)
    else:
        print(report, end='')


if __name__ == '__main__':
    main()
