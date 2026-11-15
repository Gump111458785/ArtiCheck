# EdgeOne Pages / Makers 部署

部署包包含静态工作台与 Python 云函数，页面和 `/v1` 接口使用同一域名。项目使用 EdgeOne 国际站、海外访问区域与新加坡云函数；默认域名为 [articheck-workbench.edgeone.dev](https://articheck-workbench.edgeone.dev)，项目 ID 为 `makers-f8jofllfpwva`。

网站提供模型 API 审查和 E2B CPU 执行；原 v1 材料静态审阅接口继续保留。使用流程与 v2 接口见 [在线工作台](ONLINE_WORKBENCH.md)，实际执行记录见 [网站验收](ONLINE_ACCEPTANCE.md)。

## 1. 构建与上传

```bash
python scripts/build_edgeone.py --esbuild "$(command -v esbuild)"
edgeone login --site global
edgeone makers deploy .edgeone-build.zip -n articheck-workbench -e production --site global --area overseas --skip-ai-gateway-sync
```

构建目录和 ZIP 只包含 `web/dist`、部署配置和白名单 Python 模块。构建时将 `.mjs` 与引用改成 `.js`，并为入口生成内容指纹文件名。生产发布前安装 esbuild 并使用上面的参数，将启动脚本合并为一个文件，将 PDF 解析器打入启动脚本，并为独立解析线程生成带内容指纹的文件名。也可直接执行 `python scripts/build_edgeone.py` 生成分模块的本地预览包。

云函数入口为 `cloud-functions/v1/index.py`，框架收到的路径已去掉 `/v1` 前缀。EdgeOne Python 运行环境为 3.10，使用兼容的 `e2b==2.55.1`；不能直接升级到要求 Python 3.11 的 SDK。依赖由 `cloud-functions/requirements.txt` 安装。[平台 Python 说明](https://pages.edgeone.ai/document/python)。

函数执行上限为 120 秒。审查在单次请求内完成，应用按 108 秒控制模型与可选复核的剩余时间。长时间代码执行交给 E2B，云函数保存任务状态；页面轮询取回结果，不依赖后台线程或函数本地磁盘。

## 2. 服务端环境变量

在项目 **Settings → Environment Variables** 中设置 Production 变量，保存后重新部署。密钥只填写在服务端控制台。

| 变量 | 用途 |
|---|---|
| `ARTICHECK_API_KEY` | DeepSeek API key |
| `ARTICHECK_PUBLIC_ORIGIN` | `https://articheck-workbench.edgeone.dev`，校验浏览器请求来源 |
| `ARTICHECK_REVIEW_TOKEN` | 至少 24 字符的网站访问码，按需提供给试用者 |
| `UPSTASH_REDIS_REST_URL` | 持久化 Redis HTTPS REST 地址 |
| `UPSTASH_REDIS_REST_TOKEN` | Redis 写入凭据 |
| `ARTICHECK_BUDGET_ID` | 沿用部署的 Redis 命名空间，用于报告与图谱等数据 |
| `E2B_API_KEY` | 创建、读取和关闭 CPU 执行与大文件/GPU 中转实例 |
| `ARTICHECK_E2B_TEMPLATE` | 4096 MiB 内存 E2B 实验模板 ID |
| `ARTICHECK_CPU_MEMORY_MB` | 声明的 CPU 实例内存容量（当前为 `4096`） |
| `ARTICHECK_GPU_ENABLED` | 设为 `1` 时启用自有 GPU（`10.30.41.183` RTX 4090）队列派发与心跳检测 |
| `ARTICHECK_GITHUB_TOKEN` | 可选，仅用于提高 GitHub 服务端读取额度 |

模型地址固定为 `https://api.deepseek.com`，型号为 `deepseek-flash`，关闭思考模式。浏览器不能传入供应商密钥、任意服务地址或任意型号。网站访问码和 DeepSeek API key 是两个不同的值。

Redis 使用 [Upstash REST API](https://upstash.com/docs/redis/features/restapi)，需要写入 Token。报告保留 7 天，图谱记录持久保存。

## 3. 调用与执行

所有受邀账户均可使用模型审查、公开资料检索、隔离执行和知识图谱，无应用累计额度。`ARTICHECK_MODEL_ATTEMPTS` 与 `ARTICHECK_COMPUTE_ATTEMPTS` 已停用。模型和沙箱服务按供应商账户的余额、限流和计费规则运行。

同一审查请求或执行提交不会重复启动。执行状态与历史仍由 Redis 保存。文件大小、单次执行时限及图谱并发由各服务的运行条件约束。

## 4. 页面使用

1. 打开 `/login.html` 使用管理员分发的受邀账户登录，进入「在线审查」点击「新建审查」并为项目命名。
2. 上传 PDF、ZIP 或填写公开 GitHub 仓库；至少一项材料即可。
3. 材料初步识别后，阅读材料发送说明并点击提交，在弹窗中选择自动识别、论文自查、复现评估或代码审查。
4. 系统读取图表、核对依据并生成报告；有可执行计划时按硬件需求自动启动隔离 CPU 实例或派发至自有 RTX 4090 GPU 执行器。实际受阻后再询问缺失材料。
5. 在一页式「最终报告」查看结论横幅、问题建议、对齐指标比较表与图表证据，在「过程详情」查看阶段日志与默认展开的分层角色活动记录，并可随时导出 JSON。

完整 JSON 请求仍小于 5 MB。代码 ZIP 与 GitHub 源码包支持 100 MiB、解压合计 500 MiB；大文件通过短期 E2B 写入签名直传，原始文件不经过页面云函数请求体。临时通道最长存活 15 分钟；模型上下文预算不随文件大小扩张。大型 GPU 训练与受限数据不能在本轮 CPU 条件下完成；实际代码运行和论文结论验收分别记录。

## 5. 接口与验收

`GET /v1/capabilities` 返回在线 v2 能力、配置状态与限制，不返回密钥。v2 的材料审查、执行、查询、停止及补料接口见 [接口表](ONLINE_WORKBENCH.md#在线接口-v2)。

原有 `GET /v1/health` 和 `POST /v1/reviews` 继续支持 v1 静态审阅。v1 需要 PDF 与 ZIP，返回 `model_api_static_review`；v2 允许单材料，报告来源为 `model_api_review`，执行观测位于 `execution`。本地自托管 v1 页面从 `#http-api` 进入。

```bash
python -m pip install -e '.[cloud]'
python -m unittest discover -s tests -v
node --test tests/frontend/*.test.mjs
```

历史 v1 教学材料验收保留于 [供应商记录](evidence/edgeone-deepseek-acceptance.json) 和 [浏览器导出](evidence/edgeone-browser-acceptance.json)。v2 的真实网站 CPU 执行和材料类型测试单独记录，不用历史教学结果替代。

### 公开研究脉络

用户在图谱中主动发起检索后，服务用论文题目、DOI 或已匹配的书目 ID 查询 OpenAlex。公开书目和阅读标记保存在当前账号的图谱中，上传的 PDF、报告及其他账号的数据不会发送给书目服务。可选的 `OPENALEX_API_KEY` 由管理员在 EdgeOne 服务端配置；未设置时使用公开接口的匿名额度。找不到可核验的书目信息时保留 PDF 已核对字段或显示未知。

方法贡献使用可公开下载且来源受限的 PDF。服务先定位方法章节并检索相关段落，再调用已配置的模型总结短语及比较贡献。已提取的贡献可复用。图谱只接受能定位到相应方法段落的逐字引用。没有可获取正文时保留书目，旧审查报告如缺少方法证据，可通过公开版本或重新审查原 PDF 补充。
