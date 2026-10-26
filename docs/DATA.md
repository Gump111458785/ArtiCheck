# 数据、证据和评测协议

## 任务输入

`examples/task.json` 给出最小输入。`repo` 相对 task 文件解析；`repo_id` 必须标识原始仓库谱系，所有缺陷版本、分支和复制品共享同一 ID。每条主张需唯一 `id`、`text`、`kind`、人工审核后的 `spec`。

支持的主张：

- `metric`：probe JSON 中的数值与 `expected ± tolerance` 比较。
- `split_disjoint`：非空训练与测试样本 ID 列表的交集检查。
- `baseline_equal`：方法和 baseline 的训练步数一致性检查。

Task 的 `probe` 是默认执行 argv。Claim 可以另设 `probe`，允许 Planner 选择对应实验；相同 argv 在一次核查中共享证据。命令不经 shell 拼接。MVP 不自动生成或信任模型产生的任意 shell 命令。

Probe 的 stdout 必须是单个 JSON object；非零退出、超时、输出溢出、JSON 无效、字段缺失或类型无效都产生 `inconclusive`。当前核查器信任经审核的 probe；不包含独立重实现指标、真实性取证或反硬编码检测。因此报告必须限定为“在提供的 probe 下观察到什么”。

## 缓存与隔离

缓存仅在 task 显式设 `cacheable=true` 时启用。只有固定种子、确定性的实验才应开启。缓存键包含源码内容摘要、argv、Docker 镜像实际 ID 或 local Python 身份、执行限制。运行中源文件改变会撤销最终判定。

Docker 模式无网络、只读根文件系统和 artifact 挂载、非 root、去 capabilities、限制进程/内存/CPU。需要安装依赖时，用户应预先构建可信镜像并通过 `--image` 指定。当前模式不支持将结果写回 artifact 目录；probe 应向 stdout 输出核查结果。

local 模式会清理子进程环境变量，但不提供文件系统、网络或系统调用隔离，只用于本仓库可信教学样例。Docker 当前本地未实测，CI 为其提供独立测试步骤。

## 缺陷注入与划分

当前 injector 是教学 artifact 的显式 adapter，可分别切换 macro/micro averaging、注入数据 ID 重叠、缩减 baseline 步数。每个变体只有一个已知缺陷；其他主张保留为负样本。注入标签放在 artifact 目录外，不传给 Planner。

真实仓库扩展需要：记录原始 commit；独立验证 clean 版本；编写精确 patch；确认缺陷确实改变目标行为；让人工或独立 oracle 核对 label。不得把一次脚本退出失败直接作为科学缺陷标签。

`split` 按 SHA-256(seed + repo_id) 做 80/10/10 分组。一个仓库的四个变体仍只算一个仓库，不能构成独立训练/验证/测试集。样例出现空 validation/test split 是预期行为，不能通过修改同源变体的 repo_id 填满。

## 评测输入

`evaluate` 接受 JSONL，每行至少包含 `label: 0|1`、`score: float`，可带 `verdict`。`1` 为主张存在问题。

宏 F1 对正负两个类别的 F1 取平均。误报率为 FP/(FP+TN)。召回率为 TP/(TP+FN)。`inconclusive` 的 issue score 为 0，作为负预测参与分母；同时报告弃权率。单类数据不能用于误报约束阈值校准。

先用 validation 选择满足误报率上限且召回最高的阈值，再固定阈值评价 test。程序不会自动阻止用户传错数据文件；应在实验登记中保存 split 清单和摘要。当前规则 score 只有 0/1，不能作为校准后的概率。

报告保存单篇耗时、工具调用、模型 token 数与按配置价格计算的 API 费用。缓存命中运行不能与冷启动运行混合汇报性能；GPU 租赁、镜像准备、存储等成本需另计。

## 人工反馈

```bash
python -m articheck feedback --report runs/example/report.json \
  --output data/feedback.jsonl --claim-id C1 --label 0 \
  --reviewer reviewer-01 --reason '人工独立重算后确认该主张成立'
```

保留原始判定与更正理由，将误报、漏报和不确定样本标记为困难样本候选。反馈是可追加的审查记录；再次导出训练集前应审核冲突标注和仓库隔离，当前不会自动修改既有标签或启动训练。
