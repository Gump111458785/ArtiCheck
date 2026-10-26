# Planner 后训练路径

## 状态与接口版本

CPU 数据过滤和原生轨迹契约已测试。当前机器没有 PyTorch/CUDA、Docker、vLLM 或 verl，未实际训练 7B 模型。`train_sft.py`、`verl_loop.py` 与启动脚本属于可审查的训练基础代码，首次 GPU 集成需要验证依赖和运行时兼容性。

verl 适配参考提交：[0bd668c1aa7b63c5f174f7dcb1c5de12e0c74a0b](https://github.com/verl-project/verl/tree/0bd668c1aa7b63c5f174f7dcb1c5de12e0c74a0b)。参考 API 为 `AgentLoopBase`、`AgentLoopOutput`、`server_manager.generate` 与 Continuous Token 的 `ct_*` 方法。后续升级 verl 时需重新核对这些接口。

## 1. 收集教师轨迹

使用独立强模型作为 Planner：

```bash
export ARTICHECK_API_KEY=your-key
python -m articheck run --task data/task.json --output runs/teacher-001 \
  --planner model --base-url https://your-provider.example/v1 \
  --model your-teacher-model --policy-version teacher-model-revision \
  --input-price 1 --output-price 4
```

价格是占位示例，需替换成所选服务实际计价。普通兼容 API 的文本足够用于 SFT；不要因缺失 token IDs 而重新分词伪造 RL 轨迹。预算只限制此进程记录的调用，不能替代服务端账号额度限制。

对每个 run 独立核对主张、工具证据和动作合理性。接受清单 JSONL 格式：

```json
{"run_id":"actual-run-id","accepted":true,"reviewer":"reviewer-01","source":"human","teacher_model":"actual-teacher-model"}
```

`source` 可以是 human 或 rule；rule 只应来自与 Planner 隔离、经过验证的 oracle。模型自称“正确”不算接受。拒绝采样需对同一任务生成多个独立 output 目录，由外部评审筛选后再导出；当前不自动并行付费调用教师。

```bash
python -m articheck export-sft --traces runs/teacher-001/trace.jsonl \
  --approvals data/accepted-runs.jsonl --output data/planner-sft.jsonl
```

导出仅保留成功停止、JSON 动作有效、模型身份与外部接受记录一致的 Planner turn；保留其完整多轮上下文。它不自动保证科学正确性。

## 2. LoRA SFT

在合适的 CUDA/PyTorch 环境按官方指导安装依赖，再安装本项目训练 extras：

```bash
python -m pip install -e '.[train]'
python scripts/train_sft.py --data data/planner-sft.jsonl \
  --model Qwen/Qwen2.5-7B-Instruct --output checkpoints/planner-sft
```

脚本只对最后一条 assistant 回复计算损失，prompt 标签为 -100。检查聊天模板的 token 前缀一致性；超长样本整条跳过，避免截断 JSON 动作。启用 LoRA 与激活检查点。显存需求和速度未实测。此输出是 LoRA adapter，后续 GRPO 或 vLLM 启动前需使用 PEFT 的 `merge_and_unload()` 合并到基础模型，或者另外配置兼容的 adapter 加载方式。

## 3. 构建 RL 数据

为多份**独立原始仓库**准备 task manifests 和标签，再运行：

```bash
python scripts/prepare_rl.py --tasks data/repo-a/task.json data/repo-b/task.json \
  --labels data/labels.jsonl --output data/rl
```

真实数据数量应远多于两个仓库；此命令仅展示输入格式。按 repo_id 划分 train/validation/test。ground_truth 仅进入 reward metadata，prompt 只包含主张、已检查集合、已取得判定和剩余预算。task_path 和 artifact 必须在所有 rollout worker 上可访问。

## 4. GRPO 基础启动

先按照固定 verl 版本的官方安装步骤准备 CUDA、vLLM、FSDP 和 Ray 环境，并将 ArtiCheck 包安装到所有 worker。准备可访问的 Docker daemon 和预先构建的 artifact 镜像。

```bash
export MODEL_PATH=/absolute/path/to/merged-sft-model
export TRAIN_FILE=/absolute/path/to/train.parquet
export VAL_FILE=/absolute/path/to/validation.parquet
NGPUS=2 bash scripts/train_grpo.sh
```

`NGPUS=2` 是启动配置示例，不是已验证的最低显存要求。自定义 AgentLoop 让模型只输出 check/stop；probe 和核查规则作为环境反馈。使用 verl 原生采样 token，Continuous Token 对齐上下文，模型 token 的 response_mask 为 1，环境观察为 0。terminal reward 同时考虑漏报、误报、弃权、调用数和生成 token；标签不放入观察。

启动脚本启用 GRPO、clip-higher、FSDP2、LoRA、激活检查点、按 token 的动态批处理和分块计算 log-prob 的长度预算。它**没有**接入 DAPO 动态补采样、截断重要性采样或课程阶段切换。`objective.py` 提供这些机制的独立基础函数，不能把存在函数等同于分布式训练已完成。

## 5. 原生训练轨迹契约

vLLM HTTP native 模式要求 `/tokenize` 返回 prompt IDs，`/v1/completions` 支持 `return_token_ids` 和 `logprobs`。保留采样器实际 token IDs、逐 token behavior log-probs 和明确 checkpoint 版本。实际服务若不支持则报错，禁止降级成合成 token。

```bash
python -m articheck export-rl --traces runs/planner/trace.jsonl --output data/native-planner.jsonl
```

该导出用于离线审计和后续数据处理，不会自动替代 verl 的在线采样器。普通 API 返回的文本轨迹导出会失败，这是有意的完整性检查。

## 后续实验

1. 冻结真实仓库隔离数据和人工真值，比较外部 baseline、fixed Planner、SFT Planner、GRPO Planner。
2. 在验证集校准误报约束阈值，固定后评测测试集；报告不确定/弃权占比。
3. 分别消融误报惩罚、成本项、课程、clip-higher、动态采样和 IS。
4. 在同一硬件分别测量 FSDP2/LoRA、检查点、动态批和前缀缓存的收益。
5. 最后再接入 AWQ/FP8 并测量精度、延迟、GPU 成本。当前没有量化实现或数值收益。
