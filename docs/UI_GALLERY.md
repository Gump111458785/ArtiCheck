# ArtiCheck 界面图集

工作台从论文材料走向逐主张证据与分层验收。本页选取已归档的真实界面截图，点击图片可查看原尺寸；截图中的公开案例与个人项目分别保存。

[交互预览](https://articheck-workbench.onatanolf8074.chatgpt.site/#home) · [本地启动](WORKBENCH.md#运行方式) · [系统架构原图](assets/architecture.svg)

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

## 手机端：相同入口，单栏阅读

导航折叠，新建评估在首屏可达；案例、连接状态与个人项目依次展示。

<img src="assets/home-mobile.jpg" alt="ArtiCheck 手机端开始页" width="390">

## 从界面到实现

| 界面 | 前端入口 | 数据与执行来源 |
|---|---|---|
| 开始页 | [home.mjs](../web/dist/home.mjs) | 个人项目存储、应用 mode、公开案例 catalog |
| 执行中心 | [execution-center.mjs](../web/dist/execution-center.mjs) | `/api/runs`、`/api/reproduction/runs` 和归档记录 |
| 角色协作 | [execution-core.mjs](../web/dist/execution-core.mjs) | preflight / decision / tool / audit / complete 事件 |
| 完整实验与审查 | [review-view.mjs](../web/dist/review-view.mjs) | 冻结计划、运行阶段、分层报告与追加复核意见 |

托管预览用于材料准备与归档回放，真实执行使用本地工作台。[开始页说明](HOME_SCREEN.md) · [执行中心说明](EXECUTION_CENTER.md) · [审查模块对应](REVIEW_WORKSPACE.md)。
