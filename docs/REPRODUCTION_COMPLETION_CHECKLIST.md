# 八项能力的实现与验收位置

八项基础链路均已有实现和正反向验证。最终代码的 CI 与公开 CPU 验收已通过；私有预览同步另有部署记录。验收范围为公开 CPU 案例和已声明的受支持协议；未知、偏差和不支持的格式保持未满足，不把材料填写、执行完成或单次命中当作整篇论文复现成功。

| 项目 | 实际补充 | 代码与验收 |
|---|---|---|
| 1. 目标与整篇覆盖 | 全 PDF 独立提取、图表候选、整篇实验/主要结论/引用与执行映射；具名审核保存为新计划；未覆盖核心项阻止主要结论 | `paper_text.py`、`audit.py`、`scope-review.mjs`、`assessment.mjs`；伪造页文本/引用、完整及不完整清单测试 |
| 2. 代码完整与版本 | ZIP 安全解包、原参考与实际逐文件 SHA/Git blob 双约束、额外文件检查、Git HEAD、组件与 AST；原文/代码映射审核；修补新材料包记录 parent、before/after 并重置审核 | `materials.py`、`audit.py`；穿越/链接/大小/重复路径、错误参考、未声明文件、修补版本和陈旧 token 测试 |
| 3. 数据获取与核对 | 公共 HTTPS 受控获取，固定解析地址、字节/时间/磁盘/哈希约束、不覆盖矛盾缓存；受限数据申请状态；真实阶段输入输出追踪，生成 ID 在训练前验证 | `acquisition.py`、`verification.py`、`engine.py`；真实 LIBLINEAR 下载校验、超限/私网/错误哈希/受限获取拒绝、划分重叠和标签篡改测试 |
| 4. 环境重建 | 禁网无缓存构建、不可变 base 与镜像 ID、实际 daemon 身份/容量；锁与期望包版本映射、镜像内版本比较及 CUDA 小运算兼容检查 | `runtime_environment.py`、`environment_probe.py`；真实 Docker 重建、错误版本在 artifact 阶段前中止。GPU 无设备和未验证锁格式保持未知 |
| 5. 实验设置 | 冻结种子/方法/参数；实际使用配置严格比较；准备/预处理/训练/评估阶段类型；训练输入、模型产物、后续修改检查；验证集选择轨迹与模型对应 | `acceptance.py`、`engine.py`；错误配置、替换模型、错误候选中止；使用配置回执不等于恶意代码行为的形式证明，语义对应依赖源代码审核 |
| 6. 完整执行 | 浏览器 PDF/ZIP/计划进入本地不可变工作区，绑定后审计、幂等启动、取消、持久化进度与原始报告；按方法和种子贯通准备到汇总 | `service.py`、`workbench.py`、`material-intake.mjs`、`reproduction-workspace.mjs`；真实 HTTP + Docker 正向 15 组矩阵、拒绝/失败/取消及浏览器导入审核验收 |
| 7. 资源与费用 | 区分客户端主机、上传快照和实际 daemon；限额/要求比较；子进程回执与容器外采样分开，项目/阶段输出占用采样；可选 GPU UUID+内核+PID 归属；按阶段拆费用口径 | `monitor.py`、`gpu_monitor.py`、`executor.py`；真实 CPU 案例 30/60 阶段有容器内存采样、547 次输出占用采样；GPU 仅模拟验证，未知单价不生成费用，预先下载/拉基础镜像费用单列排除 |
| 8. 科学验收 | 独立 accuracy/macro F1/MSE/MAE；配对 bootstrap 与多重比较；失败/缺失不丢弃；控制配置、划分、训练输入与预算核对；固定/validation 选择；层级由实际证据计算 | `statistics.py`、`verification.py`、`acceptance.py`；完整/缺失/波动/失败/错误配置/错误选择正反向测试；具名语义审核与完整来源仍是前提 |

公开案例是 [LIBLINEAR CPU 作业 40889691677](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889691677)：15 次 / 60 阶段，147.41363385900002 秒，准确率均值 96.76%。当前作者版本和重新划分的偏差、Figure 1 / rcv1 / 外部求解器未覆盖继续保留；其 training / conclusion 为 false 是验收的正确结果。完整自制协议的训练/主要结论正向门槛则由真实 Docker 和 HTTP CI 验证，不能拿该自制结果冒充论文成绩。

当前本地：120 项 Python 测试，116 通过、4 项 Docker 专项由 CI 验证；47 项前端测试通过。最终代码 ba90da5 已通过 [CI 40889257751](https://github.com/Gump111458785/ArtiCheck/actions/runs/40889257751)，包括真实 HTTP / Docker 正向和错误环境中止；同一代码的真实 CPU 论文运行包含独立 PDF 读回、镜像兼容与外部资源采样。详细操作见 [执行证据说明](EXECUTION_EVIDENCE.md)。

正式外部 benchmark、50 仓库数据集、模型后训练收益、真实 GPU 性能测试不在此次八项 CPU 工程验收中冒充完成。科学结论取决于具体材料和协议，系统不能自动保证任意论文可复现。
