"""Trusted CPU supervisor copied into each E2B VM, run as root without secrets.

Artifact commands run as the unprivileged `user`, with a bounded wall clock,
process count, file size and address space. Results are root-owned. Uploaded code
can still print arbitrary numbers: an observed stdout is not scientific truth.
"""
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


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(path)


def limits(address_space_mb=3072):
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024**2, 128 * 1024**2))
    if sys.platform.startswith('linux'):
        bound=max(3072,min(18432,int(address_space_mb))) * 1024**2
        resource.setrlimit(resource.RLIMIT_AS, (bound, bound))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_plan(plan, root, results, *, run_as='articheck'):
    root = Path(root); results = Path(results)
    started = time.time(); deadline = time.monotonic() + plan['max_seconds']
    report = {'status': 'running', 'started_at': started, 'stages': [], 'metrics': [],
              'execution_performed': False, 'scientific_validation': False,
              'hardware': {'cpu_count': os.cpu_count(), 'gpu': False}, 'events': []}
    disk=shutil.disk_usage(root)
    report['runtime']={'python':platform.python_version(),'system':platform.system(),
                       'release':platform.release(),'architecture':platform.machine(),
                       'disk_total_bytes':disk.total,'disk_free_before_bytes':disk.free}
    status_path = results / 'status.json'

    def event(role, kind, **data):
        report['events'].append({'role': role, 'kind': kind, 'time': time.time(), **data})

    event('planner', 'plan_scheduled', policy='frozen_api_plan', stages=len(plan['stages']))
    atomic(status_path, report)
    all_logs = [];stage_logs={}
    failed = False
    for stage in plan['stages']:
        row = {k: stage[k] for k in ('id', 'title', 'command', 'file')}
        row['experiment']=stage.get('experiment','')
        dependencies=stage.get('depends_on',[report['stages'][-1]['id']] if report['stages'] else [])
        blocked=any(not any(s['id']==d and s['status']=='completed' for s in report['stages']) for d in dependencies)
        if blocked or deadline <= time.monotonic():
            row.update(status='skipped', reason='依赖阶段未完成。' if blocked else '时间预算已用尽。')
            report['stages'].append(row)
            continue
        row.update(status='running', started_at=time.time())
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
                env={'PATH': '/home/articheck/venv/bin:/usr/local/bin:/usr/bin:/bin', 'HOME': '/home/articheck', 'LANG': 'C.UTF-8',
                     'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
                     'PYTHONUNBUFFERED': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'},
                start_new_session=True, preexec_fn=child_limits)
            report['execution_performed'] = True
            try:
                code = process.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
            finally:
                # Kill descendants left in the process group before the next stage.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        with log_path.open('rb') as stream:
            raw = stream.read(24000)
        log_text = raw.decode(errors='replace')
        all_logs.append(log_text)
        stage_logs[stage['id']]=log_text
        row.update(status='completed' if code == 0 and not timed_out else 'failed', exit_code=code,
                   timed_out=timed_out, finished_at=time.time(), output=log_text,
                   output_truncated=log_path.stat().st_size > len(raw))
        row['child_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        failed = row['status'] == 'failed'
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
