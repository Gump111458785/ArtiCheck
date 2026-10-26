# 验证记录

验证日期：2026-10-26。环境：macOS，Python 3.12.14。核心包已在独立虚拟环境以 editable 方式安装，并验证 `articheck` console entry point。

## 本地已通过

- `python -m unittest discover -s tests -v`：28 项测试通过。
- `python -m compileall -q articheck scripts`：源码可编译。
- `bash -n`：三个 shell 启动脚本语法通过。
- `articheck demo --sandbox local --output runs/release-demo`：四组受控任务端到端通过。

测试覆盖：三类缺陷和 clean 对照、DAG 依赖与环检测、预算耗尽、停止后未检查主张、不同 probe 的预算共享、缓存命中与失效、随机任务禁用缓存、仓库隔离划分、手算评测指标、缺失证据与非法数值、上游报告映射、外部 SFT 接受记录、原生 token 对齐和禁止伪造、人工反馈、环境清理、进程超时与输出限额。

## 受控样例结果

| 版本 | 指标主张 C1 | 划分主张 C2 | 基线主张 C3 |
|---|---|---|---|
| clean | supported | supported | supported |
| metric_average | issue | supported | supported |
| split_leakage | supported | issue | supported |
| baseline_budget | supported | supported | issue |

合计 TP=3、FP=0、TN=9、FN=0，固定规则阈值为 0.5。该分数来自用于开发验证的 1 个原创教学仓库及其变体，**不是独立测试集，不用于宣称真实论文性能**。

保存的实际输出：

- [metrics.json](smoke/metrics.json)
- [指标缺陷报告](smoke/metric-defect-report.md)
- [clean 报告](smoke/clean-report.md)

## 尚未本地验证

- Docker 容器执行：当前机器未安装 Docker。GitHub Actions 已配置 Ubuntu Docker 冒烟测试，应以实际 CI 结果为准。
- 真实 baseline PDF/API 端到端运行：没有调用付费模型；只核对指定上游提交的 CLI 和报告结构。
- 真实 vLLM 原生 token HTTP 接口：本地测试使用响应契约模拟。
- SFT、verl 自定义 AgentLoop、GRPO 分布式训练和 `grpo_loss` 的 PyTorch 数值/梯度行为：当前没有 PyTorch/CUDA；代码和配置已提供，仍需在 GPU 环境验证。
- DAPO 动态补采样与 IS 接入、AWQ/FP8、真实人工试用、真实论文数据、显存/吞吐/耗时/成本收益：未完成，不应写成简历已达成指标。
