# 执行中心与角色导航

执行中心汇总完整实验、短时核查和公开归档。打开一条记录可查看六角色进度、阶段输出、复核证据与报告。

## 工作区层级

| 分组 | 页面 | 优先回答的问题 |
| --- | --- | --- |
| 复现工作 | 论文项目 | 要核查哪份论文、材料与计划？ |
| 复现工作 | 执行中心 | 哪次任务正在运行、失败或需要关注？ |
| 复现工作 | 角色协作 | 某个角色接收什么、输出什么，实际发生过什么？ |
| 复现工作 | 证据复核 | 当前任务的判断有什么依据？ |
| 评测与数据 | 系统评测 | ArtiCheck 的判定质量如何？ |
| 评测与数据 | 反馈与训练交接 | 已保存哪些人工修正？ |
| 开发工具 | API 与集成 | 这些操作对应什么接口契约？ |

“运行轨迹”并入单次任务详情。角色协作页展开六角色子导航；其他页面折叠角色树。角色的职责和事件从同一份目录映射，主张、代码并行预检，Planner / 执行 / 交叉核查按主张迭代。

![执行中心](assets/execution-center.jpg)

![角色协作](assets/role-workspace.jpg)

## 列表与详情

执行中心是独立的记录列表，不在列表下方同时铺开报告。完整实验、短时核查、公开 CI 归档、教学归档可在同一列表检索；类型和来源分别标明。状态计数随搜索与筛选变化，返回列表保留筛选，超过 25 条按需展开。

单次完整实验有“任务概览 / 角色协作 / 阶段与输出 / 证据复核 / 完整报告”；单次短时核查有“任务概览 / 角色协作 / 执行事件 / 证据复核”。共用任务身份、来源、计划指纹和一层标签，避免重复任务选择器、执行类型切换与报告标题。

角色协作页可选择任一短时核查或完整实验记录，并查看六角色状态及各角色的真实输入输出。

- **短时核查**：`LiteratureReader` 与 `CodeInspector` 共享 preflight 事件，但仅展开所属角色数据；Planner 读 decision/model，执行器读 tool，审计读 audit，报告器读 complete。
- **完整实验**：事件来自执行器写入的 `roles.jsonl`（`GET /api/reproduction/runs/{run_id}/roles`）。阶段归属由 [`articheck/reproduction/roles.py`](../articheck/reproduction/roles.py) 定义：审计 `scope` 维度归 LiteratureReader；`code / data / environment / settings` 维度、源码快照与完整性核对归 CodeInspector；`commands / resources / acceptance` 维度、资源核对、每次运行排程与停止原因归 Planner；镜像构建、环境验证与阶段执行归 ExperimentRunner；镜像兼容、阶段核查、运行判定与实验验收归 CrossAuditor；分层验收归 Reporter。Planner 在此路径按冻结计划排程（`policy: frozen_plan`），不做模型决策。
- 角色状态只由实际事件推出：无事件为“未开始”，任一事件 `fail` 为“执行失败”，任务进行中为“执行中”。早于角色标注的归档没有 `roles.jsonl`，页面明确显示“没有角色记录”，不补造事件。当前 LIBLINEAR 案例已更新为含 162 条真实角色事件的新 CI 归档。
- 角色记录写入失败只记入 `report.roles.errors`，不改变执行状态、指标或分层验收（`tests/test_reproduction_roles.py` 覆盖）。

归档教学报告缺少时间时显示“未记录时间”，不使用页面打开时间代替。

## 核心模块

| 模块 | 作用 |
| --- | --- |
| `web/dist/navigation.mjs` | 分组导航、角色子导航及状态标记 |
| `web/dist/execution-core.mjs` | 六角色目录、事件归属、记录归一化、筛选与计数 |
| `web/dist/execution-center.mjs` | 列表 / 详情 / 角色页面、记录读取、刷新、导出与返回 |
| `web/dist/review-view.mjs` | 嵌入任务详情的完整实验证据视图，共用单层导航 |
| `web/dist/workspaces.css` | 新工作区响应式布局，与原材料页面样式分开维护 |
| `tests/frontend/execution-center.test.mjs` | 新页面的数据关系与交互状态回归 |

本机活跃任务每 3 秒更新；输入、复核和展开阅读原始事件时暂停刷新画面。新任务响应不会覆盖已经返回的列表；缓存报告的旧状态与进度不覆盖新任务元数据。搜索只更新结果区域，保持输入节点和焦点，支持连续输入及输入法组合。

## 公开案例中的六角色记录

[CI 41408434563](https://github.com/Gump111458785/ArtiCheck/actions/runs/41408434563) 成功，162 条角色事件：15 次 schedule_run、60 次 stage、60 次 stage_checks、15 次 run_verdict，以及材料审计、环境与报告记录。Planner 事件固定 policy=frozen_plan；分层验收 run/environment_rebuilt 为 true，training/conclusion 仍为 false。

前端从原始角色归档读取，不补造事件。角色页和任务详情均支持刷新；活跃任务轮询角色记录，接口失败单独提示并保留旧记录；取消任务保持停止状态。原始角色文件和报告的 SHA256 保存在案例 provenance 中。


![完整实验六角色与实际排程事件](assets/full-experiment-roles.jpg)
