"""Role attribution for the frozen-plan reproduction engine.

The engine's stages are attributed to the same six roles used by short claim
checks.  This module only *records* which role performed which step; it never
decides anything.  In reproduction mode the Planner follows the frozen plan
(``policy: frozen_plan``) and the CrossAuditor's verdicts come from the
existing verification code.  Trace failures are collected in ``errors`` and
must never change execution or acceptance outcomes.
"""
from __future__ import annotations

import json
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 'articheck-role-trace-v1'

ROLE_CATALOG = {
    'LiteratureReader': 'Paper scope: identity, text origin, citations and experiment coverage',
    'CodeInspector': 'Material audit (code/data/environment/settings), source snapshot and integrity',
    'Planner': 'Frozen-plan scheduling: commands, resources, acceptance, run order and stop reason',
    'ExperimentRunner': 'Network-disabled environment build, in-image verification and stage execution',
    'CrossAuditor': 'Compatibility, mutation, split, training, metric recomputation and fairness checks',
    'Reporter': 'Layered acceptance levels and the final report',
}
ROLES = tuple(ROLE_CATALOG)

# Audit dimension -> role that owns its checks.
AUDIT_ROLE = {
    'scope': 'LiteratureReader',
    'code': 'CodeInspector', 'data': 'CodeInspector',
    'environment': 'CodeInspector', 'settings': 'CodeInspector',
    'commands': 'Planner', 'resources': 'Planner', 'acceptance': 'Planner',
}

STATUSES = ('ok', 'warn', 'fail', 'skipped')


def audit_status(checks):
    states = {c.get('status') for c in checks}
    if 'fail' in states:
        return 'fail'
    if states & {'unknown', 'review_required'}:
        return 'warn'
    return 'ok'


class RoleTrace:
    """Append-only JSONL log of role events for one reproduction run."""

    def __init__(self, path, run_id):
        self.path, self.run_id = Path(path), run_id
        self.seq, self.errors = 0, []
        self.counts = Counter()

    def emit(self, role, event, *, status='ok', summary=None, evidence=None, **fields):
        try:
            if role not in ROLE_CATALOG:
                raise ValueError('Unknown role: '+str(role))
            if status not in STATUSES:
                raise ValueError('Unknown role event status: '+str(status))
            seq = self.seq + 1
            row = {'schema_version': SCHEMA_VERSION, 'run_id': self.run_id, 'seq': seq,
                   'ts': datetime.now(timezone.utc).isoformat(), 'role': role, 'event': event,
                   'status': status, 'summary': summary, 'evidence': list(evidence or []), **fields}
            if role == 'Planner': row['policy'] = 'frozen_plan'
            if role == 'CrossAuditor': row['policy'] = 'rule_based'
            with self.path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)+'\n')
            self.seq = seq
            self.counts[(role, status)] += 1
            return row
        except Exception as error:  # Tracing must never alter execution.
            self.errors.append(type(error).__name__+': '+str(error))
            return None

    def emit_audit(self, audit, *, event='audit', evidence=('audit.json',)):
        groups = {}
        for check in audit.get('checks', []):
            role = AUDIT_ROLE.get(check.get('dimension'))
            if role:
                groups.setdefault(role, []).append(check)
        for role in ('LiteratureReader', 'CodeInspector', 'Planner'):
            checks = groups.get(role, [])
            tally = Counter(c.get('status') for c in checks)
            dims = sorted({c['dimension'] for c in checks})
            self.emit(role, event, status=audit_status(checks) if checks else 'skipped',
                      summary=f"{len(checks)} checks in {', '.join(dims) or 'no dimensions'}: "
                              + ', '.join(f'{k}={v}' for k, v in sorted(tally.items())),
                      evidence=evidence, dimensions=dims,
                      failed=[c['code'] for c in checks if c.get('status') == 'fail'][:20])

    def summary(self):
        per_role = {role: {} for role in ROLES}
        for (role, status), count in sorted(self.counts.items()):
            per_role[role][status] = count
        return {'format': SCHEMA_VERSION, 'trace': self.path.name, 'events': self.seq,
                'policy': {'Planner': 'frozen_plan', 'CrossAuditor': 'rule_based'},
                'counts': per_role, 'errors': list(self.errors)}


def load_role_events(path, *, limit=None, run_id=None):
    """Read a role trace; malformed lines are skipped and counted."""
    path = Path(path)
    if not path.is_file():
        return {'events': [], 'skipped': 0, 'available': False}
    events, skipped = deque(maxlen=limit), 0
    with path.open('rb') as handle:
        for line in handle:
            try:
                row = json.loads(line.decode('utf-8'))
                if (isinstance(row, dict) and row.get('role') in ROLE_CATALOG
                        and row.get('schema_version') == SCHEMA_VERSION
                        and row.get('status') in STATUSES
                        and (run_id is None or row.get('run_id') == run_id)):
                    events.append(row)
                else:
                    skipped += 1
            except (ValueError, TypeError):
                skipped += 1
    return {'events': list(events), 'skipped': skipped, 'available': True}
