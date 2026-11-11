"""Review-Aware Scientific Contribution Graph (知识图谱) service.

Implements the structured Extraction -> Normalization -> Retrieval -> Pairwise Comparison ->
Human-in-the-Loop Verification & Graph View Builder pipeline specified in docs/功能1.md.
"""
import copy
import hashlib
import json
import math
import uuid

from .kg_literature import KINDS, LIMITS, OpenAlex, normalize_title, retrieve_public_methods
from .kg_methods import method_key, synthesize
from .review_api import ReviewError, now

KG_TTL = 30 * 86400

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
        self.literature = OpenAlex(env.get('OPENALEX_API_KEY', ''))

    def _redis_get(self, key, default):
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            return default
        try:
            raw = self.store.command('GET', key)
            return json.loads(raw) if raw else default
        except Exception as exc:
            raise ReviewError('graph_storage_unavailable', '暂时无法读取图谱存储。', 503) from exc

    def _redis_set(self, key, value):
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            return False
        try:
            self.store.command('SET', key, json.dumps(value, ensure_ascii=False), 'EX', str(KG_TTL))
            return True
        except Exception as exc:
            raise ReviewError('graph_storage_unavailable', '暂时无法保存图谱，请重试。', 503) from exc

    def _owner_hash(self, owner):
        return hashlib.sha256(str(owner or 'anon').encode()).hexdigest()[:24]

    def get_private_papers(self, owner):
        oh = self._owner_hash(owner)
        key = f"articheck:kg:private:{self.store.namespace}:{oh}"
        data = self._redis_get(key, None)
        if data is None:
            return list(self._mem_private.get(oh, []))
        self._mem_private[oh] = data
        return list(data)

    def save_private_papers(self, owner, papers):
        oh = self._owner_hash(owner)
        self._mem_private[oh] = papers[-30:]
        key = f"articheck:kg:private:{self.store.namespace}:{oh}"
        self._redis_set(key, self._mem_private[oh])

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
        data = self._redis_get(key, None)
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
redis.call('SET',KEYS[1],cjson.encode(state),'EX',ARGV[5])
return 1
"""
                if self.store.command('EVAL', script, '1', key, node_id, json.dumps(position),
                                      '1' if change['pinned'] else '0', stamp, str(KG_TTL)) != 1:
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
        self._redis_set(key, state)
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
        return key, copy.deepcopy(self._redis_get(key, self._mem_literature.get(key, default)))

    def update_literature(self, owner, change):
        # Compare-and-swap the raw value so simultaneous searches and reading edits merge.
        key, _ = self.literature_state(owner)
        if not getattr(self.store, 'url', '') or not getattr(self.store, 'token', ''):
            _, state = self.literature_state(owner)
            change(state)
            self._mem_literature[key] = state
            return
        script = ("if (redis.call('GET',KEYS[1]) or '')~=ARGV[1] then return 0 end; "
                  "redis.call('SET',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1")
        for _ in range(4):
            raw = self.store.command('GET', key)
            state = json.loads(raw) if raw else {'papers': {}, 'links': {}, 'matches': {}, 'choices': {}, 'method_links': {}}
            change(state)
            if self.store.command('EVAL', script, '1', key, raw or '', json.dumps(state, ensure_ascii=False), str(KG_TTL)) == 1:
                return
        raise ReviewError('graph_changed', '文献条目正在更新，请重试。', 409)

    def expand_literature(self, owner, paper_id, *, kinds, limit):
        if not isinstance(kinds, list) or any(not isinstance(kind, str) or kind not in KINDS for kind in kinds):
            raise ReviewError('invalid_literature_kind', '请选择需要查找的研究关系。')
        if type(limit) is not int or limit not in LIMITS:
            raise ReviewError('invalid_literature_limit', '请选择每类 3、5 或 8 篇。')
        _, state = self.literature_state(owner)
        own = {paper['id']: paper for paper in self.owned_papers(owner)}
        paper = own.get(paper_id) or state['papers'].get(paper_id)
        if not paper or state['choices'].get(paper_id, {}).get('removed'):
            raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
        metadata, groups = self.literature.neighborhood(
            title=paper['title'], identifier=state['matches'].get(paper_id, paper_id if paper_id in state['papers'] else ''),
            doi=paper.get('doi', ''), kinds=set(kinds), limit=limit,
        )

        anchor = metadata['id']
        discovered = {item['id']: item for items in groups.values() for item in items
                      if not state['choices'].get(item['id'], {}).get('removed')}
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
        fetch = [item for wid, item in available.items() if not existing[wid]]
        chunks = retrieve_public_methods(fetch, paper['title'], self.literature)
        inputs = [{'id': wid, 'title': item['title'], 'chunks': chunks.get(wid, []), 'existing': existing[wid]}
                  for wid, item in available.items() if chunks.get(wid) or existing[wid]]
        with_evidence = {row['id'] for row in inputs}
        pairs = [[anchor, wid] for wid in discovered if anchor in with_evidence and wid in with_evidence]
        analysis_error = ''
        try:
            extracted, relationships = synthesize(self.reviewer, self.budget, inputs, pairs)
        except (ReviewError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
            extracted, relationships = {}, []
            analysis_error = ('本轮模型额度已用完。已保留公开书目。'
                              if isinstance(error, ReviewError) and error.code == 'budget_exhausted'
                              else '方法分析暂未完成。已保留公开书目，可重试扩展。')

        for wid, item in available.items():
            # Never write an uploaded paper's excerpts into the public metadata record.
            item['contributions'] = extracted.get(wid) or [
                row for row in state['papers'].get(wid, {}).get('contributions', []) if row.get('method_grounded')
            ]
            item['method_status'] = ('grounded' if item['contributions'] else
                                     'pending' if chunks.get(wid) else 'unavailable')

        def save(current):
            if current['choices'].get(paper_id, {}).get('removed'):
                raise ReviewError('paper_not_found', '当前图谱没有这篇论文。', 404)
            identifier = metadata['id']
            current['matches'][paper_id] = identifier
            def save_public(item):
                wid = item['id']
                prior = current['papers'].get(wid, {})
                if not item.get('contributions') and any(row.get('method_grounded') for row in prior.get('contributions', [])):
                    item = {**item, 'contributions': prior['contributions'], 'method_status': 'grounded'}
                current['papers'][wid] = item

            save_public(metadata)
            for kind, papers in groups.items():
                for related in papers:
                    target = related['id']
                    if current['choices'].get(target, {}).get('removed'):
                        continue
                    save_public(related)
                    source, destination = (target, identifier) if kind == 'previous' else (identifier, target)
                    if kind == 'similar':
                        source, destination = sorted((identifier, target))
                    key = f'{kind if kind == "similar" else "citation"}:{source}:{destination}'
                    current['links'][key] = {'source': source, 'target': destination,
                                             'kind': 'similar' if kind == 'similar' else 'citation'}
            methods = current.setdefault('method_links', {})
            for relation in relationships:
                a, b = sorted(((relation['left_paper'], relation['left_id']),
                               (relation['right_paper'], relation['right_id'])))
                if any(current['choices'].get(wid, {}).get('removed') for wid, _ in (a, b)):
                    continue
                methods[':'.join((*a, *b))] = relation
            if len(methods) > 300:
                raise ReviewError('literature_capacity', '图谱的贡献关系已达上限，请先移除部分节点。', 409)
            if len(current['papers']) > 75 or len(current['links']) > 300:
                raise ReviewError('literature_capacity', '图谱的公开条目或关系已达上限，请先移除部分条目。', 409)

        self.update_literature(owner, save)
        return {**self.build_graph_response(owner, focus_paper_id=paper_id), 'method_notice': analysis_error}

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
            contributions = paper.get('method_graph') or [row for row in public.get('contributions', [])
                                                           if row.get('method_grounded')]
            papers.append({
                'id': paper['id'], 'title': paper['title'], 'project_id': paper['project_id'],
                'source_type': 'USER_UPLOAD', 'source_url': public.get('source_url', ''), 'canonical': matched or paper['id'],
                'review_status': paper['review_status'], 'contributions': contributions,
                'abstract': paper['abstract'], 'metadata': self.metadata(paper, public),
                'method_status': 'grounded' if contributions else public.get('method_status', 'unavailable'),
            })
        for public in library['papers'].values():
            if public['id'] not in aliases and not library['choices'].get(public['id'], {}).get('removed'):
                contributions = [row for row in public.get('contributions', []) if row.get('method_grounded')]
                papers.append({**public, 'source_type': 'PUBLIC_LITERATURE', 'metadata': self.metadata({}, public),
                               'canonical': public['id'], 'contributions': contributions,
                               'method_status': 'grounded' if contributions else public.get('method_status', 'unavailable')})
        focus_paper_id = aliases.get(focus_paper_id, focus_paper_id)
        if not any(paper['id'] == focus_paper_id for paper in papers):
            focus_paper_id = next((paper['id'] for paper in reversed(papers) if paper['source_type'] == 'USER_UPLOAD'), papers[0]['id'] if papers else '')
        papers.sort(key=lambda paper: paper['id'] != focus_paper_id)
        layout = self.get_layout(owner)
        positions = layout.get('positions') or {}
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

        for index, paper in enumerate(papers):
            paper_id = paper['id']
            flags = {**library['choices'].get(paper_id, {})}
            for public_id, own_id in aliases.items():
                if own_id == paper_id:
                    flags = {**library['choices'].get(public_id, {}), **flags}
            ring = 1 + (index - 1) // 6 if index else 0
            angle = (index - 1) % 6 * math.pi / 3 + (ring % 2) * math.pi / 6
            radius = ring * 252
            item = {'paper_id': paper_id, 'title': paper['title'],
                    'year': paper['metadata']['year']['value'], 'direction': paper['metadata']['direction']['value'],
                    'venue': paper['metadata']['venue']['value'], 'source_type': paper['source_type'],
                    'visibility': 'PRIVATE', 'read': bool(flags.get('read', paper['source_type'] == 'USER_UPLOAD')), 'method_status': paper['method_status'], 'hidden': bool(flags.get('hidden')), 'source_url': paper.get('source_url', '')}
            timeline.append(item)
            px, py = append_node({**item, 'id': paper_id, 'node_type': 'Paper', 'layer': 1,
                                  'label': paper['title'], 'full_title': paper['title'],
                                  'abstract': paper.get('abstract', ''), 'metadata': paper['metadata']},
                                 520 + radius * math.cos(angle), 325 + radius * math.sin(angle))
            for offset, contribution in enumerate(paper['contributions'][:6]):
                method_id = method_key(contribution)
                cid = f'{paper_id}_contribution_{method_id}'
                if library['choices'].get(cid, {}).get('removed'):
                    continue
                direction = angle + (offset - (len(paper['contributions'][:6])-1) / 2) * .65
                parent = {'id': cid, 'paper_id': paper_id, 'paper_title': paper['title'],
                          'parent_id': paper_id, 'node_type': 'Contribution', 'layer': 2,
                          'label': contribution['title'], 'full_title': contribution['title'],
                          'summary': contribution['title'], 'source_url': contribution.get('source_url', ''),
                          'quote': contribution['quote'], 'page': contribution['page'], 'section': contribution['section'],
                          'method_id': method_id, 'canonical_paper': paper['canonical']}
                cx, cy = append_node(parent, px + 105*math.cos(direction), py + 105*math.sin(direction))
                add_edge(paper_id, cid, 'HAS_CONTRIBUTION', '主贡献')
                method_nodes[paper['canonical'], method_id] = parent
                for detail_index, detail in enumerate(contribution.get('details', [])[:3]):
                    did = f'{cid}_detail_{method_key(detail)}'
                    if library['choices'].get(did, {}).get('removed'):
                        continue
                    theta = direction + (detail_index - 1) * .63
                    child = {'id': did, 'paper_id': paper_id, 'paper_title': paper['title'],
                             'parent_id': cid, 'node_type': 'Detail', 'layer': 3,
                             'label': detail['title'], 'full_title': detail['title'],
                             'quote': detail['quote'], 'page': detail['page'], 'section': detail['section'],
                             'source_url': detail.get('source_url', '')}
                    append_node(child, cx + 79*math.cos(theta), cy + 79*math.sin(theta))
                    add_edge(cid, did, 'HAS_DETAIL', '细分贡献')
            contributions_by_paper[paper_id] = True

        for link in library['links'].values():
            source, target = (aliases.get(link[key], link[key]) for key in ('source', 'target'))
            if source == target or source not in contributions_by_paper or target not in contributions_by_paper:
                continue
            if link['kind'] == 'citation':
                add_edge(source, target, 'CITED_BY', '被后续论文引用', '箭头由被引用论文指向引用它的论文。', 'https://openalex.org/' + link['target'])
        for relation in library.get('method_links', {}).values():
            left = method_nodes.get((relation['left_paper'], relation['left_id']))
            right = method_nodes.get((relation['right_paper'], relation['right_id']))
            if not left or not right or left['paper_id'] == right['paper_id']:
                continue
            add_edge(left['id'], right['id'], 'SIMILAR_CONTRIBUTION', '方法贡献关联',
                     relation['description'], left['source_url'] or right['source_url'])
            edges[-1]['excerpts'] = [left['quote'], right['quote']]
            edges[-1]['evidence'] = [{key: node[key] for key in ('page','section','source_url')} for node in (left,right)]

        node_ids = {node['id'] for node in nodes}
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
