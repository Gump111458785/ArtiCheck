# ArtiCheck Workbench：界面与接口

工作台把现有 Python 核查链路封装为可操作的界面，并用实际交互检验接口设计。前端为原生 HTML / CSS / JavaScript，无需 Node 依赖安装；本地服务使用 Python 标准库。

## 运行方式

从完整源码 checkout 的根目录运行：

```bash
python -m pip install -e .
python -m articheck.workbench --port 8787 --workspace . --storage runs/workbench
```

打开 `http://127.0.0.1:8787`。新建任务、执行核查、读取报告和提交人工反馈均通过本地 HTTP API 调用现有 Python 实现。首页从「复现项目」开始；可导入自己的材料，或打开教学样例并在「运行条件」执行。原有任务操作保留在「执行记录」。

也可以打开 [私有托管预览](https://articheck-workbench.soft-bun-8328.chatgpt.site)。它支持在浏览器准备 PDF、代码目录与主张，也使用 `scripts/build_workbench.py` 从真实教学 fixture 生成的归档证据回放交互。预览不执行外部仓库、不访问本机文件系统，反馈仅保存在该浏览器。导出的回放报告带 `data_source=archived_sample_replay`，不能作为新的真实执行记录。

本地页面可使用 `?mode=demo` 检查回放模式。更新归档样例或契约后执行：

```bash
python scripts/build_workbench.py
node --check web/dist/app.js
python -m unittest discover -s tests -v
```

## 界面设计

工作区先建立论文与代码的材料来源，再确认实验范围与主张，最后绑定执行与证据。PDF 原文和编辑中的主张并排显示；指标摘要与六角色状态位于同一运行上下文。手机端折叠导航，主张与证据详情分屏呈现。具体设计与验证见 [设计记录](WORKBENCH_DESIGN.md)。

## 工作视图

| 视图 | 用户操作 | 对应资源 |
|---|---|---|
| 复现项目 | PDF / GitHub / ZIP 导入、主张确认、资源预检、分层评估、项目导出 | ReviewProject / PaperSource / ClaimBinding |
| 执行记录 | 新建任务、修改主张预期值、设置预算、启动与停止运行 | Task / ReviewRun |
| 证据审查 | 搜索主张、按问题过滤、查看预期与观测值、打开原始 JSON | Claim / Finding / Evidence |
| 运行轨迹 | 查看规划动作、工具结果、核查事件、下载 JSONL | TraceEvent |
| API 契约 | 浏览接口、查看示例、复制 cURL、下载 OpenAPI | HTTP / SSE schema |
| 训练交接 | 查看人工反馈、区分困难样本候选、导出反馈 JSONL | HumanFeedback |

前端角色图对应 LiteratureReader、CodeInspector、Planner、ExperimentRunner、CrossAuditor、Reporter。当前阶段状态由原始 preflight / decision / tool / audit / complete 事件推导，不作为独立的角色耗时测量；精确的角色开始、结束时间属于后续 instrumentation 扩展。

## 关键接口决策

### 任务定义与运行分离

`POST /api/tasks` 注册或复制任务，创建独立 task_id；`POST /api/runs` 用 task_id 与运行预算创建执行实例。修改主张通过创建新任务保存，历史任务与报告保持原样。

任务来源支持内置样例，或服务 workspace 内已有的 task.json。PDF 文件在浏览器解析与保存，不通过 HTTP 上传给本地 Python 服务；真正执行时仅提交选定原文、页码与 PDF SHA256。代码 ZIP 只检查中央目录，不解压执行；GitHub 只读取公共目录并固定提交，不自动 clone。内置样例允许可信 local 执行；导入的 artifact 使用 Docker。

### 运行 ID 与报告 ID 分离

HTTP 层先返回 ReviewRun.id，Python pipeline 在执行时创建自己的 report.run_id。完成后的 ReviewRun.report_id 指向后者。反馈沿用原始 report.run_id，因此不会把任务 ID、HTTP 运行 ID 和证据 ID 混用。

状态机：

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running
    queued --> cancelled
    running --> completed
    running --> failed
    running --> cancelled
```

HTTP 202 表示已接收，不表示核查完成。接口关闭后重启时，未完成运行恢复为 failed 并记录原因；不将中断的任务标成成功。预算耗尽但已生成报告的运行仍保留报告与 inconclusive 判定，详细原因见 report.stop_reason。

### 证据不可变、反馈可追加

Finding.evidence_ids 关联原始 Evidence。缓存命中只复用证据，不伪造额外工具调用。人工反馈追加 reviewer、reason、label、timestamp 和 previous_verdict，不覆盖原始 Finding。

反馈不是 SFT 接受记录。导出的 feedback.jsonl 用于后续人工或独立规则审核；`export-sft` 仍要求对应教师轨迹和接受清单，界面不会自动触发 GPU 训练。

### 执行事件可重放

`GET /api/runs/{run_id}/events` 提供 SSE，trace 事件带递增 sequence / SSE id，可使用 after 或 Last-Event-ID 续读；终态发送 terminal 事件。sequence 是适配层的行序号，原始 trace 字段保留不变。

当前前端每 700ms 读取运行快照，事件流供后续更细粒度订阅。两种方式使用同一份落盘 trace。取消中途执行的任务可能只有部分 trace，没有最终 report；报告下载和反馈提交在这种情况下返回 409。

## 本地 HTTP API

契约文件：[openapi.json](../web/dist/openapi.json)。本地服务也暴露 `/api/openapi.json`。所有写请求需带 `X-ArtiCheck-Client: workbench` 与 JSON body。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /api/health | 运行时能力 |
| POST | /api/repositories/inspect | 读取固定 GitHub API 的公共仓库目录与提交 |
| POST | /api/preflight | 检查 workspace、manifest 指纹、probe、Docker 与所需资源 |
| GET / POST | /api/tasks | 列出 / 创建任务 |
| GET / POST | /api/runs | 列出 / 启动运行 |
| GET | /api/runs/{run_id} | 状态、角色阶段、判定、报告与反馈 |
| GET | /api/runs/{run_id}/events | SSE 事件流 |
| POST | /api/runs/{run_id}/cancel | 请求取消 |
| GET | /api/runs/{run_id}/report | JSON / Markdown 下载 |
| GET | /api/runs/{run_id}/trace | 原始轨迹 JSON |
| POST | /api/runs/{run_id}/feedback | 追加人工纠正 |
| GET | /api/feedback | 全部反馈记录 |
| GET | /api/openapi.json | OpenAPI 3.1 契约 |

```bash
curl -X POST http://127.0.0.1:8787/api/runs \
  -H 'Content-Type: application/json' \
  -H 'X-ArtiCheck-Client: workbench' \
  -d '{"task_id":"sample-metric_average","sandbox":"local","planner":"fixed","budget":{"max_tools":8,"max_seconds":180}}'
```

可在「API 契约」页复制其他接口的示例；路径中的 `{run_id}` 需替换为实际 HTTP 运行 ID。接口错误统一为 `{"error":{"code":"request_error","message":"..."}}`。

## 当前部署范围

本地服务只绑定 127.0.0.1，校验 Host、写请求 Origin 与专用客户端 header；没有多用户登录、权限分组或远程任务队列。不要将当前服务直接暴露到公网。真实任务文件及其 artifact 必须位于指定 workspace 中。

托管站点仅发布静态界面与合成教学数据。它不持有 GitHub、模型 API 或 Docker 凭据，不是远程执行服务。

后续接口扩展可沿现有资源增加：服务端材料存储与导入、模型配置引用、精确角色事件、异步工作队列与认证，以及独立的训练作业资源。CLI 中的模型和训练能力不等于这些 HTTP 功能已提供。

## 材料与执行的连接

`ReviewProject` 保存在当前浏览器 IndexedDB，包含 PDF/ZIP Blob、文件指纹、页文本、人工确认、资源条件和运行关联。导出的 `articheck-review-project-v1` JSON 含出处、主张与分层评估，不含二进制文件；保留原始 PDF/代码以便交接。当前没有项目 JSON 重新导入或跨设备同步。

- PDF：最大 20 MB、150 页。浏览器本地 PDF.js 解析，空文本页可手工登记；不执行 OCR。论文链接只作为出处。
- ZIP：最大 50 MB、5,000 个条目，声明解压大小上限 500 MB；拒绝路径穿越、重复路径、加密、ZIP64 和多卷格式。这里只检查目录，不验证归档载荷与代码行为。
- GitHub：支持 `https://github.com/owner/repo` 公共仓库。本地经受限 API 代理读取；托管页直接请求 GitHub API，无凭据，遇限流可改用 ZIP。目录读取不代表依赖安装成功。
- 预检：`POST /api/preflight` 接收 `task_path` 和 `resources`，返回逐项条件、manifest 与 SHA256、probe 及匹配检查项。检查路径存在与 Docker 可用性，不证明数据版本、GPU 兼容性或实验已执行。
- 绑定：每条选定且人工确认的主张匹配一个同类型 manifest 检查项，沿用已审核的 probe / 输出键。用户确认本地代码与导入材料版本一致。创建任务附带 manifest SHA256；变化返回 409 并要求重新预检。
- 变更：替换论文或代码清除主张确认、执行绑定与当前运行关联；修改执行资源使预检失效。历史报告仍保留在「执行记录」。

材料、执行和指标结论分别计算。没有绑定的实际报告时显示「未验证 / 无法判定」；失败、取消或缺少执行证据均不会被写成复现成功。归档回放与本地执行标注不同来源，教学样例不接受替换成外部论文后继续使用样例结果。

## 前端开发验证

```bash
node --check web/dist/app.js
node --check web/dist/intake.mjs
node --test tests/frontend/intake.test.mjs
python -m unittest discover -s tests -v
```

共 15 个 HTTP 操作。`scripts/build_workbench.py` 会重新执行教学 fixture 并更新归档数据；仅修改 API 契约时，可直接调用该脚本中的 `contract()` 生成 `openapi.json`，避免无关的样例时间戳变化。
