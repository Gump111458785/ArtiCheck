# Baseline 来源与对接约定

- 业务 baseline：[1a1a11a/2026_paper_reproduce](https://github.com/1a1a11a/2026_paper_reproduce)。
- 参考提交：[dffac1885dbca1aff9b28d79916140b8af71dedf](https://github.com/1a1a11a/2026_paper_reproduce/tree/dffac1885dbca1aff9b28d79916140b8af71dedf)。
- 本地核对日期：2026-10-26。
- 核对接口：`repro_cli.py run`、`paper_agent/schema.py` 中 `ReproReport`、`ClaimVerdict`。
- 上游负责 PDF 读取、仓库发现、环境安装与复跑；ArtiCheck 提供独立的任务核查和训练基础架构。

参考版本根目录没有 LICENSE。本项目不分发、修改或重新许可其源码，MIT 仅覆盖本仓库原创实现。`vendor/` 默认忽略；外部安装前应自行确认上游使用授权。README 中克隆命令用于取得用户指定 baseline，不表示 ArtiCheck 向第三方授予其源码权利。

## 安装与运行

将 baseline 安装在独立环境中：

```bash
git clone https://github.com/1a1a11a/2026_paper_reproduce.git vendor/baseline
git -C vendor/baseline checkout dffac1885dbca1aff9b28d79916140b8af71dedf
python3 -m venv vendor/baseline/.venv
vendor/baseline/.venv/bin/python -m pip install -r vendor/baseline/requirements.txt

export UPSTREAM_DIR="$PWD/vendor/baseline"
export BASELINE_PYTHON="$UPSTREAM_DIR/.venv/bin/python"
bash scripts/run_upstream.sh /absolute/paper.pdf /absolute/baseline-report.md \
  --vm-host your-dedicated-host --vm-user your-user

python -m articheck import-upstream \
  --input /absolute/baseline-report.json --output runs/imported-baseline.json
```

上述命令从 ArtiCheck 仓库根目录运行；按上游 README 设置其模型 API 凭据与远程执行环境。PDF、报告路径和主机名需替换为实际值。上游执行隔离由其自身配置，本项目的 Docker 限制不会自动作用于该独立进程。

## 报告映射

| 上游 status | ArtiCheck 导入 verdict | 原因 |
|---|---|---|
| reproduced | supported | 保留上游的复现成功断言，仍需核验证据 |
| partially_reproduced | inconclusive | 未完全覆盖主张 |
| not_reproduced | inconclusive | 运行失败与科学结论错误不能等同 |
| not_attempted | inconclusive | 没有执行证据 |

导入记录带 `import_only=true`；不会生成“已验证”的 token 轨迹或真值。`reference_commit` 是适配器参考版本，`actual_upstream_commit` 是启动脚本记录的实际执行版本；直接导入他人报告时后者可能为 unknown。

## 公平对照建议

正式实验应冻结相同论文/仓库版本、硬件、工具预算和可用数据，分别运行外部 baseline、固定 Planner 与训练后 Planner。人工审查后的主张 ID 才能用于对齐不同系统输出。当前版本未提供跨系统语义自动对齐，也未运行真实论文对照实验。
