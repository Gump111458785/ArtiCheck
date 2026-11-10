# 用户反馈与待处理问题

记录日期：2026-11-04。

处理约定：用户已授权集中修复，目标是在后训练前，以真实模型 API 与云端 CPU 执行完成网站体验。以下问题描述保留为原始反馈；代码、真实调用与上线验收分开记录，当前进度见文末。

## 问题总览（2026-11-04）

当前共 23 项反馈，合并为以下六组。核心差距是产品预期默认自动识别、检查和执行，而现有网页仍要求用户填写、绑定和逐条确认，并混用了云端静态审阅与本地执行流程。

| 问题组 | 反馈编号 | 核心问题 | 统一处理目标 |
|---|---|---|---|
| 任务与材料适用范围 | UF-001～005、007 | 强制 PDF＋ZIP；没有完整区分作者自查、复现预审、代码检查及不同文档类型 | 按材料和任务开展适用检查，允许单材料输入，非论文和不适用维度明确处理 |
| 仓库获取与失败恢复 | UF-009、022 | GitHub 需手动读取；只拿目录，后续还需 ZIP；受限提示笼统 | 自动读取与取得所需代码、固定版本、缓存和合理退避；失败后给出具体恢复方式 |
| 指标与证据识别 | UF-012、016 | 正文碎句被当作指标；未理解图表和作者方法，缺少对应验证路径 | 图表结构化提取，优先作者方法，正文按上下文或外部来源核对，保留可追溯依据 |
| 范围与主张交互 | UF-010、011、013～015、017 | 范围层级混乱；新增不可删、不能收起、默认页码误导；强制逐条确认；缺少就地校验 | 默认自动检查，限定范围按需选择；编辑可逆，出处未知时不造页码，真正必填项才校验 |
| 自动准备与实际执行 | UF-018～021、023 | 入口、数据、硬件判断交给用户；线上本地预检不可用；默认系统沙箱尚未接入 | 自动识别入口、准备条件、沙箱执行；受阻再询问，本地执行按需选择，时限选填 |
| 信息层级与辅助栏 | UF-006、008 | 标题、状态、证据、建议缺少区分；右栏占空间但帮助有限 | 清楚区分信息层级，辅助条目简短、可操作，不干扰主任务 |

### 处理原则与依赖

- 先明确作者自查、复现预审与代码检查的任务路径，避免把所有用户送入本地执行表单；当前托管服务只具备模型静态审阅，默认沙箱执行需要真正新增后端能力。
- 材料与类型识别、图表指标提取和代码获取，为自动计划提供依据；不能仅把人工表单隐藏就称为自动化。
- 默认检查可核查项目，用户主动限定范围时再选择；系统先尝试解决阻塞，需要用户补充时说明具体缺口。
- 用户确认必要条件不可得后，对受影响实验记录“当前条件下无法复现”并跳过；无法复现、结果不一致、尚未检查、不适用和通过分别报告。
- 清单与报告必须说明检查覆盖及未完成原因；教学素材跑通不能代替上述场景的验收。
- 推荐先修任务路径与流程阻塞，再补识别和自动获取，随后接通系统沙箱与执行证据；视觉和编辑交互随对应页面统一调整。当前已进入实现与分项验收。

## 本轮反馈

| 编号 | 场景 | 当前表现与风险 | 候选处理方向 | 状态 |
|---|---|---|---|---|
| UF-001 | 用户只上传 PDF | 真实审阅接口要求同时提供 PDF 和 ZIP，单独 PDF 无法提交；缺少论文预审入口 | 支持仅论文的预审，提取主张、实验与材料需求；明确代码一致性无法核对，不能把用户未提交代码解释为作者未提供代码 | 实施与验收中 |
| UF-002 | 用户只上传代码 | 真实审阅接口要求 PDF，单独代码无法提交 | 支持代码可复现性检查，核对运行说明、依赖、入口、配置和数据说明；论文一致性保留为无法判断 | 实施与验收中 |
| UF-003 | 用户上传诊断型／分析型论文 | 没有类型识别与专门审阅规则，固定实验维度可能不适用 | 根据论文实际方法核对数据来源、分析或诊断协议、对照、统计和结论证据，不默认要求模型训练；“诊断型”的具体范围待收集实际样本确认 | 实施与验收中 |
| UF-004 | 用户上传综述型论文 | 固定八项实验审阅可能把训练、算力或代码要求错误应用于综述 | 根据综述类型检查检索策略、纳入排除标准、文献覆盖和归纳依据；无关实验维度标为不适用；保留综述同时包含实验的可能性 | 实施与验收中 |
| UF-005 | 用户上传的 PDF 不是论文 | 现有格式与解析校验不能确认文档属于论文，仍可能生成形式完整的论文审阅报告 | 识别内容是否在服务范围内；非论文或无法判断时明确提示，不强行输出论文复现评价 | 实施与验收中 |

## 第二批反馈：视觉层级与论文自查

记录日期：2026-11-04。以下为原始反馈。

### UF-006：字体、颜色和内容分组缺乏层级

- **用户观察**：字号、字重与颜色过于接近，重点不突出；“示例问题与修正建议”的三条内容之间区分度低，连续阅读费力；八项复现条件的名称、判定和说明混在同一视觉层级。
- **截图佐证**：[用户提供的界面截图](feedback-assets/2026-11-04-typography-hierarchy.png)。截图展示“在目标服务器如何采集”区域：命令已有独立底色，但说明文字仍为连续、相近样式的长段落。问题与建议列表、八项条件的表现来自用户文字反馈，不将本截图描述为这些区域的直接截图。
- **候选处理方向**：每条问题形成独立且有间距的分组，可使用轻边框或浅底色；问题标题、判定状态、证据、修正建议分别设置明确层级；条件名称与状态分开布局，使用文字加图标或标签表达状态，不仅依赖颜色；说明文字采用常规字重和足够对比度，避免整段加粗或过浅灰字。技术命令与说明文字保持独立区域。
- **验收关注**：三条问题可以快速区分；每条问题与对应修正建议可直接对应；八项条件的名称、状态和依据一眼可辨；长说明易读；未知、不适用与未通过不混用同一种标记。具体字体、字号、色值和布局在统一设计时确定。

### UF-007：用户希望检查自己论文的数据与逻辑

- **用户场景**：作者在投稿前上传自己的论文，希望检查文中数据是否一致、论证是否自洽，不一定要复现他人的实验。
- **当前缺口**：入口与八项条件主要围绕复现组织，尚无独立的作者自查任务及对应报告结构。现有通用静态审阅不能视为该模式已经通过验收。
- **候选处理方向**：任务目的与论文类型分别确定。任务目的可包括作者自查、他人论文复现预审、代码检查；论文类型仍可为实验、分析、综述或其他类型。允许仅凭论文开展适用的文字与数值一致性检查，不强制进入环境重建和训练流程。
- **自查范围候选**：摘要、正文、表格和结论的数值一致性；样本量、比例、单位、分母与统计口径；指标定义、公式与表格之间的对应；研究问题、方法、证据和结论之间的支撑关系；前后矛盾、推断跳跃及结论超出实验范围。
- **证据边界**：仅凭 PDF 可检查文内可见内容的一致性，不能确认原始数据真实性、所有计算正确性或结论在现实中成立。需要数值重算时，应支持补充数据表、计算脚本、日志等材料，并区分静态建议与实际重算结果。
- **验收关注**：仅 PDF 可进入作者自查；不适用的代码与训练条件不扣分；每项建议能定位到原文、表格或补充材料；缺少原始数据时不输出“数据已验证正确”；兼容作者后续补充材料和复核。

### UF-008：材料导入页右侧辅助栏缺乏实用性

- **用户观察**：右侧“最近项目”和“从一个实验开始”等内容对当前材料上传帮助有限，不能提供便捷操作，占用较多空间。
- **截图佐证**：[用户圈出的右侧辅助栏](feedback-assets/2026-11-04-intake-right-rail.png)。本项针对材料导入页的右侧区域，不是应用左侧主导航。
- **用户补充约束**：条目不必过于详细；避免长说明或过多内容干扰用户专注。
- **候选处理方向**：围绕本次上传提供少量、简短且可操作的信息，例如 PDF／代码就绪状态与下一步入口；历史项目与通用说明是否移位或折叠，待统一设计时确定。不能把辅助栏改成另一份冗长检查清单。
- **验收关注**：用户能快速发现当前缺什么材料、下一步点哪里；辅助栏能提供实际便利，同时保持视觉克制，不抢占主表单注意力。
- **处理约定**：用户明确要求本项也先记录，暂不修改前端、功能或线上部署，待反馈收集完成后统一处理。

### UF-009：填写 GitHub 地址后自动读取目录

- **用户诉求**：遇到“请读取 GitHub 目录或导入代码 ZIP”时，希望系统自动读取，减少手动操作。
- **候选处理方向**：用户粘贴或完成输入有效 GitHub 仓库地址后自动读取目录，展示读取中、成功或失败状态；ZIP 作为备选入口保留。触发时机在统一实现时确定，避免输入未完成时反复请求。
- **验收关注**：有效地址不必再点“读取目录”；重复地址不重复请求；更换地址后旧请求结果不能覆盖新结果；读取失败、私有仓库或接口限流时提供简短提示和重试／ZIP 入口。目录读取不等于已取得完整源码，后续 API 所需材料应与此入口衔接，避免自动读取成功后仍让用户无说明地卡在 ZIP 要求上。
- **处理约定**：仅记录，待反馈收集完成后统一处理。

## 第三批反馈：主张编辑与默认自动核查

记录日期：2026-11-04。用户继续收集反馈，本批仅记录，不实施功能修改。

复现样本：用户提供的 `1512.03385v1.pdf`（本机路径 `/Users/gump/Desktop/简历/项目2/1512.03385v1.pdf`，已确认 12 页）。保留本机样本路径，不将整篇 PDF 复制进仓库。[界面截图](feedback-assets/2026-11-04-claim-scope-and-editing.png)。

### UF-010：评估范围与实验主张的层级不清

- **用户疑问**：“复现范围”放在“选定实验主张”下面，容易理解为某一条主张的下级字段。
- **预期关系**：评估范围决定本次任务的整体边界；实验主张是该范围内的具体检查对象。全局范围不应混入单条主张编辑。
- **用户追加位置**：“实验范围与资源”页同样存在“0/2 条主张已确认”与“复现范围”的关系不清问题，需要与主张页统一调整，避免重复要求填写范围或逐条确认。
- **核实说明**：截图中的 `itive accuracy (Table 3), suggesting that the solver works` 显示为候选主张，范围输入框本身为空；用户反馈中将其称为系统给出的“复现范围”，反映概念与界面表达均需澄清。

### UF-011：误新增实验主张后无法删除

- **当前问题**：手工添加没有对应的删除入口；取消纳入评估不能代替删除误建条目。
- **预期行为**：支持删除误新增条目，并评估撤销操作；删除、取消纳入和取消编辑的含义明确区分，尽量减少确认负担。

### UF-012：指标候选抽取来源与结构错误

- **用户要求**：数值指标从图或表中定位，不能把包含指标关键词的正文碎句当成可核查指标；上述 `itive accuracy...` 是明确的问题样例。
- **已核实实现**：`candidatesFromPages` 当前按文本行匹配指标词与数字，不理解图表结构；表号等数字可能满足数值筛选条件。当前未提取完整的图表指标记录。
- **预期行为**：识别图表区域、图表编号、方法／模型、数据集、指标名、数值、单位与实验设置的对应关系，保留出处。正文中的图表引用用于补充语义，不直接作为数值指标候选。图中不能可靠读取的数值应保留无法确定或估读标记，不能编造精确值。

### UF-013：新建主张不应默认带入当前阅读页码

- **用户观察**：手工新增条目直接显示“第 9 页”，容易让用户以为系统已经找到出处。
- **已核实实现**：新增动作使用 `page: this.page`，即继承阅读器当前页，并非固定默认第 9 页。
- **预期行为**：未定位出处时不展示具体页码；定位后再显示来源页。支持从用户选中的图表／原文添加时，才绑定明确出处。避免将未知页码默认为第一页或当前页。

### UF-014：展开的新增／编辑条目无法收起

- **当前问题**：展开条目后缺少明确收起或关闭入口；当前展开动作只设置选中条目，没有切回收起状态的操作。
- **预期行为**：提供简明的展开／收起交互，明确关闭编辑是否保留内容；不能强制始终展开某一条。与删除操作分别设计。

### UF-015：默认自动识别需求并核查全部适用指标

- **用户要求**：不要求逐条选择和确认才开始；没有主动框定范围时，系统自动识别可开展的任务，默认检查全部可核查指标。只有用户明确选择“限定范围”时，才进入指定图表／指标的选择流程。
- **预期流程**：材料识别与任务判断 → 自动形成检查清单与范围摘要 → 按适用任务开展检查；用户可以修改或限定范围，不必逐项手工填报。
- **覆盖要求**：说明识别了哪些图表与指标、实际检查了哪些、哪些因缺少材料或预算未检查。不能将候选抽取上限（当前为 30 条）、正文解析遗漏或执行预算耗尽静默解释为已核查全篇。沿用费用保护，自动化不等于无限调用。
- **任务衔接**：与 UF-007 作者自查、论文类型识别共同设计；自动识别任务要有材料依据，不能凭空推断用户的特殊需求。

### UF-016：优先核查作者方法，正文与对照按证据关系处理

- **用户要求**：图表中尤其关注 `ours` 或与论文模型名称对应的数据；其他方法的数据仅在有必要时检索求证，或不逐项求证。正文陈述由系统结合论文上下文或网页资料自动核对，不要求用户逐条选择。
- **预期行为**：识别作者方法的全称、简称、模型变体及图例／行标签，不能只搜索字面 `ours`；对照指标根据支撑关系决定是否检查，报告说明覆盖范围。区分数值图表指标与正文陈述，采用相应检查方式。
- **证据要求**：外部查询保留来源，并核对模型版本、数据集、划分和评估设置是否可比。文内一致性、外部来源一致性与实际运行重算分别记录；网页上的相近数字不能直接证明本论文数据正确或实验已经复现。图表未提供可读取证据时不能输出确定性通过结论。

### UF-017：确认时对未完整填写的必填项提供就地提醒

- **用户要求**：用户未填写完整就点击确认时，在相应位置显示小红色警告符号，提醒补全。
- **候选处理方向**：按当前任务模式校验真正必填的字段；缺失或无效时，在对应字段／条目旁显示小红色警告图标及简短、具体的文字提示，可配合输入框错误边框，并定位到首个问题。不仅依赖颜色表达错误，填写有效后清除提示。
- **与默认自动核查衔接**：默认全量自动核查时，未主动限定的范围应保持可选，不能要求用户为了通过校验填写范围或逐条确认。用户选择自定义范围、手工填写主张或配置实际执行时，再校验相应必填信息。
- **验收关注**：点击确认后能直接发现缺少哪一项及如何补全；条目简短、提示不堆叠；不将正常选填项或“未人工确认但允许自动核查”的状态标成错误；未通过必要校验时不误显示确认成功。
- **处理约定**：仅记录，待反馈收集完成后统一处理。

### UF-018：执行信息与材料应自动识别获取，受阻后再询问

- **用户要求**：实验入口、执行配置及其他复现所需信息应由系统自行识别和获取，不能在开始时要求用户手工查找、填写或绑定。执行过程中发现无法获取时再询问；用户确认无法提供后，跳过并判定无法复现。
- **当前缺口**：“绑定本地执行入口”要求用户提供 `task.json` 并关联检查项，将关键识别工作转交给用户，自动化程度不足。只改字段名称不能解决该问题。
- **预期流程**：系统读取论文、仓库说明、脚本与配置 → 查找论文对应实验入口、依赖、数据、权重及合法可用的获取方式 → 自动形成内部执行配置并记录识别依据 → 在受控执行环境尝试验证和运行 → 遇到无法解决的具体阻塞时，集中向用户询问缺失信息。
- **询问方式**：说明具体缺什么、已尝试哪些方式、失败原因以及哪些实验受影响；只询问无法自行取得的材料或授权，不笼统要求用户补齐所有配置。无法确认的入口不能作为已识别事实直接执行；保留必要的安全、资源和费用约束。
- **用户确认后处理**：缺少运行所必需的材料且用户确认无法获取时，停止该实验并标为“当前材料／条件下无法复现”，记录阻塞证据和跳过原因；其他不受影响的实验继续。用户所说的“pass 掉”指跳过，不是验收通过。尚未获得确认时保留待补充／受阻，不提前形成用户已确认无法提供的记录。
- **判定范围**：缺失关键输入导致无法复现，与实验已运行但结果不一致分别呈现；非关键或不适用信息不直接导致无法复现。局部实验受阻时说明整篇覆盖缺口，不据此把所有实验一并判为失败。
- **与已有反馈衔接**：联合 UF-009 仓库自动读取、UF-015 默认自动核查、UF-017 必填校验处理；自动识别字段不应继续作为启动前要求用户手填的必填项。用户只有在主动限定范围或解决实际阻塞时才需要介入。
- **处理约定**：仅记录，待反馈收集完成后统一处理，当前尚未实现上述自动发现与获取流程。

### UF-019：数据与计算条件由系统先判断、检查和获取

- **用户要求**：“数据与计算条件”同样由系统自行判断与获取，必要时才向用户索取；用户确认找不到或无法提供时，判定无法复现。
- **预期行为**：从论文、仓库说明和实验配置识别所需数据集、版本、划分、预处理、权重及计算资源；先检查已有材料和执行环境，查找可用的数据／权重获取方式，并在既有授权和预算内尝试准备、校验和使用。不能将数据路径、硬件要求等信息一开始全部交由用户手工判断和填写。
- **资源边界**：自动识别需求与检查当前 CPU、GPU、显存、内存、磁盘和环境兼容性；数据或权重可获取时尝试获取。购买数据、租用算力、申请受限访问或扩大费用预算不能因“自动获取”而默认获准；需要时向用户说明缺口。
- **询问及终止条件**：自动处理确实受阻后，具体说明缺失的数据／权重或不足的计算条件、已尝试的方式、受影响实验，以及是否存在符合原实验要求的可行替代路径。用户确认仍无法提供必要条件后，对应实验标为“当前数据／计算条件下无法复现”，记录原因并跳过；不记为验收通过，不把所有不受影响的实验一并判为失败。
- **与已有反馈衔接**：作为 UF-018 的数据与资源专项要求，与 UF-017 校验共同处理。自动识别的信息不应继续以启动前必填表单强制交给用户；当前未探测到资源时先保留未知，不能提前推定用户已确认无法提供。
- **处理约定**：仅记录，待反馈收集完成后统一处理。

### UF-020：执行预算仅保留选填的最长时限

- **用户要求**：“执行预算”区域可以保留，但只让用户填写最长执行时限，也可以不填。
- **预期界面**：保留一个选填的“最长执行时限”，明确单位；移除面向普通用户的工具调用次数等预算输入，避免要求用户理解内部调度参数。
- **默认行为**：不填时采用系统默认时限，不报必填错误；具体默认值在统一实现时确定。为空不代表无限运行，内部费用、资源和安全限制继续生效。
- **验收关注**：空值可继续；显式填写时校验正数、单位和系统允许范围；达到时限时明确报告停止原因及未完成范围，不误记为实验通过或因缺少时限而无法复现。
- **处理约定**：仅记录，待反馈收集完成后统一处理。

### UF-021：默认系统沙箱执行，本地执行由用户主动选择

- **用户要求**：“绑定本地执行入口”不应成为默认流程。系统自行创建沙箱并开展实验执行；只有用户要求使用自己的本地环境时，再选择本地执行。
- **默认流程**：系统识别实验入口与依赖，自动准备内部执行配置，创建隔离沙箱，准备材料、运行实验并回收执行环境；保留日志、产物和必要证据。不要求用户先启动本地工作台或手写、绑定 `task.json`。
- **本地分支**：用户主动选择“本地执行”后，才显示本地连接、工作区映射、权限及环境检查等必要选项；入口识别和配置生成仍由系统优先完成，而不是重新把全部准备工作交给用户。
- **与其他反馈衔接**：联合 UF-018 自动识别执行入口、UF-019 数据与计算条件、UF-020 选填最长时限设计。系统沙箱受内部资源、费用和隔离约束；受阻时按既定流程询问，不静默切换到用户本机执行。
- **实现边界**：当前 EdgeOne 云函数只提供材料静态审阅，没有托管论文代码执行能力。此需求需要实际接入沙箱执行服务、任务调度与证据存储，不能只把页面上的“本地”改成“沙箱”就标为已实现。
- **验收关注**：默认用户无需配置本地环境即可启动受支持的沙箱实验；明确显示真实执行环境及状态；本地选项按需展开；执行结果、失败与超时有证据，沙箱运行结束后完成资源清理。
- **处理约定**：仅记录，待反馈收集完成后统一处理。

### UF-022：GitHub 读取受限提示过于笼统，缺少自动恢复

- **用户遇到的提示**：“GitHub 请求受限，请稍后重试或导入代码 ZIP。”
- **已核实实现**：托管网页直接从浏览器匿名请求 GitHub REST API，一次成功读取包含仓库信息、默认分支提交、递归文件树三个请求。HTTP 403 和 429 都被映射为同一条提示，未解析错误正文及限流响应头。因此当前提示不能证明具体限流原因，也不能据此判断仓库或论文不可复现。
- **外部规则依据**：GitHub 匿名 REST 请求的主额度按出口 IP 计，每小时 60 次；限流原因与恢复时间需结合 `x-ratelimit-remaining`、`x-ratelimit-reset`、`retry-after` 及错误正文判断。[官方限流说明](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) · [错误排查](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api)。
- **候选处理方向**：区分限流、访问拒绝、私有仓库和网络错误；准确展示可重试时间；对同一提交缓存目录、合并重复请求并按响应指示退避。评估服务端 GitHub 授权与代码获取方案，凭据不进入前端；自动恢复确实失败后，再请用户补充 ZIP 或授权，衔接 UF-009、UF-018。不能通过更换出口反复请求规避限流。
- **处理约定**：仅记录，待反馈收集完成后统一处理。

### UF-023：线上本地预检入口不可操作，阻断启动且缺少可理解的指引

- **用户实际阻塞**：“绑定本地执行入口”中的“执行规范路径／检查条件”按钮按不了；“本地执行环境：待连接与预检／未验证”未说明如何验证，最终无法点击“启动选定核查”。
- **已核实原因**：非 `runtime` 模式下“检查条件”直接禁用，预检函数也拒绝调用；启动条件要求本地运行模式、有效预检和执行绑定等。EdgeOne 目前提供的云端模型静态审阅不含这些本地工作台接口。填写路径或反复确认主张不能让线上页面完成本地预检。
- **候选处理方向**：按所选任务及执行环境展示入口，静态 API 审阅不进入本地预检的必经路径。默认系统沙箱的识别、环境准备、预检由系统执行并显示真实状态；本地分支仅在用户主动选择后展示必要连接指导和明确的恢复操作。前端不能用可填写表单与无说明的禁用按钮暗示一项当前不可用的线上能力。
- **状态语义**：“未连接”“正在检查”“检查失败”“环境不支持”分别说明；用户能知道系统正在做什么、具体受阻原因，以及是否需要补充材料。尚未连接执行器不等于论文已被判定无法复现。
- **验收关注**：线上静态审阅不因本地环境未验证被阻断；系统沙箱准备与预检路径可实际完成；选择本地执行时，用户可以从未连接状态按明确步骤恢复；按钮不可用时有具体原因和可执行下一步。
- **关联反馈**：UF-018 自动识别入口、UF-019 自动准备数据与计算条件、UF-021 默认系统沙箱执行。
- **处理约定**：记录为会阻断用户完成流程的问题，待统一处理，当前未修改前端或部署。

## 关联缺口

以下为讨论中识别的关联问题，和上述反馈一起评估，暂不实施。

- **论文与代码的对应关系**：两份材料齐全仍可能来自不同项目；关联证据不足时不能直接判定一致或不一致。
- **解析质量与类型不确定性**：扫描件、空正文或文字提取失败应先说明解析问题；不能把读不到正文判定为非论文。内容类型允许重叠，低置信度时需要用户确认或保留无法判断。
- **报告状态语义**：区分“用户未提供”“维度不适用”“尚未评估”和“实际证据缺失”，避免混为论文缺陷。
- **验收覆盖不足**：已有教学 PDF＋ZIP 验收证明上传、模型调用、展示、导出链路可用，尚未证明系统能处理上述材料组合、论文类型及非论文输入。

## 统一处理时需要覆盖的范围

材料上传页、请求校验、文档类型与任务范围判断、模型提示词、报告契约、结果界面及验收样例需要一致调整，不能仅改提示词。候选流程为：材料识别与解析质量检查 → 内容类型及适用范围判断 → 按可用材料开展对应审阅。

后续验收样例至少包含：仅 PDF、仅 ZIP、实验论文与对应代码、诊断／分析型论文、综述、非论文 PDF、解析失败或扫描件、类型不确定、论文与代码不对应，以及正常材料组合的回归检查。

## 后续反馈记录

继续按 UF-024 起编号追加。每项尽量记录用户操作、材料类型、实际表现、期望行为及可复现样例；样例中的个人资料和未公开材料不直接提交到仓库。


## 集中实施与验收（2026-11-05）

当前在线 v2 流程已部署到 EdgeOne；原 v1 静态接口与本地工作台保留。以下状态指当前支持的 CPU 范围，原始反馈仍保留，避免丢失问题背景。

| 反馈 | 修改位置 | 验收依据与范围 |
|---|---|---|
| UF-001、002 | `hosted_review.py`、`online-workspace.mjs` | 正式网站已接受仅 PDF、仅 ZIP；代码 ZIP 经模型审查后完成真实 CPU 执行 |
| UF-003、004、005 | `hosted_review.py`、`hosted_audit.py` | 实测分析论文、学术评论、含实验的综述；学术评论按论文自查，不以无实验判非论文。普通文档与空白材料分别验证，详见验收记录 |
| UF-006 | `online.css` | 每条问题独立边框、编号与标题，建议使用浅底色与左边线；八项条件采用名称与文字状态标签，依据可展开。真实报告截图已复核 |
| UF-007 | `online-core.mjs`、`hosted_review.py` | 论文自查入口；文内数字、图表、引文与论证建议独立于代码执行，不确认原始数据真实 |
| UF-008 | `online-workspace.mjs` | 右侧只保留当前材料、范围、执行方式和时限摘要，长说明折叠；移除上传页的冗长通用条目 |
| UF-009、022 | `hosted_github.py`、`hosted_store.py`、`online-workspace.mjs` | 正式浏览器粘贴 GitHub 地址后自动取得固定提交的 39 个源文件；防抖、丢弃旧响应、缓存和限流恢复提示保留。没有无限重试或将限流判为论文缺陷 |
| UF-010、015、017 | `online-core.mjs`、`online-workspace.mjs` | 审查范围独立；默认检查适用内容，主动限范围才必填；空材料、空访问码、空指定范围与无授权就地提示。在线启动不依赖人工逐主张确认 |
| UF-011、013、014 | `intake.mjs`、`tests/frontend/online.test.mjs` | 本地主张可删除、撤销、展开与收起；新增页码为空。在线主流程直接使用模型图表清单 |
| UF-012、016 | `pdf_extract.py`、`review_api.py`、`hosted_images.py`、`hosted_audit.py` | 按全篇分配文字上下文并读取原页图像，优先作者方法、Ours 和变体；数字与出处关联，正文片段不转为指标。31 页综述的后半篇表格、分析论文图表已实测；曲线估读与精确值分开，不保证穷尽或识别无误 |
| UF-018 | `hosted_review.py`、`hosted_runner.py` | 从作者仓库说明生成依赖、编译、训练、预测命令；正式网站的 LIBLINEAR 各阶段均已实际执行。失败后记录具体步骤；依赖失败的步骤跳过，独立实验继续，已通过真实子进程回归 |
| UF-019 | `hosted_review.py`、`hosted_sandbox.py`、`hosted_api.py` | 自动检查/使用代码包内数据，记录实际 CPU、内存、时间、磁盘与日志；下载与缺失资源受实际网络/权限约束。代码运行受阻可补充线索；明确超出 CPU 能力时先核对配置，用户确认后记录受影响实验未复现。受限数据不会自动申请权限或付费 |
| UF-020、021、023 | `online-workspace.mjs`、`hosted_sandbox.py` | 唯一预算输入为选填最长时限；默认创建云端 CPU 实例，无需本地连接或手写 task.json。实际网页上传、执行、报告链路已完成；本地环境由用户主动选择 |

[真实网站验收与限制](ONLINE_ACCEPTANCE.md) · [使用与接口](ONLINE_WORKBENCH.md)。质量验收与功能验收分开：当前测试不能推导任意论文都可复现，或所有模型建议均正确。

预算：本轮用户授权总额不超过 100 元；主审、检索和交叉复核共用原有持久化计数，最多 60 次，CPU 执行最多 20 次，各预留 1 元，合计 80 元并保留 20 元余量。预留不是实际账单；失败也计入预留。E2B API key 仅由服务端读取。

## 100 MB 仓库与 ZIP 扩容（2026-11-05）

用户反馈原 GitHub 源码包阈值过小。本轮将 GitHub 压缩源码与本地 ZIP 的上限统一为 100 MiB；GitHub 大仓库返回固定提交引用，本地大文件通过短期签名直传，避免 EdgeOne 单次请求限制。已验证 88 MB ResNet 仓库读取与审查，以及恰好 100 MiB 文件的网页上传、指纹校验和 CPU 执行。[验收记录](ONLINE_ACCEPTANCE.md#6-100-mb-大文件扩容)。

## 集中实施与验收：邀请制登录、实验审查案卷视觉、审查流程与自有 GPU（2026-11-06）

以下五批反馈（2026-11-05 记录）已完成代码实施、自动化回归测试与 EdgeOne 生产环境（`dpcx8t5a48yd`）及自有 GPU 服务器（`10.30.41.183`）实测验收。原始反馈背景保留，状态更新如下。

### 1. 密码可见性图标、邀请制登录、视觉与自有 GPU

| 项目 | 用户要求与修改位置 | 当前状态与验收依据 |
|---|---|---|
| 密码可见性 | `web/dist/ui-icons.mjs`、`web/dist/login.mjs`、`web/dist/account.mjs`：将“显示 / 隐藏”文字替换为眼睛 / 眼睛斜线 SVG 图标，保留 `aria-label`、`aria-pressed` 与键盘操作 | **已完成**：独立登录页与个人中心密码框均已验证切换可见状态 |
| 独立登录页 | `web/dist/login.html`、`web/dist/login.mjs`、`web/dist/login.css`、`web/dist/app.js`：未登录访问工作台先跳转至 `/login.html`，登录成功后返回原页面；配套服务端会话校验 | **已完成**：未登录访问 `/#home` 自动跳转 `/login.html`，登录后进入工作台 |
| 邀请制账户 | `articheck/hosted_auth.py`、`scripts/manage_accounts.py`、`web/dist/account.mjs`：关闭公开注册页面与接口（`POST /v1/auth/register` 返回 `403 invitation_only`）；管理员在个人中心或 CLI 统一创建、停用、启用和重置指定用户密码 | **已完成**：已初始化管理员与受邀验收账户，公开注册已关闭，管理员后台可管理受邀账户 |
| 移除网站访问码 | `articheck/hosted_api.py`、`articheck/hosted_auth.py`、`web/dist/online-workspace.mjs`：用受邀账户会话替代额外网站访问码，移除表单与对应校验；上传、审查、执行与报告读取统一按受邀会话授权，保留全站预算上限 | **已完成**：界面与接口不再要求额外访问码，跨账户报告隔离与费用预算上限保持有效 |
| 配色与设计 skill | `web/dist/feedback-redesign.css`、`web/dist/index.html`、`docs/FEEDBACK_REDESIGN_PLAN.md`：使用 `frontend-design` 建立“实验审查案卷”高对比学术工作台配色（`#f3f6fa` 纸面背景、`#172b3d` 墨色文字、`#1f5f94` 主操作色、`#a6293b` 未通过醒目红、`#17664b` 验收通过色） | **已完成**：全站配色、排版层级与桌面/窄屏布局已更新并截图归档 |
| 自有 GPU | `articheck/hosted_gpu.py`、`articheck/gpu_worker.py`、`articheck/hosted_review.py`、`articheck/hosted_api.py`：接入 `10.30.41.183`（NVIDIA GeForce RTX 4090，24 GB 显存），通过私有 Redis 队列与 systemd 守护进程 `articheck-gpu-worker.service` 拉取任务，在 `bwrap` 无特权命名空间（`--unshare-all`、`--cap-drop ALL`、禁网、只读挂载 CUDA 运行时）中隔离执行需要 GPU 的阶段 | **已完成**：`/v1/capabilities` 实时返回 RTX 4090 容量，生产网页提交 CUDA 任务已在 RTX 4090 上真实完成执行且全阶段退出码为 0 |
| 动态协作 | `web/dist/review-activity.mjs`、`web/dist/online-workspace.mjs`：增强真实阶段变化与运行反馈；“查看 n 条活动记录”默认展开（`open=true`），按阶段分组且不补造角色事件 | **已完成**：活动记录默认展开，刷新不再折叠 |
| API 与集成 | `web/dist/navigation.mjs`：从侧边栏移除“API 与集成”（`contracts`）入口，保留工作台内部依赖的后端接口 | **已完成**：侧边栏已移除该入口 |
| 自托管 API | `web/dist/navigation.mjs`、`web/dist/api-review.mjs`：保留“自托管 API”（`http-api`）入口及连接自部署 ArtiCheck 审阅后端的功能 | **已完成**：侧边栏保留并可正常切换 |

### 2. 审查流程与一页式报告

| 项目 | 修改位置 | 当前状态与验收依据 |
|---|---|---|
| 云端资源位置 | `web/dist/navigation.mjs`、`web/dist/app.js`：将“云端资源”按钮移至左侧栏底部辅助区（`#sidebar-resource`），弹窗实时展示 CPU（2 vCPU / 4 GB）与自有 GPU（RTX 4090 / 24 GB）状态 | **已完成**：不再与项目选择和新建审查混排 |
| 源码读取反馈 | `web/dist/online-workspace.mjs`：GitHub 源码读取增加旋转指示器与实时每秒计时（`data-repo-elapsed`），明确区分读取中、已读取固定提交与读取失败重试，不捏造百分比 | **已完成**：动态等待计时与状态显示已上线 |
| 审查需求弹窗 | `web/dist/online-workspace.mjs`（`chooseTask`）：移除常驻任务单选框；在材料上传并初步识别（页数 / 代码文件数）后、正式调用模型审查前弹出四选一需求窗口，每项附用途与适用范围说明 | **已完成**：符合“材料初步识别后、正式审查前选择”时机 |
| 项目命名 | `web/dist/online-workspace.mjs`（`new`、`createProject`）：新建审查先弹出项目命名窗口，名称同步用于项目选择器、左侧栏与最终报告 | **已完成**：支持自定义项目名创建与展示 |
| 审查中材料区 | `web/dist/online-workspace.mjs`（`render`、`sidebar`）：开始审查及查看报告/过程时隐藏完整上传表单，文件名与材料摘要收拢至左侧栏当前审查卡片 | **已完成**：主体区域专注审查进度与结果 |
| 左侧栏反馈与完成提醒 | `web/dist/online-workspace.mjs`（`sidebar`、`notifyFinished`）：审查或执行进行时左侧栏显示动态状态与快捷入口；完成后弹出提醒并自动切换至最终报告，任务完成与论文结论通过分别表达 | **已完成**：已完成浏览器与单测核验 |
| 角色状态区分 | `web/dist/review-activity.mjs`、`web/dist/feedback-redesign.css`：六角色卡片通过底色、边框、图标标记（`✓` / `!` / 动画点）与文字标签明确区分“已执行 / 进行中 / 需关注 / 未执行” | **已完成**：不再仅靠相近色圆点区分 |
| 结束后材料文案 | `web/dist/online-workspace.mjs`：已有报告后原“准备材料”标签自动改为“材料管理” | **已完成**：状态文案随阶段切换 |
| 活动记录层级 | `web/dist/review-activity.mjs`（`activityGroups`）：默认展开活动记录，并按“材料审阅与计划 / 执行准备 / 各执行阶段 / 实验核查与汇总”分组缩进展示父子层级 | **已完成**：阶段组与子事件层级清晰 |
| 执行计划主流程 | `web/dist/online-workspace.mjs`：开启自动执行时审查返回后自动衔接 CPU / GPU 执行并进入主进度视图；条件不足时在主流程明确展示阻塞原因与补充操作 | **已完成**：无需用户去底部手动寻找执行入口 |
| 指标数值对齐 | `web/dist/online-workspace.mjs`（`observations`）、`web/dist/feedback-redesign.css`：采用固定四列宽度（`.metric-comparison`）与 `tabular-nums` 右对齐数值列，指标、论文值、观测值、比较结果逐列严格对应，“未观测”与数值 0 明确区分 | **已完成**：列标题与数值对齐已修正 |
| 结果优先 | `web/dist/report-verdict.mjs`、`web/dist/online-workspace.mjs`（`finalReport`）：报告顶部显著展示“通过 / 未通过 / 待进一步核查”结论横幅；未通过采用醒目红字（`#a6293b`），未执行或无观测单独注明为待核查，不冒充通过 | **已完成**：顶部结论横幅与状态配色已上线 |
| 一页式最终报告 | `web/dist/online-workspace.mjs`（`finalReport`）：将顶部结论、总体判断、八项条件、问题建议、目标与观测指标比较表、图表出处与覆盖边界整合为一页式最终报告 | **已完成**：无需跨多个标签页拼凑结果 |
| 过程详情合并 | `web/dist/online-workspace.mjs`：将六角色活动记录、执行计划、各阶段命令与实际 stdout 日志统一合并至专门的“过程详情”（`process`）标签页 | **已完成**：结果与过程清晰分离 |

### 3. 帮助模块与公开复现案例卡片

| 项目 | 修改位置 | 当前状态与验收依据 |
|---|---|---|
| 帮助模块与内置样例入口 | `web/dist/navigation.mjs`、`web/dist/app.js`（`helpView`）、`web/dist/home.mjs`：侧边栏新增“帮助”（`help`）模块，将“先用内置样例熟悉流程”移入帮助页，从开始页主操作区移出 | **已完成**：开始页更聚焦，内置样例在帮助页可正常打开 |
| 公开复现案例卡片 | `web/dist/home.mjs`、`web/dist/feedback-redesign.css`（`.start-case`）：开始页 `LIBLINEAR / news20` 公开复现案例采用深海蓝高对比档案卡片，突出案例名称、15 次运行 / 60 个阶段关键数据与四层验收状态区分（通过项与未满足项以不同徽章和对比度呈现） | **已完成**：视觉区分显著，保留真实案例数据与原始验收边界 |

[在线验收与 GPU 实测记录](ONLINE_ACCEPTANCE.md#8-邀请制登录一页式报告与自有-rtx-4090-gpu-验收2026-11-06) · [界面图集](UI_GALLERY.md) · [改版设计方案](FEEDBACK_REDESIGN_PLAN.md)。

## 下拉框细节、底色和谐度、全站状态区分度与 GPU 在线下载复现（2026-11-06 第二批已闭环）

本批 6 项问题已完成代码修复、单元测试、GPU 节点更新（`10.30.41.183`）与 EdgeOne 生产环境部署（`dp5jifitpyre`）及 23 项线上浏览器 + RTX 4090 真机下载复现验收。

| 编号 | 用户反馈问题 | 根因定位 | 实际修复方案与代码位置 | 当前状态与验收依据 |
|---|---|---|---|---|
| 1 | **下拉框右侧小三角位置太靠右，快脱离边框**（图 1：`当前项目` 选择器） | 浏览器原生 `select` 箭头紧贴右边框内侧，不受右内边距控制 | `web/dist/feedback-redesign.css`：为全站 `select:not([multiple])` 设置 `appearance: none`（含 `-webkit-appearance: none`），使用内嵌 SVG 下拉箭头背景并固定右侧留白（`background-position: right 14px center; padding-right: 42px !important; padding-left: 14px !important`） | **已完成**：已验证 `appearance === 'none'`、`paddingRight === '42px'`，箭头与右边框间距舒适 |
| 2 | **卡片颜色可以，但整体背景颜色显得不够和谐，整体底色需改为和谐配色** | 原 `.page` 为刺眼纯白 `#ffffff`，外框 `--ground` 与深海蓝卡片（`#173d61`）及遗留灰绿硬编码（`#e0e6e2` 等）冷暖生硬、卡片缺少表面层级 | `web/dist/feedback-redesign.css`、`web/dist/login.css`、`web/dist/index.html`：将外框与侧边栏底色统一为柔和岩灰蓝 `--ground: #e8eef5`，`.page` 画布设为珍珠浅灰蓝 `#f4f7fb`，内部功能卡片（`.online-form`、`.online-rail`、`.online-stage`、`.online-criterion` 等）保持纯白 `#ffffff` 悬浮卡片层级，并全面清除遗留灰绿硬编码色 | **已完成**：已通过浏览器实测核验 `body`（`#e8eef5`）、`.page`（`#f4f7fb`）、深蓝案例卡片（`#173d61`）与纯白内容卡片（`#ffffff`）过渡自然和谐 |
| 3 | **右侧“本次审查”卡片看不到读取后的变化过程，字体字号与颜色缺少区分**（图 2） | `web/dist/online-workspace.mjs`（`aside.online-rail`）原仅输出静态纯文本“已导入 / 未提供”，字号颜色完全一致且不反映解析/读取过程 | `web/dist/online-workspace.mjs`（`railRows`）、`web/dist/feedback-redesign.css`（`.rail-badge`）：新增实时状态胶囊标签（`ready` 翠绿、`running` 亮蓝配旋转指示器与每秒计时、`failed` 醒目红、`gpu` 深海蓝、`active` 琥珀黄、`info` 钢蓝、`empty` 虚线中性灰）及文件名/页数/文件数/提交号副标题，并在输入或读取变化时实时刷新 `#online-rail-dl`；上传槽新增 `.has-file` 实线绿框与“已就绪”角标 | **已完成**：截图 `docs/assets/feedback-materials-rail.png` 与自动化断言已核验实时状态切换及高对比徽章 |
| 4 | **执行阶段列表区分度不足，“执行中”与“计划中”几乎一样**（图 3） | `web/dist/online-workspace.mjs`（`execution`）原将 `running` 与 `planned` 均映射为 `needs_review` 浅米黄徽章，阶段卡片边框与底色无状态差异，顶部说明小字偏小 | `web/dist/online-workspace.mjs`、`web/dist/feedback-redesign.css`：为每个阶段赋予独立的 `.stage-{running,planned,completed,failed,skipped}` 与 `.status-{running,planned,completed,failed,skipped}` 样式：执行中采用亮蓝实心胶囊 `#1f6feb`、4px 亮蓝左边框、微蓝底色 `#f4f9ff` 与高亮序号圆标；计划中采用虚线边框与中性灰标签；已执行采用森林绿左边框与绿底胶囊；执行失败采用醒目红左边框与红底胶囊；顶部 `.online-kicker` 改为结构化胶囊徽章 | **已完成**：截图 `docs/assets/feedback-gpu-execution.png` 与单测/线上断言已核验 |
| 5 | **全站多处存在类似区分度不够的问题，需全面排查并修复** | 八项审查条件卡片、问题严重度标签、角色协作泳道、上传槽与指标对比表存在扁平与弱对比问题 | `web/dist/feedback-redesign.css`：系统升级八项条件卡片（`.online-criterion.{documented,needs_review,missing,not_applicable}` 4px 状态左边框与背景区分）、问题严重度胶囊（`.online-severity.{high,medium,low}` 独立红/琥珀/蓝配色）、六角色协作泳道（`.review-role-lane.{completed,running,failed,idle}`）、上传槽（`.online-upload` 虚线待上传 vs `.has-file` 实线绿底已就绪）及表格表头/作者方法胶囊标签 | **已完成**：全站各工作区已完成视觉巡检与回归验证 |
| 6 | **自有 GPU 支持在线下载数据/权重/依赖并完整运行，运行结束后无论通过与否均清理删除** | 原 `articheck/gpu_worker.py` 未开启外网连接且缺少 Conda OpenSSL CA 路径映射，同时 `articheck/hosted_review.py` 限制了 `owned_gpu` 阶段在线下载 | `articheck/gpu_worker.py`、`articheck/hosted_review.py`：1. 在 `bwrap` 中保留无特权与文件系统隔离（`--unshare-all --cap-drop ALL --uid 65534` 只读挂载宿主机与 `/opt/articheck-runtime`），启用 `--share-net` 并只读绑定 `/etc/resolv.conf` 与系统 CA 证书；2. 配置 `SSL_CERT_FILE`、`REQUESTS_CA_BUNDLE`、`TORCH_HOME=/work/.cache/torch`、`HF_HOME=/work/.cache/huggingface`、`PIP_CACHE_DIR=/work/.cache/pip`、`PYTHONUSERBASE=/work/.pydeps`、`PIP_USER=1`，将单文件写入上限提升至 2 GiB；3. 更新模型规划提示词，允许自动下载公开数据集、预训练权重与缺失依赖包并运行实验；4. 任务结束（无论通过、失败、超时或取消）后立即执行 `shutil.rmtree(work_dir, ignore_errors=True)` 并销毁 `/dev/shm` 临时目录，回写 `runtime.workspace_cleaned = true` | **已完成**：已在 RTX 4090（`10.30.41.183`）真机沙箱内实测完成外网 HTTPS 下载 + CUDA 张量计算，并验证运行后 `workspace_cleaned: true`、`/dev/shm` 零残留 |

## 集中实施与闭环验收：纯白底色与绿色收敛、运行态防打断、持续运行与自主中断、PPT时间轴与“用设计说明文字”视觉升级（2026-11-06 第三批全部闭环）

本批 12 项反馈已全部完成代码实施、186 项 Python + 112 项 Node 单元测试、EdgeOne 生产环境（`dp7mkzgp3a3y`）部署、RTX 4090 GPU（`10.30.41.183`）真机运行及 21 项线上自动化端到端验收：

| 编号 | 用户反馈问题 | 已核实原因与定位 | 实际修复方案与代码位置 | 当前状态与验收依据 |
|---|---|---|---|---|
| 1 | **图 1 上传成功后的绿色（及其他类似绿色）与主题色违和；尝试将网页底色改为纯白，使绿色和蓝色更顺眼** | `web/dist/feedback-redesign.css` 中 `.online-upload.has-file`、`.review-role-lane.completed` 等使用了整块翠绿底色（`#f1fbf6` / `#e9f8ef`）与高饱和绿框（`#268561`）及全绿文字（`#0f4732`），在灰蓝底色与深蓝主色旁显得突兀违和 | 1. `web/dist/feedback-redesign.css`：将网页主底色（`body` 与 `.page` 画布）改为干净通透的纯白（`#ffffff`），侧边栏使用浅冷灰（`#f8fafc`）与细边框（`#e2e8f0`）；<br>2. 收敛全站绿色：上传就绪卡片（`.online-upload.has-file`）改为纯白卡片表面（`#ffffff`）+ 柔和蓝边框（`#2563eb`）+ 低饱和柔绿胶囊徽章（`#ecfdf5` / `#059669`），深石板黑文件名标题（`#0f172a`），彻底消除整卡刺眼大绿底 | **已完成**：已通过生产环境自动化断言 `bodyBg === 'rgb(255, 255, 255)'`、卡片 `bg === 'rgb(255, 255, 255)'` 并生成实测截图 `docs/assets/feedback-materials-purewhite.png` |
| 2 | **图 2 正在查看运行信息时被强制切到最终报告，并显示“本次操作未完成”** | `web/dist/online-workspace.mjs` 在主审模型返回后直接切换 `this.tab='report'`，随后调用 `execute(p)`；当执行因额度或条件受阻时，页面被切走并弹出顶部阻塞红框；`notifyFinished` 也在后台完成时强制切页打断正在查看过程的用户 | 1. `web/dist/online-workspace.mjs`：当用户正停留在 `process`（过程详情）、`execution` 或 `roles` 查看运行日志时，严禁强制跳出切页，保持在当前过程视图；<br>2. 彻底解耦“主审成功”与“自动执行”，主审报告已生成时不再在顶部弹出全站阻断红框，执行状态与重试按钮内嵌在主流程卡片中 | **已完成**：已通过端到端执行验证，主审与执行平滑流转且不打断过程视图，全站阻断式红框已清除 |
| 3 | **300 秒太少，数据集都下不完；删掉“最长执行时间（默认 300 秒）”输入框，默认只要用户不阻止就不中断，并添加用户自己中断的按钮** | 1. 材料表单原包含 `#online-seconds` 输入框且写死 300 秒；<br>2. 后端与 worker 按 300 秒强制强杀长时间任务；<br>3. 界面缺少随时可点的中断按钮且 `this.busy` 会阻塞操作 | 1. `web/dist/online-workspace.mjs`：彻底移除材料页 `#online-seconds` 输入框与 300 秒强杀提示，默认持续运行至完成；<br>2. `articheck/gpu_worker.py` 与 `articheck/hosted_gpu.py`：移除中途强杀定时器，默认运行至进程自然结束或收到中止信号；<br>3. 在顶部进度条（`.online-progress`）、过程详情卡片头部均加入红色描边“中断运行”按钮，直接触发 `action('cancel')` 中断后端 GPU 执行并清理沙箱 | **已完成**：已通过生产环境 DOM 断言 `!document.querySelector('#online-seconds')`，并验证中断机制与无超时限制执行 |
| 4 | **图 2 六角色卡片（文献审阅 / 代码检查 / 计划编排 / 实验执行 / 交叉核查 / 报告整理）支持点击展开或跳转到详细执行位置** | 原卡片为静态 `div`，无法响应用户交互 | `web/dist/review-activity.mjs` 与 `web/dist/online-workspace.mjs`：将各里程碑节点绑定 `data-role-jump`，点击“实验执行/计划编排”平滑滚动并高亮定位至执行计划与命令区域；点击“文献审阅/代码检查/交叉核查”展开并定位对应活动分组；点击“报告整理”切换并定位到最终报告 | **已完成**：实测点击角色节点支持精准平滑滚动与目标区块高亮脉冲反馈 |
| 5 | **贯彻“用设计来说明文字，而不是用文字来说明设计”，增加图标与合理的微交互/动态化，并进行自我评估与优化美化** | 界面堆砌解释性长句，上传卡片、输入框与状态卡片缺少视觉图标与动态流 | 1. `web/dist/online-workspace.mjs`、`web/dist/review-activity.mjs`：引入成套专业线性 SVG 图标（PDF 论文、代码 ZIP、GitHub、图表指标、问题建议、观测、覆盖等）；<br>2. 材料页新增四选一审查模式胶囊栏（`.review-mode-strip`），以结构化设计自明意图；<br>3. 加入克制呼吸光晕、时间轴动态进度填充与高亮波纹微交互 | **已完成**：已全面替换文字为自明视觉设计，生产断言 `hasModeStrip === true`，见截图 `docs/assets/feedback-materials-purewhite.png` |
| 6 | **“云端执行额度已用完”与“模型调用额度太少”，请大幅调高额度** | `MAX_ATTEMPTS = 60` 与 `MAX_COMPUTE_ATTEMPTS = 20` 额度较小，多轮运行后触顶报 HTTP 429 | 1. `articheck/edgeone_review.py`：模型调用额度 `MAX_ATTEMPTS` 上调至 **`100000` 次**；<br>2. `articheck/hosted_store.py`：云端执行额度 `MAX_COMPUTE_ATTEMPTS` 上调至 **`100000` 次**；<br>3. 生产 Redis 计数已全部安全重置为 0，支持持续高频审查与复现 | **已完成**：`/v1/capabilities` 实时断言 `limits.compute_attempts === 100000`，生产真实评测调用已通过 |
| 7 | **最终报告四项统计卡片（识别图表指标 / 问题与建议 / 执行观测指标 / 覆盖缺口）支持点击跳转到对应详情位置** | 原 `.online-counts` 四项为静态展示，无法点击直达 | `web/dist/online-workspace.mjs`（`finalReport`）：将四项统计卡片改造为 `role="button"` 可交互导航卡片（`data-report-jump`），分别对应指标出处、问题清单、观测对比与覆盖边界，点击触发平滑滚动与 1.5s 柔和高亮呼吸波纹（`section-highlight-pulse`） | **已完成**：生产自动化断言 `countCardsLength === 4`，点击后断言 `target.classList.contains('section-highlight-pulse') === true` |
| 8 | **仅审查论文（或未提供代码）时，不展示未用到的角色卡片（图 1）与无需执行的“执行计划”卡片（图 2）** | 原逻辑固定展示全部 6 角色且无代码时仍渲染大块“执行计划”空卡片 | 1. `articheck/hosted_api.py` 与 `web/dist/review-activity.mjs`：根据材料实际内容动态过滤角色，纯论文时仅保留文献审阅、交叉核查、报告整理，隐藏代码检查与实验执行；<br>2. `web/dist/online-workspace.mjs`：在未提供代码且无执行记录时彻底隐藏“执行计划”区块 | **已完成**：已在单测与生产不同材料输入下核验，纯论文不再出现多余代码/执行卡片 |
| 9 | **所有类型的最终报告顶部固定按“项目名称 → 论文标题与摘要（如有） → 论文创新点或核心贡献（如有） → 审查内容”顺序展示** | 原报告直接呈现结论横幅与模型断言，缺少用户输入的项目主标题及论文自身的学术元数据 | 1. `articheck/hosted_review.py`：模型结构与后处理新增 `paper_title`、`paper_abstract` 与 `paper_contributions` 提取；<br>2. `web/dist/online-workspace.mjs`（`finalReport`）：顶部信息架构重构，最上方展示用户项目名称（`p.title`），紧随论文题录与摘要、核心创新点条目，接下来才是结论横幅与条件判定 | **已完成**：生产自动化断言 `reportStructureCheck.isProjBeforeVerdict === true`，见截图 `docs/assets/feedback-report-priority.png` |
| 10 | **将六角色并排方框（图 1）重构为“一条主轴线 + 分支里程碑节点 + 文字说明”的经典 PPT 时间发展历程样式，并加入动态化效果** | 原设计为 6 个简单圆角方框并排，缺乏流程演进主线与时间轴美感 | `web/dist/review-activity.mjs` 与 `web/dist/feedback-redesign.css`：重构为 `.review-timeline-axis` 水平动态发展历程时间轴，包含贯穿轨道（`timeline-track`）、动态填充进度条（`timeline-progress`）、环形里程碑锚点（`timeline-dot`）、垂直分支线（`timeline-stem`）、文字说明气泡（`timeline-callout`）及进行中呼吸波纹动效 | **已完成**：生产自动化断言 `timelineCheck.hasAxis && timelineCheck.hasTrack`，见实测截图 `docs/assets/feedback-ppt-timeline.png` |
| 11 | **删除左侧导航顶部无用的“研究工作空间 · 论文与代码项目 `>`”跳转卡片（图 1）与顶栏右侧无用的“在线工作台”文字（图 2）** | 侧边栏与顶栏包含多余的不必要跳转与纯展示文字，侵占空间且干扰视线 | `web/dist/app.js`：彻底移除侧边栏顶部的 `.workspace-context` 按钮，移除顶栏右侧的 `.mode-label` 文字标签，保持界面克制聚焦 | **已完成**：生产自动化断言 `!hasWorkspaceContextBtn && !hasModeLabel` |
| 12 | **修复个人中心“个人资料 / 账户访问”排版不合理、左侧空间过大的问题（图 3）** | 原双列网格左侧说明列占用过大宽度，内容偏少导致大片留白 | `web/dist/account.mjs` 与 `web/dist/feedback-redesign.css`：重构为对称的平衡双卡片网格布局（`.account-settings .account-card`），内嵌表头与表单，彻底消除左侧空白 | **已完成**：生产自动化断言 `accountLayout.cardCount === 2 && accountLayout.cols === 2`，见实测截图 `docs/assets/feedback-account-2card.png` |

## 集中实施与闭环验收：第四批用户反馈（2026-11-07 全部闭环）

本批 9 项反馈已全部完成代码实施、189 项 Python（185 通过 / 4 跳过）+ 112 项 Node 单元测试、EdgeOne 生产环境（`dp0orbf34av1`）部署及 20 项线上自动化真机验收（见 `docs/evidence/fourth-batch-acceptance.json`）：

| 编号 | 用户反馈问题 | 已核实原因与定位 | 实际修复方案与代码位置 | 当前状态与验收依据 |
|---|---|---|---|---|
| 1 | **图一这里不要留空白区，直接冲到最上面意思就是直接用一条线把边框与内容分开，停在哪里用边框变色来表示** | 1. `style.css` 中 `.content` 包含 `padding-right: 8px; padding-bottom: 8px;`，主画布 `.page` 有 `border-radius: 16px; border: 1px solid var(--line)`，导致顶栏底部与内容区之间有悬浮卡片留白缝隙；<br>2. 导航与卡片缺少边框变色定位反馈 | 1. `web/dist/feedback-redesign.css`：`.content` padding 清零，`.page` 移除圆角和独立外边框（`border: 0 !important; border-radius: 0 !important;`），内容直冲顶栏底边 1px 细线（`border-bottom: 1px solid var(--line)`）；<br>2. 侧边栏当前激活导航项添加 `border-left: 3px solid #2563eb` 与 `#93c5fd` 边框高亮，页面内悬停与聚焦卡片引入平滑边框色变（`border-color: #3b82f6`） | **已完成**：生产真机断言 `gapTop <= 1`、`pageBorderRadius === '0px'`、`navBorderLeftWidth === '3px'`，见截图 `docs/assets/fourth-batch-flush-layout.png` |
| 2 | **图一添加一个换头像功能**（个人中心头像区域） | 个人中心仅展示固定首字母单字圆标，缺少自定义头像上传或预设更换能力 | 1. `articheck/hosted_auth.py`：`/v1/auth/profile` 支持保存与清空 `avatar`（支持 `preset:*` 与压缩后 Base64 图片），由 Redis Lua 原子更新并随 `/v1/auth/me` 返回；<br>2. `web/dist/account.mjs` 与 `web/dist/feedback-redesign.css`：个人中心头像区新增“更换头像”按钮与弹窗，支持 6 款科研预设图标、本地 PNG/JPG/WebP 上传（Canvas 自动裁剪压缩至 160×160）及恢复默认字母头像，实时同步顶栏与个人中心 | **已完成**：生产真机实测更换头像并持久化至 `/v1/auth/me`（`avatar: "preset:atom"`），见截图 `docs/assets/fourth-batch-avatar-modal.png` 与 `docs/assets/fourth-batch-account-avatar.png` |
| 3 | **图二接口保留但这些内容删去，对于网页用户用不到**（“只检查指定范围”多选框与文本框） | 网页普通用户默认全量检查，界面保留该选项增加认知负担 | `web/dist/online-workspace.mjs`：从材料表单界面中移除“只检查指定范围”多选框与文本框，内部项目数据结构与 `/v1/assessments` 请求载荷仍保留 `scope` 字段兼容 | **已完成**：生产真机断言 `!hasRestrictCheckbox && !hasScopeTextarea`，见截图 `docs/assets/fourth-batch-materials-form.png` |
| 4 | **图三更换样式与跳转方式放在自动审查旁边**（“在自己的电脑执行”折叠项） | 原为页面底部不显眼的 `<details class="online-local">` 折叠区域，操作层级深且与主动作脱节 | `web/dist/online-workspace.mjs` 与 `web/dist/feedback-redesign.css`：移除底部 `<details class="online-local">` 折叠卡片，在“开始自动审查”主按钮旁并列放置带显示器图标的 `.online-local-btn`（“在本地电脑执行”），点击直达本地执行配置 | **已完成**：生产真机断言 `hasNewLocalBtnInSubmit && !hasOldLocalDetails`，见截图 `docs/assets/fourth-batch-materials-form.png` |
| 5 | **图四删去**（“自动准备并执行适用实验计划”复选框） | 界面出现冗余复选框打扰用户；系统已默认持续运行至完成且随时支持中断 | `web/dist/online-workspace.mjs`：移除材料页 `[data-online-field="online_auto_execute"]` 复选框，默认静默启用 `online_auto_execute = true` | **已完成**：生产真机断言 `!hasAutoExecCheckbox`，见截图 `docs/assets/fourth-batch-materials-form.png` |
| 6 | **正在协作审查这几个字加一个动态效果** | “正在协作审查”原为静态文字，缺乏进行时流转动感 | `web/dist/review-activity.mjs`、`web/dist/online-workspace.mjs` 与 `web/dist/feedback-redesign.css`：将运行态标题升级为 `.live-heading`，结合渐变流光扫过动画（`headingShimmer`）与三点波浪跳动指示器（`.live-dots` / `liveDotBounce`），并遵循 `prefers-reduced-motion` | **已完成**：生产真机断言 `.live-heading` 渲染 `headingShimmer` 动画及 3 个动态圆点，见截图 `docs/assets/fourth-batch-live-reviewing.png` |
| 7 | **上传pdf启动自动审查却提示本次操作未完成服务暂时没有返回有效响应，请稍后重试。同时卡在审查阶段无法终止也没有最终报告** | 1. 纯论文审查时模型偶发引用未提供的代码文件名或越界页码，`validate_assessment` 原逻辑直接抛 `ReviewError('invalid_citation', 502)` 导致整篇审查失败；<br>2. 多页 PDF（如 12 页 ResNet 论文）原逻辑将全部 12 页渲染为 1600px 原图（6.55MB Base64）耗时过长导致云函数请求超时；<br>3. EdgeOne 网关将函数 5xx 响应体替换为 HTML 错误页，前端解析 JSON 失败报错“服务暂时没有返回有效响应”；<br>4. `action('cancel')` 原逻辑仅在已有 `execution` 时才向后端发取消，审阅阶段不发且未清理 `online_pending_request`，导致每 3 秒无限轮询卡死 | 1. `articheck/hosted_review.py`：不可核实的页码/文件引用优雅降级记入 `coverage.gaps`，纯论文模式自动忽略模型误生成的计划阶段；增加多模态超时自动降级全文文本审阅保护；<br>2. `articheck/hosted_images.py` 与 `articheck/reproduction/pdf_render.py`：长文优先选取代表性图表页（最多 4 页）并优化分辨率，12 页 PDF 视觉载荷从 6.55MB/35s 降至 1.03MB/0.57s；<br>3. `articheck/edgeone_review.py`：v2 接口将内部 `>=500` 错误映射为 HTTP `424` JSON 返回，穿透网关 HTML 拦截；<br>4. `articheck/hosted_api.py` 与 `web/dist/online-workspace.mjs`：`/assessments/<job>/cancel` 支持直接取消 `reviewing` 状态任务且防止晚到结果覆盖，前端点击“中断运行”立即中止请求、清空 `online_pending_request` 并展示中止状态卡片（`.review-ended`） | **已完成**：生产真机实测审查中点击“中断运行”立即中止并展示 `.review-ended.cancelled`（截图 `docs/assets/fourth-batch-cancelled-review.png`）；重新提交 `1512.03385v1.pdf` 自动审查完整成功（Assessment ID: `632202b0327742e1a15f9592a1c8871d`，提取 35 项图表指标、3 项建议，截图 `docs/assets/fourth-batch-pdf-report.png`） |
| 8 | **最终报告这一块在审查完再给要不然点了无响应** | 原标签栏在未完成审查、尚无报告时也显示“最终报告”标签，用户点击后因为 `r?.review` 为空无任何反馈 | `web/dist/online-workspace.mjs`：计算 `reportReady = Boolean(r?.review && !running)`，仅当审查完成且报告就绪时才在顶部标签栏、侧边栏与材料页展示“最终报告”入口；审查前、审查进行中及已中止/未完成状态下均隐藏该标签 | **已完成**：生产真机断言审查前、审查中与取消后 `!hasReportTab`，审查完成后 `hasReportTab === true` |
| 9 | **在线审查添加终端按钮** | 线上审查缺乏快速打开运行控制台与终端命令日志的直达按钮 | `web/dist/online-workspace.mjs` 与 `web/dist/feedback-redesign.css`：在在线审查顶部工具栏新增深色等宽字体样式的“终端”按钮（`[data-online="terminal"]`，运行态附带绿色呼吸指示点 `.terminal-live-dot`），点击立即切换至过程详情并展开/高亮定位至执行命令、阶段输出或实时活动终端日志 | **已完成**：生产真机断言工具栏存在 `.online-terminal-btn` 且点击后自动切至 `process` 视图并展开高亮终端日志 |

## 集中实施与闭环验收：第五批用户反馈（2026-11-07 全部闭环）

本批 8 项反馈已全部完成代码实施、189 项 Python（185 通过 / 4 跳过）+ 112 项 Node 单元测试、自有 GPU 节点（`10.30.41.183`）守护进程更新、EdgeOne 生产环境（`dp760xsnhwau`）部署及 24 项线上自动化真机验收（见 `docs/evidence/fifth-batch-acceptance.json`）：

| 编号 | 用户反馈问题 | 已核实原因与定位 | 实际修复方案与代码位置 | 当前状态与验收依据 |
|---|---|---|---|---|
| 1 | **图一这个全都删掉，包括下边这一条线**（顶栏左侧 `研究工作空间 > ArtiCheck · 开始` 面包屑及顶栏底部分隔线） | `web/dist/app.js` 与 `web/dist/feedback-redesign.css` 中 `.topbar` 仍渲染 `.breadcrumbs`（`研究工作空间 > ...`）且 `.topbar` 带有 `border-bottom: 1px solid var(--line)` 分隔线 | `web/dist/app.js` 与 `web/dist/feedback-redesign.css`：清空 `.topbar .breadcrumbs` 面包屑文字，并移除 `.topbar` 下方整条分隔横线与阴影（`border-bottom: 0 !important; box-shadow: none !important;`），让主内容区与顶部浑然一体 | **已完成**：生产真机断言 `breadcrumbText === ''` 且 `borderBottomWidth === '0px'`，见截图 `docs/assets/fifth-batch-topbar-clean.png` |
| 2 | **图二这个按钮删了在这里很突兀，加上自定义修改名字的功能**（个人中心头像旁突兀的独立“更换头像”按钮） | `web/dist/account.mjs` 的 `.account-overview` 中除了头像本身的悬浮点击触发外，还在用户名下方多放了一个独立的 `.account-change-avatar-btn`（“更换头像”）按钮，显得突兀；同时顶部概览区名字仅作静态 `<h2>` 展示 | `web/dist/account.mjs`、`web/dist/online-workspace.mjs` 与 `web/dist/feedback-redesign.css`：删除用户名下方突兀的 `.account-change-avatar-btn` 按钮（保留点击头像圆标本身更换头像）；在个人中心顶部名称旁新增“修改名字”按钮与内联表单（`.account-inline-name-form`），支持直接修改保存显示名称并同步顶栏；同时在在线审查工具栏新增“修改名称”按钮（`[data-online="rename"]`），支持随时重命名当前审查项目 | **已完成**：生产真机断言 `!hasAbruptAvatarBtn`、内联改名持久化至 `/v1/auth/me` 且项目改名生效，见截图 `docs/assets/fifth-batch-account-name-edit.png` |
| 3 | **这个也尽量优化掉：`本次操作未完成 请填写 GitHub 仓库首页地址。`** | `web/dist/online-workspace.mjs` 的 `github()` 在用户输入过程防抖触发或粘贴带分支/子路径的链接（如 `/tree/master`、`/blob/...`、`.git`、简写等）时，直接在页面顶部弹出红色报错框 `本次操作未完成 请填写 GitHub 仓库首页地址。` | `web/dist/online-workspace.mjs`（`normalizeGitHubUrl`）：自动从任意 GitHub 链接（含 `/tree/...`、`/blob/...`、`.git`、查询参数或 `owner/repo` 简写）智能提取并归一化为标准仓库地址 `https://github.com/<owner>/<repo>`；输入防抖未构成完整地址时静默等待，不再弹出顶部红色报错横幅 | **已完成**：生产真机实测粘贴 `https://github.com/yoonkim/CNN_sentence/tree/master` 自动归一化为仓库首页并成功读取，全程无报错横幅，见截图 `docs/assets/fifth-batch-materials-repo-name.png` |
| 4 | **图三点开始审查后有弹窗就没必要出现在这里图三的位置了**（材料页四选一审查模式胶囊条） | `web/dist/online-workspace.mjs` 材料页同时存在 `.review-mode-strip`（`自动识别 / 论文自查 / 复现评估 / 代码审查` 四个横向卡片）与点击“开始自动审查”后的模式选择弹窗（`chooseTask`），两者功能重复 | `web/dist/online-workspace.mjs`：从材料准备页移除 `.review-mode-strip` 四卡片区域，统一在用户点击“开始自动审查”后弹出模式确认窗口 | **已完成**：生产真机断言 `!document.querySelector('.review-mode-strip')` 且点击“开始自动审查”正常弹出需求选择弹窗，见截图 `docs/assets/fifth-batch-materials-repo-name.png` |
| 5 | **图四这些没必要每条一个卡片，优化成一个框展示动态终端运行内容即可，类似于 llm 的思考中屏幕上输出的东西**（阶段列表多卡片） | `web/dist/online-workspace.mjs` 的 `execution()` 将每个计划阶段渲染成独立的 `<details class="online-stage">` 卡片，静态感强且割裂 | `web/dist/online-workspace.mjs` 与 `web/dist/feedback-redesign.css`：取消逐条独立卡片列表，合并为一个统一的深色动态终端流式输出框（`.online-terminal-box.online-stage-list`），含终端状态顶栏（`.terminal-topbar`）、环境依赖提示行（`[env]`）与按序实时展示的阶段命令及标准输出流（`.terminal-stream-body`） | **已完成**：生产真机断言 `separateDetailsCount === 0` 且 `.online-terminal-box` 正常渲染，见截图 `docs/assets/fifth-batch-unified-terminal-running.png` 与 `docs/assets/fifth-batch-terminal-completed.png` |
| 6 | **图 5 三个中断执行不知道是否生效，还有一个按完按钮就消失了** | 1. 过程详情页同时出现 3 个中断按钮：顶部 `.online-progress` 的“中断运行”（仅在轮询 `this.busy` 瞬间出现，请求一返回即闪烁消失）、`.review-activity` 头部的“中断运行”、以及 `#online-execution-section` 的“停止执行”；<br>2. 排队或刚接单的 GPU 任务点击停止时存在与 worker 状态回写的竞态，导致状态未能稳定保持 `cancelled` | 1. `web/dist/online-workspace.mjs` 与 `web/dist/review-activity.mjs`：后台 3 秒轮询改用静默刷新 `refresh-silent`（不设置 `this.busy`），消除顶部闪烁进度条；进入实验阶段后 `.review-activity` 展示“阶段执行中”状态胶囊，全页仅保留唯一一个位置固定的停止/中断按钮；<br>2. `articheck/hosted_gpu.py`、`articheck/gpu_worker.py` 与 `web/dist/online-workspace.mjs`：停止时立即从 Redis 队列移除并写入 `:cancel` 标记与 `status='cancelled'`，`GPUWorker.save_record` 拒绝将已取消任务覆盖回 `running`，前端通过 `pollGeneration` 与 `cancelling` 锁立即切换为“已停止”且跨轮询保持不变 | **已完成**：生产真机断言运行期全页仅 1 个可见取消按钮，点击后立即变为“已停止”且跨轮询不回退，见截图 `docs/assets/fifth-batch-execution-cancelled.png` |
| 7 | **源码已读后边最好跟项目名** | `web/dist/online-workspace.mjs` 中 GitHub 源码读取成功后仅显示 `源码已读取 · <commit前12位>` 或 `源码已导入 · N 个文件`，缺少直观的仓库/项目名称 | `web/dist/online-workspace.mjs`：在输入框下方的 `.online-repo-state` 及右侧“本次审查”状态栏徽章（`#online-rail-dl .rail-badge.ready`）中统一显示 `源码已读取 · <owner/repo> (<commit>)` | **已完成**：生产真机断言两处均显示 `源码已读取 · yoonkim/CNN_sentence`，见截图 `docs/assets/fifth-batch-materials-repo-name.png` |
| 8 | **环境跟库肯定也要我们亲自配置呀，不然怎么跑，配置好运行完把环境跟库删了就行（分析源码后自动推导补齐，而非死板照搬作者可能错给或漏给的 requirements）** | 1. 论文源码常存在 `requirements.txt` 缺失、漏写依赖、版本冲突或锁死过时包的问题；<br>2. 缺少结合源码实际 `import` 与运行报错自动推导、补齐环境与第三方库的机制 | `articheck/gpu_worker.py`、`articheck/hosted_runner.py` 与 `articheck/hosted_review.py`：1. 新增 `infer_project_dependencies(work_dir)`（AST 语法树 + Python 2/混合语法正则回退），静态扫描项目全部 `.py` 源码的实际 `import`/`from ... import` 语句，过滤本地模块与标准库，并将常见导入名映射至标准 PyPI 包名（如 `cv2`→`opencv-python-headless`、`sklearn`→`scikit-learn`、`yaml`→`PyYAML`、`PIL`→`Pillow`、`bs4`→`beautifulsoup4`、`skimage`→`scikit-image` 等）；<br>2. 在阶段执行前自动检测隔离环境缺失包并预装至独立 `.pydeps`，若阶段运行出现 `ModuleNotFoundError`/`ImportError` 或 `requirements.txt` 冲突则由 `parse_missing_modules_from_log` 自动补装依赖并重试；<br>3. 运行结束或中断后立即清理整个临时工作目录、`.pydeps` 依赖库与 `.cache` 缓存，回写 `runtime.workspace_cleaned = true` 并在界面底部明确展示 | **已完成**：生产真机实测自动扫描源码推导依赖 `["numpy", "pandas", "theano"]`，运行结束后验证 `workspaceCleaned === true` 且界面展示“隔离环境与临时依赖库已清理”，见 `docs/evidence/fifth-batch-acceptance.json` |

## 集中实施与闭环验收：第六批用户反馈（2026-11-08 全部闭环）

本批 18 项用户反馈已全部完成前后端代码修改、Python 后端与 112 项 Node 前端单元测试、自有 GPU 节点（`10.30.41.183`）`articheck-gpu-worker.service` 守护进程同步重启、EdgeOne 生产环境（`dpqcikcr3edz`）正式部署及 21 项生产环境浏览器端到端自动化真机验收（详见 `docs/evidence/sixth-batch-acceptance.json`）：

| 编号 | 用户反馈问题 | 已核实原因与定位 | 实际修复方案与代码位置 | 当前状态与验收依据 |
|---|---|---|---|---|
| 1 | **最好每条运行时能输出你给的指令与最新三行日志以便用户看到动态变化** | 1. `articheck/gpu_worker.py`（`run_stage_command`）与 `articheck/hosted_runner.py` 原仅在单个阶段进程完全退出后才一次性读取 `S*.log`，运行期间前端看不到实时跳动日志；<br>2. 前端需突出展示当前执行指令与最新 3 行实时滚动日志 | 1. `articheck/gpu_worker.py` 与 `articheck/hosted_runner.py`：新增 `collapse_cr_lines`、`extract_live_tail` 与 `read_bounded_log`，在 `run_stage_command` 轮询循环中每 ~1.8 秒实时流式读取日志末尾最新 3 行（`live_tail`）及累计输出同步回写 Redis / `status.json`；<br>2. `web/dist/online-workspace.mjs`（`extractStageLiveLines`、`execution`）与 `web/dist/feedback-redesign.css`：每个阶段固定展示执行指令 `$ <command>` 并实时渲染最新 3 行日志（`.terminal-live-tail`），同时提供“展开完整日志”折叠面板 | **已完成**：后端单测与生产真机断言 `.terminal-live-tail` 实时展示指令与最新 3 行输出 |
| 2 | **图中黑色过于突兀，换一个舒服点的颜色搭配**（动态运行终端框 `.online-terminal-box`） | `web/dist/feedback-redesign.css` 中 `.online-terminal-box` 原使用纯黑底色（`#0f172a` / `#090d16`），在浅色工作台中反差过大、视觉突兀 | `web/dist/feedback-redesign.css`：将 `.online-terminal-box` 重构为柔和舒适的浅云灰蓝学术控制台配色（`#f8fafc` 底色、`#cbd5e1` 细边框、`#eff6ff` 顶栏、深石板文字 `#0f172a`、雅致蓝提示符 `#2563eb`） | **已完成**：生产真机断言 `termBg === 'rgb(248, 250, 252)'`，与全站白底蓝调风格和谐统一 |
| 3 | **加上临时终止按钮，尤其是复现时的** | 用户在复现评估/实验执行期间盯看终端运行框或时间轴时，缺少触手可及的就地“临时终止”按钮 | `web/dist/online-workspace.mjs` 与 `web/dist/review-activity.mjs`：在动态运行终端框顶栏（`.terminal-topbar`）右侧、执行区块头部及时间轴头部（`.review-activity-actions`）直接内置醒目的红色“临时终止”按钮（`data-online="cancel"`），点击立即终止当前复现并保留已产生证据 | **已完成**：单测与生产真机断言运行期终端顶栏与时间轴均提供“临时终止”按钮且点击即停 |
| 4 | **图中最顶上不要留空这么多**（`在线审查` 标题上方大面积空白） | `.topbar` 占整行高度叠加 `.page` 顶部 `padding-top` 及 `h1` 默认上边距，导致主标题上方留白过大 | `web/dist/feedback-redesign.css`：将 `.topbar` 高度压缩至 `36px`（`padding: 2px 24px 0`），`.page` 顶部内边距收紧至 `4px`，`.page-title` 与 `h1` 上边距清零 | **已完成**：生产真机断言 `topbarHeight === 36px`，页面主标题上方紧凑无多余留白 |
| 5 | **有报错直接中断**（阶段执行遇错立即中止后续阶段） | `articheck/gpu_worker.py` 与 `articheck/hosted_runner.py` 原在某阶段失败时仅跳过显式声明 `depends_on` 的步骤，未绑定依赖的后续阶段仍继续运行 | `articheck/gpu_worker.py`、`articheck/hosted_runner.py` 与 `articheck/hosted_review.py`：默认启用 `fail_fast = True`（有报错直接中断），一旦任意阶段执行失败（自动补包重试后 `exit_code != 0` 或超时），立即中断后续全部阶段并标记为 `skipped`（“前序阶段执行报错，已触发快速中断”），立即清理临时环境并返回中断诊断 | **已完成**：后端单测与生产真机断言阶段 S1 报错后 S2 立即标记为 `stage-skipped` |
| 6 | **图一时间轴各节点按需点开展示该节点的总结报告与信息：下方初始不保留任何内容或卡片，点哪个节点下方显示哪个，不点就不显示，点两下（再次点击）关闭** | 时间轴下方原常驻展示流水账活动记录与执行卡片，且点击节点仅跳往时间戳流水账 | `web/dist/online-workspace.mjs`（`renderRoleNodePanel`、`jumpFromRole`）与 `web/dist/review-activity.mjs`：<br>1. 初始状态 `this.activeRoleNode = null`，时间轴下方不渲染任何活动记录或常驻卡片；<br>2. 点击 `01 文献审阅`～`06 报告整理` 任一节点，在时间轴正下方展开该节点的专属结构化总结报告面板（`#online-role-node-panel`）；再次点击同一节点（点两下）或点“收起节点报告 ✕”立即关闭面板恢复空白 | **已完成**：生产真机断言初始无下方卡片、6 个节点均可点击展开对应总结面板、再次点击即关闭（见 `docs/assets/sixth-batch-node-click-summary.png`） |
| 7 | **图二这里标题 `ArtiCheck · 开始` 过小**（开始页顶部主标题） | 开始页顶部主标题字号偏小，视觉权重不足 | `web/dist/feedback-redesign.css`：将 `.page[data-view="home"] .page-title h1` 字号放大至 `clamp(28px, 3vw, 36px)`、`font-weight: 800`、`letter-spacing: -0.025em` | **已完成**：生产真机断言开始页 `h1` 计算字号为 `36px`（见 `docs/assets/sixth-batch-start-carousel.png`） |
| 8 | **图二右边黑色的也太突兀，改颜色，同时加伪造的多条进行轮播包括各方面未成功的项目案例**（开始页右侧公开复现案例卡片） | `.start-case` 原为突兀黑色且仅静态展示单个案例 | `web/dist/home.mjs`（`SHOWCASE_CASES`）、`web/dist/app.js` 与 `web/dist/feedback-redesign.css`：改为柔和云蓝渐变卡片配色（`.start-case.start-case-carousel`），内置 5 条典型复现案例自动轮播与手动切换（含 `LIBLINEAR / news20` 部分未满足、`ResNet-110 / CIFAR-10` 指标超出容差、`TextCNN / SST-2` 预训练词向量缺失中断、`GAT-Variant / Cora` 数据划分泄漏拦截、`QLoRA-Adapter / MMLU` 评测协议漂移） | **已完成**：生产真机断言 5 条案例轮播与前后切换生效（见 `docs/assets/sixth-batch-start-carousel.png`） |
| 9 | **将“案例与归档”页直接改造为展示“正在复现”与“已复现过”项目条目的专门页面（参考主流网站订单条目页 + 动态效果）** | 原“案例与归档”未集中展示用户正在复现与已复现过的项目条目 | `web/dist/execution-center.mjs`（`onlineOrderItems`、`renderOrderCenter`）、`web/dist/app.js` 与 `web/dist/feedback-redesign.css`：在“案例与归档”顶部构建主流网站订单条目页风格的“我的复现与审查项目条目”中心（`.repro-order-center`），含状态筛选标签页（全部 / 正在复现 / 已完成复现 / 中断·待补完）、订单号、更新时间、动态进度条、当前阶段实时命令与日志摘要，以及“查看实时复现 / 临时终止 / 查看中断原因并补完 / 查看最终报告”快捷按钮 | **已完成**：生产真机断言 `.repro-order-card` 订单卡片列表、筛选与直达跳转正常（见 `docs/assets/sixth-batch-order-center.png`） |
| 10 | **开始页底部“继续我的项目”区域意义不大，予以删减精简** | 开始页底部 `.start-recent` 列表文案老旧且与订单式条目中心重复 | `web/dist/home.mjs`：彻底移除开始页底部 `.start-recent`（`继续我的项目`）区域，并在主操作区提供“查看复现项目列表”直达按钮 | **已完成**：生产真机断言 `!document.querySelector('.start-recent')` |
| 11 | **这种与我们资源有关的隐私问题没必要提交给用户**（左侧边栏底部 `云端资源 · 16 GB` 按钮及页面内服务器硬件/内存/显卡型号明细） | 侧边栏 `#sidebar-resource` 按钮及界面文案暴露了服务器具体 CPU 核数、内存容量与 `RTX 4090` 显卡型号 | `web/dist/app.js`、`web/dist/online-workspace.mjs` 与 `articheck/gpu_worker.py`：从侧边栏彻底移除 `#sidebar-resource`（`云端资源 · 16 GB`）按钮，并在全站前端与执行器状态提示中隐去具体 vCPU、内存 MB/GB 与显卡型号，统一使用中性描述“云端隔离执行” | **已完成**：生产真机断言 `!document.querySelector('#sidebar-resource')` 且界面无硬件隐私暴露 |
| 12 | **左侧栏目当前项目状态卡片（如 `测试2 · 正在执行审查`）支持点击跳转** | `.sidebar-review` 原为静态 `<section>`，点击无跳转响应 | `web/dist/online-workspace.mjs`（`sidebar`、`bind`）与 `web/dist/feedback-redesign.css`：为 `.sidebar-review` 绑定 `role="button" tabindex="0" data-sidebar-jump="<project.id>"`，在任意页面点击该卡片立即跳转至“在线审查”并打开该项目对应阶段视图 | **已完成**：生产真机断言 `.sidebar-review[data-sidebar-jump]` 存在且点击直达对应项目 |
| 13 | **长耗时复现任务在服务器跑完后，前端界面仍停留在旧阶段（如 `[2/6] 执行中`）未自动刷新** | 1. 后台轮询遇到瞬时网络波动将 `this.error` 置非空导致定时器停止；<br>2. 阶段日志超 24KB 时原仅截取文件头导致末尾评测输出丢失且含大量 `\r` 进度条 | 1. `web/dist/online-workspace.mjs`：静默轮询 `refresh-silent` 忽略瞬时网络抖动、不设置阻塞式 `this.error`，且只要任务处于运行态始终保持 `this.timer` 轮询，并在 `visibilitychange` 切回可见时立即同步；<br>2. `articheck/gpu_worker.py` 与 `articheck/hosted_runner.py`：新增 `collapse_cr_lines` 折叠 `\r` 进度条，新增 `read_bounded_log` 在日志超长时同时保留文件头与文件尾（Tail）关键输出 | **已完成**：前后端单测已覆盖验证长日志首尾保留、`\r` 折叠与静默轮询容错 |
| 14 | **执行完这个主线就不要动了，执行哪一步哪一步的圈转圈**（图一时间轴主线动画与节点圆圈状态） | 时间轴主线原带流光闪烁动画，而正在执行的节点圆圈无旋转动效 | `web/dist/review-activity.mjs` 与 `web/dist/feedback-redesign.css`：移除 `.timeline-track-fill` 流光动画，完成态保持纯静态实色翠绿（`.timeline-track-fill.done`）；当某一步处于 `running` 状态时，该步节点圆圈（`.timeline-node.running .timeline-dot`）启用 `@keyframes nodeRingSpin` 旋转圆环动画，执行完或中断后立即停止 | **已完成**：单测与生产真机断言完成态主线静态 `.done`，运行态节点圆圈旋转 |
| 15 | **执行完或中断直接跳转，图二就可以删了**（删除 `.process-ready-banner`“审查报告已就绪 · 查看最终报告”横幅，并在完成或中断时自动跳转） | 执行完成后仍停留在过程页并显示 `.process-ready-banner` 横幅要求用户手动点击 | `web/dist/online-workspace.mjs`（`render`、`notifyFinished`）：彻底删除 `.process-ready-banner` 横幅；当审查与执行正常完成时，`notifyFinished` 自动将视图切换至 `this.tab = 'report'`（最终报告）；当发生报错中断或临时终止时，自动切换至 `process` 并展开中断问题诊断与补完面板 | **已完成**：单测与生产真机断言 `!document.querySelector('.process-ready-banner')` 且完成/中断自动直达目标视图 |
| 16 | **哪一步中断给出问题所在，希望用户纠正或补完材料可以继续审查** | 阶段中断时缺少明确步骤归因与就地补完材料继续审查的入口 | `web/dist/online-workspace.mjs`（`isInterruptedReport`、`interruptionPanel`、`endedCard`）与 `web/dist/feedback-redesign.css`：新增 `#online-interruption-panel` 中断问题诊断与材料补完面板，精准展示中断发生在哪一步/哪一阶段、退出码、命令与报错日志末尾，并内嵌论文 PDF / 代码 ZIP 替换上传、GitHub 地址修正、补充说明文本框及一键“纠正/补完材料并继续审查”按钮（`data-online="resume-review"`） | **已完成**：生产真机断言 `#online-interruption-panel` 准确显示阶段 `S1` 报错原因及内联补完继续审查控件（见 `docs/assets/sixth-batch-interruption-diagnosis.png`） |
| 17 | **是否通过的结果放在最上边不要卡片，最终报告卡片滥用，希望在保证辨识度与区分度的情况下减少卡片的使用**（图三最终报告排版去卡片化重构） | 最终报告拆成大量嵌套边框卡片，且“是否通过”结论被包裹在卡片中 | `web/dist/online-workspace.mjs`（`finalReport`）与 `web/dist/feedback-redesign.css`：将是否通过的裁定结果（`.review-verdict.editorial-verdict`）置于最终报告最顶端，采用无卡片外框、无背景盒子的醒目左侧语义色竖线 + 大号裁定标题排版；全报告去卡片化，将统计条、八项条件、问题建议、指标对比表与覆盖边界改为干净的底部分割线与左侧语义导引线学术排版 | **已完成**：生产真机断言 `.report-editorial-top .review-verdict.editorial-verdict` 位于报告最顶部且全报告去卡片化（见 `docs/assets/sixth-batch-final-report-decarded.png`） |
| 18 | **最终报告给出核心代码并简要解释** | 最终报告原缺少源码中的核心实现代码片段与中文解析 | `articheck/hosted_review.py`（`extract_core_code_snippets`）、`web/dist/online-workspace.mjs`（`extractCoreCodeSnippets`、`coreCodeSection`）与 `web/dist/feedback-redesign.css`：后端与前端从所审源码和执行计划中提取关键实现代码片段（含文件路径、行号范围、代码内容与简明中文逻辑解释），在最终报告中渲染 `#report-code-section`（“核心代码与实现解析”）章节 | **已完成**：后端单测与生产真机断言 `#report-code-section` 展示核心代码片段与实现解释（见 `docs/assets/sixth-batch-final-report-decarded.png`） |


---

## 集中实施待办：第七批用户反馈详细记录（2026-11-08）

以下为第七批用户反馈的逐项定位与待实施方案，已记入本集中实施清单：

| 序号 | 用户原始反馈 | 现状定位 | 待实施修改方案 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | **开始页案例卡片顶部标题栏删除**：“图一这个头直接删了”（配图：`media_1794134666070_f32e7cdd.png`） | `web/dist/home.mjs`（`.start-case.start-case-carousel` 内 `.start-case-topbar`）左侧渲染了 `.start-case-source`（如 `复现受阻案例 · 评测基准版本漂移` + 红色胶囊 `评测协议不符`） | 删除 `.start-case-source` 顶部标题文字与状态标签，保留卡片直接从标题与论文/代码对比切入 | **已完成**：前端单测与真机断言 `start-case-source` 已删除 |
| 2 | **条目去掉项目单号，更新时间与右侧结果移入白底主体**：“图二单号删了，更新时间放在下边白色卡片中，右边结果也放在下边白色卡片中”（配图：`media_1794134697738_0994835b.png`） | `web/dist/execution-center.mjs`（`.order-card-topbar`）单独在灰色顶栏渲染了 `项目单号 #3158921FAB`、`更新时间` 与右侧状态胶囊 `.order-status-pill` | 彻底删除 `项目单号 #...`（`.order-no`）及独立的灰色顶栏 `.order-card-topbar`，将 `更新时间` 与 `审查结果/执行状态标签` 直接合并到下方白色主体行与表格列中展示 | **已完成**：条目卡片/表格行已无单号，时间与结果在白底主体中 |
| 3 | **仅论文项目不应显示“等待云端执行”**：“图三这种只有论文的为什么要等待云端执行，就没有代码应该就不用云端执行了吧”（配图：`media_1794134771645_2f4dda6d.png`） | `web/dist/execution-center.mjs` 与 `web/dist/online-workspace.mjs`：当项目无代码仓库时，状态仍回退为 `'等待云端执行'`，且显示了 `阶段进度：0/0` 与 `查看实时复现` | 识别无代码的纯论文项目：不触发云端执行，状态显示为 `正在审阅论文` / `论文审阅已完成` / `待开始论文审阅`，隐藏阶段进度 `0/0`，按钮提供论文审阅与报告查看 | **已完成**：纯论文项目不再显示等待云端执行与 0/0 阶段 |
| 4 | **案例与归档改为带多维筛选与优先级排序的表格条目页**：“案例与归档做成表格条目的形式，同时在上边加上各种形式的筛选（包括时间，项目名称，按钮以供查询，是否通过审查等内容可以自己引申，代码名字论文名字等），同时未执行完与等待资源的放在最上面，可以参考图五的样式，注意只是样式参考，结构排版，内容颜色等都需要你来判断”（配图：`media_1794135385696_509a219d.png`） | `web/dist/execution-center.mjs` 目前上半部分为订单卡片流、下半部分为旧版执行列表，缺少统一表格结构与多条件筛选栏 | 重构为统一的白底数据表格条目视图：顶部多维筛选栏（项目名、论文名、代码仓库、是否通过审查结论、任务类型、时间）与查询/重置按钮；未执行完（进行中）与等待资源/中断项目优先置顶 | **已完成**：表格条目页支持 6 项筛选与未完成项自动置顶 |
| 5 | **删除案例与归档底部冗余说明条**：“图四这一块直接删了”（配图：`media_1794134850740_a0462fd1.png`） | `web/dist/execution-center.mjs` 渲染了 `完整实验：冻结计划与多次运行` 与 `短时核查：六角色与逐主张判定` | 直接删除 `.execution-list-note` 区块及其相关样式 | **已完成**：`.execution-list-note` 说明条已彻底移除 |
| 6 | **临时中断增加“中断中”动态效果并及时停止普通转圈**：“图六临时中断还是在转圈，能否加个中断中的动态” | `web/dist/online-workspace.mjs` 与 `web/dist/execution-center.mjs`：点击 `临时终止` 后，在异步取消期间仍复用普通蓝灰旋转圈或残留请求导致继续转圈 | 新增专属的 `正在中断…`（`is-cancelling`）琥珀脉冲收敛动效（`.cancelling-anim`），按钮与状态胶囊同步提示；清理本地残留请求，后端确认后立即停止所有转圈动效 | **已完成**：临时中断显示专用动态并在中断后彻底停转 |
| 7 | **案例与归档条目不展示过长命令/简要命令块**：“图一这种过长就不要往上写，其实本来就没必要往上写，因为只是简要内容，没必要”（配图：`media_1794135520448_4efd2f54.png`） | `web/dist/execution-center.mjs` 在项目条目中渲染了完整的命令行与日志尾部 | 在案例与归档条目中直接删去 `.order-live-stage` 命令展示块，保持条目作为简要概览的整洁度 | **已完成**：已移除条目卡片中过长的命令展示块 |
| 8 | **最终报告“八项审查条件”移至审查名字之前、是否通过之后，并删去副标题**：“图二八项审查记录放在审查名字之前，是否通过之后，同时吧材料依据与执行结论分开记录删了”（配图：`media_1794135915636_06777f38.png`） | `web/dist/online-workspace.mjs`：`#report-criteria-section` 排在项目名称、论文摘要和统计数字下方，且带有 `<span>材料依据与执行结论分开记录</span>` | 调整 `finalReport` 排版顺序：将 `#report-criteria-section` 上移到最顶部结论栏（`.editorial-verdict`）下方、审查项目名字（`.report-project-banner`）之前；删除 `材料依据与执行结论分开记录` 副标题 | **已完成**：八项审查条件移至结论后、项目名前，副标题已删除 |
| 9 | **统计数字大数字加颜色，小数字不加颜色**：“图三大数字加颜色，小数字没必要加”（配图：`media_1794135990621_640b5448.png`） | `web/dist/online-workspace.mjs` 与 `web/dist/feedback-redesign.css`：四个统计指标目前大数字与小数字/单位同为深灰黑色 | 为主大数字赋予语义主题色（识别指标 `#1d4ed8`、问题建议 `#d97706`、执行观测 `#059669`、覆盖缺口 `#4f46e5`），单位与分母保持中性灰，不加彩色 | **已完成**：大数字彩色高亮，小数字保持灰度 |
| 10 | **“本地项目”改为开源仓库引导与本地配置教程**：“本地项目改，直接引导到我们的开源仓库内容改成本地配置教程，要符合我们当前网页样式的审美” | `web/dist/navigation.mjs` 与 `web/dist/intake.mjs`（`projects` 页面） | 将“本地项目”重构为开源仓库引导与四步本地环境配置教程，引导至官方开源仓库 `https://github.com/Gump111458785/ArtiCheck`，提供一键复制命令 | **已完成**：本地项目已改为开源仓库引导与本地配置教程 |
| 11 | **删除“自托管 API 接口”**：“自托管api接口直接删了” | `web/dist/navigation.mjs` 与 `web/dist/app.js`（`http-api`） | 从左侧导航栏、页面路由与帮助中心中彻底删除“自托管 API 接口” | **已完成**：已从系统各处彻底删除自托管 API 接口 |
| 12 | **美化“帮助”内容界面**：“帮助内容界面进行美化，符合我们当前网页样式的审美” | `web/dist/app.js` 中的 `helpView()` 与对应样式 | 按照当前统一的白底微边框、清晰四步引导与蓝灰学术配色对“使用帮助”进行全新卡片式美化重构 | **已完成**：使用帮助界面已全面美化升级 |
| 13 | **删除左侧栏底部“在线工作台 / 材料保存在当前浏览器”区块**：“图四这一块直接删去”（配图：`media_1794136192410_b2c41ede.png`） | `web/dist/app.js` 侧边栏底部渲染了连接状态按钮（`.connection-status`） | 直接删除左侧边栏底部的 `.connection-status` 区域 | **已完成**：侧边栏底部连接状态区块已删除 |
| 14 | **拉宽右上角个人信息栏与下方操作按钮的间距**：“图五两个靠的太近了，适当加宽”（配图：`media_1794136380048_93445348.png`） | `web/dist/feedback-redesign.css`：右上角顶栏用户胶囊与页面标题操作按钮间距过近 | 增大 `.topbar` 与下方 `.page-title` 之间的上边距（`margin-top: 28px`），并加宽按钮组间距 | **已完成**：右上角与下方操作按钮间距已合理拉宽 |
| 15 | **删除材料准备页底部的勾选授权说明与保留天数提示**：“图一两个都删去感觉没必要”（配图：`media_1794136543451_72fb8ad3.png`） | `web/dist/online-workspace.mjs` 渲染了勾选框与保留 7 天提示，且提交时校验 `this.consent` | 删除勾选框与保留天数提示文字，`this.consent` 默认设为 `true`，点击开始审查直接提交 | **已完成**：勾选框与保留 7 天提示已删除 |
| 16 | **论文审查后（无论是否通过）新增“学术贡献知识图谱”入口按钮并接入 `功能1.md` 完整能力**：“功能1.md是别人的类似网站的一个知识图谱的功能，我觉得很好所以我也想加一个，为我们的论文审查后不管是否通过没有都加一个按钮引入这个prompt写的功能” | 报告页与项目条目缺少学术贡献知识图谱入口及模块 | 1. 完整实现 `docs/功能1.md` 规格规范：新增 `articheck/kg_service.py`、`web/dist/knowledge-graph.mjs`；<br>2. 支持三层学术贡献网络（Paper → Contribution → Claim → Evidence / ReviewFinding）、交互式星图拖拽平移缩放、节点固定与双击下钻展开、双贡献并排对比面板、邻近贡献学习、研究演化时间轴、私有/总体图谱切换、开关 A/B 与候选冲突人工复核；<br>3. 在所有论文审查后（无论是否通过）及条目列表中均提供醒目的「探索学术贡献知识图谱」按钮 | **已实现图谱入口与报告映射**：论文证据来自已有审查报告。模型抽取、外部元数据检索及完整规格仍待验收 |
| 17 | **删除“终端”按钮**：“图二终端删了”（配图：`media_1794138877024_e6c132af.png`） | `web/dist/online-workspace.mjs` 顶部操作区渲染了深色胶囊按钮 `终端` | 直接删除该 `终端` 按钮并清理相关逻辑与单测断言 | **已完成**：已从工具栏彻底删除终端按钮 |
| 18 | **复现时无条件建立临时 Conda 环境**：“不管有没有要求，复现时都建立临时conda环境” | `articheck/gpu_worker.py` 与 `hosted_runner.py` 原在无额外依赖时不创建新环境 | 修改执行器：无论是否有额外依赖声明，每次复现任务均在临时隔离目录中创建独立 Conda 环境（`.conda_env`），所有命令激活执行，运行结束自动清理 | **待完成**：CPU 使用任务 VM 内的 Python venv，GPU 使用现有运行时与任务专用依赖目录。独立 Conda 环境需在执行模板和 GPU worker 中验证后启用 |
| 19 | **中断诊断面板中的“重试”按钮改为“终止”**：“图一中重试改为终止”（配图：`media_1794139500695_cd277290.png`） | `web/dist/online-workspace.mjs` 中断面板中渲染了“直接重试当前计划” | 将 `直接重试当前计划` 按钮替换为 `终止本次审查`，点击后将项目状态标记为终止并清理待决请求 | **已完成**：中断面板中已将重试改为终止按钮 |

## 第八批反馈（2026-11-10）

| 区域 | 反馈与处理要求 |
| --- | --- |
| 本地项目（图 1） | 按现有工作台的视觉风格重做。首屏主要介绍 ArtiCheck 仓库、用途和适用场景，保留 GitHub 入口与最简上手方式，把详细配置说明放到次要位置。核对仓库可见性、运行命令和环境描述。 |
| 帮助页（图 2） | 「前往账户中心」目前用了 `btn text`，另外两个按钮使用 `btn`。统一三张卡片按钮的边框、尺寸和对齐。 |
| 知识图谱画布（图 3） | 实施时参考开源知识图谱的画布和选中反馈。提高背景、节点标签和连线标签的对比度，减少标签重叠，使选中节点及其关联边一眼可辨。右侧应能读到节点全名。 |
| 图谱范围（图 4） | 删除「总体图谱」「我的＋总体图谱」及分享入口，只保留当前账号自己的图谱。前端和接口均不得读取、展示或关联其他账号的论文，也不再引入外部论文建立图谱关联。旧的总体图谱记录不得通过旧入口或直接调用接口被访问。 |
| 工具栏与研究脉络（图 5） | 上方保留知识图谱主视图与筛选，去掉独立的「研究脉络」切换。把研究脉络放到右侧栏，增加年份、研究方向、发表期刊或会议筛选。缺失的元数据保留为未知。 |
| 潜在冲突 | 从知识图谱侧栏移除「潜在冲突」，把候选冲突和依据放到「论文自查」的最终报告。保留候选与已核实状态的区分。 |
| 侧栏页脚（新增图 1） | 删除左下角两条横向分隔线中靠上的一条，保留 ArtiCheck 与版本号上方的分隔线。 |
| 案例与归档筛选（新增图 2） | 优化搜索和筛选区的布局与控件样式，统一间距与对齐。为「是否通过审查」「材料与任务类型」「更新时间」三个下拉框加清晰的下三角。 |
| 案例与归档条目 | 重排标题、材料、更新时间、状态与操作的层级，按用途设置结构化操作按钮，用颜色区分状态。移除归档条目前方的黄色装饰条带。 |

## 第九批反馈（2026-11-10）

| 区域 | 反馈与处理要求 |
| --- | --- |
| 案例与归档的筛选选项与状态标签 | 每个选项或标签只对应一个预先定义的结论、状态或类型，筛选逻辑与显示名称一一对应。同义表述统一为一个名称，含义不同的状态拆成独立选项，例如「正在审阅」与「正在复现」、「已中断」与「等待资源」。审查结论与执行状态分别归类，避免用「或」或斜杠把多个状态塞进同一个选项。 |
| 归档状态与终止 | 等待补充、可恢复中断用黄色，运行完成且核查通过用绿色，运行完成但发现问题用红色。可恢复中断提供「终止本次审查」，终止后保留记录并关闭原任务的继续与重试入口。 |
| 公开研究脉络 | 从当前论文查找公开的前序研究和后续研究。论文级引用或承接关系直接连接论文节点，标明方向、关系类型和出处。相似创新点或贡献连接各自的贡献节点，说明具体相似之处及来源。公开文献检索与账号内审查记录保持隔离。 |
| 研究脉络的阅读状态 | 每篇论文分别记录「未读」或「已读」。检索发现的论文默认未读，阅读状态由用户确认，与是否上传、是否完成审查分开显示。 |
| 研究脉络的扩展与条目管理 | 任一检索到的论文都可作为新起点，由用户继续查找并记录它的前身、后继和相似贡献。每次只展开有限数量的结果，默认收起更深层级；用户可选择保留、隐藏或移除条目，以及继续展开哪些节点。重复论文复用已有节点，布局为新增节点留出空间。 |
| 知识图谱内容与排版 | 每篇论文展示主贡献和有依据的子贡献，指标与运行证据留在报告。减小文字和圆点，拉开节点间距并避免圆点遮挡标签。 |
| 论文元数据 | 从 PDF 提取并用公开书目核对年份、研究方向、发表期刊或会议，保留来源。无法确认时显示未知。 |
