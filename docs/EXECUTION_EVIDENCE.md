# 实际材料、环境与测量

完整实验页可导入当前项目 PDF、ZIP 和计划。浏览器先保留原始文件，用户点击导入后才传到本地运行时；托管预览禁用传输。服务器独立解析 PDF，安全解包 ZIP，生成实际逐文件指纹。绑定只重定位材料路径，分别保留上传计划和绑定计划的 SHA256，不覆盖原计划的参考值。代码根目录确认后，审计、启动与运行报告使用同一材料包。计划或材料变化需要重新核验。

论文清单、主要结论、页码引用、核心实验和执行映射来自计划；全页图表引用是候选，人工审核声明保留审核人和依据。未分类引用或未覆盖核心实验阻止主要结论验收；AST 和文件存在不证明论文方法语义正确。

## 公开数据获取

显式运行 `articheck acquire-data --plan PATH --output RECEIPT.json`，不执行论文代码。为数据集声明 `acquisition`：

```json
{"id":"dataset-id","source":{"url":"https://example.org/data","version":"publisher-version","license":"documented terms","access":"public"},"files":[{"path":"data.bin","sha256":"REFERENCE_SHA256"}],"acquisition":[{"path":"data.bin","url":"https://example.org/data","sha256":"REFERENCE_SHA256","max_bytes":104857600}]}
```

先从可信来源取得真实 SHA256，再填写计划。只支持公共 HTTPS 443；拒绝凭据 URL、私网/保留地址，连接固定到已校验的 DNS 地址并验证 TLS，重定向重新检查。下载有字节、时间和空闲磁盘预算，失败清理临时文件；缓存也重算哈希，不覆盖已有矛盾文件。不接收数据访问凭据，受限数据走原申请流程，用户提供获准的本地材料及来源。获取回执与实验时间范围分别记录。

准备、预处理、训练和评估阶段记录输入/输出指纹；生成划分在训练前检查重复、大小和交集。训练产物、实际使用配置和冻结配置需要一致，模型被后续阶段替换会使验收失败。预测按精确样本 ID 与冻结标签独立重算。

## 环境与资源

`environment.expected` 可包含 `python`（major.minor 或 patch）、`packages`（精确版本）、`architecture`、`cuda`（required/runtime）。实际 Docker daemon 的身份摘要和容量与客户端主机快照分别保存，资源要求同时对比容器限额及 daemon 可观测容量。构建无缓存、禁网；不可变 FROM digest、锁文件指纹、镜像内版本与验证记录共同保留。简单 requirements 锁与期望包版本逐项关联；带复杂 markers 的锁或不识别的格式保持未验证。自定义 source-build 锁需绑定不可变 base，并说明其随镜像提供的依赖。

CUDA 要求必须显式选择 GPU；镜像内检查 PyTorch 实际可用性、运行时版本和小矩阵运算。无设备、无框架或版本冲突会失败，不能用主机装有 CUDA 替代。当前公开案例只验证 CPU；GPU 代码分支的单元测试不代表真实 GPU 机器通过验收。

子进程 getrusage / cgroup 回执与容器外 Docker sampler 分开保存。外部采样记录容器 ID、采样内存/CPU 峰值、阶段与整个项目输出占用采样峰值。短阶段可能没有容器采样，短时峰值也可能遗漏。输出字节数不等于磁盘 I/O，GPU 峰值保持未测。`disk_limit_bytes` 控制单次运行输出，`project_disk_limit_bytes` 记录项目输出预算违反；采样预算不是文件系统配额。

费用按声明单价估计，拆出环境构建、验证、artifact 阶段与其他编排时间；没有单价就没有金额。获取数据和拉取基础镜像可能发生在计时前，报告明确排除这些费用，另保存获取回执；不冒充账单或人工成本。

## 验收层级

命令矩阵完成、环境重建、论文训练协议、主要结论分别计算。完整自制材料在真实 Docker 和 HTTP 链路中验证正向行为；公开 LIBLINEAR 验证实际论文代码执行，并继续保留版本/划分偏差和未覆盖核心实验。

固定参数的对照比较核对预注册差异、生成划分、实际训练输入、配置和资源限额。validation_only 协议核对预注册 search_space / tuning_budget，独立重算全部声明候选的验证指标，检查最优候选与最终模型的指纹，并对实际阶段耗时、候选数和种子设门槛。声明轨迹是否完整仍依赖源码审核；固定参数或验证选择的公平性通过均不代表基线最优。方法对应与完整清单是具名、可追溯的审核声明，不是程序对论文语义的形式证明。

审核新版本在「完整实验 → 实际导入回执」中保存；「实验覆盖」同时显示已核验清单。方法审核必须提供 `citations: [{page, quote, paths}]`，审计从真实 PDF 独立读取文本并核对文件，不能用手写的 pages 冒充原文。具名审核确认方法语义；原文/文件对应通过不代替语义判断。代码/数据修补以同项目的新材料包导入，记录 parent 和每个新增、删除、修改文件的前后 SHA256，重置方法审核确认；审核端口不能修改代码和命令。

可选 NVIDIA profiler 按镜像内观测的 GPU UUID 采样整卡使用量。只有客户端与容器的内核 boot-id 摘要一致，且 `docker top` PID 对应时，才记录容器计算进程的显存采样峰值；整卡占用单独保留，不能冒充当前任务显存。不支持的数据、远端无法关联或未采样均保持未知。当前该分支只有模拟测试，真实 CPU 验收不包含 GPU 成绩。查询口径参考 [NVIDIA nvidia-smi 文档](https://docs.nvidia.com/deploy/nvidia-smi/)。来自其他服务器的完整报告可在「导入证据报告」查看，界面将其标为用户上传，不替代已连接执行器身份。

validation 搜索轨迹在 `training_evidence.selection_record_path` 声明，必须是训练阶段输出。`fairness` 包含相同的 `tuning_budget: {max_trials,max_seconds}`、`search_space` 和 `validation_metric`。轨迹包含 protocol、seed、trials（id、settings、records_path、model_path）和 selected_trial_id。验证标签与 ID 冻结，全部候选独立重算，最终模型必须与所选候选指纹相同，选错候选会在测试评估前中止。


## 2026-11-02 · 六角色接入后的公开案例重跑

[CI 41408434563](https://github.com/Gump111458785/ArtiCheck/actions/runs/41408434563)，代码 784ba4bb3197dcccdf84cb052627caaaa52e5ece：15 次运行、60 阶段、162 条角色事件；均值 96.76%，样本标准差 0.31 个百分点。执行器墙钟 111.359116234 秒，全阶段子进程 RSS 最大 384049152 字节（366.3 MiB），容器外采样峰值 227960422 字节（217.4 MiB），覆盖 33/60 阶段。采样不能保证捕获短时峰值；上述时间不含下载与基础镜像拉取，不代表角色标注带来加速。原报告主机快照在网页副本中置空，其余执行内容及原始 SHA256 留存；角色原始字节另存 liblinear-roles.jsonl。training/conclusion 仍为 false。
