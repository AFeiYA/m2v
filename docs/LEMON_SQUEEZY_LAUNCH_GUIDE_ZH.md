> Historical/provider-specific reference. Current commercial rules: [Billing policy](BILLING_POLICY.md). Current launch procedure: [Paddle go-live](PADDLE_GO_LIVE_ZH.md). Older prices and activation steps below are not current release instructions.

# Sonicflow Studio 开户、收款与订阅上线操作指南

核对日期：2026-10-22。适用项目：`mv.fovea.si`；支付平台：Lemon Squeezy。

这份文档面向运营者，按执行顺序说明从开户到正式收费的步骤。配置名称、接口和套餐取自当前代码；没有读取线上密钥，也没有验证你的商户账户、线上配置或实际收款状态。平台页面名称可能调整，以登录后的控制台为准。

## 1. 先确认你能开户并收到款

“用户付款成功”和“钱结算到你的账户”是两回事。最先确认商户身份和提现渠道，再花时间配置商品。

1. 打开 [Lemon Squeezy](https://www.lemonsqueezy.com/)，注册账户并验证邮箱。
2. 按真实情况填写经营者身份、所在地区和网站。不要借用他人身份或虚填国家。
3. 查看 [支持地区](https://docs.lemonsqueezy.com/help/getting-started/supported-countries)，确认你的银行或 PayPal 收款方式可用。
4. 在控制台的 Payout 设置中确认实际可选的结算渠道、币种和身份要求。
5. 若以中国大陆个人身份申请，先向平台客服说明身份所在地与拟使用的收款方式，确认是否接受该组合。

截至核对日，官方银行结算国家列表未列出中国大陆，但列有香港、澳门等地区。官方同时提供 PayPal 结算说明；这不等于所有中国大陆个人或任意 PayPal 账户都会获批。**不要把“身份证就能开户、当天上线、一定能提现到国内银行卡”当成承诺。** [地区依据](https://docs.lemonsqueezy.com/help/getting-started/supported-countries)

如果平台不接受你的真实身份或收款方式，应暂停接入并重新选择可支持的收款方案，而不是先收钱再解决提现。

## 2. 开店审核前准备什么

建议准备下列资料，具体提交项目由平台决定：

| 内容 | 你需要准备的材料 |
| --- | --- |
| 商户身份 | 真实姓名／主体名称、所在地、平台要求的身份证明 |
| 网站 | 可访问的 `https://mv.fovea.si`，以及产品介绍和价格说明 |
| 产品展示 | 导入歌曲 → 编辑歌词 → 调整样式 → 导出视频的录屏或截图 |
| 联系方式 | 能接收售后咨询的邮箱，公开在网站上；不要填写尚未创建的地址 |
| 交易规则 | 服务条款、隐私政策、退款规则和订阅取消方式 |
| 收款与税务资料 | 平台接受的银行／已验证 PayPal 信息，以及平台要求的税务资料 |

这些页面和联系方式应真实可用。本指南没有替你发布法律条款，也没有确认现有网站已补齐上述内容。

在控制台选择 **Activate your store**，填写业务问卷并完成身份验证。官方说明审核通常需要 2–3 个工作日，但可能要求补充材料或拒绝申请；注册成功不代表已获正式收款资格。 [开店审核](https://docs.lemonsqueezy.com/help/getting-started/activate-your-store)、[身份验证](https://docs.lemonsqueezy.com/help/getting-started/verify-your-identity)

可以参考以下英文产品描述，提交前确认与实际开放功能一致：

> Sonicflow Studio is a web-based lyric video creation tool. Users import music they own or are authorized to use, review and edit lyric timing, customize visual layouts, and export lyric videos. We sell prepaid usage credits and monthly credit subscriptions. We do not sell music rights or access to third-party paid content.

不要宣称与 Suno 官方合作，也不要把产品描述成破解下载限制或提供歌曲版权的服务。用户公开发布歌曲，并不自动证明其拥有所有相关权利。

## 3. 当前应该创建哪三个商品

下面是当前 `src/billing_config.py` 与 `.env.example` 的正式套餐；不是重新建议定价，也不会因为写本文而修改价格。

| 内部商品 ID | 建议展示名称 | 价格（USD，适用税费另计） | 获得积分 | 积分有效期 |
| --- | --- | --- | --- | --- |
| `topup_200` | Credit Top-Up | $4.99，单次付款 | 200 | 永久有效，不自动续费 |
| `pro_monthly` | Creator Pro | $9.99／月 | 每付费周期600 | 当前计费周期结束失效，不结转 |
| `studio_monthly` | Studio Matrix | $24.99／月 | 每付费周期2500 | 当前计费周期结束失效，不结转 |

代码还兼容早期的 `$5/月1000积分、$10/月2500积分、$5买500永久积分` 测试组合。首次上线建议使用上表，避免与当前示例配置和页面文案不一致。若你决定恢复早期价格，应统一修改平台商品、后端目录和网站说明后再上线，不能混用。

**当前代码并非允许任意调价。** 商品目录只接受正式组合或早期兼容组合；其他价格／积分组合会被拒绝。未来运营调价还需要修改目录校验，不能只在平台后台改数字。

### 在平台创建商品

先在 **Test mode** 操作，进入 Products，新建三个商品或三个明确对应的 variant：

1. Credit Top-Up：Single payment，USD 4.99。
2. Creator Pro：Subscription，USD 9.99，每1个月续费。
3. Studio Matrix：Subscription，USD 24.99，每1个月续费。
4. 使用标准固定价格；不要启用按量计费、阶梯价、安装费、年付或免费试用。
5. 暂不开放客户自助换套餐、调整数量或折扣入口。现有代码不提供完整的升级降级／补差价权益计算。
6. 记录每个商品的数字 **Variant ID**，以及数字 Store ID。Variant ID 不是商品名称、Product ID 或结算链接。

月付方式由平台负责续费扣款；每次付费发放多少应用积分由我们后端控制。平台不会自行理解“600积分”意味着什么。 [平台订阅说明](https://docs.lemonsqueezy.com/help/products/subscriptions)

建议商品说明明确写出：自动续费、取消方法、积分到期规则和适用税费。不承诺无限生成、额外存储或优先队列，当前订阅购买的是积分。

## 4. 用户购买与续费的实际流程

1. 用户从公开首页进入 `/app` 登录 Sonicflow，再进入 Quota & Credits，选择积分包或月订阅。
2. 后端创建与该登录账户绑定的结算单，跳转到 Lemon Squeezy 托管收银台。
3. 用户在平台付款；我们不收集银行卡号或CVV。
4. Lemon Squeezy 向后端发送付款通知（Webhook）。
5. 后端验证签名、金额、商品和归属，记录订单并发放积分。
6. 用户返回网站后查看到账状态。仅返回“成功页面”不能发放积分。
7. 月订阅后续由平台续费；成功付款的账单触发新周期积分发放。

不要把普通平台商品链接作为唯一购买入口发给用户。当前后端要求网站先创建带账户绑定信息的 checkout；直接在商店下单可能缺少归属信息，不能保证自动到账。推广链接应优先引导用户进入网站并登录购买。

### 月度积分到底何时清零

按**个人订阅计费周期**，不是所有人每月1日统一清零。例如10月22日订阅，每月按平台账单周期续费；该周期未用积分到期失效，新周期成功扣款后发放新积分。短月的日期以平台实际周期为准。

- 使用时优先消费即将到期的月度积分，再消费永久积分。
- 取消续费通常保留当前已付周期权益，到期后不再续费；永久积分不因取消被清空。
- 续费失败不能凭空发放新周期积分。
- 退款会撤回相应购买积分；已使用的退款积分可能形成负余额，不能承诺“退款后已用积分也保留”。

不要把“取消订阅”与“退款”当成同一个操作。

## 5. 在哪里配置密钥

支付配置放在**实际运行 Python API 的后端**。如果仍使用 Hugging Face，就在该 Space 的 Settings → Variables and secrets 配置；如果通过 CI 注入，以实际部署链路为准。

Cloudflare Pages 只负责前端，不应保存 Lemon Squeezy API Key 或 Webhook Secret。Firebase 负责登录，不保存收款密钥。GitHub Secrets 即使配置了，也必须有工作流显式传递才会到达后端。

| 配置名 | 填什么 | 建议保存方式 |
| --- | --- | --- |
| `BILLING_ENABLED` | 完成配置和验证后为 `true` | 后端变量 |
| `LEMONSQUEEZY_API_KEY` | 对应环境的商户API密钥 | 后端 Secret |
| `LEMONSQUEEZY_WEBHOOK_SECRET` | 创建Webhook时设置的签名密钥 | 后端 Secret |
| `LEMONSQUEEZY_STORE_ID` | 数字Store ID | 后端变量 |
| `LEMONSQUEEZY_TEST_MODE` | 测试 `true`，正式 `false` | 后端变量 |
| `BILLING_ALLOW_TEST_TRANSACTIONS` | 仅隔离测试部署设置 `true`，正式为 `false` | 后端变量 |
| `LEMONSQUEEZY_ALLOWED_HOSTS` | 实际收银台／门户／收据的准确域名，逗号分隔 | 后端变量 |
| `BILLING_SITE_URL` | 正式站点 `https://mv.fovea.si`；测试填测试站点 | 后端变量 |
| `BILLING_PRODUCTS_JSON` | 三个商品的后端映射，见下文 | 后端变量 |

域名白名单示例：`YOUR_STORE.lemonsqueezy.com,app.lemonsqueezy.com`。把 `YOUR_STORE` 换成真实商店子域名；若实际门户或自定义支付域名不同，核实后添加其准确主机名。不要带协议或路径，不支持通配符。

商品映射示例（这里只用虚构数字，不是可直接使用的真实ID）：

```json
[
  {"id":"topup_200","name":"Credit Top-Up (200 Credits)","variant_id":"101","kind":"topup","credits":200,"price_cents":499,"currency":"USD"},
  {"id":"pro_monthly","name":"Creator Pro (600 Credits/mo)","variant_id":"102","kind":"subscription","credits":600,"price_cents":999,"currency":"USD"},
  {"id":"studio_monthly","name":"Studio Matrix (2,500 Credits/mo)","variant_id":"103","kind":"subscription","credits":2500,"price_cents":2499,"currency":"USD"}
]
```

将101／102／103替换为对应环境实际Variant ID。环境变量输入框通常应粘贴压缩成单行的JSON，不要带Markdown代码围栏；修改后重启／重新部署后端。

购买积分的价格与“导出消耗多少积分”是两套配置。后者查看当前后端的 `LYRIC_EXPORT_CREDITS`、`MOTION_EXPORT_CREDITS`、`MOTION_WEBCODECS_CREDITS` 及前端报价结果，不要用旧文档默认值推断生产价格。当前账务尚不支持的 `DRAFT_EXPORT_CREDITS`、`CLIP_EXPORT_CREDITS`、`SEPARATION_CREDITS` 必须保持0，否则支付配置检查会拒绝开启。

## 6. 配置付款通知 Webhook

在 Lemon Squeezy 的 Webhooks 设置中新建通知：

```text
https://YOUR_BACKEND_HOST/api/payments/webhook/lemonsqueezy
```

若当前仍使用原HF后端，候选地址为：

```text
https://lucazhou-suno2mv-api.hf.space/api/payments/webhook/lemonsqueezy
```

先确认它就是当前实际部署的API。**不要填 Pages 静态站点地址，也不要填付款后返回页面。** 通知接口不能被Cloudflare交互验证或用户登录页面拦截；请求由后端签名校验，不需要浏览器登录。

设置足够随机且保密的 Signing secret，并将同一值写入后端 `LEMONSQUEEZY_WEBHOOK_SECRET`。订阅以下当前代码支持的事件：

```text
order_created
order_refunded
subscription_created
subscription_updated
subscription_cancelled
subscription_resumed
subscription_expired
subscription_paused
subscription_unpaused
subscription_payment_success
subscription_payment_failed
subscription_payment_recovered
subscription_payment_refunded
```

这里必须包含订单、续费、退款和订阅状态，不是只勾选付款成功。代码会根据原始请求体验证 `X-Signature`，再处理账务；重复通知不应重复发放。 [Webhook说明](https://docs.lemonsqueezy.com/help/webhooks)、[事件说明](https://docs.lemonsqueezy.com/help/webhooks/event-types)

## 7. 先在隔离测试环境验收

需要独立测试后端、独立数据库，最好同时隔离文件存储前缀。**不能在真实用户数据库中启用测试交易。** 代码中的环境标识不能替代部署隔离。

测试配置为：`LEMONSQUEEZY_TEST_MODE=true`，`BILLING_ALLOW_TEST_TRANSACTIONS=true`，并使用测试API Key、测试商品Variant ID和测试Webhook。配置完整后在测试环境开启 `BILLING_ENABLED=true`。

在相同后端环境运行只读预检：

```bash
python -m scripts.billing_preflight
```

它核对商品、价格、环境和待处理通知，不会创建checkout或扣款。通过仅代表配置匹配，不能代替以下验收。

| 验收项 | 必须观察到的结果 |
| --- | --- |
| 买200永久积分 | 支付确认后仅增加200，刷新不重复增加 |
| 买600月度积分 | 首次付费账单仅发放一次，显示正确到期时间 |
| 续费成功／失败 | 成功发新周期积分；失败不发积分 |
| 取消订阅 | 未来续费停止，永久积分保留，周期结束时间正确 |
| 退款／重复退款通知 | 对应积分只撤回一次，不影响无关购买 |
| 重复Webhook | 不重复发放积分 |
| 中断通知后重放 | 能恢复处理，且不会重复到账 |
| 用户A、用户B | 无法读取对方的订单、收据或管理门户 |
| 关闭付款页面／仅访问返回链接 | 不会凭空加积分 |
| 导出成功／失败 | 成功按展示价格结算；失败按账本规则释放预留 |

测试银行卡可使用官方Visa测试号 `4242 4242 4242 4242`，填写未来有效期与测试CVC；不要输入真实卡号，也不要用测试订单冒充营业收入。测试产品不会自动成为正式产品，正式模式还需重新配置ID、密钥和Webhook。 [测试模式](https://docs.lemonsqueezy.com/help/getting-started/test-mode)

## 8. 从测试切换到正式收费

按以下顺序执行，不是只关掉Test mode开关：

1. 商户审核通过，确认提现渠道可用，公开价格、条款、隐私和退款联系方式。
2. 备份正式数据库，并确认能够恢复。确保用户额度、订单和账本不在临时容器磁盘上。
3. 把三个测试商品复制到Live或创建正式商品，逐个核对价格、月周期和币种，记录新的正式Variant ID。
4. 创建Live API Key和Live Webhook，使用独立的正式Signing secret。
5. 在正式后端填Live配置：`LEMONSQUEEZY_TEST_MODE=false`、`BILLING_ALLOW_TEST_TRANSACTIONS=false`，并替换正式目录ID。
6. 初始保持 `BILLING_ENABLED=false`，部署后端使现有初始化逻辑建立账务表；不要手动删除原表。
7. 配齐后开启 `BILLING_ENABLED=true` 并重启，在正式后端运行 `python -m scripts.billing_preflight`。失败则关闭购买入口、检查配置，不能带病收款。
8. 发布匹配的前端，确认网站显示上表套餐、实际扣分和订阅规则。不要只检查代码仓库，要检查线上页面。
9. 从网站登录入口创建正式checkout，核对最终币种、商品和含税金额。真实付款由你或受邀测试者自行完成，并遵循平台的商户测试规则；不能把测试卡用于Live。
10. 完成一笔受控真实订单后，核对平台付款、Webhook、站内积分、订单收据；退款测试也要核对积分撤回。
11. 安排通知重试任务与告警，再小范围邀请用户付费。

官方明确要求上线时配置正式API Key和指向生产端点的Live Webhook。 [上线切换说明](https://docs.lemonsqueezy.com/guides/developer-guide/testing-going-live)

## 9. 提供订阅后，日常怎么管理

用户通过站内订阅管理入口打开平台Customer Portal，管理付款资料、取消或恢复续费。首版不开放自助套餐切换；如果平台设置无法限制换套餐，应先补齐后端权益规则，再开放该能力。

退款在商户控制台处理，之后核对Webhook与积分冲销。不要直接修改数据库余额“退款”，也不要删除账本。退款规则和适用消费者权利需要明确展示；不能简单写“数字产品一律不退”。

生产环境应每5分钟在可信后端调度一次：

```bash
python -m scripts.replay_billing_events
```

该命令会重试已收到但未处理完的通知，并执行到期积分清理。代码提供命令，**不代表线上已经配置了定时执行**。不要通过公开无鉴权HTTP接口触发，也不要把密钥写进仓库。

若原通知根本没到后端，数据库没有收件记录，需要从Lemon Squeezy控制台重新投递。用户的“检查近期付款”只能复核已知记录，无法自动发现完全漏收的首次购买。

每天检查：待处理通知、到账投诉、退款冲销、续费失败、异常负余额、后端可用性。定期验证数据库备份；初期不建议让收款回调后端随空闲休眠。

## 10. 费用与到账时间怎么理解

Lemon Squeezy处理其交易的销售税／VAT，不代表你的经营收入申报、个人或企业所得税义务自动消失。不要把MoR理解为“完全不用管税”。

官方基础收费口径为5%＋$0.50；订阅、国际交易、PayPal和结算方式可能另有费用。按基础费率粗算，$4.99单次订单约扣$0.75，尚未计额外费用、税务影响与算力成本，因此小额订单固定费用占比较高。最终以商户后台账单为准。 [费用说明](https://docs.lemonsqueezy.com/help/getting-started/fees)

官方提现说明包含$50最低结算门槛、销售款等待期及分批付款安排。因此首笔销售不会立刻到账银行卡；可提现金额与时间以控制台为准。 [收款结算说明](https://docs.lemonsqueezy.com/help/getting-started/getting-paid)

## 11. 出问题时先查什么

| 现象 | 优先检查 |
| --- | --- |
| 购买入口不可用／404 | `BILLING_ENABLED`、后端版本、前端API地址 |
| `Billing setup is incomplete` | API Key、签名密钥、数字Store ID、允许域名是否完整 |
| `Billing catalogue is invalid` | JSON格式、数字字符串Variant ID、三套餐价格／积分组合 |
| 商品环境／价格不匹配 | Test/Live混用、用错ID、平台价格与后端目录不一致 |
| 付款完成但没积分 | 平台订单是否已付、Webhook投递、后端pending事件；不要催用户重复付款 |
| 管理订阅跳转失败 | 实际门户域名是否在准确白名单、用户归属是否正确 |
| Webhook 401 | 签名密钥或环境不匹配；不要通过关闭验签解决 |
| 月积分没更新 | 续费账单是否支付成功、事件是否处理、新旧周期是否正确 |
| 平台有余额但不能提现 | 最低门槛、等待期、身份验证与提现渠道状态 |

不要把API Key、完整连接串、身份证件或带签名的门户链接粘贴到公开工单或Git。排错提供时间、错误摘要和脱敏订单标识即可。

## 12. 你现在的执行顺序

- [ ] 先确认真实身份和提现渠道能通过商户审核。
- [ ] 准备网站说明、价格、联系方式、条款、隐私和退款规则。
- [ ] 注册并申请激活商店；审核期间配置三个测试商品。
- [ ] 准备隔离测试部署，完成API Key、商品目录和Webhook配置。
- [ ] 跑预检及交易验收，尤其验证续费、取消、重复通知和退款。
- [ ] 获批后创建Live配置，备份数据库，部署并完成正式核对。
- [ ] 配置重放任务与告警，小范围开放真实付费。

## 代码与旧文档的对应关系

本指南依据：`src/billing_config.py`、`src/billing_provider.py`、`src/payments.py`、`src/billing_service.py`、`src/settings.py`、`.env.example`及账务运维脚本。

旧工程说明 [LEMON_SQUEEZY_BILLING.md](LEMON_SQUEEZY_BILLING.md) 保留实现细节，但其中“仍在支付分支”、早期商品配置和导出默认扣分描述存在历史信息。**实际开户执行以本文和当前代码为准，线上生效值另行核验。**
