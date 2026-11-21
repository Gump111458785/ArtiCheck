# 纯前端动态评测演示

演示在浏览器播放预设流程和报告，适合熟悉六角色进度和结果页。

## 使用

1. 打开开始页，新建论文评估。
2. 导入 PDF（真实提取文本与页数）和代码 ZIP（真实读取中央目录），也可读取公开 GitHub 目录。
3. 保持「提交后播放演示评测」选中，点击「提交材料并演示评测」。浏览器预览默认选中，本地真实运行模式默认不选中。
4. 六角色约 16 秒依次播放，阶段、百分比和事件随时间更新；可暂停、继续或直接查看结果。
5. 结果页切换「发现待修正项 / 条件全部符合 / 材料不足待补充」，展开问题建议、查看八项条件并导出 JSON。

已有项目也可从「论文与代码」的「开始演示评测」进入。开始页最近项目会续接演示结果。刷新时运行中演示恢复为暂停，不把离线时间算成已执行；更换材料会使原演示失效。

直接播放内置材料：`?mode=demo&example=demo`；静态结果：`?mode=demo&example=demo&view=report`；暂停在进度中段：`?mode=demo&example=demo&view=progress`。

## 实现与边界

- `web/dist/presentation.mjs`：六阶段脚本、三种固定场景、时间推进、暂停恢复、材料身份、结果与导出。
- `web/dist/presentation.css`：演示界面的布局与动画样式，支持移动端和系统的减少动态效果设置。
- `web/dist/intake.mjs`：导入和提交入口、独立演示标签与材料变化失效。
- `tests/frontend/presentation.test.mjs`：材料门槛、推进与暂停、来源、计数、失效、转义、刷新和真实报告隔离。

状态保存在项目 `presentation_review`，不写入 `run_id`、实际核查发现、完整实验验收或系统自评。JSON 带 `format=articheck-frontend-demo-v1`、`data_source=frontend_demo`、`scientific_validation=false`。预设问题没有被冒充为对用户代码的实际定位，文件内容不用于推导演示结论。

演示模块没有 HTTP 请求；PDF / ZIP 只在浏览器读取。选用 GitHub 来源时仍需访问 GitHub 公共目录 API。远程模型调用与实验执行不属于本演示路径。

## 界面示例

![演示进度](assets/demo-progress.jpg)

![演示结果](assets/demo-results.jpg)
