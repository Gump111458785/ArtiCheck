"""Owned GPU pull-worker with unprivileged bubblewrap + network isolation.

Polls the private Redis queue using only scoped storage credentials, downloads
short-lived source archives over HTTPS, verifies SHA256, and runs each stage
inside an isolated user/network/PID/mount namespace with read-only CUDA runtime.
"""
import ast
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import pwd
import re
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

MAX_CODE_BYTES = 100 * 1024**2
RUNTIME_DIR = '/opt/articheck-runtime'
ALLOWED_ARCHIVE_SUFFIXES = ('.e2b.app', '.e2b.dev')

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

PREINSTALLED_RUNTIME_MODULES = {
    'torch', 'torchvision', 'torchaudio', 'numpy', 'scipy', 'PIL', 'requests',
    'urllib3', 'certifi', 'idna', 'charset_normalizer', 'packaging', 'filelock',
    'jinja2', 'markupsafe', 'networkx', 'sympy', 'mpmath', 'fsspec',
}

SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.pydeps', '.conda_env', '.cache', 'venv', '.venv', 'env', 'node_modules', 'build', 'dist'}
SAFE_PKG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$')


def infer_project_dependencies(work_dir):
    """Analyze Python source imports and dependency files without blindly trusting strict pins."""
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
    """Extract missing module names from ModuleNotFoundError / ImportError tracebacks."""
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


def collapse_cr_lines(text):
    """Collapse carriage-return progress bar updates on the same line into the latest frame."""
    if not text:
        return ''
    out = []
    for raw_line in text.split('\n'):
        if '\r' in raw_line:
            parts = [p for p in raw_line.split('\r') if p.strip()]
            out.append(parts[-1] if parts else '')
        else:
            out.append(raw_line)
    return '\n'.join(out)


def extract_live_tail(log_text, max_lines=3):
    """Return the latest non-empty lines from stage stdout/stderr."""
    cleaned = collapse_cr_lines(log_text or '')
    lines = [ln.strip()[:260] for ln in cleaned.splitlines() if ln.strip()]
    return lines[-max_lines:]


def read_bounded_log(log_path, limit=24000):
    """Read log file preserving both head and tail when large, collapsing CR progress bars."""
    if not log_path.exists():
        return '', False
    size = log_path.stat().st_size
    if size <= limit * 2:
        with log_path.open('rb') as stream:
            raw = stream.read(limit * 2)
        text = collapse_cr_lines(raw.decode(errors='replace'))
        if len(text) <= limit:
            return text, False
        head = text[:8000].rstrip()
        tail = text[-(limit - 8050):].lstrip()
        return f"{head}\n...[中间进度日志已折叠]...\n{tail}", True
    with log_path.open('rb') as stream:
        head_raw = stream.read(12000)
        stream.seek(max(0, size - 48000))
        tail_raw = stream.read(48000)
    head_text = collapse_cr_lines(head_raw.decode(errors='replace'))[:8000].rstrip()
    tail_text = collapse_cr_lines(tail_raw.decode(errors='replace'))[-(limit - 8050):].lstrip()
    return f"{head_text}\n...[中间进度日志已折叠]...\n{tail_text}", True


class WorkerStore:
    def __init__(self, env):
        self.url = env.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
        self.token = env.get('UPSTASH_REDIS_REST_TOKEN', '')

    def command(self, *args):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                raise ValueError('Redirect disabled')
        req = urllib.request.Request(self.url, data=json.dumps(list(args)).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as resp:
            value = json.loads(resp.read(1_000_001))
        if 'error' in value or 'result' not in value:
            raise RuntimeError('Redis command error')
        return value['result']


def detect_capacity(runtime=RUNTIME_DIR):
    capacity = {'provider': 'owned_gpu', 'cpu_count': min(8, os.cpu_count() or 4),
                'memory_mb': 16384, 'gpu': True, 'gpu_name': 'NVIDIA GeForce RTX 4090',
                'gpu_memory_mb': 24564}
    python_bin = Path(runtime) / 'bin/python'
    if python_bin.exists():
        try:
            code = ('import json,torch;p=torch.cuda.get_device_properties(0);'
                    'print(json.dumps({"gpu":torch.cuda.is_available(),"gpu_name":p.name,'
                    '"gpu_memory_mb":int(p.total_memory//(1024*1024))}))')
            out = subprocess.check_output([str(python_bin), '-c', code],
                env={'PYTHONHOME': runtime, 'PATH': f'{runtime}/bin:/usr/bin:/bin',
                     'PYTHONNOUSERSITE': '1', 'CUDA_VISIBLE_DEVICES': '0'},
                text=True, timeout=15)
            capacity.update(json.loads(out.strip().splitlines()[-1]))
        except Exception:
            pass
    return capacity


def validate_source_url(url):
    parsed = urllib.parse.urlparse(url or '')
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not any(host.endswith(s) for s in ALLOWED_ARCHIVE_SUFFIXES):
        raise ValueError('Untrusted GPU source archive URL')
    return url


def fetch_source_archive(url, expected_bytes, expected_sha256):
    validate_source_url(url)
    if not isinstance(expected_bytes, int) or not 1 <= expected_bytes <= MAX_CODE_BYTES:
        raise ValueError('Invalid source archive size')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Redirect disabled')
    req = urllib.request.Request(url, headers={'User-Agent': 'ArtiCheck-GPU-Worker/1.0'})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=45) as resp:
        raw = resp.read(expected_bytes + 1)
    if len(raw) != expected_bytes:
        raise ValueError('Source archive size mismatch')
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Source archive SHA256 mismatch')
    return raw


def extract_archive(raw, dest):
    root = Path(dest).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if not n.endswith('/')]
        if not names or len(names) > 4000:
            raise ValueError('Archive file count out of bounds')
        prefix = names[0].split('/')[0] + '/'
        strip = bool(prefix) and all(n.startswith(prefix) for n in names)
        total = 0
        for item in archive.infolist():
            if item.is_dir():
                continue
            mode = item.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                raise ValueError('Symlinks are not allowed in archive')
            rel = item.filename[len(prefix):] if strip else item.filename
            if not rel or rel.startswith('/') or '..' in Path(rel).parts:
                raise ValueError('Unsafe archive path')
            target = (root / rel).resolve()
            if os.path.commonpath([str(root), str(target)]) != str(root):
                raise ValueError('Unsafe archive target')
            total += item.file_size
            if total > 512 * 1024 * 1024:
                raise ValueError('Uncompressed archive exceeds limit')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            if mode & 0o111:
                target.chmod(0o755)


def bwrap_args(work_dir, command, runtime=RUNTIME_DIR):
    args = ['/usr/bin/bwrap', '--unshare-all', '--share-net', '--new-session', '--die-with-parent',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/bin', '/bin',
            '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--ro-bind', '/sys', '/sys', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--ro-bind', runtime, runtime,
            '--tmpfs', runtime + '/conda-meta', '--tmpfs', runtime + '/etc',
            '--bind', str(work_dir), '/work', '--chdir', '/work',
            '--uid', '65534', '--gid', '65534', '--cap-drop', 'ALL']
    resolv = Path('/etc/resolv.conf')
    if resolv.exists():
        args += ['--ro-bind', str(resolv.resolve()), '/etc/resolv.conf']
    for etc_path in ('/etc/hosts', '/etc/nsswitch.conf', '/etc/ssl', '/etc/ca-certificates', '/etc/pki', '/etc/alternatives'):
        if Path(etc_path).exists():
            args += ['--ro-bind', etc_path, etc_path]
    for dev in ('nvidia0', 'nvidiactl', 'nvidia-uvm', 'nvidia-uvm-tools'):
        dev_path = '/dev/' + dev
        if Path(dev_path).exists():
            args += ['--dev-bind', dev_path, dev_path]
    return args + ['/bin/bash', '-c', command]


def bwrap_env(runtime=RUNTIME_DIR):
    ca_bundle = '/etc/ssl/certs/ca-certificates.crt'
    return {'PYTHONHOME': runtime,
            'PATH': f'/work/.pydeps/bin:{runtime}/bin:/usr/local/bin:/usr/bin:/bin',
            'HOME': '/work',
            'PYTHONUSERBASE': '/work/.pydeps',
            'PIP_USER': '1',
            'PIP_CACHE_DIR': '/work/.cache/pip',
            'XDG_CACHE_HOME': '/work/.cache',
            'TORCH_HOME': '/work/.cache/torch',
            'HF_HOME': '/work/.cache/huggingface',
            'SSL_CERT_FILE': ca_bundle,
            'SSL_CERT_DIR': '/etc/ssl/certs',
            'REQUESTS_CA_BUNDLE': ca_bundle,
            'CURL_CA_BUNDLE': ca_bundle,
            'LANG': 'C.UTF-8',
            'OMP_NUM_THREADS': '4',
            'OPENBLAS_NUM_THREADS': '4',
            'MKL_NUM_THREADS': '4',
            'PYTHONUNBUFFERED': '1',
            'PIP_DISABLE_PIP_VERSION_CHECK': '1',
            'CUDA_VISIBLE_DEVICES': '0'}


def evaluate_metrics(plan, stage_logs, all_logs):
    logs = '\n'.join(all_logs)
    targets = {m['id']: m for m in plan.get('metrics', [])}
    metrics = []
    for rule in plan.get('metric_patterns', []):
        target = targets.get(rule['metric_id'])
        if not target:
            continue
        try:
            output = stage_logs.get(rule.get('stage_id'), logs if len(plan['stages']) == 1 else '')
            values = [float(m.group(1)) for m in re.finditer(rule['pattern'], output)]
            values = [v for v in values if math.isfinite(v)]
            observed = (statistics.mean(values) if rule.get('aggregation') == 'mean' else values[-1]) if values else None
        except (ValueError, re.error):
            observed = None
            values = []
        metrics.append({'id': target['id'], 'metric': target['metric'], 'expected': target['value'],
            'observed': observed, 'unit': target['unit'], 'tolerance': rule['tolerance'],
            'observations': values, 'n': len(values), 'std': statistics.stdev(values) if len(values) > 1 else None,
            'aggregation': rule.get('aggregation', 'last'),
            'stage_id': rule.get('stage_id'), 'target_evidence_kind': target.get('evidence_kind', 'text_verified'),
            'status': 'unobserved' if observed is None else 'within_tolerance' if abs(observed - target['value']) <= rule['tolerance'] else 'outside_tolerance',
            'evidence_kind': 'artifact_stdout', 'pattern': rule['pattern']})
    return metrics


class GPUWorker:
    def __init__(self, env, *, store=None, fetcher=fetch_source_archive,
                 runtime=RUNTIME_DIR, run_as='articheck', work_root=None):
        self.env = env
        self.store = store or WorkerStore(env)
        self.fetcher = fetcher
        self.runtime = runtime
        self.run_as = run_as
        self.prefix = 'articheck:gpu:' + env.get('ARTICHECK_BUDGET_ID', '') + ':'
        self.capacity = detect_capacity(runtime)
        shm = Path('/dev/shm')
        self.work_root = Path(work_root) if work_root else (shm if shm.is_dir() and os.access(shm, os.W_OK) else Path(tempfile.gettempdir()))
        self.last_heartbeat = 0.0

    def send_heartbeat(self, force=False):
        now = time.time()
        if not force and now - self.last_heartbeat < 20:
            return
        payload = {'time': now, 'capacity': self.capacity}
        self.store.command('SET', self.prefix + 'heartbeat', json.dumps(payload, ensure_ascii=False), 'EX', '120')
        self.last_heartbeat = now

    def job_key(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('Invalid GPU job id')
        return self.prefix + 'job:' + job_id

    def save_record(self, record):
        if record.get('status') == 'running' and self.is_cancelled(record['id']):
            record['status'] = 'cancelled'
            record['source_url'] = None
            record['notice'] = '用户停止执行，保留已产生的证据。'
            if isinstance(record.get('result'), dict):
                record['result']['status'] = 'cancelled'
        self.store.command('SET', self.job_key(record['id']), json.dumps(record, ensure_ascii=False), 'EX', '604800')

    def is_cancelled(self, job_id):
        return bool(self.store.command('GET', self.job_key(job_id) + ':cancel'))

    def run_stage_command(self, work_dir, log_path, command, deadline, job_id):
        args = bwrap_args(work_dir, command, self.runtime)
        env = bwrap_env(self.runtime)
        account = pwd.getpwnam(self.run_as) if self.run_as else None

        def child_setup():
            resource.setrlimit(resource.RLIMIT_FSIZE, (2048 * 1024**2, 2048 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
            if account and os.getuid() == 0:
                os.setgroups([])
                os.setgid(account.pw_gid)
                os.setuid(account.pw_uid)

        timed_out = False
        cancelled = False
        last_tick = 0.0
        with log_path.open('wb') as log:
            process = subprocess.Popen(args, cwd=work_dir, stdout=log, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=True, preexec_fn=child_setup)
            try:
                while True:
                    code = process.poll()
                    if code is not None:
                        break
                    self.send_heartbeat()
                    if self.is_cancelled(job_id):
                        cancelled = True
                        os.killpg(process.pid, signal.SIGKILL)
                        code = process.wait()
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGKILL)
                        code = process.wait()
                        break
                    now_mono = time.monotonic()
                    tick_cb = getattr(self, '_stage_tick', None)
                    if callable(tick_cb) and now_mono - last_tick >= 1.8:
                        last_tick = now_mono
                        try:
                            tick_cb(log_path)
                        except Exception:
                            pass
                    time.sleep(1.0)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return code, timed_out, cancelled

    def process_job(self, job_id):
        raw_record = self.store.command('GET', self.job_key(job_id))
        if not raw_record:
            return None
        record = json.loads(raw_record)
        if record.get('status') not in {'queued', 'running'}:
            return record
        if self.is_cancelled(job_id):
            record.update(status='cancelled', source_url=None, notice='已按请求停止实验任务。')
            self.save_record(record)
            return record
        if time.time() > record.get('deadline', 0):
            record.update(status='expired', source_url=None, notice='队列任务已超过最长时限。')
            self.save_record(record)
            return record

        source_url = record.get('source_url')
        try:
            archive_bytes = self.fetcher(source_url, record.get('source_bytes'), record.get('source_sha256'))
        except Exception as exc:
            record.update(status='failed', source_url=None,
                          notice='执行器未能取回源码归档：' + type(exc).__name__,
                          result={'status': 'failed', 'stages': [], 'metrics': [], 'events': [],
                                  'execution_performed': False, 'scientific_validation': False,
                                  'failure_category': 'transient_service'})
            self.save_record(record)
            return record

        plan = record['plan']
        started = time.time()
        deadline = time.monotonic() + max(int(plan.get('max_seconds') or 0),
                                          record.get('deadline', time.time() + 86400) - time.time())
        report = {'status': 'running', 'started_at': started, 'stages': [], 'metrics': [],
                  'execution_performed': False, 'scientific_validation': False,
                  'hardware': {'cpu_count': self.capacity['cpu_count'], 'gpu': True,
                               'gpu_name': self.capacity.get('gpu_name')},
                  'events': []}

        def event(role, kind, **data):
            report['events'].append({'role': role, 'kind': kind, 'time': time.time(), **data})

        with tempfile.TemporaryDirectory(prefix='articheck-gpu-', dir=self.work_root) as tmp:
            base = Path(tmp)
            work_dir = base / 'artifact'
            results_dir = base / 'results'
            results_dir.mkdir(parents=True, exist_ok=True)
            extract_archive(archive_bytes, work_dir)
            (work_dir / '.cache').mkdir(parents=True, exist_ok=True)
            (work_dir / '.pydeps').mkdir(parents=True, exist_ok=True)
            if self.run_as and os.getuid() == 0:
                account = pwd.getpwnam(self.run_as)
                os.chown(base, account.pw_uid, account.pw_gid)
                base.chmod(0o700)
                for parent, dirs, files in os.walk(work_dir):
                    os.chown(parent, account.pw_uid, account.pw_gid)
                    for d in dirs:
                        os.chown(os.path.join(parent, d), account.pw_uid, account.pw_gid)
                    for f in files:
                        os.chown(os.path.join(parent, f), account.pw_uid, account.pw_gid)

            disk = shutil.disk_usage(work_dir)
            inferred_deps = infer_project_dependencies(work_dir)
            auto_candidates = sorted({pkg for mod, pkg in inferred_deps.items() if mod not in PREINSTALLED_RUNTIME_MODULES})
            provisioned_pkgs = []
            if auto_candidates and not self.is_cancelled(job_id):
                prep_log = results_dir / '_auto_deps.log'
                probe_json = json.dumps({m: p for m, p in inferred_deps.items() if m not in PREINSTALLED_RUNTIME_MODULES})
                prep_cmd = (
                    f"python -c 'import importlib.util, json, subprocess, sys; "
                    f"mapping = json.loads({ json.dumps(probe_json) }); "
                    f"missing = sorted({{pkg for mod, pkg in mapping.items() if importlib.util.find_spec(mod) is None}}); "
                    f"print(\"[ArtiCheck Auto-Env] Inferred imports:\", list(mapping.keys()), \"-> Missing packages:\", missing); "
                    f"sys.exit(subprocess.call([sys.executable, \"-m\", \"pip\", \"install\", \"--user\", \"--no-input\", \"--prefer-binary\", *missing]) if missing else 0)'"
                )
                try:
                    p_code, _, _ = self.run_stage_command(work_dir, prep_log, prep_cmd, min(deadline, time.monotonic() + 180), job_id)
                    if p_code == 0:
                        provisioned_pkgs = auto_candidates
                except Exception:
                    pass
            report['runtime'] = {'python': platform.python_version(), 'system': platform.system(),
                                 'release': platform.release(), 'architecture': platform.machine(),
                                 'gpu_name': self.capacity.get('gpu_name'),
                                 'disk_total_bytes': disk.total, 'disk_free_before_bytes': disk.free,
                                 'conda_env_created': False,
                                 'environment_kind': 'gpu_base_with_job_packages',
                                 'inferred_dependencies': sorted(set(inferred_deps.values())),
                                 'auto_provisioned_packages': provisioned_pkgs}
            event('planner', 'plan_scheduled', policy='frozen_api_plan', stages=len(plan['stages']), hardware='GPU')
            record.update(status='running', source_url=None,
                          notice='云端隔离执行器已接单，额外依赖安装到任务专用目录。',
                          result=report)
            self.save_record(record)

            all_logs = []
            stage_logs = {}
            cancelled = False
            failed_stage_id = None
            fail_fast = plan.get('fail_fast', True)
            for stage in plan['stages']:
                row = {k: stage[k] for k in ('id', 'title', 'command', 'file')}
                row['experiment'] = stage.get('experiment', '')
                dependencies = stage.get('depends_on', [report['stages'][-1]['id']] if report['stages'] else [])
                blocked = any(not any(s['id'] == d and s['status'] == 'completed' for s in report['stages']) for d in dependencies)
                if cancelled or self.is_cancelled(job_id):
                    cancelled = True
                    row.update(status='skipped', reason='任务已按请求停止。')
                    report['stages'].append(row)
                    continue
                if fail_fast and failed_stage_id:
                    row.update(status='skipped', reason=f'前序阶段 {failed_stage_id} 执行报错，已直接中断后续阶段。')
                    report['stages'].append(row)
                    continue
                if blocked or deadline <= time.monotonic():
                    row.update(status='skipped', reason='依赖阶段未完成。' if blocked else '时间预算已用尽。')
                    report['stages'].append(row)
                    continue
                row.update(status='running', started_at=time.time(), live_tail=[])
                report['stages'].append(row)
                event('experiment_runner', 'stage_started', stage=stage['id'])
                record['result'] = report
                self.save_record(record)

                log_path = results_dir / (stage['id'] + '.log')

                def on_stage_tick(cur_log_path, cur_row=row):
                    live_text, _ = read_bounded_log(cur_log_path)
                    if live_text:
                        cur_row['output'] = live_text
                        cur_row['live_tail'] = extract_live_tail(live_text)
                        record['result'] = report
                        self.save_record(record)

                self._stage_tick = on_stage_tick
                try:
                    code, timed_out, stage_cancelled = self.run_stage_command(
                        work_dir, log_path, stage['command'], deadline, job_id)
                finally:
                    self._stage_tick = None
                report['execution_performed'] = True
                log_text, truncated = read_bounded_log(log_path)
                if code != 0 and not timed_out and not stage_cancelled and not self.is_cancelled(job_id) and time.monotonic() < deadline:
                    missing_mods = parse_missing_modules_from_log(log_text)
                    req_conflict = bool(re.search(r'pip install.*-r\s+\S*requirements', stage['command'])) and bool(
                        re.search(r'(ResolutionImpossible|No matching distribution| Conflict|Cannot install|subprocess-exited-with-error)', log_text, re.I))
                    heal_pkgs = sorted(set(missing_mods.values()))
                    if not heal_pkgs and req_conflict and inferred_deps:
                        heal_pkgs = sorted(set(inferred_deps.values()))
                    if heal_pkgs:
                        heal_log = results_dir / (stage['id'] + '_autoheal.log')
                        pkg_args = ' '.join(heal_pkgs)
                        retry_cmd = stage['command']
                        if req_conflict and not missing_mods:
                            retry_cmd = f"python -m pip install --user --no-input --prefer-binary {pkg_args}"
                        else:
                            retry_cmd = f"python -m pip install --user --no-input --prefer-binary {pkg_args} && ({stage['command']})"
                        self._stage_tick = on_stage_tick
                        try:
                            code2, timed_out2, stage_cancelled2 = self.run_stage_command(
                                work_dir, heal_log, retry_cmd, deadline, job_id)
                        finally:
                            self._stage_tick = None
                        heal_text, heal_trunc = read_bounded_log(heal_log)
                        log_text = (log_text.rstrip() + f"\n\n[ArtiCheck 自动补齐依赖: {', '.join(heal_pkgs)}]\n" + heal_text)[-24000:]
                        truncated = truncated or heal_trunc
                        code, timed_out, stage_cancelled = code2, timed_out2, stage_cancelled2
                        provisioned_pkgs = sorted(set(provisioned_pkgs) | set(heal_pkgs))
                        report['runtime']['auto_provisioned_packages'] = provisioned_pkgs
                all_logs.append(log_text)
                stage_logs[stage['id']] = log_text
                live_tail = extract_live_tail(log_text)
                if stage_cancelled:
                    cancelled = True
                    row.update(status='skipped', exit_code=code, timed_out=False,
                               finished_at=time.time(), output=log_text, live_tail=live_tail,
                               output_truncated=truncated,
                               reason='任务已按请求停止。')
                else:
                    row.update(status='completed' if code == 0 and not timed_out else 'failed',
                               exit_code=code, timed_out=timed_out, finished_at=time.time(),
                               output=log_text, live_tail=live_tail, output_truncated=truncated)
                    if row['status'] == 'failed':
                        failed_stage_id = stage['id']
                row['child_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
                event('experiment_runner', 'stage_finished', stage=stage['id'], exit_code=code, timed_out=timed_out)
                event('cross_auditor', 'stage_checked', stage=stage['id'], status=row['status'])
                record['result'] = report
                self.save_record(record)

            report['metrics'] = evaluate_metrics(plan, stage_logs, all_logs)
            failed = any(s['status'] == 'failed' for s in report['stages'])
            if cancelled or self.is_cancelled(job_id):
                report['status'] = 'cancelled'
                record['notice'] = '实验执行已按请求停止。'
            elif all(s['status'] == 'completed' for s in report['stages']):
                report['status'] = 'completed'
                record['notice'] = '实验阶段计划已执行完毕。'
            else:
                report['status'] = 'failed'
                record['notice'] = f'阶段 {failed_stage_id or ""} 执行报错中断，请查看问题诊断与实际日志。'.strip()
            report['finished_at'] = time.time()
            report['elapsed_seconds'] = round(report['finished_at'] - started, 3)
            shutil.rmtree(work_dir, ignore_errors=True)
            report['runtime']['disk_free_after_bytes'] = shutil.disk_usage(base).free
            report['runtime']['workspace_cleaned'] = not work_dir.exists()
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            report['runtime']['child_cpu_seconds'] = round(usage.ru_utime + usage.ru_stime, 3)
            failure_logs = '\n'.join(s.get('output', '') for s in report['stages'] if s['status'] == 'failed')
            transient = failed and bool(re.search(
                r'((?:HTTP(?:\s+Error|/[\d.]+)?|status(?:\s+code)?)\s*[:=]?\s*429\b|429\s+(?:Client Error|Too Many Requests)|too many requests|rate.?limit|temporary failure|connection timed out)',
                failure_logs, re.I))
            report['failure_category'] = 'transient_service' if transient else 'execution_blocked' if failed else None
            report['needs_user'] = failed and not transient and bool(re.search(
                r'(file not found|filenotfound|no such file|permission denied|HTTP(?:\s+Error|/[\d.]+)?\s*[:=]?\s*(?:401|403)\b|credentials|download|dataset|checkpoint|cuda|out of memory|modulenotfounderror|importerror)',
                failure_logs, re.I))
            report['question'] = '自动下载或 GPU 执行遇到阻碍，请查看失败步骤日志。能否补充缺失的数据、权重或公开获取线索？' if report['needs_user'] else None
            report['acceptance'] = {'process': report['status'] == 'completed', 'paper_conclusion': None,
                                    'notice': '阶段退出码和 stdout 指标仅证明本次 GPU 运行观测；主要结论需核对完整协议与对照。'}
            event('planner', 'stopped', reason=report['status'], policy='frozen_api_plan')
            event('cross_auditor', 'execution_checked', metrics=len(report['metrics']))
            event('reporter', 'report_written', status=report['status'])
            record['status'] = report['status']
            record['result'] = report
            self.save_record(record)
            return record

    def poll_once(self):
        self.send_heartbeat()
        job_id = self.store.command('LPOP', self.prefix + 'queue')
        if not job_id:
            return None
        return self.process_job(job_id)

    def serve_forever(self, poll_interval=2.0):
        self.send_heartbeat(force=True)
        while True:
            try:
                worked = self.poll_once()
                if not worked:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                sys.stderr.write(f'[gpu_worker] error: {type(exc).__name__}: {exc}\n')
                sys.stderr.flush()
                time.sleep(min(10.0, poll_interval * 2))


def main():
    env_file = os.environ.get('ARTICHECK_GPU_ENV_FILE')
    env = dict(os.environ)
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env.setdefault(k.strip(), v.strip())
    worker = GPUWorker(env)
    if '--once' in sys.argv:
        worker.send_heartbeat(force=True)
        worker.poll_once()
    else:
        worker.serve_forever()


if __name__ == '__main__':
    main()
