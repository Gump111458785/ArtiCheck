# 工作报告：自有 RTX 4090 GPU 执行器接入与 2026-11-05 五批用户反馈闭环（2026-11-06）

本报告供后续 AI 或工程师独立核对本轮开发范围、架构设计、安全边界、真机验收证据与回归测试结果。

---

## 1. 交付元信息

- **日期**：2026-11-06（北京时间）
- **GitHub 仓库**：`https://github.com/Gump111458785/ArtiCheck`（分支 `main`）
- **EdgeOne 生产域名**：`https://articheck-workbench.edgeone.dev`（登录页：`https://articheck-workbench.edgeone.dev/login.html`）
- **EdgeOne 项目 ID / 部署 ID**：`makers-f8jofllfpwva` / `dp5jifitpyre`（前序部署：`dpcx8t5a48yd`、`dpeka5nesmh2`）
- **自有 GPU 服务器**：`10.30.41.183`（NVIDIA GeForce RTX 4090，24,564 MiB 物理显存 / 24,111 MiB CUDA 可用显存，systemd 服务 `articheck-gpu-worker.service`）

---

## 2. 本轮完成事项与代码位置对照

### 2.1 自有 GPU 隔离执行器接入（`OwnedGPUExecutor` + `HybridExecutor` + `GPUWorker`）

1. **云函数侧混合调度（`articheck/hosted_gpu.py`、`articheck/hosted_api.py`、`articheck/hosted_review.py`）**：
   - `HybridExecutor` 根据 `assessment['review']['plan']['hardware']` 自动路由：`hardware == 'GPU'` 派发至 `OwnedGPUExecutor`，`hardware == 'CPU'` 派发至 `E2BExecutor`。
   - `OwnedGPUExecutor.launch`：验证上传代码 ZIP 的 SHA256 与审查材料指纹一致后，通过禁网 E2B 临时中转实例生成短期签名下载链接（最长 180 秒），将任务元数据推入私有 Redis 队列 `articheck:gpu:<budget_id>:queue` 并记录 `articheck:gpu:<budget_id>:job:<job_id>`。
   - `OwnedGPUExecutor.poll` / `stop`：白名单读取执行器回写的阶段、指标、事件与运行环境字段（源码签名 URL 在拉取后立即清空，且永不返回前端）；当状态离开 `queued` 后自动销毁中转实例；取消操作写入 `:cancel` 键并返回 `cancelling` 状态，直至守护进程终止进程组并确认 `cancelled`。
   - `/v1/capabilities`：实时检查 `articheck:gpu:<budget_id>:heartbeat`（100 秒超时窗口），仅当心跳有效且 `ARTICHECK_GPU_ENABLED=1` 时向模型与前端声明 `gpu=true` 及真实显卡型号 `NVIDIA GeForce RTX 4090`。
2. **GPU 服务器侧拉取守护进程与无特权隔离（`articheck/gpu_worker.py`）**：
   - 部署位置：`10.30.41.183:/opt/articheck-worker/gpu_worker.py`，由 `/etc/systemd/system/articheck-gpu-worker.service` 托管运行。
   - 凭据隔离：`/etc/articheck-gpu-worker.env`（`0600`）仅包含 `UPSTASH_REDIS_REST_URL`、`UPSTASH_REDIS_REST_TOKEN`、`ARTICHECK_BUDGET_ID`，不含 DeepSeek、GitHub、E2B 密钥。
   - 运行时与磁盘保护：将 `/root/miniconda3/envs/deim` 只读绑定挂载至 `/opt/articheck-runtime`（不修改服务器既有文件与环境）；单任务工作目录创建于 `/dev/shm` tmpfs（约 16 GB 可用空间），并在任务结束（无论通过、失败、超时或取消）后立即执行 `shutil.rmtree(work_dir, ignore_errors=True)` 彻底删除工作目录并退出 `TemporaryDirectory`，记录 `runtime.workspace_cleaned = True`，保护仅剩 2.4 GB 的 `/` 根分区与 `/dev/shm` 内存盘。
   - `bwrap` 沙箱与在线下载复现支持：每个阶段命令在 `/usr/bin/bwrap` 中以无特权用户（宿主机降权至 `articheck`，容器内映射为 `65534:65534`）运行，启用 `--unshare-all --share-net`（隔离 user / pid / ipc / uts / cgroup 命名空间并开启外网连接）、`--cap-drop ALL`、`--new-session`、`--die-with-parent`，只读挂载系统库、`/opt/articheck-runtime` 及系统 DNS/CA 证书（`/etc/resolv.conf`、`/etc/ssl`、`/etc/ca-certificates`），并注入 `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`、`REQUESTS_CA_BUNDLE`、`TORCH_HOME=/work/.cache/torch`、`HF_HOME=/work/.cache/huggingface`、`PIP_CACHE_DIR=/work/.cache/pip`、`PYTHONUSERBASE=/work/.pydeps`、`PIP_USER=1`，支持自动下载公开数据集（如 CIFAR-10）、预训练权重与缺失依赖包并完整执行实验。

### 2.4 2026-11-06 第二批 6 项视觉与 GPU 在线下载复现反馈修复

1. **下拉框右侧箭头内距（图 1）**：`web/dist/feedback-redesign.css` 为全站 `select:not([multiple])` 设置 `appearance: none`、内嵌 SVG 下拉箭头（`background-position: right 14px center`）与 `padding-right: 42px !important; padding-left: 14px !important`，彻底消除原生下拉箭头紧贴右边框的问题。
2. **全站和谐底色与卡片表面层级**：`web/dist/feedback-redesign.css`、`web/dist/login.css`、`web/dist/index.html` 将外框与侧边栏底色设为柔和岩灰蓝 `--ground: #e8eef5`、`.page` 画布设为珍珠浅灰蓝 `#f4f7fb`、内部功能卡片（`.online-form`、`.online-rail`、`.online-stage`、`.online-criterion` 等）保持纯白 `#ffffff` 悬浮卡片层级，并清除遗留灰绿硬编码色（`#e0e6e2` 等），与开始页深海蓝案例卡片（`#173d61`）自然融合。
3. **右侧“本次审查”实时状态与高对比胶囊徽章（图 2）**：`web/dist/online-workspace.mjs`（`railRows`）与 `web/dist/feedback-redesign.css`（`.rail-badge`）为“论文 / 代码 / 范围 / 执行位置”四栏提供实时状态胶囊（`ready` 翠绿、`running` 亮蓝配旋转指示器与每秒计时、`failed` 醒目红、`gpu` 深海蓝、`active` 琥珀黄、`info` 钢蓝、`empty` 虚线中性灰）及文件名/页数/文件数/提交号副标题；上传槽新增 `.has-file` 实线绿框与“已就绪”角标。
4. **执行阶段列表状态区分度（图 3）**：`web/dist/online-workspace.mjs`（`execution`）与 `web/dist/feedback-redesign.css` 将各阶段卡片拆分为 `.stage-{running,planned,completed,failed,skipped}` 与 `.status-{running,planned,completed,failed,skipped}`：执行中采用亮蓝实心胶囊 `#1f6feb`、4px 亮蓝左边框、微蓝底色 `#f4f9ff` 与高亮序号圆标；计划中采用虚线边框与中性灰标签；已执行采用森林绿左边框与绿底胶囊；执行失败采用醒目红左边框与红底胶囊；顶部 `.online-kicker` 改为结构化胶囊徽章。
5. **全站状态对比度巡检与增强**：统一升级八项审查条件卡片（`.online-criterion.{documented,needs_review,missing,not_applicable}`）、问题严重度胶囊（`.online-severity.{high,medium,low}`）、六角色协作泳道（`.review-role-lane.{completed,running,failed,idle}`）及指标目录表头与作者方法胶囊标签。
6. **GPU 在线下载复现与运行后自动删除**：`articheck/hosted_review.py` 与 `articheck/gpu_worker.py` 允许 GPU 阶段在线下载公开数据集、权重与缺失 Python 依赖，并在运行结束后无论通过与否均执行 `shutil.rmtree(work_dir, ignore_errors=True)` 彻底删除所有下载和生成文件。

### 2.2 邀请制账户、独立登录页与移除额外网站访问码

1. **后端认证与授权（`articheck/hosted_auth.py`、`articheck/hosted_api.py`、`scripts/manage_accounts.py`）**：
   - 关闭公开注册：`POST /v1/auth/register` 固定返回 `403 invitation_only`。
   - 新增管理员接口：`GET /v1/auth/admin/users`、`POST /v1/auth/admin/users`（创建受邀账户）、`POST /v1/auth/admin/users/<user_id>`（支持 `reset_password`、`disable`、`enable`，禁止管理员停用自身）。
   - 移除网站访问码：在默认邀请制模式下，`/v1/uploads`、`/v1/repositories`、`/v1/assessments` 等接口统一验证受邀登录会话 Cookie，不再要求额外的网站访问码；全站模型与算力预算计数继续生效。
2. **前端独立登录页与管理界面（`web/dist/login.html`、`web/dist/login.mjs`、`web/dist/login.css`、`web/dist/ui-icons.mjs`、`web/dist/account.mjs`）**：
   - 未登录访问工作台自动跳转 `/login.html?next=...`，登录成功后跳回目标页。
   - 登录页与个人中心密码输入框均采用眼睛 / 眼睛斜线 SVG 图标切换明文/密文，保留无障碍标签与键盘焦点。
   - 管理员在个人中心可直接创建受邀用户、重置密码、停用/启用账户。

### 2.3 “实验审查案卷”视觉、审查工作流与一页式报告改版

1. **视觉与导航（`web/dist/feedback-redesign.css`、`web/dist/navigation.mjs`、`web/dist/home.mjs`、`web/dist/app.js`）**：
   - 侧边栏移除“API 与集成”（`contracts`），保留“自托管 API”（`http-api`），新增“帮助”（`help`，内置教学样例入口移入其中），并将“云端资源”（`.sidebar-resource`）移至侧边栏底部。
   - 开始页公开 `LIBLINEAR / news20` 案例采用深海蓝高对比卡片（`.start-case`），突出 15 次运行 / 60 个阶段关键数据，并将四层验收状态按通过/未满足做显著视觉区分。
2. **审查工作流（`web/dist/online-workspace.mjs`）**：
   - 新建审查先弹出项目命名弹窗（`#new-review-form`）。
   - 移除上传表单中的常驻任务单选框与网站访问码输入框；材料上传并初步识别（页数 / 代码文件数）后、正式调用模型前弹出四选一“选择本次审查需求”窗口（`chooseTask`）。
   - GitHub 仓库读取增加旋转指示器与每秒动态计时（`[data-repo-elapsed]`）。
   - 审查开始及查看结果/过程时隐藏完整上传区，左侧栏 `#sidebar-review` 实时显示当前项目进度与材料摘要，审查结束后弹出完成提醒并自动切换至最终报告。
3. **一页式最终报告与过程详情分离（`web/dist/report-verdict.mjs`、`web/dist/review-activity.mjs`、`web/dist/online-workspace.mjs`）**：
   - **最终报告（`report`）**：单页汇总顶部结论横幅（`.review-verdict`，未通过采用醒目红字 `#a6293b`，通过采用 `#17664b`，未执行或缺少观测值明确标为“待进一步核查”）、总体判断、八项条件、问题建议、四列对齐的“论文目标与实际观测”比较表（`.metric-comparison`，右对齐 `tabular-nums`，严格区分“未观测”与数值 0）、图表指标目录与覆盖边界。
   - **过程详情（`process`）**：整合默认展开（`open=true`）且按阶段父子层级分组的六角色协作活动记录（`.review-activity-log`）、强化区分度的角色状态卡片（`.review-role-lane`）以及各阶段命令与实际 stdout 日志。

---

## 3. 核验方法与实测证据

其他 AI 可直接通过以下命令与文件核对本轮结果：

1. **自动化单元测试**：
   - Python 测试（186 项：182 项通过，4 项本地 Docker 专项跳过）：
     ```bash
     /Users/gump/Documents/Codex/2026-10-26/1-articheck-artifact-pytorch-verl-vllm/work/test-venv/bin/python -m unittest discover -s /Users/gump/Documents/Codex/2026-10-26/1-articheck-artifact-pytorch-verl-vllm/outputs/ArtiCheck/tests
     ```
   - 前端测试（112 项全部通过）：
     ```bash
     /Users/gump/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test /Users/gump/Documents/Codex/2026-10-26/1-articheck-artifact-pytorch-verl-vllm/outputs/ArtiCheck/tests/frontend/*.test.mjs
     ```
2. **生产环境真机 GPU 与浏览器验收证据**：
   - 结构化验收记录：`docs/evidence/feedback-gpu-acceptance.json`（包含 23 项断言、`/v1/capabilities` 返回的 RTX 4090 容量、评估 ID `f51badca5a5f4cea86e439cc9e1e5792`、`plan_hardware: "GPU"`、`provider: "owned_gpu"`、阶段 `exit_code: 0`、实测外网 HTTPS 下载 `download_ok: True bytes= 65536`、CUDA 输出 `gpu_device: NVIDIA GeForce RTX 4090` / `cuda_square_sum: 85344.0` 以及运行后工作目录清理确认 `workspace_cleaned: true`）。
   - 生产截图归档：
     - `docs/assets/feedback-login.png`（独立受邀登录页与眼睛图标）
     - `docs/assets/feedback-home.png`（开始页和谐岩灰蓝/珍珠白底色与深海蓝公开案例卡片）
     - `docs/assets/feedback-materials-rail.png`（准备材料页自定义下拉箭头、已就绪上传槽与“本次审查”高对比实时胶囊徽章）
     - `docs/assets/feedback-task-choice.png`（材料初步识别后的四选一需求弹窗）
     - `docs/assets/feedback-onepage-report.png`（一页式最终报告）
     - `docs/assets/feedback-gpu-execution.png`（RTX 4090 过程详情、阶段状态胶囊与默认展开的分层活动记录）
     - `docs/assets/feedback-admin-accounts.png`（管理员受邀账户管理）
3. **GPU 服务器状态核查**：
   - 在可访问 `10.30.41.183` 的环境中运行 `ssh root@10.30.41.183 systemctl status articheck-gpu-worker.service` 可确认拉取守护进程在线，且 `df -h / /dev/shm` 可确认根分区未被任务临时文件占用。
