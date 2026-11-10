"""Review-Aware Scientific Contribution Graph (知识图谱) service.

Implements the structured Extraction -> Normalization -> Retrieval -> Pairwise Comparison ->
Human-in-the-Loop Verification & Graph View Builder pipeline specified in docs/功能1.md.
"""
import hashlib
import json
import math
import uuid

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
        'venue': review.get('publication_venue') or '', 'direction': review.get('research_direction') or '', 'doi': payload.get('doi') or '',
        'arxiv_id': payload.get('arxiv_id') or '',
        'abstract': review.get('paper_abstract') or payload.get('paper_abstract') or '',
        'visibility': 'PRIVATE', 'source_type': payload.get('source_type') or 'USER_UPLOAD',
        'review_status': review_status, 'repro_status': reproduction, 'created_at': now(),
        'contributions': contributions,
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
    def __init__(self, env, store, reviewer=None):
        self.env = env
        self.store = store
        self.reviewer = reviewer
        self._mem_private = {}
        self._mem_layouts = {}
        self._mem_verifications = {}

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
        papers = self.owned_papers(owner)
        saved_layout = self.get_layout(owner)

        nodes = []
        edges = []
        comparisons = []
        all_contribs = []

        # 1. Build Paper -> Contribution -> Claim -> Evidence / ReviewFinding nodes & edges
        num_papers = max(1, len(papers))
        for p_idx, paper in enumerate(papers):
            angle = (2 * math.pi * p_idx) / num_papers
            radius = 0 if num_papers == 1 else 190
            px = round(520 + radius * math.cos(angle), 1)
            py = round(340 + radius * math.sin(angle), 1)
            pos_override = (saved_layout.get('positions') or {}).get(paper['id'])
            if isinstance(pos_override, dict) and 'x' in pos_override and 'y' in pos_override:
                px, py = float(pos_override['x']), float(pos_override['y'])

            nodes.append({
                'id': paper['id'],
                'node_type': 'Paper',
                'label': paper['title'][:38] + ('…' if len(paper['title']) > 38 else ''),
                'full_title': paper['title'],
                'year': paper.get('year'),
                'venue': paper.get('venue') or '',
                'visibility': paper.get('visibility') or 'PRIVATE',
                'source_type': paper.get('source_type') or 'USER_UPLOAD',
                'review_status': paper.get('review_status') or 'UNREVIEWED',
                'repro_status': paper.get('repro_status') or 'NOT_RUN',
                'abstract': paper.get('abstract') or '',
                'project_id': paper.get('project_id') or '',
                'direction': paper.get('direction') or '',
                'x': px,
                'y': py,
                'layer': 1
            })

            contribs = paper.get('contributions') or []
            for c_idx, contrib in enumerate(contribs):
                c_angle = angle + ((c_idx - (len(contribs) - 1) / 2.0) * 0.42)
                c_dist = 115
                cx = round(px + c_dist * math.cos(c_angle), 1)
                cy = round(py + c_dist * math.sin(c_angle), 1)
                c_pos = (saved_layout.get('positions') or {}).get(contrib['id'])
                if isinstance(c_pos, dict) and 'x' in c_pos and 'y' in c_pos:
                    cx, cy = float(c_pos['x']), float(c_pos['y'])

                all_contribs.append((contrib, paper))
                nodes.append({
                    'id': contrib['id'],
                    'paper_id': paper['id'],
                    'paper_title': paper['title'],
                    'paper_year': paper.get('year'),
                    'node_type': 'Contribution',
                    'label': contrib['title'][:30] + ('…' if len(contrib['title']) > 30 else ''),
                    'full_title': contrib['title'],
                    'summary': contrib.get('summary') or '',
                    'problem': contrib.get('problem') or '',
                    'method': contrib.get('method') or '',
                    'applicable_task': contrib.get('applicable_task') or '',
                    'datasets': contrib.get('datasets') or [],
                    'metrics': contrib.get('metrics') or [],
                    'baselines': contrib.get('baselines') or [],
                    'key_delta': contrib.get('key_delta') or '',
                    'limitations': contrib.get('limitations') or '',
                    'contribution_type': contrib.get('contribution_type') or 'METHOD',
                    'confidence': contrib.get('confidence'),
                    'review_support_level': contrib.get('review_support_level') or 'UNVERIFIED',
                    'visibility': paper.get('visibility') or 'PRIVATE',
                    'source_spans': contrib.get('source_spans') or [],
                    'claims': contrib.get('claims') or [],
                    'x': cx,
                    'y': cy,
                    'layer': 2
                })
                edges.append({
                    'id': f"edge_{paper['id']}__{contrib['id']}",
                    'source': paper['id'],
                    'target': contrib['id'],
                    'edge_type': 'HAS_CONTRIBUTION',
                    'label': '包含核心贡献',
                    'layer': 1
                })

                # Layer 2 & 3: Claim -> Evidence & ReviewFinding (expanded on demand in UI)
                for cl_idx, claim in enumerate(contrib.get('claims') or []):
                    cl_angle = c_angle + (cl_idx - 0.5) * 0.35
                    clx = round(cx + 82 * math.cos(cl_angle), 1)
                    cly = round(cy + 82 * math.sin(cl_angle), 1)
                    nodes.append({
                        'id': claim['id'],
                        'parent_id': contrib['id'],
                        'paper_id': paper['id'],
                        'node_type': 'Claim',
                        'label': f"{claim.get('dataset') or '实验'}: {claim.get('reported_value') or '声明'}",
                        'full_title': claim.get('claim_text') or '',
                        'claim_type': claim.get('claim_type') or 'PERFORMANCE',
                        'dataset': claim.get('dataset') or '',
                        'metric': claim.get('metric') or '',
                        'baseline': claim.get('baseline') or '',
                        'reported_value': claim.get('reported_value') or '',
                        'condition': claim.get('condition') or '',
                        'support_status': claim.get('support_status') or 'UNVERIFIED',
                        'x': clx,
                        'y': cly,
                        'layer': 3
                    })
                    edges.append({
                        'id': f"edge_{contrib['id']}__{claim['id']}",
                        'source': contrib['id'],
                        'target': claim['id'],
                        'edge_type': 'HAS_CLAIM',
                        'label': '具体声明',
                        'layer': 3
                    })
                    for ev in (claim.get('evidences') or []):
                        nodes.append({
                            'id': ev['id'],
                            'parent_id': claim['id'],
                            'contrib_id': contrib['id'],
                            'paper_id': paper['id'],
                            'node_type': 'Evidence',
                            'label': f"{ev.get('section') or '证据'} · P{ev.get('page') or 1}",
                            'full_title': ev.get('quote') or '',
                            'evidence_type': ev.get('evidence_type') or 'TABLE',
                            'section': ev.get('section') or '',
                            'page': ev.get('page') or 1,
                            'x': round(clx + 55, 1),
                            'y': round(cly - 28, 1),
                            'layer': 3
                        })
                        edges.append({
                            'id': f"edge_{claim['id']}__{ev['id']}",
                            'source': claim['id'],
                            'target': ev['id'],
                            'edge_type': 'SUPPORTED_BY',
                            'label': '原文证据',
                            'layer': 3
                        })
                    for fd in (claim.get('findings') or []):
                        nodes.append({
                            'id': fd['id'],
                            'parent_id': claim['id'],
                            'contrib_id': contrib['id'],
                            'paper_id': paper['id'],
                            'node_type': 'ReviewFinding',
                            'label': f"审查发现 ({fd.get('severity') or 'MEDIUM'})",
                            'full_title': fd.get('message') or '',
                            'finding_type': fd.get('finding_type') or 'WEAK_EVIDENCE',
                            'severity': fd.get('severity') or 'MEDIUM',
                            'x': round(clx + 55, 1),
                            'y': round(cly + 32, 1),
                            'layer': 3
                        })
                        edges.append({
                            'id': f"edge_{claim['id']}__{fd['id']}",
                            'source': claim['id'],
                            'target': fd['id'],
                            'edge_type': 'QUESTIONED_BY',
                            'label': '审查质疑',
                            'layer': 3
                        })

        # 2. Pairwise Contribution Comparisons & Relation Edges
        for i in range(len(all_contribs)):
            for j in range(i + 1, len(all_contribs)):
                ca, pa = all_contribs[i]
                cb, pb = all_contribs[j]
                cmp_item = compare_contributions_pair(ca, pa, cb, pb)
                if cmp_item['overlap_score'] >= 0.32 or (cmp_item['shared_datasets'] and cmp_item['shared_metrics']):
                    comparisons.append(cmp_item)
                    edges.append({
                        'id': cmp_item['id'],
                        'source': ca['id'],
                        'target': cb['id'],
                        'edge_type': cmp_item['relation_type'],
                        'conflict_type': cmp_item['conflict_type'],
                        'verdict': cmp_item['verdict'],
                        'overlap_score': cmp_item['overlap_score'],
                        'confidence': cmp_item['confidence'],
                        'user_verified': cmp_item['user_verified'],
                        'label': {
                            'EXTENDS': '脉络演进 (Extends)',
                            'COMPLEMENTARY': '方法互补',
                            'SIMILAR': '相似基线对照'
                        }.get(cmp_item['relation_type'], '贡献关联'),
                        'layer': 2
                    })

        # 3. Build Research Evolution Timeline
        timeline = sorted(
            [
                {
                    'paper_id': p['id'],
                    'title': p['title'],
                    'year': p.get('year'),
                    'venue': p.get('venue') or '',
                    'direction': p.get('direction') or '',
                    'visibility': p.get('visibility') or 'PRIVATE',
                    'review_status': p.get('review_status') or 'PASS',
                    'repro_status': p.get('repro_status') or 'NOT_RUN',
                    'contributions': [
                        {
                            'id': c['id'],
                            'title': c['title'],
                            'type': c.get('contribution_type') or 'METHOD',
                            'key_delta': c.get('key_delta') or c.get('summary') or '',
                            'support': c.get('review_support_level') or 'SUPPORTED'
                        }
                        for c in (p.get('contributions') or [])
                    ]
                }
                for p in papers
            ],
            key=lambda x: (x['year'] is None, x['year'] or 0, x['title'])
        )

        node_ids = {node['id'] for node in nodes}
        saved_layout = {
            'positions': {key: pos for key, pos in (saved_layout.get('positions') or {}).items() if key in node_ids},
            'pinned': [key for key in saved_layout.get('pinned', []) if key in node_ids],
        }
        if not any(p['id'] == focus_paper_id for p in papers):
            focus_paper_id = papers[-1]['id'] if papers else ''

        return {
            'focus_paper_id': focus_paper_id,
            'papers': papers,
            'nodes': nodes,
            'edges': edges,
            'comparisons': comparisons,
            'timeline': timeline,
            'layout': saved_layout,
            'stats': {
                'paper_count': len(papers),
                'contribution_count': len(all_contribs),
                'claim_count': sum(len(c.get('claims') or []) for c, _ in all_contribs),
            }
        }
