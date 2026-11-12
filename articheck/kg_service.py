"""Review-Aware Scientific Contribution Graph (知识图谱) service.

Implements the structured Extraction -> Normalization -> Retrieval -> Pairwise Comparison ->
Human-in-the-Loop Verification & Graph View Builder pipeline specified in docs/功能1.md.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from threading import Lock
import time
import uuid
from urllib.parse import quote

from .kg_literature import KINDS, LIMITS, OpenAlex, OpenPDFSources, normalize_title, paper_reference, pdf_text_status, retrieve_public_methods, verify_public_fulltext, work_metadata
from .kg_pdfs import PaperPDFs, markdown_index
from .kg_methods import extract_contributions, method_key, retrieve_methods, synthesize
from .reproduction.paper_text import extract_paper
from .review_api import ReviewError, decode_material, now

KG_TTL = 30 * 86400
METHOD_REASONS = {
    'pending': '方法提取尚未完成，可重试。',
    'no_full_text': '暂未取得可读取的正文。可查看公开书目获取原文。',
    'insufficient_evidence': '现有正文片段不足以核实技术贡献。',
    'no_sub_contributions': '已核实主要贡献，正文未提供足以细分的独立依据。',
    'unavailable': '尚无可核实的方法证据，可尝试提取。',
}

FULLTEXT_LABELS = {
    'verified': '已核验正文',
    'download_failed': '开放原文下载失败，可重试',
    'unreadable_pdf': '原文无法提取正文，可能为扫描件',
    'identity_mismatch': '下载文件与书目标题无法核对',
    'no_full_text': '仅有书目，未取得可读开放原文',
    'not_checked': '仅有书目，正文待核验',
}


def _tokenize(text):
    import re
    raw = str(text or '').lower()
    tokens = set(re.findall(r'[a-z0-9][a-z0-9_+-]{1,24}|[\u4e00-\u9fff]{2,6}', raw))
    for ch in re.findall(r'[\u4e00-\u9fff]{2,}', raw):
        for i in range(len(ch) - 1):
            tokens.add(ch[i:i + 2])
    return tokens


def _similarity(a, b):
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return round(inter / max(1, union), 3)


def _support_level_from_report(report):
    if not report or not isinstance(report, dict):
        return 'UNVERIFIED', 'NOT_RUN'
    rv = report.get('review') or {}
    ex = report.get('execution') or {}
    status = report.get('status')
    if status in {'failed', 'cancelled'}:
        return 'UNVERIFIED', 'NOT_RUN'
    high_findings = any(f.get('severity') == 'high' for f in rv.get('findings', []))
    support = 'PARTIAL' if high_findings else 'UNVERIFIED'
    if ex.get('scientific_validation') is True and ex.get('status') == 'completed':
        return 'SUPPORTED', 'REPRODUCED'
    if ex.get('status') == 'completed':
        return support, 'PARTIAL'
    if ex.get('status') in {'failed', 'cancelled', 'expired'}:
        return support, 'FAILED'
    return support, 'NOT_RUN'


def extract_paper_graph_entry(project_payload, owner_id='anonymous'):
    """Build graph entries from available report fields and traceable evidence."""
    payload = project_payload
    report = payload.get('report') or {}
    review = report.get('review') or {}
    execution = report.get('execution') or {}
    source_id = report.get('id') or payload.get('project_id') or uuid.uuid4().hex
    paper_id = 'paper_' + hashlib.sha256(f'{owner_id}:{source_id}'.encode()).hexdigest()[:24]
    title = review.get('paper_title') or payload.get('paper_title') or payload.get('title') or '受审学术论文'
    support, reproduction = _support_level_from_report(report)
    review_status = {'SUPPORTED': 'PASS', 'PARTIAL': 'PARTIAL'}.get(support, 'UNREVIEWED')
    metrics = review.get('metrics') or []
    observations = {m['id']: m for m in execution.get('metrics', []) if m.get('id')}
    claims = []
    for index, metric in enumerate(metrics):
        claim_id = f'{paper_id}_metric_{index + 1}'
        observation = observations.get(metric.get('id')) or {}
        section = metric.get('reference') or ''
        value = f"{metric.get('value', '')} {metric.get('unit') or ''}".strip()
        evidence = []
        if metric.get('quote') and metric.get('page'):
            evidence.append({'id': claim_id + '_paper', 'evidence_type': 'TEXT',
                             'section': section, 'page': metric['page'], 'quote': metric['quote']})
        if observation.get('observed') is not None:
            evidence.append({'id': claim_id + '_run', 'evidence_type': 'EXECUTION',
                             'section': '执行观测', 'page': None,
                             'quote': f"{observation['observed']} {observation.get('unit') or ''}".strip()})
        claims.append({
            'id': claim_id, 'claim_type': 'PERFORMANCE',
            'claim_text': ' · '.join(str(v) for v in (metric.get('model'), metric.get('dataset'), metric.get('metric'), value) if v),
            'dataset': metric.get('dataset') or '', 'metric': metric.get('metric') or '',
            'reported_value': value, 'condition': metric.get('protocol') or '',
            'support_status': {'outside_tolerance': 'QUESTIONED', 'within_tolerance': 'SUPPORTED'}.get(observation.get('status'), 'UNVERIFIED'),
            'evidences': evidence, 'findings': [],
        })

    contributions = []
    for index, description in enumerate(review.get('paper_contributions') or []):
        if not isinstance(description, str) or not description.strip():
            continue
        contributions.append({
            'id': f'{paper_id}_contribution_{index + 1}', 'title': description.strip(),
            'summary': description.strip(), 'review_support_level': 'UNVERIFIED',
            'contribution_type': 'UNCLASSIFIED', 'claims': [],
            'details': [row for row in review.get('contribution_details', []) if row.get('index') == index + 1][:3],
        })
    if claims:
        contributions.append({
            'id': paper_id + '_reported_metrics', 'title': '论文报告的指标',
            'summary': '按审查报告整理的指标，待与各项贡献逐一关联。',
            'contribution_type': 'EMPIRICAL', 'claims': claims,
            'review_support_level': 'UNVERIFIED',
            'datasets': sorted({m['dataset'] for m in claims if m['dataset']}),
            'metrics': sorted({m['metric'] for m in claims if m['metric']}),
        })
    return {
        'id': paper_id, 'evidence_schema': 1, 'project_id': payload.get('project_id') or '', 'owner_id': owner_id,
        'title': title, 'authors': [], 'year': review.get('publication_year'),
        'venue': review.get('publication_venue') or '', 'direction': review.get('research_direction') or '',
        'doi': report.get('public_paper_identifier', '') if report.get('public_paper_identifier', '').startswith('10.') else '',
        'metadata_source': 'PDF' if any(review.get(key) for key in ('publication_year','publication_venue','research_direction')) else '',
        'arxiv_id': payload.get('arxiv_id') or '',
        'abstract': review.get('paper_abstract') or payload.get('paper_abstract') or '',
        'paper_sha256': (report.get('materials') or {}).get('paper'),
        'visibility': 'PRIVATE', 'source_type': payload.get('source_type') or 'USER_UPLOAD',
        'review_status': review_status, 'repro_status': reproduction, 'created_at': now(),
        'contributions': contributions, 'method_graph': review.get('method_graph') or [],
    }


def compare_contributions_pair(contrib_a, paper_a, contrib_b, paper_b, verified_overrides=None):
    """Prompt 2 & Prompt 3 implementation: Pairwise multi-dimensional contribution comparison
    and conflict verification with explicit evidence chains."""
    pair_id = f"cmp_{contrib_a['id']}__{contrib_b['id']}"
    ds_a = {d.lower() for d in (contrib_a.get('datasets') or [])}
    ds_b = {d.lower() for d in (contrib_b.get('datasets') or [])}
    shared_datasets = [d for d in (contrib_a.get('datasets') or []) if d.lower() in ds_b]

    m_a = {m.lower() for m in (contrib_a.get('metrics') or [])}
    m_b = {m.lower() for m in (contrib_b.get('metrics') or [])}
    shared_metrics = [m for m in (contrib_a.get('metrics') or []) if m.lower() in m_b]

    text_a = f"{paper_a.get('title')} {contrib_a.get('title')} {contrib_a.get('summary')} {contrib_a.get('method')} {' '.join(contrib_a.get('datasets') or [])}"
    text_b = f"{paper_b.get('title')} {contrib_b.get('title')} {contrib_b.get('summary')} {contrib_b.get('method')} {' '.join(contrib_b.get('datasets') or [])}"
    sim = _similarity(text_a, text_b)

    if paper_a['id'] == paper_b['id']:
        rel_type, conflict_type = 'COMPLEMENTARY', 'NONE'
        explanation = '两项贡献来自同一篇论文。'
    elif shared_datasets and shared_metrics:
        rel_type, conflict_type = 'SIMILAR', 'PARTIAL_OVERLAP'
        explanation = f"共享数据集 {', '.join(shared_datasets)} 和指标 {', '.join(shared_metrics)}。需核对实验协议和原文证据。"
    elif sim > 0.12:
        rel_type, conflict_type = 'SIMILAR', 'INSUFFICIENT_EVIDENCE'
        explanation = '文本有共同术语，需核对原文和实验条件。'
    else:
        rel_type, conflict_type = 'COMPLEMENTARY', 'INSUFFICIENT_EVIDENCE'
        explanation = '现有材料不足以判断两项贡献的关系。'
    overlap_score = sim
    verdict = 'NEEDS_MORE_EVIDENCE'

    override = (verified_overrides or {}).get(pair_id)
    user_verified = False
    if override:
        user_verified = True
        if override.get('decision') == 'confirm':
            rel_type = 'POTENTIAL_CONFLICT'
            verdict = 'CONFIRMED_CONFLICT'
        elif override.get('decision') == 'dismiss':
            rel_type = 'COMPLEMENTARY'
            conflict_type = 'NONE'
            verdict = 'REJECTED_CONFLICT'
        elif override.get('decision') == 'more_evidence':
            verdict = 'NEEDS_MORE_EVIDENCE'

    claim_a = (contrib_a.get('claims') or [{}])[0]
    claim_b = (contrib_b.get('claims') or [{}])[0]

    return {
        'id': pair_id,
        'source_id': contrib_a['id'],
        'target_id': contrib_b['id'],
        'source_paper_id': paper_a['id'],
        'target_paper_id': paper_b['id'],
        'source_title': contrib_a['title'],
        'target_title': contrib_b['title'],
        'source_paper_title': paper_a['title'],
        'target_paper_title': paper_b['title'],
        'relation_type': rel_type,
        'conflict_type': conflict_type,
        'verdict': verdict,
        'overlap_score': overlap_score,
        'confidence': None,
        'user_verified': user_verified,
        'user_note': (override or {}).get('note') or '',
        'shared_datasets': shared_datasets,
        'shared_metrics': shared_metrics,
        'explanation': explanation,
        'dimensions': [
            {
                'dimension': '研究问题 (Problem)',
                'source_value': contrib_a.get('problem') or '未声明',
                'target_value': contrib_b.get('problem') or '未声明',
                'alignment': 'HIGH_OVERLAP' if conflict_type in {'NOVELTY_OVERLAP', 'CONTRADICTORY_RESULT'} else 'COMPLEMENTARY'
            },
            {
                'dimension': '核心方法机制 (Method)',
                'source_value': contrib_a.get('method') or contrib_a.get('title'),
                'target_value': contrib_b.get('method') or contrib_b['title'],
                'alignment': 'NOVELTY_OVERLAP' if conflict_type == 'NOVELTY_OVERLAP' else 'DIFFERENT_APPROACH'
            },
            {
                'dimension': '数据集与评测协议 (Dataset & Protocol)',
                'source_value': ', '.join(contrib_a.get('datasets') or []) + f" ({claim_a.get('condition') or '标准协议'})",
                'target_value': ', '.join(contrib_b.get('datasets') or []) + f" ({claim_b.get('condition') or '标准协议'})",
                'alignment': 'SHARED_BENCHMARK' if shared_datasets else 'DIFFERENT_BENCHMARK'
            },
            {
                'dimension': '核心定量指标与方向 (Metric & Value)',
                'source_value': f"{claim_a.get('metric') or '主指标'}: {claim_a.get('reported_value') or '见正文'}",
                'target_value': f"{claim_b.get('metric') or '主指标'}: {claim_b.get('reported_value') or '见正文'}",
                'alignment': 'CONTRADICTORY' if conflict_type == 'CONTRADICTORY_RESULT' else 'COMPARABLE' if shared_metrics else 'INCOMPARABLE'
            },
            {
                'dimension': 'ArtiCheck 审查支持度 (Review Support)',
                'source_value': (contrib_a.get('review_support_level') or 'UNVERIFIED'),
                'target_value': (contrib_b.get('review_support_level') or 'UNVERIFIED'),
                'alignment': 'VERIFIED'
            },
            {
                'dimension': '方法局限与边界 (Limitations)',
                'source_value': contrib_a.get('limitations') or '未单独列出',
                'target_value': contrib_b.get('limitations') or '未单独列出',
                'alignment': 'COMPLEMENTARY'
            }
        ],
        'evidence_chain': {
            'source_quote': (claim_a.get('evidences') or [{}])[0].get('quote') or contrib_a.get('summary'),
            'target_quote': (claim_b.get('evidences') or [{}])[0].get('quote') or contrib_b.get('summary')
        }
    }


class KnowledgeGraphService:
    def __init__(self, env, store, reviewer=None, budget=None):
        self.env = env
        self.store = store
        self.reviewer = reviewer
        self.budget = budget
        self._mem_private = {}
        self._mem_layouts = {}
        self._mem_verifications = {}
        self._mem_literature = {}
        self._extraction_inflight = set()
        self._extraction_lock = Lock()
        self._memory_operations = {}
        self.literature = OpenAlex(env.get('OPENALEX_API_KEY', ''))
        self.open_pdf_sources = OpenPDFSources(env)
        self.pdfs = PaperPDFs(store)

    def _redis_get(self, key, default, *, permanent=False):
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            return default
        try:
            raw = self.store.command('GET', key)
            if raw and permanent:
                self.store.command('PERSIST', key)
            return json.loads(raw) if raw else default
        except Exception as exc:
            raise ReviewError('graph_storage_unavailable', '暂时无法读取图谱存储。', 503) from exc

    def _redis_set(self, key, value, *, permanent=False):
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            return False
        try:
            expiry = () if permanent else ('EX', str(KG_TTL))
            self.store.command('SET', key, json.dumps(value, ensure_ascii=False), *expiry)
            return True
        except Exception as exc:
            raise ReviewError('graph_storage_unavailable', '暂时无法保存图谱，请重试。', 503) from exc

    def _owner_hash(self, owner):
        return hashlib.sha256(str(owner or 'anon').encode()).hexdigest()[:24]

    def get_private_papers(self, owner):
        oh = self._owner_hash(owner)
        key = f"articheck:kg:private:{self.store.namespace}:{oh}"
        data = self._redis_get(key, None, permanent=True)
        if data is None:
            return list(self._mem_private.get(oh, []))
        self._mem_private[oh] = data
        return list(data)

    def save_private_papers(self, owner, papers):
        oh = self._owner_hash(owner)
        self._mem_private[oh] = papers
        key = f"articheck:kg:private:{self.store.namespace}:{oh}"
        self._redis_set(key, self._mem_private[oh], permanent=True)

    def get_verifications(self, owner):
        oh = self._owner_hash(owner)
        key = f"articheck:kg:verify:{self.store.namespace}:{oh}"
        data = self._redis_get(key, None)
        if data is None:
            return dict(self._mem_verifications.get(oh, {}))
        self._mem_verifications[oh] = data
        return dict(data)

    def save_verification(self, owner, comparison_id, decision, note=''):
        if decision not in {'confirm', 'dismiss', 'more_evidence'}:
            raise ReviewError('invalid_decision', '请选择有效的冲突复核结论（confirm / dismiss / more_evidence）。')
        oh = self._owner_hash(owner)
        current = self.get_verifications(owner)
        current[comparison_id] = {'decision': decision, 'note': str(note or '')[:500], 'updated_at': now()}
        self._mem_verifications[oh] = current
        key = f"articheck:kg:verify:{self.store.namespace}:{oh}"
        self._redis_set(key, current)
        return current[comparison_id]

    def get_layout(self, owner):
        oh = self._owner_hash(owner)
        key = f"articheck:kg:layout:{self.store.namespace}:{oh}"
        data = self._redis_get(key, None, permanent=True)
        if data is None:
            return dict(self._mem_layouts.get(oh, {}))
        self._mem_layouts[oh] = data
        return dict(data)

    def save_layout(self, owner, payload):
        oh = self._owner_hash(owner)
        if 'change' in payload:
            change = payload['change']
            if not isinstance(change, dict) or not isinstance(change.get('id'), str) or not 1 <= len(change['id']) <= 150:
                raise ReviewError('invalid_layout', '图谱节点标识无效。')
            node_id = change['id']
            if type(change.get('pinned')) is not bool or any(
                type(change.get(axis)) not in (int, float) or not -100000 <= change[axis] <= 100000 for axis in ('x','y')
            ):
                raise ReviewError('invalid_layout', '图谱节点布局无效。')
            position = {axis: change[axis] for axis in ('x','y')}
            key = f'articheck:kg:layout:{self.store.namespace}:{oh}'
            stamp = now()
            if getattr(self.store, 'url', '') and getattr(self.store, 'token', ''):
                script = """
local state=cjson.decode(redis.call('GET',KEYS[1]) or '{}')
state.positions=state.positions or {}
local n=0
for _ in pairs(state.positions) do n=n+1 end
if n>=500 and not state.positions[ARGV[1]] then return 0 end
state.positions[ARGV[1]]=cjson.decode(ARGV[2])
local pins={}
for _,id in ipairs(state.pinned or {}) do
    if id~=ARGV[1] then table.insert(pins,id) end
end
if ARGV[3]=='1' then table.insert(pins,ARGV[1]) end
state.pinned=pins
state.updated_at=ARGV[4]
redis.call('SET',KEYS[1],cjson.encode(state))
return 1
"""
                if self.store.command('EVAL', script, '1', key, node_id, json.dumps(position),
                                      '1' if change['pinned'] else '0', stamp) != 1:
                    raise ReviewError('layout_capacity', '图谱布局节点达到上限。', 409)
            else:
                state = self.get_layout(owner)
                positions = {**state.get('positions', {}), node_id: position}
                if len(positions) > 500:
                    raise ReviewError('layout_capacity', '图谱布局节点达到上限。', 409)
                pinned = [item for item in state.get('pinned', []) if item != node_id]
                if change['pinned']:
                    pinned.append(node_id)
                self._mem_layouts[oh] = {'positions': positions, 'pinned': pinned, 'updated_at': stamp}
            return {'saved': True}
        positions = payload.get('positions') or {}
        pinned = payload.get('pinned') or []
        if not isinstance(positions, dict) or not isinstance(pinned, list) or len(positions) > 500 or len(pinned) > 500:
            raise ReviewError('invalid_layout', '图谱布局格式不正确。')
        for position in positions.values():
            if not isinstance(position, dict) or any(
                type(position.get(axis)) not in (int, float) or not -100000 <= position[axis] <= 100000
                for axis in ('x', 'y')
            ):
                raise ReviewError('invalid_layout', '图谱节点坐标无效。')
        state = {
            'positions': positions,
            'pinned': [item for item in pinned if isinstance(item, str) and len(item) <= 150],
            'updated_at': now()
        }
        self._mem_layouts[oh] = state
        key = f"articheck:kg:layout:{self.store.namespace}:{oh}"
        self._redis_set(key, state, permanent=True)
        return state

    def owned_papers(self, owner):
        owner_id = self._owner_hash(owner)
        return [
            {**paper, 'visibility': 'PRIVATE'}
            for paper in self.get_private_papers(owner)
            if paper.get('owner_id') == owner_id and paper.get('evidence_schema') == 1
            and paper.get('source_type') == 'USER_UPLOAD'
        ]

    def ingest_project(self, owner, payload):
        entry = extract_paper_graph_entry(payload, owner_id=self._owner_hash(owner))
        papers = [paper for paper in self.owned_papers(owner) if paper['id'] != entry['id']]
        self.save_private_papers(owner, [*papers, entry])
        return self.build_graph_response(owner, focus_paper_id=entry['id'])

    def literature_state(self, owner):
        key = f'articheck:kg:literature:{self.store.namespace}:{self._owner_hash(owner)}'
        default = {'papers': {}, 'links': {}, 'matches': {}, 'choices': {}, 'method_links': {}}
        return key, copy.deepcopy(self._redis_get(key, self._mem_literature.get(key, default), permanent=True))

    def update_literature(self, owner, change, *, operation_key=None):
        # Compare-and-swap the raw value so simultaneous searches and reading edits merge.
        key = f'articheck:kg:literature:{self.store.namespace}:{self._owner_hash(owner)}'
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            with self._extraction_lock:
                if operation_key and self._memory_operations.get(operation_key):
                    raise ReviewError('graph_operation_closed', '此图谱操作已停止或已处理。', 409)
                _, state = self.literature_state(owner)
                change(state)
                self._mem_literature[key] = state
                if operation_key:
                    self._memory_operations[operation_key] = 'completed'
            return
        script = ("if #KEYS==2 and redis.call('EXISTS',KEYS[2])==1 then return -1 end; "
                  "if (redis.call('GET',KEYS[1]) or '')~=ARGV[1] then return 0 end; "
                  "redis.call('SET',KEYS[1],ARGV[2]); "
                  "if #KEYS==2 then redis.call('SET',KEYS[2],'completed','EX',300) end; return 1")
        keys = ('2', key, operation_key) if operation_key else ('1', key)
        for _ in range(4):
            raw = self.store.command('GET', key)
            state = json.loads(raw) if raw else {'papers': {}, 'links': {}, 'matches': {}, 'choices': {}, 'method_links': {}}
            change(state)
            result = self.store.command('EVAL', script, *keys, raw or '', json.dumps(state, ensure_ascii=False))
            if result == 1:
                return
            if result == -1:
                raise ReviewError('graph_operation_closed', '此图谱操作已停止或已处理。', 409)
        raise ReviewError('graph_changed', '文献条目正在更新，请重试。', 409)

    def graph_operation_key(self, owner, operation_id):
        if operation_id is None:
            return None
        if not isinstance(operation_id, str) or not re.fullmatch(r'[a-f0-9]{32}', operation_id):
            raise ReviewError('invalid_request_id', '图谱操作编号无效。')
        return f'articheck:kg:operation:{self.store.namespace}:{self._owner_hash(owner)}:{operation_id}'

    def cancel_graph_operation(self, owner, operation_id):
        key = self.graph_operation_key(owner, operation_id)
        if key is None:
            raise ReviewError('invalid_request_id', '图谱操作编号无效。')
        if getattr(self.store, 'url', '') and getattr(self.store, 'token', ''):
            self.store.command('SET', key, 'cancelled', 'NX', 'EX', '300')
            return {'status': self.store.command('GET', key)}
        with self._extraction_lock:
            self._memory_operations.setdefault(key, 'cancelled')
            return {'status': self._memory_operations[key]}

    def graph_progress(self, operation_key, phase=None):
        if not operation_key:
            return {}
        key = operation_key + ':progress'
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            return {}
        if phase:
            self.store.command('SET', key, phase, 'EX', '180')
            return {}
        return {'phase': self.store.command('GET', key)}

    def operation_checkpoint(self, operation_key):
        mutex = Lock()
        last_check = float('-inf')
        status = None

        def check():
            nonlocal last_check, status
            if operation_key is None:
                return
            with mutex:
                if time.monotonic() - last_check > .3:
                    last_check = time.monotonic()
                    if getattr(self.store, 'url', '') and getattr(self.store, 'token', ''):
                        status = self.store.command('GET', operation_key)
                    else:
                        status = self._memory_operations.get(operation_key)
                if status:
                    raise ReviewError('graph_operation_closed', '此图谱操作已停止或已处理。', 409)
        return check

    @contextmanager
    def public_work_slot(self, owner):
        owner_hash = self._owner_hash(owner)
        if not (getattr(self.store, 'url', '') and getattr(self.store, 'token', '')):
            with self._extraction_lock:
                active = getattr(self, '_public_work', set())
                if owner_hash in active or len(active) >= 3:
                    raise ReviewError('literature_busy', '文献任务已达到并发上限，请稍后重试。', 429)
                self._public_work = active
                active.add(owner_hash)
            try:
                yield
            finally:
                with self._extraction_lock:
                    active.remove(owner_hash)
            return
        key = f'articheck:kg:public-work:{self.store.namespace}'
        member = owner_hash + ':' + uuid.uuid4().hex
        script = """
local now=tonumber(redis.call('TIME')[1])
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now)
local active=redis.call('ZRANGE',KEYS[1],0,-1)
if #active>=3 then return 0 end
for _,item in ipairs(active) do
    if string.sub(item,1,string.len(ARGV[1])+1)==ARGV[1]..':' then return 0 end
end
redis.call('ZADD',KEYS[1],now+135,ARGV[2])
redis.call('EXPIRE',KEYS[1],135)
return 1
"""
        if self.store.command('EVAL', script, '1', key, owner_hash, member) != 1:
            raise ReviewError('literature_busy', '文献任务已达到并发上限，请稍后重试。', 429)
        try:
            yield
        finally:
            try:
                self.store.command('ZREM', key, member)
            except ReviewError:
                pass  # The lease expires after the request lifetime.

    def acquire_paper_pdf(self, owner, paper, deadline, *, progress=lambda phase: None):
        downloaded = []
        chunks, status = verify_public_fulltext(paper, self.literature, deadline, progress=progress,
                                               sources=self.open_pdf_sources,
                                               save_pdf=lambda raw, source: downloaded.append((raw, source)))
        file = self.pdfs.save(self._owner_hash(owner), downloaded[0][0], paper, downloaded[0][1]) if downloaded else None
        return chunks, status, file

    def methods_from_saved_pdf(self, owner, file, deadline):
        if time.monotonic()>=deadline:
            return []
        try:
            raw = self.pdfs.read(self._owner_hash(owner),file)
            with tempfile.TemporaryDirectory(prefix='articheck-saved-paper-') as directory:
                path=Path(directory)/'paper.pdf'
                path.write_bytes(raw)
                pages,_=extract_paper(path,timeout=max(1,min(12,deadline-time.monotonic())))
            return [{**row,**({'source_url':file['source']} if file.get('source') else {})}
                    for row in retrieve_methods(pages,query='architecture design algorithm implementation',limit=4)]
        except (OSError, ValueError):
            return []

    def paper_file_record(self, owner, paper_id):
        _, state = self.literature_state(owner)
        files = state.get('pdf_files', {})
        canonical = state['matches'].get(paper_id)
        if paper_id not in files and not canonical:
            own = next((paper for paper in self.owned_papers(owner) if paper['id']==paper_id),None)
            matches = [wid for wid,paper in state['papers'].items()
                       if own and normalize_title(paper['title'])==normalize_title(own['title'])]
            canonical = matches[0] if len(matches)==1 else None
        record = files.get(paper_id) or files.get(canonical)
        if not record or state['choices'].get(paper_id, {}).get('removed'):
            raise ReviewError('paper_file_missing','这篇论文尚未保存 PDF。',404)
        return record

    def paper_file(self, owner, paper_id, *, offset=0, size=None):
        record = self.paper_file_record(owner,paper_id)
        return self.pdfs.read(self._owner_hash(owner),record,offset=offset,size=size), record

    def paper_index(self, owner):
        _, state = self.literature_state(owner)
        papers = {**state['papers'], **{paper['id']:paper for paper in self.owned_papers(owner)}}
        files = state.get('pdf_files', {})
        attempts = state.get('pdf_attempts', {})
        return markdown_index((paper, ('已下载' if files[wid].get('source') else '已插入') if files.get(wid) else FULLTEXT_LABELS.get(attempts.get(wid) or paper.get('fulltext_status'),'未获取'),
                               files.get(wid)) for wid, paper in papers.items()
                              if not state['choices'].get(wid, {}).get('removed'))

    def import_public_paper(self, owner, reference):
        if not isinstance(reference,str) or not reference.strip() or len(reference)>600:
            raise ReviewError('invalid_paper_reference','请填写论文标题、DOI、arXiv ID 或论文链接。')
        try:
            kind, value = paper_reference(reference)
        except ValueError as exc:
            raise ReviewError('invalid_paper_reference','论文链接格式无效。') from exc
        deadline = time.monotonic()+38
        edition = self.open_pdf_sources.arxiv(identifier=value, deadline=deadline) if kind=='arxiv' else {}
        semantic = self.open_pdf_sources.semantic(reference='URL:'+value,deadline=deadline) if kind=='url' else {}
        if kind=='url' and not semantic.get('title'):
            raise ReviewError('literature_unmatched','未能从链接识别论文，请输入标题、DOI 或 arXiv ID。',404)
        title = edition.get('title') or semantic.get('title') or (value if kind=='title' else '')
        doi = edition.get('doi') or (semantic.get('externalIds') or {}).get('DOI') or (value if kind=='doi' else '')
        if kind=='arxiv' and not doi:
            doi='10.48550/arxiv.'+re.sub(r'v[0-9]+$','',value)
        try:
            raw = self.literature.identify(title=title, doi=doi, identifier=value if kind=='openalex' else '')
            paper = work_metadata(raw)
        except ReviewError:
            if not edition:
                raise
            paper = {**edition,'id':'P'+hashlib.sha256(value.encode()).hexdigest()[:20],
                     'pdf_sources':[],'authors':[]}

        if not paper:
            raise ReviewError('literature_unmatched','未能定位论文书目。',404)
        if kind=='arxiv':
            paper['arxiv_id']=value
        _, state = self.literature_state(owner)
        prior = state['papers'].get(paper['id'],{})
        if not prior and len(state['papers'])>=75:
            raise ReviewError('literature_capacity','图谱的公开条目已达上限，请先移除部分条目。',409)
        file = state.get('pdf_files',{}).get(paper['id'])
        status = 'verified' if file else 'not_checked'
        if not file:
            _, status, file = self.acquire_paper_pdf(owner,paper,deadline)
        def save(current):
            if paper['id'] not in current['papers'] and len(current['papers'])>=75:
                raise ReviewError('literature_capacity','图谱的公开条目已达上限，请先移除部分条目。',409)
            existing = current['papers'].get(paper['id'],prior)
            current['papers'][paper['id']]={**existing,**paper,'fulltext_status':status}
            if file:
                current['papers'][paper['id']].update(self.method_fields(existing.get('contributions',[]),'pending'))
            current['choices'].setdefault(paper['id'],{}).pop('removed',None)
            if file:
                current.setdefault('pdf_files',{})[paper['id']]=file
        self.update_literature(owner,save)
        return {**self.build_graph_response(owner,focus_paper_id=paper['id']),
                'method_notice': '' if file else FULLTEXT_LABELS.get(status,'开放 PDF 暂不可用。')}

    def discover_literature(self, metadata, groups, *, kinds, depth, total, state, deadline, check=lambda: None):
        anchor = metadata['id']
        papers, links = {}, {}
        frontier = [(metadata, groups)]

        def neighborhood(paper):
            check()
            if time.monotonic() >= deadline:
                return paper, {}
            try:
                return self.literature.neighborhood(title=paper['title'], identifier=paper['id'],
                                                    kinds=set(kinds), limit=min(5, total))
            except ReviewError as error:
                if error.code == 'graph_operation_closed':
                    raise
                return paper, {}

        for level in range(depth):
            check()
            candidates = []
            for source, group in frontier:
                ordered = [group[kind] for kind in kinds if kind in group]
                for rank in range(max(map(len, ordered), default=0)):
                    for kind in kinds:
                        items = group.get(kind, [])
                        if rank < len(items):
                            candidates.append((source['id'], kind, items[rank]))
            next_papers = []
            allowance = max(1, (total - len(papers)) // (depth - level))
            for source, kind, target in candidates:
                wid = target['id']
                if wid == source or state['choices'].get(wid, {}).get('removed'):
                    continue
                if wid != anchor and wid not in papers:
                    if len(next_papers) >= allowance or len(papers) >= total:
                        continue
                    papers[wid] = target
                    next_papers.append(target)
                links[(source, kind, wid)] = (source, kind, wid)
            if level + 1 == depth or not next_papers or len(papers) >= total or time.monotonic() >= deadline:
                break
            with ThreadPoolExecutor(max_workers=min(3, len(next_papers))) as pool:
                frontier = list(pool.map(neighborhood, next_papers))
        return papers, list(links.values())

    def expand_literature(self, owner, paper_id, *, kinds, limit, depth=1, total=None, operation_id=None):
        if not isinstance(kinds, list) or any(not isinstance(kind, str) or kind not in KINDS for kind in kinds):
            raise ReviewError('invalid_literature_kind', '请选择需要查找的研究关系。')
        kinds = list(dict.fromkeys(kinds))
        if type(depth) is not int or depth not in {1, 2, 3}:
            raise ReviewError('invalid_literature_depth', '请选择一至三级扩展。')
        if total is not None and (type(total) is not int or not 3 <= total <= 15):
            raise ReviewError('invalid_literature_total', '新增论文上限为 3 至 15 篇。')
        if type(limit) is not int or limit not in LIMITS:
            raise ReviewError('invalid_literature_limit', '请选择每类 3、5 或 8 篇。')
        _, state = self.literature_state(owner)
        own = {paper['id']: paper for paper in self.owned_papers(owner)}
        paper = own.get(paper_id) or state['papers'].get(paper_id)
        if not paper or state['choices'].get(paper_id, {}).get('removed'):
            raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
        operation_key = self.graph_operation_key(owner, operation_id)
        check = self.operation_checkpoint(operation_key)
        check()
        deadline = time.monotonic() + 38
        self.graph_progress(operation_key, 'searching')
        metadata, groups = self.literature.neighborhood(
            title=paper['title'], identifier=state['matches'].get(paper_id, paper_id if paper_id in state['papers'] else ''),
            doi=paper.get('doi', ''), kinds=set(kinds), limit=limit,
        )

        anchor = metadata['id']
        if depth == 1 and total is None:
            discovered = {item['id']: item for items in groups.values() for item in items
                          if item['id'] != anchor and not state['choices'].get(item['id'], {}).get('removed')}
            links = [(anchor, kind, item['id']) for kind, items in groups.items() for item in items
                     if item['id'] in discovered]
        else:
            discovered, links = self.discover_literature(metadata, groups, kinds=kinds, depth=depth,
                total=total or 10, state=state, deadline=deadline, check=check)
        available = {anchor: metadata, **discovered}
        existing = {
            wid: [row for row in state['papers'].get(wid, {}).get('contributions', []) if row.get('method_grounded')]
            for wid in available
        }
        for wid, record in available.items():
            matches = [item for item in own.values()
                       if state['matches'].get(item['id']) == wid or
                       normalize_title(item['title']) == normalize_title(record['title'])]
            if wid == anchor and paper_id in own:
                matches = [paper]
            if len(matches) == 1 and matches[0].get('method_graph'):
                existing[wid] = matches[0]['method_graph']
            if len(matches) == 1:
                methods = state.get('private_methods', {}).get(matches[0]['id'], {}).get('contributions', [])
                existing[wid] = self.merge_contributions(methods, existing[wid])
        check()
        inputs = [{'id': wid, 'title': item['title'], 'chunks': [], 'existing': existing[wid]}
                  for wid, item in available.items() if existing[wid]]
        with_evidence = {row['id'] for row in inputs}
        saved_pairs = {self.link_key(row['left_paper'], row['right_paper'])
                       for row in state.get('method_links', {}).values()}
        pairs = list(dict.fromkeys(tuple(sorted((source, target))) for source, _, target in links
                     if source in with_evidence and target in with_evidence
                     and self.link_key(source, target) not in saved_pairs))[:30]
        analysis_error = ''
        try:
            if pairs:
                self.graph_progress(operation_key, 'extracting')
            _, relationships = synthesize(self.reviewer, self.budget, inputs, pairs)
        except (ReviewError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
            relationships = []
            analysis_error = ('本轮模型额度已用完。已保留公开书目。'
                              if isinstance(error, ReviewError) and error.code == 'budget_exhausted'
                              else '方法分析暂未完成。已保留公开书目，可重试扩展。')

        def save(current):
            if current['choices'].get(paper_id, {}).get('removed'):
                raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
            identifier = metadata['id']
            current['matches'][paper_id] = identifier
            files = current.setdefault('pdf_files', {})
            if identifier in files:
                files.setdefault(paper_id,files[identifier])
            for wid, item in available.items():
                if not current['choices'].get(wid, {}).get('removed'):
                    prior = current['papers'].get(wid, {})
                    metadata_fields = {key: value for key, value in item.items() if key != 'contributions'}
                    current['papers'][wid] = {**prior, **metadata_fields}
            for origin, kind, target in links:
                if any(current['choices'].get(wid, {}).get('removed') for wid in (origin, target)):
                    continue
                source, destination = (target, origin) if kind == 'previous' else (origin, target)
                if kind == 'similar':
                    source, destination = sorted((origin, target))
                key = f'{kind if kind == "similar" else "citation"}:{source}:{destination}'
                current['links'][key] = {'source': source, 'target': destination,
                                         'kind': 'similar' if kind == 'similar' else 'citation',
                                         **({'depth': depth} if depth > 1 else {})}
            methods = current.setdefault('method_links', {})
            for relation in relationships:
                relation = self.with_relation_evidence(relation, existing)
                a, b = sorted(((relation['left_paper'], relation['left_id']),
                               (relation['right_paper'], relation['right_id'])))
                if any(current['choices'].get(wid, {}).get('removed') for wid, _ in (a, b)):
                    continue
                methods[':'.join((*a, *b))] = relation
            if len(methods) > 300:
                raise ReviewError('literature_capacity', '图谱的贡献关系已达上限，请先移除部分节点。', 409)
            if len(current['papers']) > 75 or len(current['links']) > 300:
                raise ReviewError('literature_capacity', '图谱的公开条目或关系已达上限，请先移除部分条目。', 409)

        self.update_literature(owner, save, operation_key=operation_key)
        return {**self.build_graph_response(owner, focus_paper_id=paper_id), 'method_notice': analysis_error}

    @staticmethod
    def method_fields(contributions, status):
        detail_count = sum(len(row.get('details', [])) for row in contributions)
        detail_status = 'grounded' if detail_count else status
        return {'method_status': 'grounded' if contributions else status, 'method_detail_status': detail_status,
                'method_reason': METHOD_REASONS.get(detail_status, ''), 'detail_count': detail_count}

    @contextmanager
    def extraction_slot(self, owner, paper_id):
        key = f'articheck:kg:extract:{self.store.namespace}:{self._owner_hash(owner)}:{paper_id}'
        redis = getattr(self.store, 'url', '') and getattr(self.store, 'token', '')
        token = uuid.uuid4().hex
        if redis:
            acquired = self.store.command('SET', key, token, 'NX', 'EX', '110') == 'OK'
        else:
            with self._extraction_lock:
                acquired = key not in self._extraction_inflight
                self._extraction_inflight.add(key)
        if not acquired:
            raise ReviewError('contribution_extraction_active', '这篇论文正在提取贡献，请稍后刷新。', 409)
        try:
            yield
        finally:
            if redis:
                script = "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0"
                try:
                    self.store.command('EVAL', script, '1', key, token)
                except ReviewError:
                    pass  # The lease still expires if the storage connection drops.
            else:
                with self._extraction_lock:
                    self._extraction_inflight.discard(key)

    @staticmethod
    def merge_contributions(existing, extracted):
        rows = {method_key(row): row for row in existing}
        titles = {row['title'].casefold() for row in existing}
        for row in extracted:
            key = method_key(row)
            if key in rows:
                old = rows[key]
                details = {method_key(item): item for item in old.get('details', []) + row.get('details', [])}
                rows[key] = {**old, 'summary': row.get('summary') or old.get('summary') or old['title'],
                             'details': list(details.values())[:2]}
            elif len(rows) < 3 and row['title'].casefold() not in titles:
                rows[key] = {**row, 'local_id': key}
                titles.add(row['title'].casefold())
        return list(rows.values())

    def retry_contributions(self, owner, paper_id, material=None, *, operation_id=None):
        operation_key = self.graph_operation_key(owner, operation_id)
        check = self.operation_checkpoint(operation_key)
        check()
        _, state = self.literature_state(owner)
        own = next((paper for paper in self.owned_papers(owner) if paper['id'] == paper_id), None)
        public = state['papers'].get(state['matches'].get(paper_id, paper_id))
        if state['choices'].get(paper_id, {}).get('removed') or not (own or public):
            raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
        paper = own or public
        storage = 'private_methods' if own else 'papers'
        cached = state.get(storage, {}).get(paper_id, {})
        existing = cached.get('contributions') or paper.get('method_graph') or []
        existing = [{**row, 'local_id': method_key(row)} for row in existing if row.get('method_grounded')]
        notice = ''
        file = None
        fulltext_status = cached.get('fulltext_status', 'not_checked')
        with self.extraction_slot(owner, paper_id):
            if material is not None:
                pdf, identity = decode_material(material, '.pdf', 20 * 1024**2)
                if own and identity['sha256'] != own.get('paper_sha256'):
                    raise ReviewError('paper_changed', 'PDF 与审查时的文件不一致。', 409)
                try:
                    with tempfile.TemporaryDirectory(prefix='articheck-kg-method-') as directory:
                        path = Path(directory) / 'paper.pdf'
                        path.write_bytes(pdf)
                        pages, _ = extract_paper(path, timeout=14)
                except (OSError, ValueError) as error:
                    raise ReviewError('literature_fulltext_required', FULLTEXT_LABELS['unreadable_pdf'], 422) from error
                chunks = retrieve_methods(pages, query='architecture design algorithm implementation')
                fulltext_status = 'verified' if own and chunks else pdf_text_status(pages, paper['title'])
                if fulltext_status != 'verified':
                    raise ReviewError('literature_fulltext_required', FULLTEXT_LABELS[fulltext_status], 422)
                status = 'pending' if chunks else 'insufficient_evidence'
                file = self.pdfs.save(self._owner_hash(owner),pdf,public or paper)
            elif (saved := state.get('pdf_files',{}).get(paper_id) or
                  (state.get('pdf_files',{}).get(public['id']) if public else None)):
                chunks = self.methods_from_saved_pdf(owner,saved,time.monotonic()+20)
                fulltext_status, status = 'verified', 'pending' if chunks else 'insufficient_evidence'
            elif isinstance(self.literature, OpenAlex):
                if not public:
                    try:
                        public = work_metadata(self.literature.identify(title=paper['title'], doi=paper.get('doi', '')))
                    except ReviewError:
                        pass  # Other open-access providers can still look up the title or DOI.
                check()
                chunks, fulltext_status, file = self.acquire_paper_pdf(owner, public or paper, time.monotonic()+28)
                status = ('pending' if chunks else 'insufficient_evidence') if fulltext_status == 'verified' else fulltext_status
                notice = FULLTEXT_LABELS.get(fulltext_status, '') if fulltext_status != 'verified' else ''
            elif public:
                chunks, status = retrieve_public_methods([public], paper['title'], self.literature,
                                                          include_status=True, **({'check': check} if operation_key else {}))[public['id']]
            else:
                chunks, status = [], 'no_full_text'
                notice = '请从审查项目重新提供原始 PDF，以提取方法贡献。'

            check()
            extracted = []
            if chunks and self.reviewer and self.reviewer.configured and self.budget:
                try:
                    extracted = extract_contributions(self.reviewer, self.budget, title=paper['title'],
                                                      chunks=chunks, existing=existing)
                    status = 'no_sub_contributions' if (existing or extracted) else 'insufficient_evidence'
                except (ReviewError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
                    notice = str(error) if isinstance(error, ReviewError) else METHOD_REASONS['pending']

            def save(current):
                if current['choices'].get(paper_id, {}).get('removed'):
                    raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
                if file:
                    current.setdefault('pdf_files', {})[paper_id] = file
                    if public and public['id'] in current['papers']:
                        current['pdf_files'].setdefault(public['id'],file)
                if not file and fulltext_status not in {'verified', 'not_checked'}:
                    current.setdefault('pdf_attempts', {})[paper_id] = fulltext_status
                bucket = current.setdefault(storage, {})
                record = bucket.get(paper_id, {})
                contributions = self.merge_contributions(record.get('contributions') or existing, extracted)
                if record.get('fulltext_status') == 'verified':
                    fulltext = 'verified'
                else:
                    fulltext = fulltext_status
                bucket[paper_id] = {**record, 'contributions': contributions, 'fulltext_status': fulltext,
                                    **self.method_fields(contributions, status)}

            self.update_literature(owner, save, operation_key=operation_key)
        return {**self.build_graph_response(owner, focus_paper_id=paper_id), 'method_notice': notice}

    @staticmethod
    def link_key(source, target):
        return ':'.join(sorted((source, target)))

    @staticmethod
    def with_relation_evidence(relation, methods):
        evidence = []
        for side in ('left', 'right'):
            match = next((row for row in methods.get(relation[f'{side}_paper'], [])
                          if (row.get('method_id') or method_key(row)) == relation[f'{side}_id']), None)
            if match:
                evidence.append({key: match.get(key) for key in ('quote', 'page', 'section', 'source_url')})
        return {**relation, 'evidence': evidence}

    def edit_relation(self, owner, source, target, action, note='', label=''):
        if action not in ('add', 'remove') or source == target:
            raise ReviewError('invalid_relation', '请选择两个不同的节点及关系操作。')
        if not isinstance(note, str) or len(note) > 360:
            raise ReviewError('invalid_relation_note', '关系说明最多 360 字。')
        if not isinstance(label, str) or len(label) > 48:
            raise ReviewError('invalid_relation_label', '关系名称最多 48 字。')
        graph = self.build_graph_response(owner)
        nodes = {node['id']: node for node in graph['nodes']}
        left, right = nodes.get(source), nodes.get(target)
        if not left or not right:
            raise ReviewError('node_not_found', '当前图谱没有这个节点。', 404)
        if (left['node_type'] == 'Paper') != (right['node_type'] == 'Paper'):
            raise ReviewError('invalid_relation_nodes', '请连接两篇论文或两个贡献节点。')
        key = self.link_key(source, target)

        def save(state):
            overrides = state.setdefault('relation_overrides', {})
            if key not in overrides and len(overrides) >= 1000:
                raise ReviewError('relation_capacity', '手动关系记录已达到上限。', 409)
            overrides[key] = {'source': source, 'target': target, 'action': action,
                              'note': note.strip(), 'label': label.strip(), 'updated_at': now()}

        self.update_literature(owner, save)
        return self.build_graph_response(owner, focus_paper_id=left.get('paper_id', source))

    def verify_related(self, owner, paper_id):
        graph = self.build_graph_response(owner, focus_paper_id=paper_id)
        nodes = {node['id']: node for node in graph['nodes']}
        if nodes.get(paper_id, {}).get('node_type') != 'Paper':
            raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
        _, library = self.literature_state(owner)
        methods = {}
        canonical = {}
        for node in nodes.values():
            if node['node_type'] == 'Contribution':
                key = node['canonical_paper']
                canonical[node['paper_id']] = key
                methods.setdefault(key, []).append({
                    'local_id': node['method_id'], 'method_id': node['method_id'], 'title': node['label'], 'quote': node['quote'],
                    'section': node['section'], 'page': node['page'],
                })
        anchor = canonical.get(paper_id)
        if not anchor or not self.reviewer or not self.reviewer.configured or not self.budget:
            return graph
        signatures = {}
        existing_pairs = {self.link_key(canonical.get(row['left_paper'], row['left_paper']),
                                        canonical.get(row['right_paper'], row['right_paper']))
                          for row in library.get('method_links', {}).values()}
        reviewed = library.get('verified_pairs', {})
        overrides = library.get('relation_overrides', {})
        candidates = []
        for other_paper, other in canonical.items():
            if other == anchor or overrides.get(self.link_key(paper_id, other_paper), {}).get('action') == 'remove':
                continue
            pair = self.link_key(anchor, other)
            if pair in existing_pairs:
                continue
            signature = hashlib.sha256(json.dumps([methods[key] for key in sorted((anchor, other))],
                                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if reviewed.get(pair) == signature:
                continue
            score = max(_similarity(a['title'] + ' ' + a['quote'], b['title'] + ' ' + b['quote'])
                        for a in methods[anchor] for b in methods[other])
            if score >= .055:
                candidates.append((score, other, pair))
                signatures[pair] = signature
        chosen = sorted(candidates, reverse=True)[:6]
        if not chosen:
            return graph
        papers = [{'id': key, 'title': nodes[node_id]['label'], 'chunks': [], 'existing': methods[key]}
                  for node_id, key in canonical.items() if key == anchor or any(row[1] == key for row in chosen)]
        try:
            _, relations = synthesize(self.reviewer, self.budget, papers, [[anchor, other] for _, other, _ in chosen])
        except (ReviewError, OSError, ValueError, KeyError, IndexError, TypeError):
            return {**graph, 'method_notice': '关系核验暂未完成，可稍后重试。'}

        def save(state):
            checked = state.setdefault('verified_pairs', {})
            for _, _, pair in chosen:
                checked[pair] = signatures[pair]
            links = state.setdefault('method_links', {})
            for relation in relations:
                endpoints = sorted(((relation['left_paper'], relation['left_id']),
                                    (relation['right_paper'], relation['right_id'])))
                links[':'.join((*endpoints[0], *endpoints[1]))] = self.with_relation_evidence(relation, methods)

        self.update_literature(owner, save)
        return self.build_graph_response(owner, focus_paper_id=paper_id)

    def delete_node(self, owner, node_id):
        graph = self.build_graph_response(owner)
        node = next((item for item in graph['nodes'] if item['id'] == node_id), None)
        if node is None:
            raise ReviewError('node_not_found', '当前图谱没有这个节点。', 404)
        owned_ids = {paper['id'] for paper in self.owned_papers(owner)}

        def remove(state):
            state['choices'].setdefault(node_id, {})['removed'] = True
            if node['node_type'] == 'Paper':
                canonical = state['matches'].get(node_id) or next(
                    (wid for wid, public in state['papers'].items()
                     if normalize_title(public['title']) == normalize_title(node['full_title'])), node_id)
                state['choices'].setdefault(canonical, {})['removed'] = True
                if node_id not in owned_ids:
                    state['papers'].pop(canonical, None)
                state['links'] = {key: item for key, item in state['links'].items()
                                  if canonical not in (item['source'], item['target'])}
                state['method_links'] = {key: item for key, item in state.get('method_links', {}).items()
                                         if canonical not in (item['left_paper'], item['right_paper'])}
            elif node['node_type'] == 'Contribution':
                state['method_links'] = {key: item for key, item in state.get('method_links', {}).items()
                                         if (node['canonical_paper'], node['method_id']) not in {
                                             (item['left_paper'], item['left_id']), (item['right_paper'], item['right_id'])}}

        self.update_literature(owner, remove)
        return self.build_graph_response(owner)

    def update_paper_choice(self, owner, paper_id, action):
        if action == 'remove':
            return self.delete_node(owner, paper_id)
        own = {paper['id'] for paper in self.owned_papers(owner)}

        def change(state):
            if paper_id not in own and paper_id not in state['papers']:
                raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
            flags = state['choices'].setdefault(paper_id, {})
            if action in {'read', 'unread'}:
                flags['read'] = action == 'read'
            elif action in {'hide', 'show'}:
                flags['hidden'] = action == 'hide'
            else:
                raise ReviewError('invalid_paper_action', '请选择可用的论文操作。')

        self.update_literature(owner, change)
        return self.build_graph_response(owner)

    def report_conflicts(self, owner, report):
        paper = extract_paper_graph_entry({'report': report}, owner_id=self._owner_hash(owner))
        verifications = self.get_verifications(owner)
        candidates = []
        for other in self.owned_papers(owner):
            if other['id'] == paper['id']:
                continue
            first, second = sorted((paper, other), key=lambda item: item['id'])
            for left in first['contributions']:
                for right in second['contributions']:
                    comparison = compare_contributions_pair(left, first, right, second, verifications)
                    if comparison['shared_datasets'] and comparison['shared_metrics'] or comparison['overlap_score'] >= 0.32:
                        candidates.append(comparison)
        return sorted(candidates, key=lambda item: (-item['overlap_score'], item['id']))[:24]

    def paper_slots(self, owner, papers, library):
        slots = library.get('paper_slots', {})
        missing = [paper['id'] for paper in papers if paper['id'] not in slots]
        if not missing:
            return slots

        def allocate(state):
            current = state.setdefault('paper_slots', {})
            used = set(current.values())
            index = 0
            for paper_id in missing:
                if paper_id in current:
                    continue
                while index in used:
                    index += 1
                current[paper_id] = index
                used.add(index)

        self.update_literature(owner, allocate)
        return self.literature_state(owner)[1]['paper_slots']

    @staticmethod
    def initial_paper_positions(papers, focus, aliases, links, overrides):
        by_id = {paper['id']: paper for paper in papers}
        groups = {-1: set(), 0: set(), 1: set()}
        for link in links.values():
            source = aliases.get(link['source'], link['source'])
            target = aliases.get(link['target'], link['target'])
            if source == focus and target in by_id and target != focus:
                groups[1 if link['kind'] == 'citation' else 0].add(target)
            if target == focus and source in by_id and source != focus:
                groups[-1 if link['kind'] == 'citation' else 0].add(source)
        if not any(groups.values()):
            return {}
        groups[0] -= groups[-1] | groups[1]
        points = {pid: (pos['x'], pos['y']) for pid, pos in overrides.items() if pid in by_id}
        nearest = [points[pid] for group in groups.values() for pid in group if pid in points]
        origin = (sum(p[0] for p in nearest)/len(nearest), sum(p[1] for p in nearest)/len(nearest)) if nearest else (520, 325)

        def fits(point):
            return all(math.dist(point, other) >= 76 and
                       (abs(point[1]-other[1]) >= 34 or abs(point[0]-other[0]) >= 220)
                       for other in points.values())

        if focus not in points:
            points[focus] = next((point for point in (origin, *((origin[0], origin[1]+dy)
                for step in range(1, len(points)+2) for dy in (step*76, -step*76))) if fits(point)))
        x, y = points[focus]

        def place_side(ids, side):
            count = len(ids)
            if not count:
                return
            grid = [(x+side*dx, y+step*76)
                    for dx in (120, 340, 560) for step in range(-len(by_id)-1, len(by_id)+2)]
            grid.sort(key=lambda point: (math.dist((x, y), point), point[1]))
            for pid in sorted(ids):
                if pid not in points:
                    points[pid] = next(point for point in grid if fits(point))

        place_side(groups[-1], -1)
        place_side(groups[1], 1)
        for index, pid in enumerate(sorted(groups[0])):
            if pid not in points:
                place_side({pid}, -1 if index%2==0 else 1)

        # Keep unrelated papers outside the local neighborhood without hiding them.
        remaining = sorted(set(by_id)-points.keys())
        for i, pid in enumerate(remaining):
            step = i+2
            while True:
                radius = 300+step*40
                angle = i*2.39996323
                point = (x+radius*math.cos(angle), y+radius*math.sin(angle))
                if fits(point):
                    points[pid] = point
                    break
                step += 1
        return points

    def build_graph_response(self, owner, *, focus_paper_id=''):
        own = self.owned_papers(owner)
        _, library = self.literature_state(owner)
        aliases = {}
        papers = []
        for paper in own:
            matched = library['matches'].get(paper['id'])
            if not matched:
                title = normalize_title(paper['title'])
                matches = [item['id'] for item in library['papers'].values()
                           if title and normalize_title(item['title']) == title]
                matched = matches[0] if len(matches) == 1 else ''
            public = library['papers'].get(matched, {})
            if matched:
                aliases.setdefault(matched, paper['id'])
            if library['choices'].get(paper['id'], {}).get('removed'):
                continue
            private_methods = library.get('private_methods', {}).get(paper['id'], {})
            contributions = self.merge_contributions(private_methods.get('contributions', []), paper.get('method_graph', []))
            if not contributions:
                contributions = [row for row in public.get('contributions', []) if row.get('method_grounded')]
            detail_status = (private_methods.get('method_detail_status') or public.get('method_detail_status') or
                             ('pending' if contributions or paper.get('paper_sha256') else public.get('method_status', 'unavailable')))
            papers.append({
                'id': paper['id'], 'title': paper['title'], 'project_id': paper['project_id'],
                'source_type': 'USER_UPLOAD', 'source_url': public.get('source_url', ''),
                'fallback_url': public.get('fallback_url') or ('https://doi.org/'+quote(paper['doi'],safe='/') if paper.get('doi') else
                                 'https://openalex.org/works?page=1&search='+quote(paper['title'])), 'canonical': matched or paper['id'],
                'review_status': paper['review_status'], 'contributions': contributions,
                'abstract': paper['abstract'], 'metadata': self.metadata(paper, public),
                'fulltext_status': private_methods.get('fulltext_status') or ('verified' if paper.get('method_graph') else public.get('fulltext_status')),
                'can_supply_original_pdf': bool(paper.get('paper_sha256')),
                **self.method_fields(contributions, detail_status),
            })
        for public in library['papers'].values():
            if public['id'] not in aliases and not library['choices'].get(public['id'], {}).get('removed'):
                contributions = [row for row in public.get('contributions', []) if row.get('method_grounded')]
                papers.append({**public, 'source_type': 'PUBLIC_LITERATURE', 'metadata': self.metadata({}, public),
                               'canonical': public['id'], 'contributions': contributions,
                               **self.method_fields(contributions, public.get('method_detail_status') or
                                                    ('pending' if contributions else public.get('method_status', 'unavailable')))})
        focus_paper_id = aliases.get(focus_paper_id, focus_paper_id)
        if not any(paper['id'] == focus_paper_id for paper in papers):
            focus_paper_id = next((paper['id'] for paper in reversed(papers) if paper['source_type'] == 'USER_UPLOAD'), papers[0]['id'] if papers else '')
        slots = self.paper_slots(owner, papers, library)
        layout = self.get_layout(owner)
        positions = layout.get('positions') or {}
        paper_points = self.initial_paper_positions(papers, focus_paper_id, aliases, library['links'], positions)
        nodes, edges, timeline = [], [], []
        contributions_by_paper = {}
        method_nodes = {}

        def append_node(node, x, y):
            override = positions.get(node['id']) or {}
            node['x'], node['y'] = override.get('x', round(x, 1)), override.get('y', round(y, 1))
            nodes.append(node)
            return node['x'], node['y']

        def add_edge(source, target, kind, label, description='', source_url=''):
            edges.append({'id': f'{kind}:{source}:{target}', 'source': source, 'target': target,
                          'edge_type': kind, 'label': label, 'description': description, 'source_url': source_url})

        for paper in papers:
            paper_id = paper['id']
            index = slots[paper_id]
            flags = {**library['choices'].get(paper_id, {})}
            for public_id, own_id in aliases.items():
                if own_id == paper_id:
                    flags = {**library['choices'].get(public_id, {}), **flags}
            ring, slot = 0, index
            while slot >= max(1, 6 * ring):
                slot -= max(1, 6 * ring)
                ring += 1
            angle = 2 * math.pi * slot / max(1, 6 * ring)
            radius = ring * 270
            item = {'paper_id': paper_id, 'title': paper['title'],
                    'year': paper['metadata']['year']['value'], 'direction': paper['metadata']['direction']['value'],
                    'venue': paper['metadata']['venue']['value'], 'source_type': paper['source_type'],
                    'visibility': 'PRIVATE', 'read': bool(flags.get('read', paper['source_type'] == 'USER_UPLOAD')),
                    'hidden': bool(flags.get('hidden')), 'source_url': paper.get('source_url', ''),
                    'fallback_url': paper.get('fallback_url') or paper.get('source_url',''),
                    **{key: paper[key] for key in ('method_status', 'method_detail_status', 'method_reason', 'detail_count')},
                    'pdf_available': bool(library.get('pdf_files',{}).get(paper_id) or library.get('pdf_files',{}).get(paper['canonical'])),
                    'fulltext_status': paper.get('fulltext_status') or library.get('pdf_attempts',{}).get(paper_id) or 'not_checked',
                    'fulltext_label': FULLTEXT_LABELS.get(paper.get('fulltext_status') or library.get('pdf_attempts',{}).get(paper_id),
                                                         FULLTEXT_LABELS['not_checked']),
                    'can_supply_original_pdf': paper['source_type'] == 'PUBLIC_LITERATURE' or paper.get('can_supply_original_pdf', False), 'project_id': paper.get('project_id', '')}
            timeline.append(item)
            px, py = append_node({**item, 'id': paper_id, 'node_type': 'Paper', 'layer': 1,
                                  'label': paper['title'], 'full_title': paper['title'],
                                  'abstract': paper.get('abstract', ''), 'metadata': paper['metadata']},
                                 *paper_points.get(paper_id, (520 + radius * math.cos(angle),
                                                               325 + radius * math.sin(angle))))
            for offset, contribution in enumerate(paper['contributions'][:6]):
                method_id = method_key(contribution)
                cid = f'{paper_id}_contribution_{method_id}'
                if library['choices'].get(cid, {}).get('removed'):
                    continue
                direction = angle + (offset - (len(paper['contributions'][:6])-1) / 2) * .65
                parent = {'id': cid, 'paper_id': paper_id, 'paper_title': paper['title'],
                          'parent_id': paper_id, 'node_type': 'Contribution', 'layer': 2,
                          'label': contribution['title'], 'full_title': contribution['title'],
                          'summary': contribution.get('summary') or contribution['title'], 'source_url': contribution.get('source_url', ''),
                          'quote': contribution['quote'], 'page': contribution['page'], 'section': contribution['section'],
                          'method_id': method_id, 'canonical_paper': paper['canonical']}
                cx, cy = append_node(parent, px + 105*math.cos(direction), py + 105*math.sin(direction))
                add_edge(paper_id, cid, 'HAS_CONTRIBUTION', '主贡献')
                method_nodes[paper['canonical'], method_id] = parent
                method_nodes[paper_id, method_id] = parent
                for detail_index, detail in enumerate(contribution.get('details', [])[:3]):
                    did = f'{cid}_detail_{method_key(detail)}'
                    if library['choices'].get(did, {}).get('removed'):
                        continue
                    theta = direction + (detail_index - 1) * .63
                    child = {'id': did, 'paper_id': paper_id, 'paper_title': paper['title'],
                             'parent_id': cid, 'node_type': 'Detail', 'layer': 3,
                             'label': detail['title'], 'full_title': detail['title'],
                             'summary': detail.get('summary') or detail['title'],
                             'quote': detail['quote'], 'page': detail['page'], 'section': detail['section'],
                             'source_url': detail.get('source_url', '')}
                    append_node(child, cx + 79*math.cos(theta), cy + 79*math.sin(theta))
                    add_edge(cid, did, 'HAS_DETAIL', '细分贡献')
            visible_details = sum(node['node_type'] == 'Detail' and node.get('paper_id') == paper_id for node in nodes)
            item['detail_count'] = visible_details
            paper_node = next(node for node in nodes if node['id'] == paper_id)
            paper_node['detail_count'] = visible_details
            contributions_by_paper[paper_id] = True

        for link in library['links'].values():
            source, target = (aliases.get(link[key], link[key]) for key in ('source', 'target'))
            if source == target or source not in contributions_by_paper or target not in contributions_by_paper:
                continue
            if link['kind'] == 'citation':
                add_edge(source, target, 'CITED_BY', '被后续论文引用', '箭头由被引用论文指向引用它的论文。', 'https://openalex.org/' + link['target'])
            elif link.get('depth'):
                add_edge(source, target, 'RELATED_WORK', '公开书目相关', 'OpenAlex 提供的相关论文线索。')
        for relation in library.get('method_links', {}).values():
            left = method_nodes.get((relation['left_paper'], relation['left_id']))
            right = method_nodes.get((relation['right_paper'], relation['right_id']))
            if not left or not right or left['paper_id'] == right['paper_id']:
                continue
            add_edge(left['id'], right['id'], 'SIMILAR_CONTRIBUTION', '方法贡献关联',
                     relation['description'], left['source_url'] or right['source_url'])
            evidence = relation.get('evidence') or [left, right]
            edges[-1]['excerpts'] = [row['quote'] for row in evidence]
            edges[-1]['evidence'] = [{key: row.get(key) for key in ('page','section','source_url')} for row in evidence]

        node_ids = {node['id'] for node in nodes}
        def resolve_node(node_id):
            paper, sep, suffix = node_id.partition('_contribution_')
            return aliases.get(paper, paper) + sep + suffix

        overrides = {}
        for link in library.get('relation_overrides', {}).values():
            left, right = (resolve_node(link[key]) for key in ('source', 'target'))
            overrides[self.link_key(left, right)] = {**link, 'source': left, 'target': right}
        by_id = {node['id']: node for node in nodes}
        paper_of = lambda node_id: by_id[node_id].get('paper_id', node_id)
        def visible_relation(edge):
            if edge['edge_type'] not in ('CITED_BY', 'RELATED_WORK', 'SIMILAR_CONTRIBUTION'):
                return True
            left, right = edge['source'], edge['target']
            return all(overrides.get(key, {}).get('action') != 'remove' for key in (
                self.link_key(left, right), self.link_key(paper_of(left), paper_of(right))))
        edges = [edge for edge in edges if visible_relation(edge)]
        for link in overrides.values():
            left, right = link['source'], link['target']
            if link['action'] == 'add' and left in node_ids and right in node_ids:
                add_edge(left, right, 'MANUAL_RELATION', link.get('label') or '自定义关联', link['note'])
        return {
            'focus_paper_id': focus_paper_id, 'nodes': nodes, 'edges': edges,
            'papers': timeline, 'timeline': sorted(timeline, key=lambda row: (row['year'] is None, row['year'] or 0, row['title'])),
            'layout': {'positions': {key: pos for key, pos in positions.items() if key in node_ids},
                       'pinned': [key for key in layout.get('pinned', []) if key in node_ids]},
            'stats': {'paper_count': len(papers)},
        }

    @staticmethod
    def metadata(paper, public):
        return {key: {'value': public.get(key) or paper.get(key),
                      'source': 'OpenAlex' if public.get(key) else 'PDF' if paper.get(key) else '',
                      'source_url': public.get('source_url', '') if public.get(key) else ''}
                for key in ('year', 'venue', 'direction')}
