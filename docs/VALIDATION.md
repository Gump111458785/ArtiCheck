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

## GitHub CI

首个完整代码提交的 [GitHub Actions 运行](https://github.com/Gump111458785/ArtiCheck/actions/runs/40318860573) 已全部通过：Ubuntu 上 Python 3.10、3.11、3.12 的核心测试与 CLI 样例，以及 Python 3.11 job 的 Docker 冒烟测试。它验证教学任务的容器路径，不代表真实论文或 GPU 训练通过。


## 可视化工作台验证（2026-10-27）

工作台增加后，本地总计 40 项测试通过。新增覆盖真实 HTTP 核查、主张修改、反馈追加、数据持久化、运行取消、Host/Origin 与工作区范围限制、报告下载，以及 SSE 的事件与终态通知。

浏览器实操已验证：创建任务并调用 Python 核查、查看指标差异、写入复核记录、浏览 API 契约，以及独立样例回放的停止操作。已检查默认窄屏与桌面双栏布局。工作台不启动模型训练，托管预览只回放教学证据。

## 2026-10-28 工作台界面改版

40 项测试通过；检查字体资源类型与 WOFF2 签名。五视图 × 三尺寸通过 Taste Skill 渲染检查（0 FAIL），并完成真实本地核查、人工反馈、搜索、导出、移动端详情与回放停止联调。检查例外与字号提示见 [界面设计记录](WORKBENCH_DESIGN.md)。


## 2026-10-28 论文材料与执行连接

- Python：48 项通过，包括真实 HTTP 路由、PDF/MJS 静态资源类型、manifest 指纹变化拒绝、资源预检和受限 GitHub 目录请求。
- 前端：13 项 Node 测试通过，覆盖 GitHub URL、ZIP 路径与目录结构、F1 名称数字误识别、原文与确认、唯一执行绑定、PDF 指纹来源、未执行不得判定、取消结果、目录限流及材料变更失效。
- 浏览器：实际导入两页 PDF 与 3 文件 ZIP，解析后人工确认 1 条主张并持久化；本地模式读取 upstream `1a1a11a/2026_paper_reproduce` 的 51 文件与固定提交 `dffac1885dbca1aff9b28d79916140b8af71dedf`。读取成功只证明目录 API 行为。
- 本地预检：检查教学 manifest、probe 与工作区资源；当前机器缺少 Docker，导入项目显示阻塞，不伪造执行成功。
- 实际执行：可信教学任务经现有运行时完成，产生 3 条判定（2 支持、1 不一致）。用户导入项目仍显示「代码未验证、指标无法判定」，未串入样例报告。
- 手机：390px 验证查看 PDF、翻页、返回主张、查看分层结论；项目 JSON 下载完成，含原文页码与主张、不含文件 Blob。
- Taste：五个新增关键界面 × 1440/768/390px 的生产静态资源检查全部 0 FAIL / 0 WARN，并逐页查看截图。设计取舍与允许项见 [WORKBENCH_DESIGN.md](WORKBENCH_DESIGN.md)。

这组验证覆盖材料准备、契约与已有执行器的连接；未验证任意论文完整训练复现、OCR、GPU 模型训练或正式论文 benchmark。


## 2026-10-29 双工作区

22 项前端测试通过（原 13 项 + 9 项）：覆盖老项目迁移到八项未核查条件、记录依据不生成复现成功、选中主张的实验覆盖、依据/阻塞/不适用原因约束、材料变更失效，以及教学聚合、假阳性与缺失判定、未知数据集拒绝借用教学真值。底层核查 API 未改动；CI 继续运行 48 项 Python 测试。

浏览器验证了系统基准切换、CORE-Bench 未执行空状态、对照方案保存、用户项目的实验新增与条件依据编辑，并在重新载入后确认记录持久化。检查结果只表示人工依据记录，不生成训练复现成功。


手机联调覆盖条件切换、统计阻塞登记与未执行结果隔离。六关键视图 × 三视口最终 Taste 检查均 0 FAIL / 0 WARN。新增导出测试确保 `paper_review` 保留实验和八项评审，原有 `assessment` 保留执行分层数组；二者不互相覆盖。
