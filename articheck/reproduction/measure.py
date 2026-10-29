"""Trusted per-stage child measurement; copied into /tmp by the executor."""
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path


def main():
    destination, *argv = sys.argv[1:]
    started = time.monotonic()
    result = subprocess.run(argv, check=False)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    cgroup_peak = None
    try:
        cgroup_peak = int(Path('/sys/fs/cgroup/memory.peak').read_text())
    except (OSError, ValueError):
        pass
    report = {'elapsed_seconds': time.monotonic()-started,
              'child_peak_rss_bytes': int(usage.ru_maxrss*(1 if platform.system() == 'Darwin' else 1024)),
              'child_user_cpu_seconds': usage.ru_utime, 'child_system_cpu_seconds': usage.ru_stime,
              'cgroup_peak_memory_bytes': cgroup_peak if os.environ.get('ARTICHECK_ISOLATED_CONTAINER') == '1' else None,
              'gpu_peak_memory_bytes': None, 'gpu_measurement': 'not_instrumented',
              'returncode': result.returncode}
    Path(destination).write_text(json.dumps(report, allow_nan=False))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
