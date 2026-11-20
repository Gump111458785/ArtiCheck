# Supervisor 后训练与评测

> 开源仓库包含训练接口：轨迹导出、LoRA SFT 脚本、`verl` 自定义 AgentLoop 与 GRPO 目标函数，覆盖本地 Planner 的 `check(cᵢ) / stop` 动作。完整的 Supervisor 与专业 Agent 训练流水线、权重和评测数据未开源。

## 1. 问题建模

把全局调度建模为**带硬约束的部分可观察序列决策问题（Constrained POMDP）**：

- **观察**：Runtime 生成的 9 层结构化状态（O1–O9，约 800–1,800 tokens）：任务与模式、材料与 PDF 覆盖、主张状态矩阵、创新点核对、执行与缓存、失败定位、补丁与重验状态、最近 5 步动作、剩余预算与合法动作。观察中不含任何真值标签。
- **动作**：12 类参数化动作——`EXTRACT_CLAIMS` · `INSPECT_CODE_AND_ENV` · `ASSESS_NOVELTY` · `PREPARE_EXPERIMENT_PLAN` · `RUN_CPU_SANDBOX` · `RUN_GPU_WORKER` · `AUDIT_EVIDENCE` · `DIAGNOSE_FAILURE` · `FIX_ENV_OR_SCRIPT` · `REQUEST_USER_MATERIAL` · `FINALIZE` · `ABSTAIN`。
- **约束**：合法动作集合由 Runtime 按当前状态计算；非法动作被拒绝、不产生副作用，并单独统计合法率。

**为什么只对 Supervisor 做 RL**：如果 5 个 Agent 同时训练，环境会持续变化，Supervisor 也分不清失败来自自己的决策还是下游 Agent。因此先用 SFT 训练专业 Agent，冻结成能力档案 ACP，再在固定环境中训练 Supervisor。

## 2. 模型与路由

| 模型 | 用途 |
|---|---|
| [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) | 主实验：专业 Agent SFT 与 Supervisor RL |
| [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) | 快速验证：动作协议、奖励与训练链路 |
| [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) | 跨代对照（非思考模式，训练与推理锁定同一聊天模板） |

三个模型均为 Apache-2.0 许可。**Model Router** 按 Agent 路由到云端 API 或本地 vLLM，记录每次调用的 token 数、时延与费用，并把原生 token IDs 与 log-prob 旁路写入 Trace Store。系统不采信 Agent 输出中自报的遥测字段。

## 3. 数据与防泄漏

- **按谱系聚类切分（80 / 10 / 10）**：同一论文、原作者仓库、fork、缺陷注入变体及其衍生问答，必须落在同一分片。共用公开数据集（如 CIFAR-10）不算同一谱系，只用于切分后的泄漏风险审计。
- **超参只在验证集上调**：奖励权重、阈值与提示词只在验证集上校准并冻结；冻结测试集不参与任何选择。轨迹导出器拒绝导出测试集数据。
- **真值与运行记录物理分离**：标注包单独存放，推理期间任何 Agent 都读不到。
- **三态 Rollout 环境**：
  - **Recorded Replay**：命中缓存时，确定性地回放真实执行结果。
  - **Live Sandbox**：未命中时，实时执行并写入缓存。
  - **Unsupported Transition**：纯离线测试中遇到未覆盖的转移时，干净地终止该分支，不伪造输出，也不记为模型失败。

  最终测试成绩全部在真实环境（Live）中跑出。

## 4. SFT

| 任务 | 内容 |
|---|---|
| S1 Reviewer | 主张、协议与计划生成，含多轮取证工具调用 |
| S2 Auditor | 盲抽证据与对抗复核；证据不足时诚实输出 `INCONCLUSIVE` |
| S3 Fixer | 经沙箱重跑验证的合法最小补丁 |
| S4 Relation Analysis | 经独立复核过滤后的用户确认 / 驳回关系 |
| Supervisor 冷启动 | 学会合法输出 12 类动作，为 RL 热身 |

- **数据**：教师模型在训练集上对每个任务采样 4–8 条候选，必须依次通过三道滤网才能入库：Schema 与确定性回放校验 → 沙箱或真值对照 → 人工抽检。刻意保留三类困难样本：诚实弃权、Fixer 拒绝修改不可修复的问题、Auditor 撤回误报。
- **训练**：只对 assistant 回复计算 loss，上下文与工具返回的 label 设为 `-100`；超长样本整条跳过并统计比例，不在 JSON 中间截断。
- **配置**：LoRA `r=16`、`alpha=32`、`dropout=0.05`，覆盖 all-linear；AdamW，学习率 `2e-5`，梯度累积 8；BF16 + 激活检查点；最大长度 4096。
- **选模**：在满足验证集 JSON 合法率与 `FPR ≤ 5%` 硬门槛的前提下，按宏 F1 择优选择检查点，不按最低训练 loss 选。合并 LoRA 后核对 vLLM 输出与合并前一致。

<a id="rl-stages"></a>

## 5. RL 训练阶段与对照条件

下表列出完整 Supervisor 流水线的阶段配置与验收条件。M1 起的 GRPO 阶段均使用 `token-mean` 聚合。比较 M1 与 M2 时固定任务子集、工具、采样预算和损失聚合，分别切换零方差组补采样与高侧裁剪。比较 M2 与 M3 时固定任务和模型，分别切换异步采样和重要性修正。课程难度变化另行评估。

[公开启动脚本](../scripts/train_grpo.sh)是本地 Planner 的一套组合配置，同时启用异步 vLLM rollout、`0.2 / 0.28` 非对称裁剪和 `token-mean`。脚本只启动一轮配置，动态补采样、截断重要性采样和课程切换的分布式配置属于完整训练流水线。公开脚本的配置只能说明启动参数，逐项对照的收益需要对应运行记录。

| 阶段 | 课程范围 | 技术 | 通过条件 |
|---|---|---|---|
| M0 | 经滤网核验的示范轨迹 | SFT 热身 | 动作合法率达到可用水平 |
| M1 | 局部恢复任务，2–4 步 | 同步 GRPO，每任务 8 条轨迹 | reward 稳定，不出现全部弃权 |
| M2 | 加入预算冲突与 Fixer 重跑，≤ 10 步 | DAPO：零方差组过滤并补批、非对称裁剪 `0.2 / 0.28` | 相比 M1 减少无效停止与恢复成本 |
| M3 | 混合难度 | 异步 vLLM rollout + 截断重要性采样（上限 `2.0`），区分 π_θ / π_old / π_behavior | 吞吐提升且策略不崩 |
| M4 | 完整双模式任务，≤ 14 步 | 扩展到 7B / 8B，3 个随机种子 | 通过第 6 节的统计检验 |

多轮交互全程使用原生 token IDs 拼接，不对文本重新分词；只有 Supervisor 自己生成的 token 参与梯度（`response_mask = 1`），观察与工具返回为 0。

**奖励**（终局时由隔离评测器对照真值计算）：

| 项 | 开源版（[`objective.py`](../articheck/training/objective.py)，本地 Planner） | Supervisor |
|---|---|---|
| 正确检出缺陷 | `+1` | `+1` |
| 误报正常主张 | `-2` | `-2` |
| 漏报缺陷 | `-0.5` | `-0.5` |
| 正确确认正常主张 | `+0.25` | `+0.25` |
| `INCONCLUSIVE` | `-0.1` | 材料确实不足 `+0.2`；资源充足却弃权 `-0.15` |
| 安全恢复（修复后重跑通过） | — | `+0.4` |
| 覆盖与创新核对 | — | `0 ~ +0.4` |
| 安全违规（越权补丁、绕过重验强行结束） | — | `-1.5` |
| 非法动作 | — | 每次 `-0.3` |
| 成本 | 每次调用 `0.02` + 每 token `1e-6`；按主张数归一 | CPU 沙箱、GPU（权重为 CPU 的 3 倍）、非缓存工具调用与生成 token 加权；命中缓存不计成本 |

误报罚分是检出奖励的 2 倍，用来压低 FPR。只按真正改变证据充分度或完成判定的终局结果计奖，不按工具调用次数给中间奖励，避免模型刷调用。

<a id="evaluation"></a>

## 6. 评测协议

**三层基准**

| 层级 | 基准 | 评测内容 |
|---|---|---|
| 公开基准 | CORE-Bench（HAL Harness）、PaperBench JudgeEval | 代码复现成功率；判定与人类专家的一致性。严格遵循官方切分，官方测试论文不进入训练 |
| 项目专项 | ArtiCheck-Claims、Recovery & FixerBench、PaperTree-RelBench | 缺陷发现；失败定位与安全修复；贡献出处与关系分类 |
| 端到端 | ArtiCheck-E2E Dual-Mode | 两种审查目的的四层验收、创新点核对、发布门禁与耗时费用 |

注入缺陷只用于可控消融，和自然缺陷分开建档、分开报数。

**对照组**：所有系统使用同一基座、同一套工具和同一预算上限。

| 编号 | 系统 |
|---|---|
| B0 | 单轮长上下文 LLM |
| B1 | 固定流水线 + 同一基座 |
| B2 | 开源版当前链路 |
| B3 | 目标架构 + 规则调度 |
| B4 | 目标架构 + 仅靠 prompt 的 Supervisor |
| B5 | 目标架构 + SFT Supervisor（另设 B5-RS：与 GRPO 同等采样预算的拒绝采样 SFT） |
| B6 | 目标架构 + SFT + GRPO Supervisor |

另做 5 组消融：盲抽开 / 关、失败定位输入、Fixer 安全防线、奖励各组成项、等预算拒绝采样 vs GRPO。

**指标**：
- 判定质量：宏 F1、召回率、FPR、Selective Error Rate（只统计给出了明确结论的主张）。
- 弃权是否诚实：Attempted Coverage、Resolved Coverage、Justified Abstention Rate。全部判 `INCONCLUSIVE` 不算有效覆盖。
- 发布安全：未经验证就放行的报告比例、Fixer 回归率（两者目标都是 0）。
- 效率：动作合法率（目标 ≥ 99%）、非缓存调用次数、沙箱耗时、token 与费用。

**统计**：同一仓库的主张相互关联，不能当作独立样本，因此以仓库谱系为单位做配对聚类 Bootstrap（10,000 次），二元比例附 Wilson 区间与 McNemar 检验，至少 3 个训练种子。

详细协议见 [Benchmark 规范](BENCHMARKS.md) 与 [后训练方案](POST_TRAINING.md)。
