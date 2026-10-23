# Stripe 沙盒接入与验收

## 当前状态

为 fovea.si 的歌词对齐与视频创作接入 Payments、Billing、Invoicing，预留 Tax 开关。
独立分支 `feat/stripe-sandbox-billing`；默认仍使用原有 Lemon Squeezy，不改线上配置。

Stripe 插件已安装，MCP OAuth 已授权沙盒，但当前会话没有加载
`stripe_implementation_planner`。因此按用户指定的备用流程，从
`https://docs.stripe.com` 安装了官方技能。以下是依据官方文档整理的方案，
**不是规划工具的执行结果**。新技能在后续会话可用。

本次只允许 sandbox：生产模式、正式密钥、正式回调均被拒绝。
自动化测试使用临时数据库和模拟 Stripe 响应，尚未执行真实沙盒 Checkout。
沙盒授权不等于商户审核通过，也不等于后端已经有可调用 API 的凭据。

## 接入方案

- 保持现有 `/api/payments` 前端契约，由 `BILLING_PROVIDER` 选择实现。
- 积分包：Stripe 托管 Checkout，`mode=payment`，付款成功后生成发票。
- 月订阅：Checkout `mode=subscription`，Stripe Billing 负责续费与催收，
  Customer Portal 负责更新支付方式、查看账单及到期取消。
- 商品、价格及积分数只读服务端配置，不接受浏览器提交的价格、额度和跳转地址。
- 收款回调先用原始请求体验签，再保存不含卡信息的资源 ID 到持久化 inbox。
  读取 Stripe 当前状态后，在数据库锁和同一事务内更新积分。
- 使用已绑定的 Checkout Session ID，经 Stripe Subscription / Invoice / PaymentIntent
  关系确认归属，不用客户端 metadata 认领付款。
- 积分包以 Session ID 去重；订阅以已支付 Invoice ID 去重。
  订阅创建和 Checkout 完成不另外送月积分；首月不会发两次。
- 月积分按发票行的实际账期到期，不是日历月月底；永久包不清零。
  每次消费继续使用现有冻结、结算、返还及先用临期积分的机制。
- 退款按已退款金额累计撤回对应积分，重复通知不重复扣除，已过期积分不二次扣。
- 争议及欺诈警告落为 `review` 事件，供运营在 Workbench 审核，不自动提交争议证据。
- 版本固定：Stripe Python SDK `16.x`、API / webhook `2026-09-30.endive`。

## 你需要准备什么

### 1. 独立测试后端与数据库

使用独立测试部署、独立数据库、测试用户。不要把
`BILLING_ALLOW_TEST_TRANSACTIONS=true` 设置到真实收费的生产部署。
模拟支付会改变该部署的用户积分，因此不能和生产共用数据库。

本次未读取或改变你现有 `.env`、线上数据库或 HF Secrets。

### 2. 沙盒凭据

在已授权的 Stripe sandbox 中创建后端专用 restricted key，优先 `rk_test_`。
配置最小权限：读取 Account、Products、Prices、Checkout Sessions / line items、
Subscriptions、Invoices、Invoice Payments、PaymentIntents、Charges、Disputes、
Radar Early Fraud Warnings、Billing Portal configurations；允许创建 Checkout
和 Billing Portal Sessions。实际权限名称以 Dashboard 为准，遇到 403 仅补充缺失权限。
Tax 读权限仅在启用 Tax 时需要。本应用不创建退款或修改订阅。

把凭据放进测试后端 Secrets 的 `STRIPE_API_KEY`；不要贴进聊天或提交 Git。
OAuth 授权是给开发工具的，应用后端不会自动继承其访问权。

### 3. 三个独立 Product 和对应 Price

沿用目前公开套餐，不在这次改动中调价：

| 套餐 | USD | 积分 | Stripe Price 类型 |
|---|---:|---:|---|
| Credit Top-Up | 4.99 | 200，永久 | one-time |
| Creator Pro | 9.99 / 月 | 600 / 账期 | recurring，每月一次 |
| Studio Matrix | 24.99 / 月 | 2500 / 账期 | recurring，每月一次 |

每个套餐使用独立 Product。暂不启用试用、优惠券、按量计费、数量修改、
年付、套餐切换或按比例补差。现有应用积分账本继续负责应用内部用量，
首版不额外引入用量计费平台。

获取三个 `price_…` ID 后，更新测试部署 `BILLING_PRODUCTS_JSON` 中的
`variant_id`（保留该字段名是为了兼容原有商品接口）。

```json
[
  {"id":"topup_200","name":"Credit Top-Up (200 Credits)","variant_id":"price_REPLACEpack","kind":"topup","credits":200,"price_cents":499,"currency":"USD"},
  {"id":"pro_monthly","name":"Creator Pro (600 Credits/mo)","variant_id":"price_REPLACEpro","kind":"subscription","credits":600,"price_cents":999,"currency":"USD"},
  {"id":"studio_monthly","name":"Studio Matrix (2,500 Credits/mo)","variant_id":"price_REPLACEstudio","kind":"subscription","credits":2500,"price_cents":2499,"currency":"USD"}
]
```

占位 ID 不可直接用于请求。实际发起 Checkout 前会读取账户与三个 Price，
检查环境、金额、币种、计费周期及独立 Product。

### 4. 配置客户门户

创建沙盒 Customer Portal configuration，开启账单历史、支付方式管理和取消订阅。
取消方式必须为账期结束时取消；关闭 subscription update / 套餐切换。
保存 `bpc_…` 到 `STRIPE_PORTAL_CONFIGURATION_ID`。

### 5. 回调

在 Workbench 为独立测试后端配置：

```text
https://你的测试后端/api/payments/webhook/stripe
```

设置 snapshot webhook API version 为 `2026-09-30.endive`，只订阅以下事件：

```text
checkout.session.completed
checkout.session.async_payment_succeeded
checkout.session.async_payment_failed
checkout.session.expired
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
customer.subscription.paused
customer.subscription.resumed
invoice.paid
invoice.payment_failed
invoice.finalization_failed
charge.refunded
charge.dispute.created
radar.early_fraud_warning.created
```

将该 endpoint 的 signing secret 放入 `STRIPE_WEBHOOK_SECRET`（`whsec_…`）。
它与 API key 不同；CLI 转发用的 signing secret 也不等于线上 endpoint 的 secret。

### 6. 其余测试配置

```dotenv
BILLING_ENABLED=true
BILLING_PROVIDER=stripe
BILLING_ALLOW_TEST_TRANSACTIONS=true
STRIPE_TEST_MODE=true
STRIPE_ACCOUNT_ID=acct_REPLACE
STRIPE_AUTOMATIC_TAX=false
BILLING_SITE_URL=https://你的测试前端域名
```

`STRIPE_API_KEY`、`STRIPE_WEBHOOK_SECRET`、`STRIPE_PORTAL_CONFIGURATION_ID` 和
`BILLING_PRODUCTS_JSON` 按上面配置，不在前端公开。

后端仍需配置自己的数据库与登录验证；沙盒账本与生产账本必须隔离。
这份分支不自动部署，也不启用线上收费。

## Tax 单独验收

暂时保持关闭：当前尚未确认税务登记或商品税码。
开启前先读取该 sandbox 的 Tax Settings，不覆盖已有地址或税码；
由商户确认业务适用税码、Price tax behavior 及需要征收的司法辖区。
在沙盒模拟对应登记，正式登记另行确认，不能从沙盒推断正式义务。

设置 `STRIPE_AUTOMATIC_TAX=true` 时，预检要求 Tax Settings active、至少一个
active registration、每个 Product 有 tax code、Price 明确 inclusive/exclusive。
这只是配置预检，不能证明所有客户地区都正确计税。还需用目标地区测试地址进行
Tax Calculation / Checkout，核对 `taxability_reason`，不能只看金额非零。

Stripe Tax 不等于 Lemon Squeezy 的 MoR 服务；商户主体、适用税务登记、申报及
正式收款资格仍要分别确认。不要为了让结果有税而随意更换商品税码。

## 验证顺序

1. 自动化契约测试（无真实账户、无网络）：
   `pytest tests/test_stripe_billing.py tests/test_lemon_billing.py tests/test_credit_expiry.py tests/test_credits.py`。
2. 仅在上述测试部署执行 `python -m scripts.billing_preflight`，读取账户、Price 和
   可选 Tax 配置；不创建付款。不要在聊天中粘贴输出中的账户凭据。
3. 用测试用户购买积分包，确认支付前不入账、回调后正确入账、返回页面仅显示状态。
4. 在 Workbench 重发相同事件及相关事件，确认只加一次积分。
5. 购买月订阅，用 Stripe Test Clock（如适用）或等待测试账期推进验证续费，
   检查老积分到期、新积分发放；用失败支付方式检查不发积分。
6. 在门户取消，确认当期积分保留且不再续费；切换套餐不可用。
7. 在 Stripe 测试后台执行部分退款、全部退款，验证账本、发票与余额。
8. 使用第二个登录账户，验证无法查询第一个人的 Checkout、发票或门户。
9. 暂停后端后重发回调，恢复后运行 `python -m scripts.replay_billing_events`，
   确认 pending 可恢复；测试部署按五分钟配置运行该脚本。
10. 模拟争议/欺诈通知，确认 inbox 标记为 review，并能在 Workbench 人工处理。

真实沙盒端到端验收必须在配置完成后执行；模拟测试通过不能写成“支付已上线”。
不涉及音频重新分离、对齐或真实视频渲染。

## 仍不属于正式上线完成项

- 商户激活、经营地区与收款账户审核。
- live key / live webhook / live Product，以及独立的生产数据库配置。
- 最小真实付款、续费、退款及财务核对验收。
- 全面 Tax 注册、目标司法辖区实测及申报安排。
- 争议审核告警与值守、凭据轮换、数据库恢复演练。
- 公开页目前仍说明 Lemon Squeezy；正式切换前应同步支付与隐私披露，
  不能在沙盒开发阶段声称 Stripe 正式收款已可用。
- 已有 Lemon 订阅不能通过改一个环境变量自动迁移；真实存在旧订阅时需
  单独制定并行路由与迁移计划，不能关闭其必要回调。

官方资料：
[Checkout](https://docs.stripe.com/payments/checkout)、
[Subscriptions webhooks](https://docs.stripe.com/billing/subscriptions/webhooks)、
[Customer Portal](https://docs.stripe.com/customer-management)、
[Stripe Tax](https://docs.stripe.com/tax/set-up)、
[沙盒](https://docs.stripe.com/sandboxes)、
[密钥管理](https://docs.stripe.com/keys-best-practices)。
