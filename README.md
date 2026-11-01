<div align="center">

# ArtiCheck

**让论文里的每一条实验主张都有执行证据。**

面向 Artifact Evaluation 与投稿前自查的论文复现预审系统。<br>
从论文、作者代码和数据出发，重建环境、执行实验、独立核对指标，生成逐主张可追溯的报告。

[![CI](https://github.com/Gump111458785/ArtiCheck/actions/workflows/ci.yml/badge.svg)](https://github.com/Gump111458785/ArtiCheck/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Version](https://img.shields.io/badge/source-v0.1.0-444444)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CPU case](https://img.shields.io/badge/LIBLINEAR-15_runs_verified-227755)](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889691677)

[打开交互预览](https://articheck-workbench.soft-bun-8328.chatgpt.site) · [快速开始](#quickstart) · [查看复现案例](#case)

</div>

![工作台界面导览：执行中心、角色协作与案例详情](docs/assets/workbench-tour.gif)

*三个现有工作台页面的截图轮播，展示各工作视图；不是一次任务的连续执行录像。交互预览仅限获授权账号，真实执行通过本地工作台完成。*

[核心能力](#capabilities) · [系统架构](#architecture) · [实测结果](#results) · [Planner 后训练](#training) · [路线图](#roadmap) · [文档](#docs)

## 三十秒看懂

| 面临的问题 | ArtiCheck 的处理方式 | 可核对的证据 |
|---|---|---|
| 论文中的数字与代码、数据和配置之间缺少明确对应 | 将实验拆成主张，绑定原文、执行入口与观测值 | [逐主张报告](docs/smoke/metric-defect-report.md) |
| 实验运行成功后，仍需判断它验证了什么 | 分开验收运行、环境重建、论文训练协议和主要结论 | [LIBLINEAR 分层报告](web/dist/samples/liblinear-reproduction.json) |
| 多次运行的材料、日志和人工意见难以追溯 | 固定材料与计划版本，保存阶段证据，追加复核记录 | [15 次运行 / 60 个阶段的 CI 证据](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889691677) |

<a id="case"></a>

## 旗舰案例：LIBLINEAR / news20

以 **LIBLINEAR（JMLR 2008）作者代码和公开 news20 数据**为输入，完成 CPU 环境重建、数据准备、训练、预测和独立指标重算。三种方法设置、五个划分种子，共产生 **15 次运行与 60 个阶段证据**。

```mermaid
flowchart LR
    A["作者代码与公开数据<br>固定提交 / 下载来源"] --> B["材料校验<br>SHA256 / 来源清单"]
    B --> C["禁网 Docker 构建<br>镜像与安装证据"]
    C --> D["训练<br>配置 / 种子 / 模型产物"]
    D --> E["预测<br>逐样本输出"]
    E --> F["独立重算<br>指标与原始计数"]
    F --> G["统计验收<br>多次运行 / 分层报告"]
```

| 实测项目 | 结果 | 证据 |
|---|---:|---|
| 方法设置 × 划分种子 | 3 × 5 = **15 次运行** | [运行明细](web/dist/samples/liblinear-reproduction.json) |
| 阶段记录 | **60 个** | [执行 CI](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889691677) |
| L2-SVM 准确率均值 | **96.76%** | [结果与统计](web/dist/samples/liblinear-reproduction.json) |
| 准确率样本标准差 | **0.31 个百分点** | 同上，5 个划分种子 |
| 执行器墙钟时长 | **147.41 秒** | [计时与资源口径](docs/EXECUTION_EVIDENCE.md) |
| 全阶段子进程峰值 RSS 最大值 | **366.4 MiB** | 同上 |
| 容器外内存采样峰值 | **370.6 MiB** | 30 / 60 阶段有容器外采样 |

准确率的波动来自本案例的五次重新划分，不是原论文成绩的置信区间。时长不含准备脚本下载及基础镜像拉取；GPU 峰值与费用未测量。

### 验收结果：明确区分“运行完成”与“论文结论成立”

| 核对项 | 本案例结果 | 判定依据 |
|---|---|---|
| 执行完成 · `run` | ✅ 通过 | 15 次运行完成，保留 60 阶段证据 |
| 环境重建 · `environment_rebuilt` | ✅ 通过 | 固定基础镜像，记录构建与环境检查 |
| 独立指标与控制核对 | ✅ 已记录验证证据 | 预测结果独立重算；新增 LR 控制与正则化消融有实际配置与公平性检查 |
| 论文训练协议 · `training` | ❌ 未通过 | 使用现代作者代码、80/20 seeded split，原始划分 ID 未找回 |
| 论文主要结论 · `conclusion` | ❌ 未通过 | Figure 1、rcv1、Pegasos/SVMperf 及论文调参与计时曲线未完整覆盖 |

**报告保留通过项，也直接暴露复现范围与论文协议的差距。** 新增控制项只用于本案例核对，不替代原论文基线；本案例不计作整篇论文复现成功。

[案例来源与完整运行命令](examples/liblinear_case/README.md) · [证据归档](web/dist/samples/liblinear-reproduction.json) · [执行 CI](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889691677)

<a id="capabilities"></a>

## 核心能力

| 能力 | 已实现的行为 | 验证与实现 |
|---|---|---|
| ✅ 主张级核查 | 六角色协作，核对指标、样本重叠和训练预算；每条判定引用执行证据，证据不足保留 `inconclusive` | [报告](docs/smoke/metric-defect-report.md) · [流水线](articheck/pipeline.py) |
| ✅ 受控执行 | Docker 禁网、只读挂载、非 root、移除 capabilities，限制 CPU、内存、进程及输出；工具 / token / 时间 / 费用预算与执行缓存 | [沙箱](articheck/sandbox.py) · [Docker CI](https://github.com/Gump111458785/ArtiCheck/actions/workflows/ci.yml) |
| ✅ 可审计执行器 | 不可变材料工作区、PDF / ZIP / 计划指纹、阶段与种子矩阵、产物与资源记录 | [执行引擎](docs/REPRODUCTION_ENGINE.md) · [实现](articheck/reproduction/) |
| ✅ 分层验收 | 结合多次运行、统计与覆盖证据，分别判断运行、环境、训练协议及主要结论 | [完成验收清单](docs/REPRODUCTION_COMPLETION_CHECKLIST.md) |
| ✅ 可视化工作台 | PDF / 代码材料导入、主张确认、服务器资源核对、执行中心、角色协作与证据复核；25 条 API 路径、29 个操作 | [界面与模块对应](docs/REVIEW_WORKSPACE.md) · [OpenAPI](web/dist/openapi.json) |
| ✅ 训练轨迹契约 | 保留采样器提供的 token IDs、行为 log-prob 与策略版本；外部接受后的教师轨迹可导出 SFT，缺失原生 token 时拒绝 RL 导出 | [轨迹契约与测试范围](docs/TRAINING.md#5-原生训练轨迹契约) · [导出实现](articheck/training/export.py) |

✅ 表示该行描述的工程行为已有结果或测试依据；训练轨迹字段与过滤经过测试，真实模型服务、GPU 采样及训练收益单独验收。

### 从材料到审查的工作台

论文项目按「论文与代码 → 实验覆盖 → 复现条件 → 服务器核对 → 短时核查主张与配置 → 完整实验 → 评估结果」组织。全局执行中心统一列出任务，打开单次记录后查看对应角色、阶段和证据；复核意见追加保存，不覆盖原始结论。

![开始页：新建评估、继续项目与公开案例](docs/assets/home-desktop.jpg)

首次进入显示开始页，可新建评估、续接浏览器内的个人项目，或直接打开 LIBLINEAR 公开案例。点击侧栏「开始」或品牌标识可随时返回。[开始页设计与模块对应](docs/HOME_SCREEN.md)。

![执行中心：按来源、状态和执行方式检索任务](docs/assets/execution-center.jpg)

<details>
<summary>查看角色协作与案例验收界面</summary>

![六角色协作：输入输出契约与实际事件](docs/assets/role-workspace.jpg)

![案例验收：实际指标、执行证据与分层结果](docs/assets/execution-detail.jpg)

</details>

PDF 正文与 ZIP 在浏览器准备，完整实验可显式导入本地材料工作区。候选主张需人工确认，任意第三方仓库的执行入口需要适配；[八项复现条件的实现与边界](docs/IMPLEMENTATION_STATUS.md)。

<a id="architecture"></a>

## 系统架构

```mermaid
flowchart TB
    UI["工作台 / CLI<br>论文材料 · 主张确认 · 资源核对 · 审查"]
    subgraph EXEC["核查与复现层 · 已验证"]
        direction LR
        L["LiteratureReader<br>文献主张"] --> P["Planner<br>选择检查项 / 停止"]
        C["CodeInspector<br>代码清单"] --> P
        P --> X["ExperimentRunner<br>预算 / Docker / 缓存"]
        X --> A["CrossAuditor<br>逐主张判定"]
        A --> P
        P --> R["Reporter<br>报告 / 证据 / 轨迹"]
        FULL["完整实验执行器<br>冻结计划 / 阶段矩阵 / 分层验收"]
    end
    subgraph DATA["评测与数据层 · 协议与内置基准已验证 / 多仓库数据在规划"]
        D["受控缺陷注入 → 仓库分组划分<br>宏 F1 / 误报约束阈值 / 人工反馈"]
    end
    subgraph TRAIN["Planner 训练层 · 代码就绪 / GPU 集成待验收"]
        T["教师轨迹过滤 → LoRA SFT → verl GRPO<br>原生 token / behavior log-prob / policy version"]
    end
    UI --> L
    UI --> C
    UI --> FULL
    R --> D
    R -.-> T
    D -.-> T
    T -. "待验收策略" .-> P
    classDef ready fill:#eaf3ef,stroke:#42745e,color:#173c2c
    classDef partial fill:#f5f1e6,stroke:#8c7848,color:#54451f
    classDef pending fill:#f2f2f2,stroke:#777,stroke-dasharray:5 5,color:#444
    class L,C,P,X,A,R,FULL ready
    class D partial
    class T pending
```

短时核查中，文献读取与代码检查通过 asyncio DAG 并发，Planner 驱动检查与停止循环；固定 Planner 是默认策略。完整实验由独立的冻结计划执行器运行，界面展示它的实际阶段，不生成虚构的六角色活动。[执行中心的数据与模块对应](docs/EXECUTION_CENTER.md)。

<a id="quickstart"></a>

## 快速开始

Python 3.10+，macOS 或 Linux。内置受控缺陷基准无需 API key、GPU 或 Docker。

**1. 获取源码并安装**

```bash
git clone https://github.com/Gump111458785/ArtiCheck.git
cd ArtiCheck
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

**2. 运行内置核查**

```bash
python -m articheck demo --sandbox local --output runs/demo
```

执行同一仓库的 clean 与三个单缺陷版本：指标计算、数据划分、baseline 训练预算。`local` 直接执行主机上的可信内置代码；再次运行请使用新的输出目录。

**3. 查看结果**

`runs/demo/metrics.json` 汇总指标；每个版本目录包含 `report.md`、`report.json` 与 `trace.jsonl`。逐主张真值与得分分别保存在 `labels.jsonl`、`scores.jsonl`。

### 启动前后端一体的本地工作台

<a id="workbench"></a>

```bash
python -m articheck.workbench --port 8787
```

打开 **http://127.0.0.1:8787**。同一 Python 服务提供界面和 API，页面提交真实任务、读取执行进度、报告与反馈，数据保存在 `runs/workbench/`。HTTP API 当前支持固定 Planner，模型服务与训练使用 CLI；托管预览使用归档回放。

### 核查自己的 artifact

按 [task.json 示例](examples/task.json) 声明本地仓库、主张和输出 JSON 的 probe，准备好镜像后运行：

```bash
docker pull python:3.11-slim
python -m articheck run --task examples/task.json --output runs/review
```

替换任务文件即可绑定自己的执行入口；额外依赖需要预构建镜像。任务字段与 probe 协议见 [数据与执行指南](docs/DATA.md)。

<a id="results"></a>
<a id="benchmarks"></a>
<a id="example"></a>

## 实测结果

| 验证对象 | 范围与结果 | 证据 |
|---|---|---|
| 公开 CPU 案例 | LIBLINEAR / news20，15 次运行、60 个阶段；L2-SVM 准确率 96.76%，样本标准差 0.31 个百分点 | [案例 CI](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889691677) · [报告](web/dist/samples/liblinear-reproduction.json) |
| 内置受控缺陷基准 | 单仓库 4 个版本、12 条主张；FixedPlanner + 规则核查：TP=3、FP=0、TN=9、FN=0，宏 F1=1.000，问题召回率 100%，误报率 0% | [原始结果](docs/smoke/metrics.json) · [问题报告](docs/smoke/metric-defect-report.md) |
| Python 工程测试 | 121 项：本地 117 项通过，4 项 Docker 专项在 CI 执行；CI 覆盖 Python 3.10–3.12 | [验证记录](docs/VALIDATION.md) · [CI](https://github.com/Gump111458785/ArtiCheck/actions/runs/41014456114) |
| 前端测试 | 72 项通过，覆盖开始页、材料、验收、资源、执行中心和审查状态 | [测试代码](tests/frontend/) · [CI](https://github.com/Gump111458785/ArtiCheck/actions/runs/41014456114) |

内置基准阈值为 0.5，正例 3 条、负例 9 条，仅验证工程链路，不能外推到真实论文或独立仓库。ArtiCheck-Claims、CORE-Bench、JudgeEval 尚无正式成绩；[评测协议与公平对照要求](docs/BENCHMARKS.md)。

<a id="training"></a>

## Planner 后训练

研究问题是：**当证据获取成本不同、执行预算有限时，Planner 应先检查哪个实验、何时停止？** 训练对象是 `check(claim_id)` / `stop` 决策；执行器与核查规则提供环境反馈。

```mermaid
flowchart LR
    A["轨迹与外部接受过滤<br>已验证"] --> B["LoRA SFT<br>代码就绪"]
    B -.-> C["多候选拒绝采样 SFT<br>手工编排 / 训练待验收"]
    C -.-> D["verl AgentLoop + GRPO<br>代码就绪 / GPU 待验收"]
```

| 里程碑 | 现有交付 | 升级为“已验证”的验收条件 | 状态 |
|---|---|---|---|
| 训练轨迹与接受过滤 | 原生 token 完整性检查、完整多轮上下文、独立接受清单与导出 | CPU 契约和过滤测试已通过；真实采样服务另行集成 | ✅ 已验证（契约与过滤） |
| LoRA SFT | [训练脚本](scripts/train_sft.py)，仅 assistant 动作计损失、激活检查点 | 完整 GPU 训练日志、检查点、冻结测试集评测 | 🧱 代码就绪 |
| GRPO Planner | [verl AgentLoop](articheck/training/verl_loop.py)、[启动配置](scripts/train_grpo.sh)、质量与成本奖励 | 三种子、等预算对照拒绝采样 SFT，保存曲线与置信区间 | 🧱 代码就绪 |
| DAPO / IS 集成 | [独立目标函数](articheck/training/objective.py)；clip-higher 已有启动配置 | 动态补采样、截断 IS 接入分布式循环并完成消融 | 🎯 规划（完整集成） |
| 推理与训练效率 | FSDP2 / LoRA / 动态批配置及 [vLLM 启动入口](scripts/serve_vllm.sh) | 同硬件同负载开关对照，质量指标不回退；量化另行实现 | 🎯 规划（性能验收与量化） |

训练配置不代表实际训练结果。目前没有 SFT / GRPO 增益、实卡显存收益、量化成绩或付费教师蒸馏数据规模。[训练步骤、依赖版本与接口边界](docs/TRAINING.md)。

| 待实测指标 | 衡量方法 | 结果 |
|---|---|---|
| 宏 F1、误报率与约束下召回率 | 独立仓库测试集；验证集固定阈值，并报告弃权比例 | 待实测 |
| 显存与训练吞吐 | 同一 GPU 与 token 负载，逐项开关对照 | 待实测 |
| 单篇延迟与成本 | 固定主张范围、硬件与预算，记录执行时间、API 用量和计价来源 | 待实测 |

<a id="roadmap"></a>

## 路线图

状态：✅ 已验证 · 🧱 代码就绪 · 🎯 规划。🧪 实验中仅在有正在运行的真实实验与日志时使用。

| 阶段 | 交付与验收门槛 | 状态 |
|---|---|---|
| v0.1.0 · 核查与复现 | 主张级流水线、前后端工作台、Docker 执行、公开 CPU 案例与证据复核 | ✅ 已验证，源码版本 |
| v0.2 · 决策环境与多仓库评测 | 先证明同预算下不同策略产生质量 / 成本差异；冻结 ≥8 个独立原始仓库，验证 / 测试均有正负例；完成固定工作流 + 7B 与单 Agent 对照 | 🎯 规划 |
| v0.3 · SFT / GRPO Planner | 训练代码已有；用冻结数据完成 GPU SFT、三种子 GRPO 及等预算对照 | 🧱 代码就绪，实验待验收 |
| v0.4 · 效率与部署 | 测量训练、缓存和量化的质量 / 显存 / 吞吐 / 延迟 / 成本；完成部署验收 | 🎯 规划 |

更新日期：**2026-11-01**。后续版本按验收结果推进，尚未设定发布日期。结果、配置和日志归档后才更新状态与成绩；当前源代码版本号不代表已创建 GitHub Release。

<a id="docs"></a>

## 文档与开发

| 入口 | 内容 |
|---|---|
| [使用与数据](docs/DATA.md) | task.json、probe、执行、缓存、受控缺陷、划分与反馈 |
| [工作台与 API](docs/WORKBENCH.md) · [执行中心](docs/EXECUTION_CENTER.md) | 本地运行、材料准备、角色与事件、HTTP / SSE、前后端对应 |
| [复现执行器](docs/REPRODUCTION_ENGINE.md) · [完成验收清单](docs/REPRODUCTION_COMPLETION_CHECKLIST.md) | 材料身份、完整实验、资源测量、统计与分层验收 |
| [Benchmark 协议](docs/BENCHMARKS.md) · [Baseline 来源](docs/BASELINE.md) | 数据隔离、误报约束、对照公平性、报告导入与许可 |
| [Planner 训练](docs/TRAINING.md) | 教师接受过滤、原生轨迹、LoRA SFT、verl GRPO |
| [验证记录](docs/VALIDATION.md) · [八项能力核对](docs/IMPLEMENTATION_STATUS.md) | 测试、CI、实际完成范围与剩余验收项 |

```bash
python -m articheck --help
python -m unittest discover -s tests -v
node --test tests/frontend/*.test.mjs
```

开发入口：[核查流水线](articheck/pipeline.py)、[六角色](articheck/roles.py)、[Planner](articheck/planner.py)、[完整实验](articheck/reproduction/)、[本地工作台服务](articheck/workbench.py)、[前端](web/dist/)、[训练适配](articheck/training/)。问题与适配建议可提交至 [Issues](https://github.com/Gump111458785/ArtiCheck/issues)，附去除敏感信息后的任务配置与日志。

## 来源与许可

业务 baseline 参考 [Paper Reproducibility Agent](https://github.com/1a1a11a/2026_paper_reproduce)，通过独立进程与 JSON 报告对接，未分发其源码；[固定参考版本与许可说明](docs/BASELINE.md)。Planner 训练接口参考 [verl](https://github.com/verl-project/verl)，推理服务提供 [vLLM](https://github.com/vllm-project/vllm) 接入入口。

PDF 阅读器随仓库分发 PDF.js 6.4.299（Apache-2.0）；字体与 CMap 各自许可见 `web/dist/vendor/pdfjs/`。ArtiCheck 原创代码采用 [MIT License](LICENSE)，外部工具、模型和数据遵循各自许可。
