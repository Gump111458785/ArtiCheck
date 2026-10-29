from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..environment import collect_environment
from ..schema import dump
from .audit import audit_plan
from .executor import StageExecutor
from .protocol import fingerprint, load_json, load_plan, relative_path, same_json
from .statistics import evaluate_experiment
from .verification import recompute_metric, verify_splits
from .acceptance import verify_training, verify_fairness, evaluate_levels
from .runtime_environment import daemon_snapshot, requirement_checks, inspect_image
from .monitor import ExternalMonitor
from .gpu_monitor import kernel_identity


def utc():
    return datetime.now(timezone.utc).isoformat()


def disk_bytes(root):
    # Output occupancy, not filesystem-wide usage or bytes of disk I/O.
    size = 0
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Experiment created a symlink; output collection stopped')
        if path.is_file():
            size += path.stat().st_size
    return size


def materialize(argv, repo, work, seed, variant, mode):
    values = {'repo': '/artifact' if mode == 'docker' else str(repo),
              'work': '/work' if mode == 'docker' else str(work),
              'config': '/work/config.json' if mode == 'docker' else str(work/'config.json'),
              'seed': str(seed), 'variant': variant}
    result = []
    for value in argv:
        for key, replacement in values.items():
            value = value.replace('{'+key+'}', replacement)
        result.append(value)
    return result


async def build_environment(plan, repo, output, *, mode, deadline, cancel=None):
    spec = plan['environment']
    if mode == 'local':
        return {'status': 'not_rebuilt', 'scope': 'explicitly trusted local fixture only', 'image': None}
    docker = shutil.which('docker')
    if not docker:
        raise RuntimeError('Docker unavailable; environment reconstruction not attempted')
    dockerfile = relative_path(repo, spec.get('dockerfile', 'Dockerfile'))
    # Build network stays disabled. A vendored wheelhouse/base image can supply pinned deps.
    iid = output/'environment-image-id.txt'
    argv = [docker, 'build', '--no-cache', '--network=none', '--pull=false', '--iidfile', str(iid), '-f', str(dockerfile), str(repo)]
    client = StageExecutor('local', allow_local_trusted=True)
    timeout = min(float(spec.get('build_timeout_seconds', 600)), max(.01, deadline-time.monotonic()))
    result = await client.execute(repo, output, argv, timeout=timeout, measurement=False, environment={'HOME': str(Path.home())}, cancel=cancel)
    dump(output/'environment-build.json', result)
    if result['status'] != 'completed' or not iid.is_file():
        return {'status': 'failed', 'log': 'environment-build.json', 'image': None}
    image = iid.read_text().strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Docker did not return an immutable image identity')
    return {'status': 'built', 'image': image, 'dockerfile_sha256': fingerprint(dockerfile)['sha256'],
            'network': 'none', 'cache': False, 'elapsed_seconds':result['elapsed_seconds'], 'log': 'environment-build.json'}


async def reproduce(plan_path, output, *, mode='docker', allow_local_trusted=False, workspace=None, cancel=None, imported=None):
    plan, source_repo, original_plan_sha = load_plan(plan_path, workspace, with_digest=True)
    if mode == 'local' and not allow_local_trusted:
        raise ValueError('Local mode requires explicit trust; Docker is required for third-party code')
    output = Path(output).resolve()
    if output == source_repo or output.is_relative_to(source_repo):
        raise ValueError('Run output must be outside the artifact repository')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Run output must be new/empty')
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + plan['resources'].get('max_seconds', 3600)
    report = {'format': 'articheck-reproduction-report-v1', 'run_id': uuid.uuid4().hex,
              'created_at': utc(), 'status': 'running', 'mode': mode, 'experiments': [], 'runs': [],
              'host': collect_environment(output), 'environment': None, 'errors': []}
    project_monitor=ExternalMonitor(output,disk_limit=plan['resources'].get('project_disk_limit_bytes'))
    project_monitor_task=asyncio.create_task(project_monitor.run())
    def save():
        report['elapsed_seconds'] = time.monotonic()-started
        dump(output/'report.json', report)
    def interrupted():
        return cancel is not None and cancel.is_set()
    try:
        audit = audit_plan(plan_path, workspace=workspace, imported=imported)
        report['audit'] = audit
        dump(output/'audit.json', audit)
        # No artifact execution when actual identity/data/config bytes contradict references.
        hard = [c for c in audit['checks'] if c['status'] == 'fail' and (c['dimension'] in ('code', 'data', 'settings', 'environment') or c['dimension'] == 'scope' and c['code'].startswith('file:'))]
        if hard:
            raise ValueError('Material verification failed before execution: '+', '.join(c['code'] for c in hard[:8]))
        # Freeze actual source bytes to separate execution from subsequent working-tree edits.
        snapshot = output/'source'
        shutil.copytree(source_repo, snapshot, symlinks=True, ignore=shutil.ignore_patterns('.git', '__pycache__', '.venv', 'node_modules'))
        for item in snapshot.rglob('*'):
            if item.is_symlink():
                raise ValueError('Source symlinks are not executable evidence')
        source_files = {p.relative_to(snapshot).as_posix(): fingerprint(p) for p in snapshot.rglob('*') if p.is_file()}
        dump(output/'source-files.json', source_files)
        snapshot_audit = audit_plan(plan_path, workspace=workspace, imported=imported, repo_override=snapshot)
        snapshot_failures = [c for c in snapshot_audit['checks'] if c['status'] == 'fail' and (c['dimension'] in ('code', 'data', 'settings', 'environment') or c['dimension'] == 'scope' and c['code'].startswith('file:'))]
        if snapshot_failures:
            raise ValueError('Copied snapshot no longer matches the verified materials')
        report['source_manifest_sha256'] = fingerprint(output/'source-files.json')['sha256']
        report['plan'] = plan
        report['plan_sha256'] = original_plan_sha
        if report['plan_sha256'] != audit['plan_sha256'] or hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()!=original_plan_sha:
            raise ValueError('Plan changed during source verification')
        save()
        daemon=await daemon_snapshot(shutil.which('docker')) if mode=='docker' and shutil.which('docker') else {'status':'not_applicable','source':'trusted local fixture'}
        report['executor']={'mode':mode,'daemon':daemon,'resource_limits':plan['resources'],
                            'requirements':requirement_checks(plan['resources'],daemon,shutil.disk_usage(output).free)}
        if any(c['status']=='fail' for c in report['executor']['requirements']):
            raise ValueError('Declared resource requirements exceed actual executor limits or available capacity')
        environment = await build_environment(plan, snapshot, output, mode=mode, deadline=deadline, cancel=cancel)
        report['environment'] = environment
        if interrupted():
            raise asyncio.CancelledError()
        if environment['status'] == 'failed':
            raise RuntimeError('Clean environment build failed; see environment-build.json')
        resources = plan['resources']
        executor = StageExecutor(mode, environment.get('image'), memory_bytes=resources.get('memory_bytes', 2*1024**3),
                                 cpus=resources.get('cpus', 1), gpu_devices=resources.get('gpu_devices'), disk_limit_bytes=resources.get('disk_limit_bytes'), allow_local_trusted=allow_local_trusted)
        verify = plan['environment'].get('verify', [])
        if mode == 'docker' and not verify:
            raise ValueError('Clean build requires explicit in-image environment verification commands')
        env_work = output/'environment-check'
        env_work.mkdir()
        checks = []
        for argv in verify:
            if interrupted() or time.monotonic() >= deadline:
                raise TimeoutError('Cancelled or total budget exhausted during environment verification')
            result = await executor.execute(snapshot, env_work, materialize(argv, snapshot, env_work, 0, 'environment', mode), timeout=min(60, deadline-time.monotonic()))
            checks.append(result)
            if result['status'] != 'completed':
                raise RuntimeError('In-image environment verification failed')
        dump(output/'environment-verification.json', checks)
        environment['verification'] = 'passed' if checks else 'not_verified'
        environment['compatibility']=await inspect_image(executor,snapshot,env_work,plan['environment'].get('expected',{}),min(60,max(.01,deadline-time.monotonic())),cancel)
        if environment['compatibility']['status']=='failed':
            raise ValueError('Actual image Python/package/CUDA environment contradicts the declared requirements')
        observed=environment['compatibility'].get('observed',{})
        if resources.get('gpu_devices'):
            executor.gpu_uuids=[d['uuid'] for d in observed.get('nvidia_devices',[]) if isinstance(d.get('uuid'),str)]
            host_kernel=kernel_identity();executor.same_kernel=bool(host_kernel and host_kernel==observed.get('kernel_identity_sha256'))
        save()
        for exp in plan['experiments']:
            rows = []
            config_source = relative_path(snapshot, exp['config']['path'])
            initial_config = load_json(config_source)
            for variant in exp['variants']:
                for seed in exp['seeds']:
                    if interrupted():
                        raise asyncio.CancelledError()
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Total experiment time budget exhausted')
                    work = output/'experiments'/exp['id']/variant['id']/str(seed)
                    work.mkdir(parents=True)
                    # Passed explicitly on every command; frozen and checked after each stage.
                    cfg = {**initial_config, 'seed': seed, 'variant': variant}
                    dump(work/'config.json', cfg)
                    config_digest = fingerprint(work/'config.json')['sha256']
                    row = {'experiment': exp['id'], 'variant': variant['id'], 'role': variant['role'], 'seed': seed,
                           'config_sha256': config_digest, 'configuration':cfg,
                           'execution_limits':{'image':environment.get('image'),'cpus':executor.cpus,'memory_bytes':executor.memory,'stage_timeouts':{s['id']:s.get('timeout_seconds',300) for s in exp['stages']}}, 'status': 'running', 'stages': [], 'metric': None}
                    rows.append(row); report['runs'].append(row)
                    passed = set()
                    for stage in exp['stages']:
                        if interrupted():
                            raise asyncio.CancelledError()
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Total experiment time budget exhausted')
                        if not set(stage.get('needs', [])).issubset(passed):
                            row['status'] = 'failed'; row['error'] = 'Dependency did not complete'; break
                        inputs = {}
                        for name in stage['inputs']:
                            origin, rel = (snapshot, name[5:]) if name.startswith('repo:') else (work, name)
                            inputs[name] = fingerprint(relative_path(origin, rel))
                        if stage.get('kind')=='train' and exp.get('split_ids') and not row.get('split_verification'):
                            row['status']='failed';row['error']='Generated splits must be verified before training';break
                        prior_models={}
                        training_spec=exp.get('training_evidence',{})
                        if training_spec.get('stage_id')==stage['id']:
                            for name in training_spec.get('model_outputs',[]):
                                candidate=relative_path(work,name,exists=False)
                                if candidate.exists():prior_models[name]=fingerprint(candidate)
                        argv = materialize(stage['argv'], snapshot, work, seed, variant['id'], mode)
                        result = await executor.execute(snapshot, work, argv,
                                    timeout=min(stage.get('timeout_seconds', 300), deadline-time.monotonic()),
                                    environment={'ARTICHECK_SEED': str(seed), 'ARTICHECK_VARIANT': variant['id'], 'ARTICHECK_CONFIG_SHA256': config_digest}, cancel=cancel)
                        result.update(id=stage['id'], kind=stage.get('kind'), argv=argv, input_fingerprints=inputs, output_fingerprints={})
                        row['stages'].append(result)
                        for name in stage['outputs']:
                            try:
                                result['output_fingerprints'][name] = fingerprint(relative_path(work, name))
                            except (OSError, ValueError) as error:
                                result['status'] = 'failed'; result['output_error'] = str(error)
                        for name,before in inputs.items():
                            if name in stage['outputs']:continue
                            origin,rel=(snapshot,name[5:]) if name.startswith('repo:') else (work,name)
                            try:
                                if fingerprint(relative_path(origin,rel))!=before:
                                    result['status']='failed';result['output_error']='Undeclared mutation of input: '+name
                            except (OSError,ValueError):
                                result['status']='failed';result['output_error']='Declared input removed: '+name
                        if stage.get('kind')=='train':row['training_inputs']={k:v for k,v in inputs.items() if k!='config.json'}
                        if fingerprint(work/'config.json')['sha256'] != config_digest:
                            result['status'] = 'failed'; result['output_error'] = 'Frozen run configuration was modified'
                        try:
                            if exp.get('split_ids') and all((work/item['path']).is_file() for item in exp['split_ids'].values()):
                                row['split_verification']=verify_splits(work,exp['split_ids'])
                            training=verify_training(work,exp,stage,cfg,prior_models,repo=snapshot,elapsed=result['elapsed_seconds']) if result['status']=='completed' else None
                            if training:row['training_evidence']=training
                        except (OSError,ValueError,KeyError) as error:
                            result['status']='failed';result['output_error']=str(error)
                        result['output_occupancy_bytes'] = disk_bytes(work)
                        dump(work/(stage['id']+'-execution.json'), result)
                        if result['status'] == 'cancelled':
                            row['status'] = 'cancelled'
                            raise asyncio.CancelledError()
                        if result['status'] != 'completed':
                            row['status'] = 'failed'; break
                        passed.add(stage['id'])
                        save()
                    if row['status'] == 'running':
                        try:
                            metric = load_json(relative_path(work, exp['metric']['path']))
                            value = metric
                            for key in exp['metric']['key'].split('.'):
                                value = value[key]
                            from .protocol import finite
                            row['metric'] = finite(value)
                            if exp.get('split_ids'):
                                row['split_verification'] = verify_splits(work, exp['split_ids'])
                            if exp['metric'].get('implementation'):
                                row['independent_metric'] = recompute_metric(snapshot, work, exp['metric'])
                                if abs(row['metric']-row['independent_metric']['value']) > 1e-12:
                                    raise ValueError('Artifact-reported metric disagrees with independent recomputation')
                                row['metric'] = row['independent_metric']['value']
                            if row.get('training_evidence'):
                                for name,expected in row['training_evidence']['model_fingerprints'].items():
                                    if fingerprint(relative_path(work,name))!=expected:raise ValueError('Trained model changed after its recorded training stage')
                                used=exp['training_evidence']['used_config_path']
                                if not same_json(load_json(relative_path(work,used)),cfg):raise ValueError('Used configuration changed after training')
                            row['metric_file'] = fingerprint(relative_path(work, exp['metric']['path']))
                            row['status'] = 'completed'
                        except (OSError, ValueError, KeyError, TypeError) as error:
                            row['status'] = 'failed'; row['error'] = str(error)
                    save()
            acceptance=evaluate_experiment(exp,rows)
            acceptance['fairness']=verify_fairness(exp,rows)
            if acceptance['fairness']['status']!='verified':
                acceptance['status']='inconclusive'
                for comparison in acceptance['comparisons']:
                    comparison['statistical_status']=comparison['status'];comparison['status']='inconclusive'
                    comparison['reason']='Predeclared control/data/selection conditions are not verified'
            report['experiments'].append(acceptance)
        # Final source integrity prevents mutations in explicit trusted local mode being overlooked.
        modified = [name for name, digest in source_files.items() if fingerprint(relative_path(snapshot, name)) != digest]
        if modified:
            raise ValueError('Artifact source snapshot mutated during execution: '+str(modified[:5]))
        report['status'] = 'completed' if all(r['status'] == 'completed' for r in report['runs']) else 'failed'
    except asyncio.CancelledError:
        report['status'] = 'cancelled'; report['errors'].append('Execution cancelled')
    except Exception as error:
        report['status'] = 'failed'; report['errors'].append(type(error).__name__+': '+str(error))
    finally:
        project_monitor.finished=True;project_monitor.stop.set();await project_monitor_task
        if project_monitor.report['disk_limit_exceeded']:
            report['status']='failed';report['errors'].append('Sampled project output exceeds declared disk budget')
        report['finished_at'] = utc()
        elapsed = time.monotonic()-started
        price = plan['resources'].get('price_per_hour_usd')
        from .protocol import finite
        try:
            price = finite(price, minimum=0) if price is not None else None
        except ValueError:
            price = None
        report['cost'] = {'price_per_hour_usd': price, 'compute_estimate_usd': elapsed/3600*price if price is not None else None,
                          'scope': 'wall-clock compute estimate at declared rate; not an invoice or total project cost'}
        stages = [s for row in report['runs'] for s in row['stages']]
        phase_seconds={'environment_build':(report.get('environment') or {}).get('elapsed_seconds',0),
                       'environment_checks':sum(c.get('elapsed_seconds',0) for c in locals().get('checks',[]))+(report.get('environment') or {}).get('compatibility',{}).get('execution',{}).get('elapsed_seconds',0),
                       'artifact_stages':sum(s.get('elapsed_seconds',0) for s in stages)}
        phase_seconds['audit_snapshot_monitor_orchestration']=max(0,elapsed-sum(phase_seconds.values()))
        report['cost'].update(phase_seconds=phase_seconds,phase_compute_estimate_usd={key:seconds/3600*price if price is not None else None for key,seconds in phase_seconds.items()},
                             excluded=['Downloads and base-image pull before this job','human review','storage and network billing'],pricing_source=plan['resources'].get('pricing_source','user-declared rate; not independently verified'))
        rss = [s['resources'].get('child_peak_rss_bytes') for s in stages if s.get('resources')]
        try:
            occupied = disk_bytes(output)
        except (OSError, ValueError) as error:
            occupied = None
            report['status'] = 'failed'
            report['errors'].append('Output collection: '+str(error))
        report['measurement'] = {'sampled_stage_count': len(rss), 'stage_count': len(stages), 'max_child_rss_bytes': max(rss) if rss else None,
                                 'output_occupancy_bytes': occupied, 'gpu_peak_memory_bytes': None,
                                 'limitations': ['Output occupancy is not peak disk usage.', 'getrusage is child-process instrumentation; GPU scope and sample coverage are reported separately.', 'Container cgroup fields are instrumentation reports, not a hostile-code attestation.']}
        external=[s['external_resources'] for s in stages if s.get('external_resources')]
        memory=[s['sampled_peak_container_memory_bytes'] for s in external if s.get('sampled_peak_container_memory_bytes') is not None]
        report['measurement']['external']={'source':'Client sampler outside artifact container','sampled_container_stages':len(memory),
            'sampled_peak_container_memory_bytes':max(memory) if memory else None,
            'sampled_peak_run_output_bytes':max((s.get('sampled_peak_output_bytes') or 0 for s in external),default=None),
            'scope':'Maximum sampled per-stage/per-run occupancy; not sum of concurrent runs or peak total project disk; raw samples coverage in each stage'}
        report['measurement']['project_output_sampling']=project_monitor.report
        gpu_peaks=[s['sampled_peak_gpu_process_total_bytes'] for s in external if s.get('sampled_peak_gpu_process_total_bytes') is not None]
        report['measurement'].update(gpu_peak_memory_bytes=max(gpu_peaks) if gpu_peaks else None,gpu_scope='Sampled container compute-process memory on selected NVIDIA UUIDs with matching host kernel; not allocator high-water mark. Unknown without complete attribution.')
        report['levels'],report['level_requirements']=evaluate_levels(plan,report.get('audit',{}),report.get('environment'),report['runs'],report['experiments'],report['status'])
        save()
    return report
