"""Trusted CPU supervisor copied into each E2B VM, run as root without secrets.

Artifact commands run as the unprivileged `user`, with a bounded wall clock,
process count, file size and address space. Results are root-owned. Uploaded code
can still print arbitrary numbers: an observed stdout is not scientific truth.
"""
import ast
import json
import math
import os
import pwd
from pathlib import Path
import platform
import re
import resource
import signal
import subprocess
import sys
import time
import shutil
import statistics

IMPORT_TO_PYPI = {
    'cv2': 'opencv-python-headless',
    'sklearn': 'scikit-learn',
    'skimage': 'scikit-image',
    'PIL': 'Pillow',
    'yaml': 'PyYAML',
    'bs4': 'beautifulsoup4',
    'attr': 'attrs',
    'dotenv': 'python-dotenv',
    'fitz': 'PyMuPDF',
    'dateutil': 'python-dateutil',
    'serial': 'pyserial',
    'Crypto': 'pycryptodome',
    'crypto': 'pycryptodome',
    'jwt': 'PyJWT',
    'git': 'GitPython',
    'Bio': 'biopython',
    'OpenGL': 'PyOpenGL',
    'hydra': 'hydra-core',
    'rouge_score': 'rouge-score',
    'pytorch_lightning': 'pytorch-lightning',
    'pynvml': 'nvidia-ml-py',
    'charset_normalizer': 'charset-normalizer',
}

STDLIB_MODULES = set(getattr(sys, 'stdlib_module_names', ())) | {
    '__builtin__', '__future__', 'abc', 'argparse', 'array', 'ast', 'asyncio', 'atexit',
    'base64', 'bdb', 'binascii', 'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb',
    'chunk', 'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections', 'colorsys',
    'compileall', 'concurrent', 'configparser', 'ConfigParser', 'contextlib', 'contextvars',
    'copy', 'copyreg', 'cProfile', 'crypt', 'csv', 'ctypes', 'curses', 'dataclasses',
    'datetime', 'dbm', 'decimal', 'difflib', 'dis', 'distutils', 'doctest', 'email',
    'encodings', 'ensurepip', 'enum', 'errno', 'faulthandler', 'fcntl', 'filecmp',
    'fileinput', 'fnmatch', 'formatter', 'fractions', 'ftplib', 'functools', 'gc',
    'getopt', 'getpass', 'gettext', 'glob', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac',
    'html', 'http', 'imaplib', 'imghdr', 'imp', 'importlib', 'inspect', 'io', 'ipaddress',
    'itertools', 'json', 'keyword', 'lib2to3', 'linecache', 'locale', 'logging', 'lzma',
    'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder',
    'multiprocessing', 'netrc', 'nis', 'nntplib', 'numbers', 'operator', 'optparse', 'os',
    'ossaudiodev', 'parser', 'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil',
    'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint', 'profile', 'pstats',
    'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc', 'queue', 'Queue', 'quopri', 'random',
    're', 'readline', 'reprlib', 'resource', 'rlcompleter', 'runpy', 'sched', 'secrets',
    'select', 'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd',
    'smtplib', 'sndhdr', 'socket', 'socketserver', 'SocketServer', 'spwd', 'sqlite3',
    'ssl', 'stat', 'statistics', 'string', 'stringprep', 'struct', 'subprocess', 'sunau',
    'symbol', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny', 'tarfile', 'telnetlib',
    'tempfile', 'termios', 'test', 'textwrap', 'threading', 'time', 'timeit', 'tkinter',
    'token', 'tokenize', 'trace', 'traceback', 'tracemalloc', 'tty', 'turtle', 'types',
    'typing', 'unicodedata', 'unittest', 'urllib', 'urllib2', 'urlparse', 'uu', 'uuid',
    'venv', 'warnings', 'wave', 'weakref', 'webbrowser', 'winreg', 'winsound', 'wsgiref',
    'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib',
    'cPickle', 'StringIO', 'cStringIO', 'httplib', 'future_builtins', 'commands', 'sets',
    'md5', 'sha', 'thread', 'dummy_thread', 'repr', 'UserDict', 'UserList', 'UserString',
    'whichdb', 'anydbm', 'dbhash', 'bsddb', 'gdbm', 'dumbdbm', 'pkg_resources',
    'typing_extensions', 'pip', 'setuptools', 'wheel',
}

SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.pydeps', '.cache', 'venv', '.venv', 'env', 'node_modules', 'build', 'dist'}
SAFE_PKG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$')


def infer_project_dependencies(work_dir):
    root = Path(work_dir)
    if not root.exists():
        return {}
    local_modules = set()
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir.parts:
            local_modules.add(rel_dir.parts[0].split('.')[0])
        for d in dirnames:
            local_modules.add(d.split('.')[0])
        for fname in filenames:
            if fname.endswith('.py'):
                stem = fname[:-3]
                if stem != '__init__':
                    local_modules.add(stem)
                py_files.append(Path(dirpath) / fname)

    imported = set()
    for py_path in py_files[:600]:
        try:
            if py_path.stat().st_size > 512 * 1024:
                continue
            source = py_path.read_text(errors='replace')
        except OSError:
            continue
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = (alias.name or '').split('.')[0].strip()
                        if top:
                            imported.add(top)
                elif isinstance(node, ast.ImportFrom) and (node.level or 0) == 0 and node.module:
                    top = node.module.split('.')[0].strip()
                    if top:
                        imported.add(top)
        except SyntaxError:
            for match in re.finditer(r'^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)', source, re.M):
                imported.add(match.group(1))

    resolved = {}
    for mod in sorted(imported):
        if mod in STDLIB_MODULES or mod in local_modules or mod.startswith('_'):
            continue
        pkg = IMPORT_TO_PYPI.get(mod, mod)
        if SAFE_PKG_RE.match(pkg):
            resolved[mod] = pkg
    return resolved


def parse_missing_modules_from_log(log_text):
    missing = {}
    for pattern in (
        r"ModuleNotFoundError:\s+No module named ['\"]([A-Za-z0-9_.-]+)['\"]",
        r"ImportError:\s+No module named ['\"]?([A-Za-z0-9_.-]+)['\"]?",
    ):
        for match in re.finditer(pattern, log_text or ''):
            raw_mod = match.group(1).split('.')[0].strip()
            if raw_mod and raw_mod not in STDLIB_MODULES and not raw_mod.startswith('_'):
                pkg = IMPORT_TO_PYPI.get(raw_mod, raw_mod)
                if SAFE_PKG_RE.match(pkg):
                    missing[raw_mod] = pkg
    return missing


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(path)


def collapse_cr_lines(text):
    if not text:
        return ''
    out = []
    for raw_line in text.split('\n'):
        if '\r' in raw_line:
            segs = [s for s in raw_line.split('\r') if s.strip()]
            out.append(segs[-1] if segs else '')
        else:
            out.append(raw_line)
    return '\n'.join(out)


def extract_live_tail(log_text, max_lines=3):
    cleaned = collapse_cr_lines(log_text or '')
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    return lines[-max_lines:] if lines else []


def read_bounded_log(log_path, limit=24000):
    if not log_path.exists():
        return '', False
    try:
        size = log_path.stat().st_size
        if size <= limit:
            raw = log_path.read_bytes()
            return collapse_cr_lines(raw.decode(errors='replace')), False
        head_len = limit // 3
        tail_len = limit - head_len - 64
        with log_path.open('rb') as stream:
            head = stream.read(head_len)
            stream.seek(max(0, size - tail_len))
            tail = stream.read(tail_len)
        combined = head.decode(errors='replace') + '\n...[中间进度输出已省略]...\n' + tail.decode(errors='replace')
        return collapse_cr_lines(combined)[-limit:], True
    except OSError:
        return '', False



def limits(address_space_mb=3072):
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024**2, 128 * 1024**2))
    if sys.platform.startswith('linux'):
        bound=max(3072,min(18432,int(address_space_mb))) * 1024**2
        resource.setrlimit(resource.RLIMIT_AS, (bound, bound))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_plan(plan, root, results, *, run_as='articheck'):
    root = Path(root); results = Path(results)
    pydeps_dir = root / '.pydeps'
    cache_dir = root / '.cache'
    pydeps_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if run_as and os.getuid() == 0:
        try:
            acct = pwd.getpwnam(run_as)
            for d in (pydeps_dir, cache_dir):
                os.chown(d, acct.pw_uid, acct.pw_gid)
        except Exception:
            pass
    inferred_deps = infer_project_dependencies(root)
    started = time.time(); deadline = time.monotonic() + plan['max_seconds']
    report = {'status': 'running', 'started_at': started, 'stages': [], 'metrics': [],
              'execution_performed': False, 'scientific_validation': False,
              'hardware': {'cpu_count': os.cpu_count(), 'gpu': False}, 'events': []}
    disk=shutil.disk_usage(root)
    report['runtime']={'python':platform.python_version(),'system':platform.system(),
                       'release':platform.release(),'architecture':platform.machine(),
                       'disk_total_bytes':disk.total,'disk_free_before_bytes':disk.free,
                       'inferred_dependencies':sorted(set(inferred_deps.values())),
                       'auto_provisioned_packages':[]}
    status_path = results / 'status.json'

    def event(role, kind, **data):
        report['events'].append({'role': role, 'kind': kind, 'time': time.time(), **data})

    event('planner', 'plan_scheduled', policy='frozen_api_plan', stages=len(plan['stages']))
    atomic(status_path, report)
    all_logs = [];stage_logs={}
    failed = False
    fail_fast = plan.get('fail_fast', plan.get('policy') == 'frozen_api_plan')
    failed_stage_id = None
    stage_env = {
        'PATH': f'{pydeps_dir}/bin:/home/articheck/venv/bin:/usr/local/bin:/usr/bin:/bin',
        'HOME': str(root),
        'PYTHONUSERBASE': str(pydeps_dir),
        'PIP_USER': '1',
        'PIP_CACHE_DIR': str(cache_dir / 'pip'),
        'XDG_CACHE_HOME': str(cache_dir),
        'LANG': 'C.UTF-8',
        'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
        'PYTHONUNBUFFERED': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
    }
    for stage in plan['stages']:
        row = {k: stage[k] for k in ('id', 'title', 'command', 'file')}
        row['experiment']=stage.get('experiment','')
        dependencies=stage.get('depends_on',[report['stages'][-1]['id']] if report['stages'] else [])
        blocked=any(not any(s['id']==d and s['status']=='completed' for s in report['stages']) for d in dependencies)
        if (fail_fast and failed_stage_id) or blocked or deadline <= time.monotonic():
            if fail_fast and failed_stage_id:
                skip_reason = f'前序阶段 {failed_stage_id} 执行报错，已直接中断后续阶段。'
            elif blocked:
                skip_reason = '依赖阶段未完成。'
            else:
                skip_reason = '时间预算已用尽。'
            row.update(status='skipped', reason=skip_reason)
            report['stages'].append(row)
            continue
        row.update(status='running', started_at=time.time(), live_tail=[])
        report['stages'].append(row)
        event('experiment_runner', 'stage_started', stage=stage['id'])
        atomic(status_path, report)
        log_path = results / (stage['id'] + '.log')
        command = ['/bin/bash', '-c', stage['command']]
        def child_limits():
            if run_as:
                account=pwd.getpwnam(run_as)
                os.setgroups([])
                os.setgid(account.pw_gid)
                os.setuid(account.pw_uid)
            # Drop identity directly. Utilities such as runuser can reset
            # RLIMIT_AS / RLIMIT_FSIZE after the supervisor has applied them.
            limits(plan.get('address_space_mb',3072))
        timed_out = False
        with log_path.open('wb') as log:
            process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                env=stage_env, start_new_session=True, preexec_fn=child_limits)
            report['execution_performed'] = True
            try:
                while True:
                    code = process.poll()
                    if code is not None:
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGKILL)
                        code = process.wait()
                        break
                    partial_log, _ = read_bounded_log(log_path, 24000)
                    if partial_log:
                        row['output'] = partial_log
                        row['live_tail'] = extract_live_tail(partial_log, 3)
                        atomic(status_path, report)
                    time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
            finally:
                # Kill descendants left in the process group before the next stage.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        log_text, truncated = read_bounded_log(log_path, 24000)
        if code != 0 and not timed_out and time.monotonic() < deadline:
            missing_mods = parse_missing_modules_from_log(log_text)
            heal_pkgs = sorted(set(missing_mods.values()))
            if heal_pkgs:
                heal_log = results / (stage['id'] + '_autoheal.log')
                pkg_args = ' '.join(heal_pkgs)
                retry_cmd = ['/bin/bash', '-c', f"python3 -m pip install --user --no-input --prefer-binary {pkg_args} && ({stage['command']})"]
                timed_out2 = False
                with heal_log.open('wb') as hlog:
                    proc2 = subprocess.Popen(retry_cmd, cwd=root, stdout=hlog, stderr=subprocess.STDOUT,
                        env=stage_env, start_new_session=True, preexec_fn=child_limits)
                    try:
                        code2 = proc2.wait(timeout=max(1, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        timed_out2 = True
                        os.killpg(proc2.pid, signal.SIGKILL)
                        code2 = proc2.wait()
                    finally:
                        try:
                            os.killpg(proc2.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                heal_text, _ = read_bounded_log(heal_log, 24000)
                log_text = (log_text.rstrip() + f"\n\n[ArtiCheck 自动补齐依赖: {', '.join(heal_pkgs)}]\n" + heal_text)[-24000:]
                code, timed_out = code2, timed_out2
                report['runtime']['auto_provisioned_packages'] = sorted(set(report['runtime']['auto_provisioned_packages']) | set(heal_pkgs))
        all_logs.append(log_text)
        stage_logs[stage['id']]=log_text
        row.update(status='completed' if code == 0 and not timed_out else 'failed', exit_code=code,
                   timed_out=timed_out, finished_at=time.time(), output=log_text,
                   live_tail=extract_live_tail(log_text, 3),
                   output_truncated=truncated)
        row['child_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        failed = row['status'] == 'failed'
        if failed and not failed_stage_id:
            failed_stage_id = stage['id']
        event('experiment_runner', 'stage_finished', stage=stage['id'], exit_code=code, timed_out=timed_out)
        event('cross_auditor', 'stage_checked', stage=stage['id'], status=row['status'])
        atomic(status_path, report)
    logs = '\n'.join(all_logs)
    targets = {m['id']: m for m in plan.get('metrics', [])}
    for rule in plan.get('metric_patterns', []):
        target = targets.get(rule['metric_id'])
        if not target:
            continue
        try:
            output=stage_logs.get(rule.get('stage_id'),logs if len(plan['stages'])==1 else '')
            values = [float(m.group(1)) for m in re.finditer(rule['pattern'], output)]
            values=[v for v in values if math.isfinite(v)]
            observed = (statistics.mean(values) if rule.get('aggregation')=='mean' else values[-1]) if values else None
        except (ValueError, re.error):
            observed = None;values=[]
        report['metrics'].append({'id': target['id'], 'metric': target['metric'], 'expected': target['value'],
            'observed': observed, 'unit': target['unit'], 'tolerance': rule['tolerance'],
            'observations':values,'n':len(values),'std':statistics.stdev(values) if len(values)>1 else None,
            'aggregation':rule.get('aggregation','last'),
            'stage_id':rule.get('stage_id'),'target_evidence_kind':target.get('evidence_kind','text_verified'),
            'status': 'unobserved' if observed is None else 'within_tolerance' if abs(observed-target['value']) <= rule['tolerance'] else 'outside_tolerance',
            'evidence_kind': 'artifact_stdout', 'pattern': rule['pattern']})
    failed=any(s['status']=='failed' for s in report['stages'])
    report['status'] = 'completed' if all(s['status'] == 'completed' for s in report['stages']) else 'failed'
    report['finished_at'] = time.time()
    report['elapsed_seconds'] = round(report['finished_at'] - started, 3)
    shutil.rmtree(pydeps_dir, ignore_errors=True)
    shutil.rmtree(cache_dir, ignore_errors=True)
    report['runtime']['workspace_cleaned'] = not pydeps_dir.exists() and not cache_dir.exists()
    report['runtime']['disk_free_after_bytes']=shutil.disk_usage(root).free
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    report['runtime']['child_cpu_seconds']=round(usage.ru_utime+usage.ru_stime,3)
    failure_logs='\n'.join(s.get('output','') for s in report['stages'] if s['status']=='failed')
    transient=failed and bool(re.search(
        r'((?:HTTP(?:\s+Error|/[\d.]+)?|status(?:\s+code)?)\s*[:=]?\s*429\b|429\s+(?:Client Error|Too Many Requests)|too many requests|rate.?limit|temporary failure|connection timed out)',failure_logs,re.I))
    report['failure_category']='transient_service' if transient else 'execution_blocked' if failed else None
    report['needs_user'] = failed and not transient and bool(re.search(
        r'(file not found|filenotfound|no such file|permission denied|HTTP(?:\s+Error|/[\d.]+)?\s*[:=]?\s*(?:401|403)\b|credentials|download|dataset|checkpoint|cuda|out of memory)', failure_logs, re.I))
    report['question'] = '自动获取或执行遇到阻碍，请查看失败步骤。能否补充缺失的数据、权重或公开获取线索？' if report['needs_user'] else None
    report['acceptance'] = {'process': report['status'] == 'completed', 'paper_conclusion': None,
                            'notice': '阶段退出码和 stdout 指标仅证明本次运行观测；主要结论需核对完整协议与对照。'}
    event('planner', 'stopped', reason=report['status'], policy='frozen_api_plan')
    event('cross_auditor', 'execution_checked', metrics=len(report['metrics']))
    event('reporter', 'report_written', status=report['status'])
    atomic(status_path, report)
    return report


if __name__ == '__main__':
    config = json.loads(Path(sys.argv[1]).read_text())
    try:
        run_plan(config, sys.argv[2], sys.argv[3])
    except Exception as exc:
        atomic(Path(sys.argv[3]) / 'status.json', {'status': 'failed', 'error': type(exc).__name__,
               'execution_performed': False, 'scientific_validation': False, 'stages': [], 'metrics': []})
        raise
