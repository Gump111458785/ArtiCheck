# ArtiCheck 术语

| 术语 | 含义 |
|---|---|
| Draft / Record | Agent 只能提交 Draft；校验通过后，才由 Runtime 写成不可变的 Record |
| `ReleaseGateStatus` | 审查报告能否发布；与论文是否有问题无关 |
| `ClaimVerdict` | 单条主张是否成立：`SUPPORTED` / `ISSUE` / `INCONCLUSIVE` |
| `StageCacheKey` | 由容器镜像摘要、运行时后端、论文摘要、相关代码子树、环境锁、权重资产、命令、随机种子、输入数据、上游产物与校验器版本算出的阶段指纹；补丁后据此按依赖图精确判断哪些结果失效 |
| O1–O9 | Runtime 提供给 Supervisor 的 9 层结构化观察 |
| ACP（Agent Capability Profile） | 冻结的专业 Agent 能力档案：模型版本、模板、采样参数与工具版本；Supervisor RL 在固定 ACP 下进行 |
| `CONFIRMED` / `SUSPECTED` | 失败定位的可信度：来自日志与退出码 / 来自模型推断 |
| Recorded Replay / Live Sandbox | RL 环境中的缓存回放 / 实时执行 |
