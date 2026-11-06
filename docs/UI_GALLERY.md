# ArtiCheck 界面图集

工作台从论文材料走向逐主张证据与分层验收。本页选取已归档的真实界面截图，点击图片可查看原尺寸；截图中的公开案例与个人项目分别保存。

[交互预览](https://articheck-workbench.edgeone.dev/#home) · [本地启动](WORKBENCH.md#运行方式) · [系统架构原图](assets/architecture.svg)

## 在线审查：材料、报告与真实执行

论文 PDF 与代码可以分别提交。GitHub 地址自动读取固定提交的源码；有适用计划时在云端 CPU 实例执行。下图来自正式网站的公开 LIBLINEAR 案例，不是预设动画。

[![在线审查报告](assets/online-report.png)](assets/online-report.png)

[![在线执行与日志](assets/online-execution.png)](assets/online-execution.png)

[![在线角色记录](assets/online-roles.png)](assets/online-roles.png)

[![论文图表与出处](assets/online-paper-evidence.png)](assets/online-paper-evidence.png)

论文自查将摘要与标题分开显示；图表清单保留模型、数据集、数值与原页入口。[实际运行范围与验收记录](ONLINE_ACCEPTANCE.md)。以下为本地工作台与归档案例页面。

## 动态协作、分层指标与账户

动态协作截图来自正式网站的一次代码验收提交，随后在 4 GB 实例上实际分配 1 GB 内存；这是系统功能验收，不是论文效果评测。指标截图展示已归档的 ResNet 报告，分组与筛选不改变原报告数值。账户截图来自实际注册登录和资料保存。

[![动态协作进度](assets/review-collaboration-live.png)](assets/review-collaboration-live.png)

[![多级图表指标](assets/metrics-classified.png)](assets/metrics-classified.png)

[![登录界面](assets/account-login.png)](assets/account-login.png)

[![个人中心](assets/account-center.png)](assets/account-center.png)

资源不足操作区使用显式界面验收样例，展示两组操作的排版，不代表已执行 GPU 实验。

[![资源补充与执行位置分开排列](assets/resources-layout.png)](assets/resources-layout.png)

[使用说明与核心模块](ACCOUNTS_AND_COLLABORATION.md)。

## 邀请制登录、实验审查案卷与自有 RTX 4090 GPU 执行（2026-11-06）

以下截图来自正式生产部署（`dpcx8t5a48yd`）：采用“实验审查案卷”高对比配色、独立受邀登录页（眼睛 SVG 密码显隐图标、无公开注册与访问码）、深海蓝公开案例卡片、材料识别后的审查需求弹窗、一页式最终报告（顶部通过/未通过/待核查结论横幅 + 对齐指标比较表）、自有 RTX 4090 GPU 隔离执行过程详情，以及管理员受邀账户后台。

[![独立受邀登录页](assets/feedback-login.png)](assets/feedback-login.png)

[![实验审查案卷开始页与公开复现案例](assets/feedback-home.png)](assets/feedback-home.png)

[![材料初步识别后的审查需求选择弹窗](assets/feedback-task-choice.png)](assets/feedback-task-choice.png)

[![一页式最终报告](assets/feedback-onepage-report.png)](assets/feedback-onepage-report.png)

[![自有 RTX 4090 GPU 执行与默认展开的分层活动记录](assets/feedback-gpu-execution.png)](assets/feedback-gpu-execution.png)

[![管理员受邀账户管理](assets/feedback-admin-accounts.png)](assets/feedback-admin-accounts.png)

## 开始：选择新建、继续项目或查看案例

新建论文评估进入现有的 PDF / 代码材料表单；最近项目来自当前浏览器，内置样例不计入个人项目数量。公开 LIBLINEAR 案例拥有独立入口。

[![开始页](assets/home-desktop.jpg)](assets/home-desktop.jpg)

## 执行中心：统一查找记录

完整实验与短时核查集中检索，明确区分本机执行、公开 CI 与教学归档。来源、状态、进度和实际记录时间随任务显示，打开任务后查看对应证据。

[![执行中心](assets/execution-center.jpg)](assets/execution-center.jpg)

## 角色协作：从职责契约读到实际事件

文献主张与代码检查并行预检，Planner 选择检查项，执行、核查与报告形成可追溯记录。角色面板复用原始运行事件，不为完整实验生成虚构角色活动。

[![角色协作](assets/role-workspace.jpg)](assets/role-workspace.jpg)

## 案例验收：让运行完成与结论依据分别可见

LIBLINEAR 公开案例展示 15 次运行、60 个阶段和重复实验指标。原报告中环境重建通过，而论文训练协议与主要结论尚未通过；界面保留原始判定及证据范围。

[![案例验收](assets/execution-detail.jpg)](assets/execution-detail.jpg)

## 从界面到实现

| 界面 | 前端入口 | 数据与执行来源 |
|---|---|---|
| 开始页 | [home.mjs](../web/dist/home.mjs) | 个人项目存储、应用 mode、公开案例 catalog |
| 执行中心 | [execution-center.mjs](../web/dist/execution-center.mjs) | `/api/runs`、`/api/reproduction/runs` 和归档记录 |
| 角色协作 | [execution-core.mjs](../web/dist/execution-core.mjs) | preflight / decision / tool / audit / complete 事件 |
| 完整实验与审查 | [review-view.mjs](../web/dist/review-view.mjs) | 冻结计划、运行阶段、分层报告与追加复核意见 |

在线网站已接入模型 API 和 CPU 执行；本地工作台用于自有材料环境、GPU 或完整实验配置。[开始页说明](HOME_SCREEN.md) · [执行中心说明](EXECUTION_CENTER.md) · [审查模块对应](REVIEW_WORKSPACE.md)。
