from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from articheck.reproduction import engine
from articheck.reproduction.engine import reproduce
from articheck.reproduction.roles import AUDIT_ROLE, ROLE_CATALOG, RoleTrace, load_role_events
from articheck.reproduction.protocol import DIMENSIONS
from articheck.reproduction.service import ReproductionService

from test_reproduction import fixture


def events(run_dir):
    return [json.loads(line) for line in (Path(run_dir)/'roles.jsonl').read_text().splitlines()]


class RoleCatalogTests(unittest.TestCase):
    def test_every_audit_dimension_has_one_owner_role(self):
        self.assertEqual(set(AUDIT_ROLE), set(DIMENSIONS))
        self.assertTrue(set(AUDIT_ROLE.values()) <= set(ROLE_CATALOG))
        self.assertEqual(len(ROLE_CATALOG), 6)

    def test_trace_failures_are_collected_instead_of_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = RoleTrace(Path(tmp)/'missing'/'roles.jsonl', 'run')
            self.assertIsNone(trace.emit('Planner', 'stop'))
            self.assertIsNone(RoleTrace(Path(tmp)/'roles.jsonl', 'run').emit('Unknown', 'x'))
            self.assertEqual(len(trace.errors), 1)
            self.assertEqual(trace.summary()['events'], 0)  # failed writes are reported, never counted
            self.assertEqual(len(trace.summary()['errors']), 1)
            ok = RoleTrace(Path(tmp)/'roles.jsonl', 'run')
            self.assertIsNone(ok.emit('Planner', 'stop', status='bogus'))
            self.assertEqual(ok.errors[0][:10], 'ValueError')

    def test_reader_skips_malformed_and_unknown_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'roles.jsonl'
            trace = RoleTrace(path, 'run')
            trace.emit('Reporter', 'report')
            with path.open('a') as handle:
                handle.write('not json\n'+json.dumps({'role': 'Someone', 'event': 'x'})+'\n')
            result = load_role_events(path)
            self.assertTrue(result['available'])
            self.assertEqual(len(result['events']), 1)
            self.assertEqual(result['skipped'], 2)
            self.assertFalse(load_role_events(Path(tmp)/'absent.jsonl')['available'])

    def test_reader_bounds_history_and_rejects_wrong_run_or_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'roles.jsonl'
            trace = RoleTrace(path, 'expected')
            for i in range(6): trace.emit('Planner', 'schedule_run', index=i)
            RoleTrace(path, 'other').emit('Reporter', 'report')
            with path.open('ab') as handle: handle.write(b'\xff\n')
            result = load_role_events(path, limit=2, run_id='expected')
            self.assertEqual([r['index'] for r in result['events']], [4, 5])
            self.assertEqual(result['skipped'], 2)
            self.assertTrue(all(r['policy'] == 'frozen_plan' for r in result['events']))


class ReproductionRoleTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_matrix_attributes_every_stage_to_a_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path, plan, repo = fixture(root)
            result = await reproduce(path, root/'run', mode='local', allow_local_trusted=True)
            self.assertEqual(result['status'], 'completed', result['errors'])
            rows = events(root/'run')
            self.assertEqual([r['seq'] for r in rows], list(range(1, len(rows)+1)))
            self.assertTrue(all(r['run_id'] == result['run_id'] and r['schema_version'] == 'articheck-role-trace-v1' for r in rows))
            self.assertEqual({r['role'] for r in rows}, set(ROLE_CATALOG))
            kinds = Counter((r['role'], r['event']) for r in rows)
            # fixture: 1 experiment x 3 variants x 5 seeds, 3 stages per run
            self.assertEqual(kinds[('Planner', 'schedule_run')], 15)
            self.assertEqual(kinds[('ExperimentRunner', 'stage')], 45)
            self.assertEqual(kinds[('CrossAuditor', 'stage_checks')], 45)
            self.assertEqual(kinds[('CrossAuditor', 'run_verdict')], 15)
            self.assertEqual(kinds[('CrossAuditor', 'experiment_acceptance')], 1)
            self.assertEqual(kinds[('Planner', 'stop')], 1)
            self.assertEqual((rows[-1]['role'], rows[-1]['event']), ('Reporter', 'report'))
            self.assertEqual(rows[-1]['levels'], result['levels'])
            self.assertEqual(result['roles']['events'], len(rows))
            self.assertEqual(result['roles']['policy']['Planner'], 'frozen_plan')
            self.assertEqual(result['roles']['errors'], [])
            # evidence references resolve to files the executor actually wrote
            for row in rows:
                for ref in row['evidence']:
                    self.assertTrue((root/'run'/ref.split('#')[0]).exists(), ref)
            stage = next(r for r in rows if r['event'] == 'stage' and r['stage'] == 'train')
            self.assertEqual(stage['run'], {'experiment': 'regression', 'variant': 'method', 'seed': 11})
            self.assertIn('training_evidence', next(r for r in rows if r['event'] == 'stage_checks' and r['stage'] == 'train')['checks'])

    async def test_material_mismatch_records_who_stopped_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path, plan, repo = fixture(root); (repo/'data.json').write_text('{}')
            result = await reproduce(path, root/'run', mode='local', allow_local_trusted=True)
            self.assertEqual(result['status'], 'failed')
            rows = events(root/'run')
            inspector = next(r for r in rows if r['role'] == 'CodeInspector' and r['event'] == 'audit')
            self.assertEqual(inspector['status'], 'fail')
            self.assertIn('file:data.json', inspector['failed'])
            self.assertFalse(any(r['role'] == 'ExperimentRunner' for r in rows))
            stop = next(r for r in rows if r['event'] == 'stop')
            self.assertEqual(stop['status'], 'fail'); self.assertIn('Material verification failed', stop['reason'])
            self.assertEqual(rows[-1]['role'], 'Reporter')

    async def test_broken_trace_does_not_change_execution_or_acceptance(self):
        class BrokenTrace(RoleTrace):
            def __init__(self, path, run_id):
                super().__init__(Path(path).parent/'no-such-dir'/'roles.jsonl', run_id)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path, plan, repo = fixture(root)
            baseline = await reproduce(path, root/'baseline', mode='local', allow_local_trusted=True)
            with patch.object(engine, 'RoleTrace', BrokenTrace):
                broken = await reproduce(path, root/'broken', mode='local', allow_local_trusted=True)
            self.assertEqual(broken['status'], baseline['status'])
            self.assertEqual(broken['levels'], baseline['levels'])
            self.assertEqual([r['metric'] for r in broken['runs']], [r['metric'] for r in baseline['runs']])
            self.assertEqual(broken['experiments'][0]['status'], baseline['experiments'][0]['status'])
            self.assertGreater(len(broken['roles']['errors']), 0)


class ServiceRoleTests(unittest.TestCase):
    def test_service_reads_role_trace_beside_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp)/'storage'
            service = ReproductionService(Path(tmp), storage)
            try:
                service.jobs['job'] = {'id': 'job', 'status': 'running'}
                with self.assertRaises(ValueError):
                    service.roles('other')
                self.assertFalse(service.roles('job')['available'])
                (storage/'job'/'run').mkdir(parents=True)
                RoleTrace(storage/'job'/'run'/'roles.jsonl', 'r1').emit('Planner', 'schedule_run', summary='E / m / seed 1')
                result = service.roles('job')
                self.assertTrue(result['available'])
                self.assertEqual(result['events'][0]['event'], 'schedule_run')
                self.assertEqual(set(result['catalog']), set(ROLE_CATALOG))
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
