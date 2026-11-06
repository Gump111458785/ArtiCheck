# 工作报告：自有 RTX 4090 GPU 执行器接入与 2026-11-05 五批用户反馈闭环（2026-11-06）

本报告供后续 AI 或工程师独立核对本轮开发范围、架构设计、安全边界、真机验收证据与回归测试结果。

---

## 1. 交付元信息

- **日期**：2026-11-06（北京时间）
- **GitHub 仓库**：`https://github.com/Gump111458785/ArtiCheck`（分支 `main`）
- **EdgeOne 生产域名**：`https://articheck-workbench.edgeone.dev`（登录页：`https://articheck-workbench.edgeone.dev/login.html`）
- **EdgeOne 项目 ID / 部署 ID**：`makers-f8jofllfpwva` / `dpcx8t5a48yd`
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
   - 运行时与磁盘保护：将 `/root/miniconda3/envs/deim` 只读绑定挂载至 `/opt/articheck-runtime`（不修改服务器既有文件与环境）；单任务工作目录创建于 `/dev/shm` tmpfs（约 16 GB 可用空间）并在任务结束后通过 `TemporaryDirectory` 自动清理，保护仅剩 2.4 GB 的 `/` 根分区。
   - `bwrap` 沙箱边界：每个阶段命令在 `/usr/bin/bwrap` 中以无特权用户（宿主机降权至 `articheck`，容器内映射为 `65534:65534`）运行，启用 `--unshare-all`（隔离 user / net / pid / ipc / uts / cgroup 命名空间）、`--cap-drop ALL`、`--new-session`、`--die-with-parent`，仅只读挂载系统库与 `/opt/articheck-runtime`、按需绑定 `/dev/nvidia0` / `/dev/nvidiactl` / `/dev/nvidia-uvm` / `/dev/nvidia-uvm-tools`。已通过探针实测验证：容器内无法访问外网（`network_reachable: false`）、无法读取 `/root/.ssh`（`root_ssh_visible: false`）、宿主机环境变量不泄露（`secret_in_environment: false`）。

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
   - 结构化验收记录：`docs/evidence/feedback-gpu-acceptance.json`（包含 17 项断言、`/v1/capabilities` 返回的 RTX 4090 容量、评估 ID `d64bc0d8df7f48e38fba3eb1a4d84263`、`plan_hardware: "GPU"`、`provider: "owned_gpu"`、阶段 `exit_code: 0` 与实测输出 `gpu_device: NVIDIA GeForce RTX 4090` / `cuda_square_sum: 85344.0`）。
   - 生产截图归档：
     - `docs/assets/feedback-login.png`（独立受邀登录页与眼睛图标）
     - `docs/assets/feedback-home.png`（开始页与深海蓝公开案例卡片）
     - `docs/assets/feedback-task-choice.png`（材料初步识别后的四选一需求弹窗）
     - `docs/assets/feedback-onepage-report.png`（一页式最终报告）
     - `docs/assets/feedback-gpu-execution.png`（RTX 4090 过程详情与默认展开的分层活动记录）
     - `docs/assets/feedback-admin-accounts.png`（管理员受邀账户管理）
3. **GPU 服务器状态核查**：
   - 在可访问 `10.30.41.183` 的环境中运行 `ssh root@10.30.41.183 systemctl status articheck-gpu-worker.service` 可确认拉取守护进程在线，且 `df -h / /dev/shm` 可确认根分区未被任务临时文件占用。
