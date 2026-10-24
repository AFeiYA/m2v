# Paddle 第 1～4 步：沙盒接入与测试

## 当前状态与范围

代码位于 `feat/paddle-sandbox-billing`。默认收费仍关闭；当前代码支持 sandbox 和 production，
本指南与隔离启动脚本只用于 sandbox。正式环境请看 [上线指南](PADDLE_GO_LIVE_ZH.md)。
这不是“切到正式账号”，不开始验证，不收真实款，不调整正式账户。

Paddle 官方插件已安装。实现沿用现有 FastAPI、Firebase 登录、SQL 数据库和积分账本，
没有为官方 Next.js 示例而替换项目框架。

| 后台步骤 | 实现与当前限制 |
|---|---|
| 01 Create your catalog | 官方 Node SDK 初始化工具已写好；没有凭据前不能确认账户内商品已经存在 |
| 02 Pricing page and checkout | 已有定价页；新接入 Paddle.js overlay，使用后端创建的 transactionId |
| 03 Fulfillment and provisioning | 原始请求体验签、持久化 inbox、后台积分发放、续费与退款处理、恢复重试 |
| 04 Test your integration | 有自动化模拟测试；真实 Paddle 测试卡付款与回调验收需凭据和可达的测试地址 |

旧套餐已有真实沙盒首付记录，见 [历史目录与测试证据](PADDLE_SANDBOX_CATALOG.md)。新三档尚未完成真实结账验收。自动化测试不能替代新目录的真实端到端测试。
初始化与运行工具均不输出密钥；不要把 `.env` 或 `work/paddle-sandbox.env` 发到聊天。

## 第一步：只需先准备沙盒 API key

进入 [Paddle sandbox](https://sandbox-vendors.paddle.com/settings/authentication)，
在 My account → Settings → Authentication → API keys 创建专门的测试 key。
它以 `pdl_sdbx_` 开头；client token 不是 API key，live key 不能替代它。

将 key 安全保存到项目本地 `.env`：

```dotenv
PADDLE_SANDBOX_API_KEY=在本地填写实际沙盒key
```

不要把示例占位字符串原样使用。`.env` 在 Git 忽略名单中。

初始化需要相应的读取权限以及 product.write、price.write、client_token.write、
notification_setting.write；读取和运行时另需 price.read、product.read、transaction.read / write、
subscription.read、adjustment.read、customer_portal_session.write。
自动配置缺失的默认支付链接需要 checkout_settings.read / write。
权限名称以当前 Dashboard 为准；没有权限时只补齐所需项，不创建一把无限权限正式 key。

## 第二步：测试地址与初始化

真实 Webhook 必须能从公网到达。可使用这个分支的独立 staging，或 HTTPS 隧道转发
到本地 8896。**不要把 sandbox 设置放到生产后端或生产数据库。**

在本地环境设 `PADDLE_SANDBOX_APP_URL` 为测试站点的 HTTPS origin，
例如自己的 staging 或本次测试的隧道地址。该站点必须运行本分支代码。
当前工具会在该地址的 `/api/payments/webhook/paddle` 接收通知。

安装工具依赖：

```bash
npm ci --prefix tools/paddle
```

先只读查看目录计划，再执行缺失项初始化：

```bash
node --env-file-if-exists=.env tools/paddle/setup-sandbox.mjs
node --env-file-if-exists=.env tools/paddle/setup-sandbox.mjs --apply
```

工具会：

1. 读取现有活动商品和价格，复用匹配项，遇到多重匹配停止。
2. 为缺失的套餐建立独立 Product 和 Price，不删除、归档或修改已有商品/价格。
3. 复用或创建名为 Sonicflow sandbox 的 client token。
4. 复用同一 URL 的通知目标，补齐必要事件，不重建或旋转 secret。
5. 将配置写到 Git 忽略的 `work/paddle-sandbox.env`，文件权限设为 0600。
6. 只在默认支付链接缺失时尝试配置；权限不足或已有值时提示检查后台，
   不覆盖已有正确设置。位置：Checkout → Checkout configuration。

生成的目录沿用公开套餐：

| 商品 | 金额 | 积分有效期 |
|---|---|---|
| Creator | USD 9.99，每月 | 300 积分，账期结束到期 |
| Pro | USD 19.99，每月 | 800 积分，账期结束到期 |
| Studio | USD 29.99，每月 | 1500 积分，账期结束到期 |

本版不启用试用、折扣、数量修改、套餐升级/降级或按比例补差；变更计费方案先单独设计。
商品税务分类默认 `saas`（本产品是在线软件服务），税务模式 `external`，
由 Paddle 计算适用税费。它不是销售现成歌曲版权或可提现储值。
请确认该软件服务分类与你的实际经营方式相符。

## 第三步：启动隔离工作台

```bash
.venv/bin/python -m scripts.run_paddle_sandbox --check
.venv/bin/python -m scripts.run_paddle_sandbox
```

浏览器访问 `http://localhost:8896/app`，或对应的 HTTPS 测试地址。
Paddle 默认支付链接指向测试站点 `/app`，需要在该站点登录后点击套餐打开 overlay。

启动器强制使用：

- 独立 SQLite：`work/paddle-sandbox/sandbox.db`。
- 独立本地媒体目录：`work/paddle-sandbox/uploads` 与 `output`。
- 本地存储，清除进程中的 R2/S3 配置，不访问生产媒体桶。
- 独立临时 JWT secret，监听本机 127.0.0.1:8896。
- Paddle sandbox；如果配置中有正式凭据则拒绝。

保留真实登录验证，没有加入匿名加积分或绕过身份验证的测试接口。
登录后进入 Quota & Credits，即可购买积分包或订阅。
如果浏览器以前手动选择过其他 API 后端，请确认当前连接的是隔离测试后端。

Webhook 会在事件持久化后立即确认接收，外部 API 请求放在响应之后。
只有 `transaction.completed` 且当前 API 交易状态为 completed 才发积分。
`transaction.paid`、订阅创建、浏览器成功事件及返回 URL 都不直接加积分。
再次读取 Paddle 当前状态后，在账本事务中按交易 ID 防重；不用客户 metadata 自行认领付款。

本地 API 服务启动后，每 10 秒扫描 pending inbox，恢复中断或暂时失败的事件。
失败状态和重试次数持久化；也可在同一隔离配置下运行
`python -m scripts.replay_billing_events`。
Gradio/HF 的挂载方式若未启用 API lifespan，需要额外配置这个定时重放脚本。

## 第四步：实际验收

只使用官方 sandbox 测试卡，不输入真实卡。

| 场景 | 预期 |
|---|---|
| 首次购买积分包 | 结账显示 USD 4.99 与税费；回调处理后仅增加 200 积分 |
| 订阅 Creator / Pro / Studio | 首笔 completed 交易分别加 300 / 800 / 1500；subscription.created 不额外再加 |
| 重发通知 | 相同事件或不同事件指向同一交易，不重复加积分 |
| 支付失败 | 不增加积分；页面有可重试提示 |
| Webhook 暂时中断 | 恢复后 pending 可重试，到账后余额只变化一次 |
| 月订阅续费 | 每个真实续费交易只加当期积分，上一账期到期，不累计旧月额度 |
| 取消订阅 | 以门户显示的生效时间为准，不把“取消”当作现金退款 |
| 退款 pending_approval | 不提前撤回积分；Paddle 批准后按对应金额撤回 |
| 部分与全部退款 | 按累计金额撤回；重复回调不重复扣，已过期月积分不二次扣 |
| 另一账户访问订单/门户 | 返回 404，不显示或访问他人的付款信息 |
| 发票/收据 | View receipt 打开当前用户的 Paddle 客户门户，在门户下载对应发票 |

测试卡参考官方文档：标准成功卡 `4242 4242 4242 4242`；有效的未来到期日期与三位 CVC。
拒绝场景卡 `4000 0000 0000 0002`。实际支持场景以官方 sandbox 文档为准。

Paddle 沙盒退款可能处于待批准状态，官方说明会周期性自动批准，不能要求点击退款后立即扣分。

通知模拟器可验证签名与接收，但它不创建真实 API 资源。
本实现会重新读取交易以确认归属，因此“虚构交易模拟通知已返回 200”不等于积分到账验收。
先用实际沙盒 Checkout，再重放该真实沙盒资源的通知验证账本。

遇到 chargeback、退款撤销等超出首版自动撤回策略的调整，事件进入 review，
由运营核对；本版不因此承诺正式生产的争议自动处理。

## 自动化测试（不需要账号和真实视频）

```bash
.venv/bin/pytest tests/test_paddle_billing.py tests/test_stripe_billing.py tests/test_lemon_billing.py tests/test_credits.py tests/test_credit_expiry.py
node --test frontend/tests/billing.test.cjs tools/paddle/setup-sandbox.test.mjs
```

模拟测试覆盖接口、签名、账本、事件恢复、退款与账户隔离，不运行音频分离、对齐或视频渲染。
只有完成上面的真实沙盒测试，才可以在清单里把第 4 步标为完成。
现阶段还未开始账号验证、正式商品迁移、真实收款或正式域名审批。

官方资料：
[沙盒与测试卡](https://developer.paddle.com/sdks/sandbox)、
[Paddle.js Checkout](https://developer.paddle.com/build/checkout/build-overlay-checkout)、
[Webhook 签名](https://developer.paddle.com/webhooks/about/signature-verification)、
[Webhook 响应约定](https://developer.paddle.com/webhooks/about/respond-to-webhooks)。
