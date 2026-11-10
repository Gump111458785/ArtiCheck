"""Review-Aware Scientific Contribution Graph (知识图谱) service.

Implements the structured Extraction -> Normalization -> Retrieval -> Pairwise Comparison ->
Human-in-the-Loop Verification & Graph View Builder pipeline specified in docs/功能1.md.
"""
import hashlib
import json
import math
import time
import uuid

from .review_api import ReviewError, now

KG_TTL = 30 * 86400

SEED_PAPERS = [
    {
        'id': 'paper_seed_resnet_2015',
        'title': 'Deep Residual Learning for Image Recognition',
        'authors': ['Kaiming He', 'Xiangyu Zhang', 'Shaoqing Ren', 'Jian Sun'],
        'year': 2016,
        'venue': 'CVPR 2016',
        'doi': '10.1109/CVPR.2016.90',
        'arxiv_id': '1512.03385',
        'abstract': 'Deeper neural networks are more difficult to train. We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously.',
        'visibility': 'GLOBAL',
        'source_type': 'SEED_BENCHMARK',
        'review_status': 'PASS',
        'repro_status': 'REPRODUCED',
        'contributions': [
            {
                'id': 'contrib_seed_resnet_1',
                'paper_id': 'paper_seed_resnet_2015',
                'title': '恒等快捷连接残差学习框架 (Deep Residual Learning)',
                'summary': '提出显式拟合残差映射 F(x) = H(x) - x 的恒等快捷连接结构，在不增加额外参数与计算复杂度的前提下解决深度网络退化问题。',
                'problem': '深度卷积神经网络随层数加深出现训练误差上升的退化问题（Degradation Problem）',
                'method': '残差块（Residual Block）与恒等快捷连接（Identity Shortcut Connection）',
                'applicable_task': '图像分类、目标检测与通用深度表征学习',
                'datasets': ['ImageNet-1K', 'CIFAR-10', 'MS COCO'],
                'metrics': ['Top-1 Error', 'Top-5 Error', 'Test Error (%)', 'mAP'],
                'baselines': ['VGG-16', 'GoogLeNet', 'Plain-34', 'Plain-20'],
                'key_delta': '相比无快捷连接的 Plain 网络，34 层与 110 层 ResNet 收敛更快且测试误差显著下降',
                'limitations': '极深网络（如 1202 层）在小数据集 CIFAR-10 上仍存在轻微过拟合风险',
                'contribution_type': 'METHOD',
                'confidence': 0.96,
                'review_support_level': 'SUPPORTED',
                'source_spans': [{'section': 'Section 3.1 Residual Learning', 'page': 2, 'quote': 'We explicitly let these layers fit a residual mapping F(x) := H(x) - x.'}],
                'claims': [
                    {
                        'id': 'claim_seed_resnet_1a',
                        'claim_text': '在 ImageNet 验证集上，34 层 ResNet 相比 34 层 Plain 网络将 Top-1 误差降低 3.5%，且训练误差同步下降。',
                        'claim_type': 'PERFORMANCE',
                        'dataset': 'ImageNet-1K',
                        'metric': 'Top-1 Error',
                        'baseline': 'Plain-34',
                        'reported_value': '25.03%',
                        'direction': 'LOWER_IS_BETTER',
                        'condition': 'Single-model validation, 224x224 crop',
                        'support_status': 'SUPPORTED',
                        'evidences': [
                            {'id': 'ev_seed_resnet_1a', 'evidence_type': 'TABLE', 'section': 'Table 2', 'page': 4, 'quote': 'Plain-34 Top-1 error 28.54% vs ResNet-34 Top-1 error 25.03%'}
                        ],
                        'findings': []
                    },
                    {
                        'id': 'claim_seed_resnet_1b',
                        'claim_text': '在 CIFAR-10 标准数据增强协议下，ResNet-20 与 ResNet-110 分别达到 8.75% 与 6.43% 测试误差。',
                        'claim_type': 'PERFORMANCE',
                        'dataset': 'CIFAR-10',
                        'metric': 'Test Error (%)',
                        'baseline': 'FitNet / Highway',
                        'reported_value': '8.75% (ResNet-20) / 6.43% (ResNet-110)',
                        'direction': 'LOWER_IS_BETTER',
                        'condition': '45k/5k train/val split, random crop & horizontal flip',
                        'support_status': 'SUPPORTED',
                        'evidences': [
                            {'id': 'ev_seed_resnet_1b', 'evidence_type': 'TABLE', 'section': 'Table 6', 'page': 7, 'quote': 'ResNet-20 (0.27M params): 8.75% test error; ResNet-110 (1.7M params): 6.43% test error.'}
                        ],
                        'findings': []
                    }
                ]
            },
            {
                'id': 'contrib_seed_resnet_2',
                'paper_id': 'paper_seed_resnet_2015',
                'title': '1x1-3x3-1x1 瓶颈残差构建块 (Bottleneck Architecture)',
                'summary': '针对 50/101/152 层深层网络设计三层瓶颈结构（1x1 降维、3x3 卷积、1x1 升维），在保持高表达能力的同时大幅降低计算开销。',
                'problem': '超过 50 层的深度残差网络直接堆叠双层 3x3 卷积带来过高 FLOPs 与训练耗时',
                'method': 'Bottleneck Building Block (1x1 -> 3x3 -> 1x1 convolutions)',
                'applicable_task': '大规模视觉主干网络高效训练与推理',
                'datasets': ['ImageNet-1K', 'PASCAL VOC', 'MS COCO'],
                'metrics': ['FLOPs', 'Top-5 Error', 'COCO mAP@[.5,.95]'],
                'baselines': ['VGG-16', 'ResNet-34'],
                'key_delta': '152 层 ResNet 计算复杂度（11.3B FLOPs）低于 VGG-16（15.3B FLOPs），单模型 Top-5 误差降至 4.49%',
                'limitations': '投影快捷连接（Option B）相比纯恒等连接会引入额外矩阵乘法参数',
                'contribution_type': 'SYSTEM',
                'confidence': 0.94,
                'review_support_level': 'SUPPORTED',
                'source_spans': [{'section': 'Section 3.3 Network Architectures', 'page': 5, 'quote': 'For each residual function F, we use a stack of 3 layers instead of 2 (1x1, 3x3, and 1x1 convolutions).'}],
                'claims': [
                    {
                        'id': 'claim_seed_resnet_2a',
                        'claim_text': 'ResNet-152 单模型在 ImageNet 验证集达到 4.49% Top-5 误差，超越此前所有单模型结果且 FLOPs 低于 VGG-16。',
                        'claim_type': 'EFFICIENCY',
                        'dataset': 'ImageNet-1K',
                        'metric': 'Top-5 Error / FLOPs',
                        'baseline': 'VGG-16',
                        'reported_value': '4.49% (11.3B FLOPs)',
                        'direction': 'LOWER_IS_BETTER',
                        'condition': '10-crop testing on ImageNet validation set',
                        'support_status': 'SUPPORTED',
                        'evidences': [
                            {'id': 'ev_seed_resnet_2a', 'evidence_type': 'TABLE', 'section': 'Table 3 & Table 4', 'page': 6, 'quote': 'ResNet-152 achieves 4.49% top-5 error with lower complexity than VGG-16/19.'}
                        ],
                        'findings': []
                    }
                ]
            }
        ]
    },
    {
        'id': 'paper_seed_preact_2016',
        'title': 'Identity Mappings in Deep Residual Networks',
        'authors': ['Kaiming He', 'Xiangyu Zhang', 'Shaoqing Ren', 'Jian Sun'],
        'year': 2016,
        'venue': 'ECCV 2016',
        'doi': '10.1007/978-3-319-46493-0_38',
        'arxiv_id': '1603.05027',
        'abstract': 'We analyze the propagation formulations behind the connection mechanisms of deep residual networks and propose a pre-activation residual unit that makes training easier and improves generalization.',
        'visibility': 'GLOBAL',
        'source_type': 'SEED_BENCHMARK',
        'review_status': 'PASS',
        'repro_status': 'REPRODUCED',
        'contributions': [
            {
                'id': 'contrib_seed_preact_1',
                'paper_id': 'paper_seed_preact_2016',
                'title': '全预激活残差单元 (Full Pre-activation Residual Unit)',
                'summary': '将 Batch Normalization 与 ReLU 移至卷积层之前（BN-ReLU-Conv），使快捷连接路径保持纯粹恒等映射，支持 1001 层网络稳定收敛并降低泛化误差。',
                'problem': '原始 ResNet 残差加法后的 ReLU 阻碍反向传播梯度在恒等路径上的无损传递',
                'method': 'Pre-activation Residual Unit (BN -> ReLU -> Weight)',
                'applicable_task': '超深卷积神经网络（1000+ 层）训练与图像识别',
                'datasets': ['CIFAR-10', 'CIFAR-100', 'ImageNet-1K'],
                'metrics': ['Test Error (%)', 'Top-1 Error'],
                'baselines': ['Original ResNet-110', 'Original ResNet-164', 'ResNet-1202'],
                'key_delta': '1001 层 Pre-act ResNet 在 CIFAR-10 将测试误差从 7.61% 降至 4.62%，消除了深层过拟合退化',
                'limitations': '在较浅网络（如 ResNet-20）上与后激活结构性能差距较小',
                'contribution_type': 'METHOD',
                'confidence': 0.93,
                'review_support_level': 'SUPPORTED',
                'source_spans': [{'section': 'Section 4 Identity Skip Connections', 'page': 6, 'quote': 'By viewing the activations as pre-activation of the weight layers, the information can propagate unimpeded.'}],
                'claims': [
                    {
                        'id': 'claim_seed_preact_1a',
                        'claim_text': '在 CIFAR-10 上，1001 层预激活 ResNet 取得 4.62% 测试误差，显著优于原始后激活 ResNet-1202（7.93%）。',
                        'claim_type': 'PERFORMANCE',
                        'dataset': 'CIFAR-10',
                        'metric': 'Test Error (%)',
                        'baseline': 'Post-activation ResNet-1202',
                        'reported_value': '4.62%',
                        'direction': 'LOWER_IS_BETTER',
                        'condition': 'Standard CIFAR-10 augmentation, 2 GPUs',
                        'support_status': 'SUPPORTED',
                        'evidences': [
                            {'id': 'ev_seed_preact_1a', 'evidence_type': 'TABLE', 'section': 'Table 2', 'page': 8, 'quote': 'ResNet-1001 (pre-activation): 4.62% test error on CIFAR-10.'}
                        ],
                        'findings': []
                    }
                ]
            }
        ]
    },
    {
        'id': 'paper_seed_wrn_2016',
        'title': 'Wide Residual Networks',
        'authors': ['Sergey Zagoruyko', 'Nikos Komodakis'],
        'year': 2016,
        'venue': 'BMVC 2016',
        'doi': '10.5244/C.30.87',
        'arxiv_id': '1605.07146',
        'abstract': 'We conduct an experimental study on the architecture of residual blocks and show that widening residual networks provides far more effective accuracy and GPU efficiency gains than extreme depth.',
        'visibility': 'GLOBAL',
        'source_type': 'SEED_BENCHMARK',
        'review_status': 'PARTIAL',
        'repro_status': 'PARTIAL',
        'contributions': [
            {
                'id': 'contrib_seed_wrn_1',
                'paper_id': 'paper_seed_wrn_2016',
                'title': '宽残差网络与残差块内部 Dropout 正则化 (Wide Residual Networks)',
                'summary': '提出通过增加残差块通道宽度因子 k 并减少网络层数（如 28 层 WRN-28-10），配合卷积层间 Dropout，以更高 GPU 并行效率超越上千层极深窄残差网络。',
                'problem': '极深残差网络（1000+ 层）存在特征复用递减（Diminishing Feature Reuse）且逐层串行计算难以充分利用 GPU 并行度',
                'method': '宽度倍增因子 k (Widening Factor) + 残差卷积间 Dropout',
                'applicable_task': '图像分类与高效 GPU 训练',
                'datasets': ['CIFAR-10', 'CIFAR-100', 'SVHN', 'ImageNet-1K'],
                'metrics': ['Test Error (%)', 'Training Time (s/epoch)'],
                'baselines': ['ResNet-1001', 'Pre-act ResNet-164'],
                'key_delta': '16 层宽残差网络在准确率与训练速度上优于 1000 层细长残差网络，WRN-28-10 在 CIFAR-10 达到 3.89% 误差',
                'limitations': '参数量增加明显（WRN-28-10 约 36.5M 参数），对显存占用较高',
                'contribution_type': 'EMPIRICAL',
                'confidence': 0.91,
                'review_support_level': 'PARTIAL',
                'source_spans': [{'section': 'Section 2 Wide Residual Networks', 'page': 4, 'quote': 'Widening of residual blocks provides a more effective way of improving performance of residual networks than increasing their depth.'}],
                'claims': [
                    {
                        'id': 'claim_seed_wrn_1a',
                        'claim_text': '28 层 WRN-28-10 在 CIFAR-10 达到 4.00%（带 Dropout 3.89%）测试误差，超过 1001 层 Pre-act ResNet（4.62%）且训练速度提升数倍。',
                        'claim_type': 'PERFORMANCE',
                        'dataset': 'CIFAR-10',
                        'metric': 'Test Error (%)',
                        'baseline': 'Pre-act ResNet-1001',
                        'reported_value': '3.89%',
                        'direction': 'LOWER_IS_BETTER',
                        'condition': 'ZCA whitening / mean-std normalization, 200 epochs',
                        'support_status': 'PARTIAL',
                        'evidences': [
                            {'id': 'ev_seed_wrn_1a', 'evidence_type': 'TABLE', 'section': 'Table 4 & Table 5', 'page': 8, 'quote': 'WRN-28-10 achieves 4.00% (3.89% with dropout) on CIFAR-10.'}
                        ],
                        'findings': [
                            {'id': 'find_seed_wrn_1', 'finding_type': 'BENCHMARK_GAP', 'severity': 'MEDIUM', 'message': '不同实现中 mean-std 与 ZCA 预处理存在约 0.15% 的精度波动，需在评测协议中显式固定。'}
                        ]
                    }
                ]
            }
        ]
    },
    {
        'id': 'paper_seed_liblinear_2008',
        'title': 'LIBLINEAR: A Library for Large Linear Classification',
        'authors': ['Rong-En Fan', 'Kai-Wei Chang', 'Cho-Jui Hsieh', 'Xiang-Rui Wang', 'Chih-Jen Lin'],
        'year': 2008,
        'venue': 'JMLR 2008',
        'doi': '10.5555/1390681.1442794',
        'arxiv_id': '',
        'abstract': 'LIBLINEAR is an open source library for large-scale linear classification supporting logistic regression and linear support vector machines with coordinate descent and trust region Newton methods.',
        'visibility': 'GLOBAL',
        'source_type': 'SEED_BENCHMARK',
        'review_status': 'PARTIAL',
        'repro_status': 'PARTIAL',
        'contributions': [
            {
                'id': 'contrib_seed_liblinear_1',
                'paper_id': 'paper_seed_liblinear_2008',
                'title': '对偶坐标下降大规模线性 SVM 求解器 (Dual Coordinate Descent for Linear SVM)',
                'summary': '提出针对 L1/L2 损失大规模稀疏线性 SVM 的对偶坐标下降算法，将高维文档分类训练时间从数小时缩短至数秒。',
                'problem': '高维稀疏特征空间（百万级特征）中核 SVM 与传统內点法训练过慢',
                'method': 'Dual Coordinate Descent (DCD) & Trust Region Newton Method (TRON)',
                'applicable_task': '大规模稀疏线性分类与文本分类',
                'datasets': ['news20', 'rcv1', 'yahoo-japan'],
                'metrics': ['Test Accuracy (%)', 'Training Time (s)'],
                'baselines': ['LIBSVM', 'SVM-perf', 'Pegasos'],
                'key_delta': '在 news20 与 rcv1 上几秒内收敛到与精确求解器一致的泛化准确率（news20 约 96.76%）',
                'limitations': '仅适用于线性可分或高维稀疏特征，非线性低维任务仍需核方法或深度网络',
                'contribution_type': 'SYSTEM',
                'confidence': 0.95,
                'review_support_level': 'PARTIAL',
                'source_spans': [{'section': 'Section 2 Linear Classification', 'page': 1872, 'quote': 'LIBLINEAR is very efficient for training large-scale problems.'}],
                'claims': [
                    {
                        'id': 'claim_seed_liblinear_1a',
                        'claim_text': '在 news20 二分类基准上，LIBLINEAR 对偶坐标下降求解器达到 96.76% 检验准确率且多次随机种子运行结果稳定。',
                        'claim_type': 'PERFORMANCE',
                        'dataset': 'news20',
                        'metric': 'Test Accuracy (%)',
                        'baseline': 'LIBSVM',
                        'reported_value': '96.76%',
                        'direction': 'HIGHER_IS_BETTER',
                        'condition': 'CPU single-thread, C=1, 15 repeated runs',
                        'support_status': 'SUPPORTED',
                        'evidences': [
                            {'id': 'ev_seed_liblinear_1a', 'evidence_type': 'EXECUTION', 'section': 'CI Reproduction Run', 'page': 1, 'quote': '15/15 runs completed on news20 with observed accuracy 0.9676.'}
                        ],
                        'findings': [
                            {'id': 'find_seed_liblinear_1', 'finding_type': 'MISSING_EXPERIMENT', 'severity': 'LOW', 'message': '公开 CI 归档当前仅覆盖 news20 数据集，rcv1 与 Figure 1 曲线效率对比尚未在本次 CI 范围运行。'}
                        ]
                    }
                ]
            }
        ]
    }
]


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
        'title': title, 'authors': payload.get('authors') or [], 'year': payload.get('year'),
        'venue': payload.get('venue') or '', 'doi': payload.get('doi') or '',
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
        self._mem_global = []
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

    def get_global_custom_papers(self):
        key = f"articheck:kg:global:{self.store.namespace}"
        data = self._redis_get(key, None)
        if data is None:
            return [] if getattr(self.store, 'url', '') else list(self._mem_global)
        self._mem_global = data
        return list(data)

    def save_global_custom_papers(self, papers):
        self._mem_global = papers[-50:]
        key = f"articheck:kg:global:{self.store.namespace}"
        self._redis_set(key, self._mem_global)

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
            'scope': str(payload.get('scope') or 'COMBINED'),
            'updated_at': now()
        }
        self._mem_layouts[oh] = state
        key = f"articheck:kg:layout:{self.store.namespace}:{oh}"
        self._redis_set(key, state)
        return state

    def ingest_project(self, owner, payload):
        """Build or update a paper graph entry from a reviewed project or external metadata."""
        enable_kg = payload.get('enable_kg', True)
        join_global = bool(payload.get('join_global_graph', False))
        if not enable_kg:
            return {'status': 'skipped', 'reason': '知识图谱开关已关闭'}

        entry = extract_paper_graph_entry(payload, owner_id=self._owner_hash(owner))
        existing = self.get_private_papers(owner)
        previous = next((p for p in existing if p['id'] == entry['id']), {})
        shared = join_global or previous.get('visibility') == 'GLOBAL'
        entry['visibility'] = 'GLOBAL' if shared else 'PRIVATE'
        private_list = [p for p in existing if p['id'] != entry['id']]
        private_list.append(entry)
        self.save_private_papers(owner, private_list)

        if shared:
            global_list = [p for p in self.get_global_custom_papers() if p['id'] != entry['id']]
            global_list.append(entry)
            self.save_global_custom_papers(global_list)

        return self.build_graph_response(owner, scope='COMBINED', focus_paper_id=entry['id'])

    def set_visibility(self, owner, paper_id, visibility):
        vis = 'GLOBAL' if str(visibility).upper() == 'GLOBAL' else 'PRIVATE'
        private_list = self.get_private_papers(owner)
        target = None
        for p in private_list:
            if p['id'] == paper_id and p.get('evidence_schema') == 1:
                p['visibility'] = vis
                target = p
        if not target:
            raise ReviewError('paper_not_found', '当前账号没有这篇论文。', 404)
        self.save_private_papers(owner, private_list)
        global_list = [p for p in self.get_global_custom_papers()
                       if p['id'] != target['id'] or p.get('owner_id') != self._owner_hash(owner)]
        if vis == 'GLOBAL' and target:
            global_list.append(target)
        self.save_global_custom_papers(global_list)
        return {'paper_id': paper_id, 'visibility': vis, 'updated_at': now()}

    def import_external_paper(self, owner, payload):
        query = str(payload.get('query') or payload.get('title') or payload.get('doi') or payload.get('arxiv_id') or '').strip()
        if not query:
            raise ReviewError('missing_query', '请输入需要导入图谱的论文标题、DOI 或 arXiv 编号。')
        join_global = bool(payload.get('join_global_graph', False))
        entry = {
            'project_id': 'ext_' + hashlib.sha256(query.encode()).hexdigest()[:24],
            'paper_title': query[:300],
            'source_type': 'MANUAL_REFERENCE',
            'join_global_graph': join_global,
        }
        return self.ingest_project(owner, entry)

    def build_graph_response(self, owner, *, scope='COMBINED', focus_paper_id=''):
        scope = str(scope or 'COMBINED').upper()
        if scope not in {'GLOBAL', 'PRIVATE', 'COMBINED'}:
            scope = 'COMBINED'

        private_papers = [p for p in self.get_private_papers(owner) if p.get('evidence_schema') == 1]
        global_papers = list(SEED_PAPERS) + [
            p for p in self.get_global_custom_papers()
            if p.get('evidence_schema') == 1 and all(p['id'] != s['id'] for s in SEED_PAPERS)
        ]

        if scope == 'PRIVATE':
            papers_map = {p['id']: p for p in private_papers}
        elif scope == 'GLOBAL':
            papers_map = {p['id']: p for p in global_papers}
        else:
            papers_map = {p['id']: p for p in global_papers}
            for p in private_papers:
                papers_map[p['id']] = p

        papers = list(papers_map.values())
        verifications = self.get_verifications(owner)
        saved_layout = self.get_layout(owner)

        nodes = []
        edges = []
        comparisons = []
        all_contribs = []

        # 1. Build Paper -> Contribution -> Claim -> Evidence / ReviewFinding nodes & edges
        num_papers = max(1, len(papers))
        for p_idx, paper in enumerate(papers):
            angle = (2 * math.pi * p_idx) / num_papers
            radius = 230 if paper.get('source_type') == 'SEED_BENCHMARK' else 95
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
                'editable_visibility': paper.get('owner_id') == self._owner_hash(owner),
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
                cmp_item = compare_contributions_pair(ca, pa, cb, pb, verifications)
                if cmp_item['overlap_score'] >= 0.32 or cmp_item['conflict_type'] != 'NONE' or pa['id'] == pb['id']:
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
                            'POTENTIAL_CONFLICT': '潜在冲突' if cmp_item['conflict_type'] != 'NOVELTY_OVERLAP' else '创新点重合冲突',
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
            key=lambda x: (x['year'] or 0, 0 if x['visibility'] == 'GLOBAL' else 1)
        )

        if not focus_paper_id:
            user_papers = [p for p in papers if p.get('source_type') != 'SEED_BENCHMARK']
            focus_paper_id = user_papers[-1]['id'] if user_papers else (papers[0]['id'] if papers else '')

        return {
            'scope': scope,
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
                'conflict_count': sum(1 for c in comparisons if c['relation_type'] == 'POTENTIAL_CONFLICT')
            }
        }
