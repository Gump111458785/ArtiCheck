# EdgeOne Pages / Makers 部署

该部署包同时包含静态工作台和 Python 云函数。页面与 `/v1` 接口使用同一域名。部署目标为 EdgeOne 国际站、新加坡云函数区域；平台当前将 Pages 称为 Makers。

线上工作台：[articheck-workbench.edgeone.dev](https://articheck-workbench.edgeone.dev)。项目 ID：`makers-f8jofllfpwva`。首页与 `/v1/health` 已通过线上检查；真实 DeepSeek 审阅已通过：教学 PDF（2 页）与 ZIP（3 个文件）经云函数解析后，返回 8 项核对和 4 条建议。耗时 10.15 秒，输入 1,401、输出 1,055 tokens，高峰价格估算 0.011242 元。[无密钥验收记录](evidence/edgeone-deepseek-acceptance.json)。这项验收验证服务链路，不代表真实论文审阅质量。

## 1. 构建与上传

```bash
python scripts/build_edgeone.py
edgeone login --site global
edgeone makers deploy .edgeone-build.zip -n articheck-workbench -e production --site global --area overseas --skip-ai-gateway-sync
```

`.edgeone-build` 与归档 `.edgeone-build.zip` 仅复制 `web/dist`、部署配置和白名单 Python 模块。上传构建把 `.mjs` 模块及引用改为 `.js`，并为入口生成内容指纹文件名，避免平台 MIME 类型和浏览器旧缓存导致空白页。源码文件保持原名。

`.env`、本地导入材料、运行目录、模型权重及训练依赖不进入上传包。不要上传整个工作目录。

云函数入口为 `cloud-functions/v1/index.py`，框架收到的路径已去掉 `/v1` 前缀。平台配置的执行上限为 120 秒，PDF 解析上限 20 秒，模型请求上限 60 秒。函数在同一个请求中完成解析和模型审阅；没有后台任务队列，也不依赖函数磁盘保存任务。

## 2. 服务端环境变量

在项目的 **Settings → Environment Variables** 中添加下列变量，作用范围选择 Production。填写后重新部署，使函数读取新配置。界面名称以当前控制台为准。

| 变量 | 填写内容 |
|---|---|
| `ARTICHECK_API_KEY` | DeepSeek 控制台创建的 API Key；只在服务端填写 |
| `ARTICHECK_PUBLIC_ORIGIN` | 网站公开源，例如 `https://articheck-workbench.edgeone.dev`；用于检查请求来源，不依赖平台转发后的内部 Host |
| `ARTICHECK_REVIEW_TOKEN` | 随机生成、至少 24 字符的网站审阅访问码；仅提供给试用者 |
| `UPSTASH_REDIS_REST_URL` | 持久化 Redis 的 HTTPS REST 地址 |
| `UPSTASH_REDIS_REST_TOKEN` | Redis REST 写入凭据；只在服务端填写 |
| `ARTICHECK_BUDGET_ID` | 随机生成、16–128 字符的固定预算标识；同一轮联调保持不变 |

模型地址固定为 `https://api.deepseek.com`，型号为 `deepseek-flash`。不接受浏览器传入供应商密钥、模型地址或型号。访问码和供应商 API Key 是两个不同的值。

持久化计数器使用 [Upstash Redis REST API](https://upstash.com/docs/redis/features/restapi)。创建个人账户下的数据库并复制 REST URL 和写入 Token；预算计数无需保存论文、代码或模型输出。选择无自动升级的免费额度或你已有的数据库，实际额度以平台控制台为准。不要使用会过期的临时数据库，也不要给预算键设置 TTL 或启用会驱逐该键的策略。

## 3. 本轮 10 元预算

云函数先通过一条原子的 Redis Lua 命令预留调用次数，再发出模型请求。全项目共享同一个计数器，整轮最多 10 次请求，每次按 1 元额度保守预留；失败、超时、格式不合格也不退回额度。服务不自动重试。重启和重新部署不清空计数。数据库故障、缺少凭据、访问码错误或额度耗尽均停止模型调用。

输入消息总计不超过 200,000 UTF-8 字节，输出最多 3,000 tokens，关闭思考模式，不调用搜索、抓取或工具接口。按 2026-11-03 查验的 [DeepSeek 官方高峰价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)（输入缓存未命中 2 元 / 百万 tokens，输出 8 元 / 百万 tokens），单次上限保守估算约 0.43 元，低于 1 元预留额。缓存优惠不计入上限。

10 元约束针对这套固定模型、固定配置、本轮计数器发出的请求，不包含账号中其他应用的用量，也不包含域名、托管及数据库费用。供应商调价后需要重新核价。不要通过修改预算标识、清除预算键或重建数据库恢复同一轮额度。建议使用独立 API Key 并关闭自动充值。

## 4. 页面使用

1. 打开部署域名，创建个人论文项目，导入 PDF 和代码 ZIP。
2. 进入「API 接入」，API 地址保持当前网站域名。
3. 填写网站审阅访问码并检查连接。访问码只保存在当前页面内存，不进入项目数据或报告。
4. 确认材料发送授权，提交审阅。等待服务端返回报告后，可在本浏览器查看、导出。

PDF 与 ZIP 合计建议小于 3.5 MB；编码后的完整 JSON 请求必须小于 5 MB，给平台 6 MB 限制保留余量。更大的材料使用本地 HTTP 服务。云端仅返回有限文本摘录的静态审阅建议，不执行作者代码，不据此宣称复现论文结论。

## 5. 接口与验收

`GET /v1/health` 返回配置状态、`mode: synchronous` 和上传限制，不暴露任何密钥。

`POST /v1/reviews` 使用原有 PDF / ZIP JSON 格式，额外要求 `Authorization: Bearer <网站访问码>` 和 `X-ArtiCheck-Client: review-api`。完成后直接返回 `{job, report}`，报告来源为 `model_api_static_review`。云端不提供异步任务查询、取消及报告下载端点，前端已按健康接口模式适配；本地服务保持原有异步协议。

先验证首页和健康接口；缺少配置时必须显示模型未配置。配置完成后，使用仓库自带的教学 PDF / ZIP 做一次供应商端到端验收，核对八项审阅、材料指纹、引用范围和额度。不得以本地假供应商测试代替真实 DeepSeek 验收。

本地检查：

```bash
python -m pip install -e '.[cloud]'
python -m unittest discover -s tests -p 'test_edgeone_review.py' -v
node --test tests/frontend/review-api.test.mjs
```

平台说明：[Python 云函数](https://pages.edgeone.ai/document/python) · [CLI 部署](https://pages.edgeone.ai/document/edgeone-cli) · [函数时限与区域](https://pages.edgeone.ai/document/edgeone-json)。

实际 Redis 并发验收在独立测试命名空间发起 20 次申请，结果为 10 次允许、10 次拒绝；正式联调计数没有被测试重置。正式首个模型请求的额度编号为 1。

网页端也完成了 PDF / ZIP 导入、访问码校验、真实 DeepSeek 请求、八项审阅展示与 JSON 导出验收。第二份报告的额度编号为 2，已验证下载内容与网页任务编号一致。[网页导出报告](evidence/edgeone-browser-acceptance.json)。
