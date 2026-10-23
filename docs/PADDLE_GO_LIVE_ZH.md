# Paddle 上线操作与验收

更新：2026-10-24。当前实现支持 sandbox / production；默认不开启收费。
本文是本项目当前上线依据，替代早期只支持沙盒的迁移评估。

## 1. 当前交付范围

- Firebase 登录，FastAPI 验证身份，SQL 数据库记录订单、订阅、积分账本。
- Paddle.js 托管结账，后端创建交易，签名通知触发真实 API 核对与积分入账。
- 充值包：USD 4.99 / 200 永久积分。
- Creator Pro：USD 9.99 / 月 / 600 积分。
- Studio Matrix：USD 24.99 / 月 / 2,500 积分。
- 月积分于 Paddle 对应账期结束时到期，不滚存；永久积分不受取消月订阅影响。
- 首版统一 USD，税费在结账显示。后台打开币种转换不代表应用支持本地币种。
- 提供取消续订、更新付款方式、付款历史和收据；不提供应用内升级降级、优惠码或无限生成。
- 退款由商户/Paddle 处理；批准后同步撤回积分。退款待批准不提前撤回。
- 争议、退款撤销等超出自动策略的事件进入人工 review，不能在未核对情况下补发积分。

对齐和视频使用费仍取后端 ENV 定价。付款获得积分与生成任务消耗积分是两个独立流程；
浏览器返回成功页面不能加分，客户端显示价格也不能决定服务端扣费。

## 2. 需要经营者完成

1. 在 Paddle 正式账户完成身份、经营信息及收款资料验证。
2. 提交并确认 **mv.fovea.si 这个具体子域名**已批准；不要假定根域名批准自动覆盖。
3. 核对公开首页、定价、联系、条款、隐私与退款政策，以及真实经营者资料。
   支持邮箱为 nafeiya@gmail.com。法定经营者名称需本人提供，不能拿昵称代替。
4. 创建正式后端 API Key、正式客户端 Token 与正式通知签名 secret，安全放入后端 Secrets。
   不把服务端 API Key、签名 secret 或数据库连接串写进 Pages 变量、浏览器或 Git。
5. 若 Paddle 门户开放套餐变更，先在商户设置关闭；本应用只链接到取消与付款方式页面。
   不能把“应用没有升级按钮”当作已限制了第三方门户。

上述审核状态需要在真实商户账户确认，代码或沙盒测试不能证明审核通过。

## 3. 环境必须分开

| 项目 | 沙盒 | 正式 |
|---|---|---|
| PADDLE_ENVIRONMENT | sandbox | production |
| API 主机 | sandbox-api.paddle.com | api.paddle.com |
| PADDLE_API_KEY | pdl_sdbx_… | pdl_live_… |
| PADDLE_CLIENT_TOKEN | test_… | live_… |
| BILLING_ALLOW_TEST_TRANSACTIONS | true | false |
| PADDLE_LIVE_ENABLED | false | 仅验收后 true |
| 数据库与媒体 | 独立测试库/目录 | 持久 PostgreSQL + 正式对象存储 |
| 资源 ID 命名空间 | paddle:sandbox:… | paddle:production:… |

不要把沙盒测试数据库转成正式数据库：命名空间能隔离订单查询，不能自动抹除用户已经获得的测试积分。
正式预检会拒绝含测试购买记录的数据库。不要为通过检查手工删除付款记录或直接改余额；
应使用独立正式库，并通过明确的数据迁移计划保留真实项目与合法额度。

`PADDLE_SANDBOX_API_KEY` 仅供沙盒便捷使用；production 不会读取它。
环境拼写、密钥前缀、Token 前缀、回跳 HTTPS 或双开关不匹配时，付款接口返回配置错误。

## 4. 准备正式目录和配置

代码提供 `tools/paddle/setup-live.mjs`。不带 `--apply` 只读检查商品目录，不创建交易或扣款。
它复用匹配商品和价格；不会归档旧商品、改已有价格或复制沙盒 ID。
正式账户与沙盒的价格 ID 完全独立。

在本地被 Git 忽略的 `work/paddle-live-input.env` 中填写：

```dotenv
PADDLE_API_KEY=你的正式后端密钥
BILLING_SITE_URL=https://mv.fovea.si
PADDLE_WEBHOOK_URL=https://你的稳定后端域名/api/payments/webhook/paddle
```

回调地址是运行 FastAPI 的后端，不是仅托管静态页面的 Pages 前端。
若继续用 HF，可以使用实际 HF API 主机的 HTTPS 地址；不要使用已经停止的临时 tunnel。

从项目根目录执行：

```bash
node --env-file=work/paddle-live-input.env tools/paddle/setup-live.mjs
```

正式域名批准且确认目录后：

```bash
node --env-file=work/paddle-live-input.env tools/paddle/setup-live.mjs --apply
```

需要的权限包括商品/价格读写、客户端 Token 读写、通知设置读写、checkout settings 读写、
checkout domain 读取。后端运行还需交易、订阅、价格、调整记录读取、交易创建和客户门户 session 创建。
不同角色按需授予，不要把 API Key 暴露给最终用户。

工具会：

- 确认具体 checkout hostname 已批准。
- 创建或复用三款正式商品与价格（SaaS、税外价、数量只能为 1、无试用）。
- 创建或复用客户端 Token、回调目标和完整事件订阅。
- 仅在默认付款链接为空时设为 `https://mv.fovea.si/app`，与现有配置冲突则停止。
- 把配置写入被忽略的 `work/paddle-live.env`，文件权限 0600，不输出密钥。
- 保持 `BILLING_ENABLED=false`、`PADDLE_LIVE_ENABLED=false`，不会自动让网站收款。

遇到已有商品但价格不同，不要直接删除或修改正在使用的价格；先核对现有客户与商品关系。

## 5. 后端部署

1. 备份正式数据库，并确认可恢复；确认 R2 写入、下载鉴权及生命周期策略可用。
2. 部署本分支后端代码、前端静态文件与编译资源；前后端应在同一发布批次更新。
3. 将生成的正确环境配置放入后端 Secrets，保留独立正式 DATABASE_URL 和 R2 配置。
4. 启动会为 `billing_events` 增加可空的 `next_attempt_at`，不会清空原通知。
5. 确认外网能到达 POST `/api/payments/webhook/paddle`，代理/WAF 不应要求浏览器登录或修改原始请求体。
   无签名 POST 应被拒绝；签名合法的通知应先持久化再快速返回 200。
6. 独立 FastAPI 启动会运行通知恢复任务；Gradio/HF 挂载模式在首次支付接口请求时也会启动。
   服务休眠时恢复任务无法执行；付费上线应使用可持续服务的运行方式，并监测睡眠/重启。
7. 建议每五分钟安排 `python -m scripts.replay_billing_events`，作为恢复兜底。
   多进程通过事务/账本幂等防止重复发放；定时重放尊重自动重试时间。
8. 小流量开始，保持现有渲染并发限制，检查数据库、磁盘、对象存储与失败率。

前端只从已鉴权后端获得环境、public client token 和 transactionId，无需把 Paddle secret 放进 Pages。
付款邮件的 `_ptxn` 链接先登录，再由后端核对订单/订阅归属；不会仅凭 URL 给积分。

## 6. 正式配置预检

配置加载到当前进程后运行（此命令只读、不创建付款）：

```bash
python -m scripts.billing_preflight --config work/paddle-live.env --prepare
```

`--prepare` 只在这个只读检查进程中启用验证开关，不会改变已运行的网站服务。
脚本先读取指定配置，再读取数据库等后端配置，不需要用 shell 执行含 JSON 或密钥的 env 文件。
检查商品金额、月周期、税外价、数量限制、默认付款链接、域名批准、稳定通知地址、
事件订阅、签名 secret、正式数据库和待处理/review 事件。失败退出非零。

预检通过仍不证明商户验证通过，也不证明端到端付款链路正常。

## 7. 上线验收清单

自动化回归不用真实账号，也不渲染实际视频。真实沙盒验收仍要单独确认：

- [ ] 正式工作台登录后点击购买，结账金额、税费、是否续费清楚。
- [ ] 成功后返回工作台，通知核实后积分和订单更新。
- [ ] 积分包只入账一次，重复通知和重新进入付款链接不重复入账。
- [ ] 月订阅首付入账、账期到期、续费幂等与付款失败处理。
- [ ] 取消续订与更新付款方式链接正确，取消时间按门户显示生效。
- [ ] 部分退款、全部退款待批准/已批准，积分回收正确。
- [ ] 用户 B 无法访问用户 A 的订单、付款链接、门户或收据。
- [ ] 服务重启或通知处理失败后能恢复，长期失败/review 能被发现。
- [ ] Suno 导入→对齐→修改保存→两个视频导出→断网重试→My Exports 下载→积分核对。
- [ ] 上传失败时提示用户留在当前页；目前未上传视频仅在本页内存，刷新后不能恢复。

真实月度续费不必等待整月才开始验证：可用模拟场景和时钟回归覆盖状态机，
但要把“模拟验收”和“真实沙盒自动续费”分别记录，不宣称两者相同。

2026-10-24 已完成的真实沙盒证据：一次性 USD 4.99/200 积分、USD 9.99 月订阅首付/600 积分，
真实通知处理和已知交易重复通知不重复发放。首付在临时结账页进行，不能代替最新版正式工作台浏览器验收。

正式审核通过后，经营者自行完成一笔真实小额付款与必要退款，核对到账、账单和平台处理费；
在此之前不开启公开收费。真实卡、身份信息、条款确认和财务操作由本人完成。

## 8. 运营和回滚

日志关注 `Paddle fulfillment delayed`、`Paddle adjustment needs operator review` 和 `Paddle inbox scan failed`。
预检会输出最多 20 条待处理事件 ID、状态、重试次数和可排查原因，不输出付款内容或密钥。
需要日志平台告警/值守，不能只把错误写进无人查看的日志。

修复问题后重放一个通知：

```bash
python -m scripts.replay_billing_events --event-id 真实事件哈希
```

review 事件须先人工核对，必要时指定一个事件：

```bash
python -m scripts.replay_billing_events --event-id 真实事件哈希 --include-review
```

重放并不意味着自动支持撤销拒付；不支持的调整仍会回到 review。退款/争议处置要核对原付款和账本。

发现收费问题时先将 `BILLING_ENABLED=false` 停止新购买，保留数据库与账本。
停用期间 Paddle 通知会失败并重试；恢复后立即核对通知日志并重放。
不要删除已完成交易、直接重置余额或把正式 secret 换成沙盒 secret。

## 官方参考

- https://developer.paddle.com/build/go-live-checklist/
- https://developer.paddle.com/build/transactions/default-payment-link/
- https://developer.paddle.com/api-reference/customer-portals/create-customer-portal-session/
- https://developer.paddle.com/api-reference/transactions/get-transaction/
