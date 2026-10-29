# 完整实验执行与材料审计

这一执行器独立于原有三类 probe。输入是冻结的 `articheck-reproduction-plan-v1`，包含整篇论文实验清单、代码内容基准、数据来源及指纹、实际配置、环境构建、种子/方法矩阵、阶段依赖、输入输出和验收协议。

## 已提供的命令

```bash
# 只读实际材料；不导入或执行论文代码
articheck reproduce --plan examples/reproduction_smoke/plan.json \
  --output runs/material-audit.json --check-only

# 默认 Docker：重新构建环境并执行矩阵
articheck reproduce --plan path/to/plan.json --output runs/paper-001

# 仅对自己信任的自制教学代码使用本地执行；没有 Docker 自动降级
articheck reproduce --plan examples/reproduction_smoke/plan.json \
  --output runs/reproduction-smoke --sandbox local --allow-local-trusted
```

`examples/reproduction_smoke` 是自制回归实验，不是发表论文，也不是外部 benchmark：准备数据 → 从样本拟合模型 → 预测并计算 MSE，三个版本为线性回归、常量预测控制和移除截距的消融；五个种子改变训练重采样。它提供 15 次运行、45 个阶段的工程验收。

## 材料审计

- 代码：逐文件 SHA256 / Git blob SHA1 比对；可核对 Git HEAD；声明的方法、预处理、训练、评估入口要真实存在，Python 源码进行 AST 语法解析。文件存在不能证明方法语义，单独保留带来源的审核人记录。
- 数据：读取真实数据文件校验和；读取训练/验证/测试样本 ID 清单，检查重复和两两交集；记录划分生成来源、转换输入输出及其内容指纹。受限数据缺少申请条件或授权时形成阻塞，不收集凭据。
- 配置：读取实际 JSON 文件及其指纹，与带论文出处的预期设置逐字段比较。运行配置再注入种子和 variant 后冻结，每个阶段后检查是否被修改。
- 范围：从全部提供页文本发现图表引用候选，对照实验清单与选定执行计划。未分类引用、缺少核心实验执行计划及未完成清单审核均保留；引用候选不冒充完整实验抽取。
- 环境：核对构建文件/依赖文件指纹；requirements 的简单格式检查要求精确版本。真正重建还需要 Docker clean build 和镜像内验证。

本地只读 HTTP 接口 `POST /api/reproduction/audit` 接收工作区内 `plan_path`，可传入带 `git_blob_sha` 或 `sha256` 的 `imported_snapshot`。只有目录/文件名而没有内容基准时保持未知，不自动认定版本一致。公共 GitHub 导入现在保留官方 tree 的 blob SHA；旧项目需重新读取目录。

## 执行与证据

Docker 构建禁用网络和缓存，记录日志与实际 immutable image ID，并运行计划声明的镜像内验证。基础镜像须提前拉取，依赖须在基础镜像或离线包中提供。该版本不默默开放构建网络，也不将成功连接 Docker 当作环境验证。尚未验证任意锁文件安装或 GPU 框架兼容性。

每次运行有独立输出目录，artifact 只读挂载，输出可写；容器禁网、非 root 身份按运行用户 UID/GID、限制 CPU/内存/PID、移除 capabilities。拒绝使用宿主 UID 0 启动实验容器。阶段接收 argv 数组和显式 `{repo}` / `{work}` / `{config}` / `{seed}` / `{variant}` 占位符，记录解析后的命令、输入输出文件哈希、stdout/stderr、返回码、超时和总预算。缺输出、配置变更、非零退出、超时或超出日志限额均失败；不运行依赖失败后的阶段。

报告保留源文件快照清单和原始计划。每次运行记录 elapsed time、子进程 getrusage 峰值 RSS/CPU 时间、容器内可读的 cgroup memory.peak；该 instrumentation 不是对恶意代码的防伪证明。GPU 峰值尚未测量；输出占用是运行后占用，不冒充峰值磁盘。费用是实际墙钟时长乘用户声明单价的计算估计，单价未知时保持 null，不当作账单。

## 统计验收

按预注册的种子与版本配对，不丢弃失败或缺失样本。报告每组 n、均值、样本标准差、范围；至少五个完整配对种子才计算 paired percentile bootstrap（固定 RNG，5,000 次重采样），多条预注册比较以 Bonferroni 分配 family alpha。方向统一后，将置信区间与预注册最小效应比较；波动覆盖最小效应则为 inconclusive。

参考值容差对齐与方法比较分开。只命中参考值而没有比较不能证明主要结论。当前 engine 的 training / conclusion 层级保守保留 false，仍需要训练阶段/模型溯源验证、独立指标重算、公平控制项和完整范围验收接入；不能把运行成功的矩阵或显著控制实验冒充整篇论文复现。

## 验证进度

本地完整测试共 72 项：71 通过，1 项 Docker 集成因本机没有 Docker 跳过。新增真实 CLI 完成上述 15 次自制运行。CI 的 Python 3.11 job 额外启用 `ARTICHECK_TEST_DOCKER=1`，验证 clean build、镜像内 Python 检查和同一矩阵的容器执行；通过与否以对应提交的 CI 为准。

真实案例选择 [LIBLINEAR（JMLR 2008）](https://www.jmlr.org/papers/v9/fan08a.html) 与 [作者仓库](https://github.com/cjlin1/liblinear)。作者源代码固定至 `491c9f1188b97ba70847c70a68be363d186ddf9d`，下载 archive SHA256 为 `ad9c824a631e48fd57fe21ab23e87e9de0413cf0558d0fa9dd89685aec76c185`。news20 原始数据已从作者站下载并记录 SHA256；真实论文完整流程仍在接入，不声称已得到论文成绩。
