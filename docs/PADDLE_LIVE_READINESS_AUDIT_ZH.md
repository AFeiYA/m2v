# Paddle 正式环境迁移前检查

检查日期：2026-10-23。检查仓库：`/Users/luca/suno2MV`。
检查时分支：`feat/stripe-sandbox-billing`，提交 `41c4538`。

## 结论

**目前不能宣布 Paddle live 已准备完成，也不应切换生产支付。**
用户要求的前提是 Paddle 沙盒接入通过测试。当前找到的是 Stripe 沙盒代码和
对应的模拟测试；仓库内没有发现 Paddle Checkout、回调、商品映射或沙盒测试。
Stripe 的测试通过不能代替 Paddle 的测试。

没有开始账号验证，没有提交域名，没有创建正式交易，没有更改任何 live 商品、
价格、订阅、客户、通知目标或 secret，也没有修改生产配置。

## 可确认的状态

| 项目 | 结果 |
|---|---|
| 原始 MCP 配置 | 本机原先没有 paddle-sandbox / paddle-live |
| paddle-sandbox 配置 | 已添加官方地址，使用 PADDLE_SANDBOX_API_KEY 环境变量 |
| 沙盒身份验证 | 尚未确认；当前环境中没有该变量 |
| paddle-live 配置 | 已添加官方地址，OAuth 返回 Successfully logged in |
| 当前会话工具 | 尚未加载 Paddle 工具，不能据此读取账户内容 |
| 本地 Paddle 配置变量 | 环境及项目 .env 中没有发现 PADDLE_ / VITE_PADDLE_ / NEXT_PUBLIC_PADDLE_ 变量；未输出任何值 |
| Paddle 接入代码 | 当前分支未找到 |
| 沙盒商品、价格、折扣 | 尚未读取，不能判断为空或不存在 |
| 正式商品、价格、折扣 | 尚未读取，不能判断为空或不存在 |
| 正式通知目标、secret | 尚未读取，禁止重建或轮换现有目标 |
| 支付方式、税务模式、结算币种 | 尚未读取，不能自动镜像 |
| 正式域名批准、默认支付链接 | 尚未读取，不能自动覆盖 |

正式账户登录成功只表示完成 OAuth，不表示账户已审核或已可正式收款。

## 公开网站检查

通过公开 HTTPS 请求实际读取页面，以下均为 HTTP 200，最终地址保持原路径，
不是重定向到通用首页。此检查不是浏览器交互或 Paddle 审核通过证明。

| 页面 | 地址 | 内容检查 |
|---|---|---|
| 首页 | https://mv.fovea.si/ | 清楚说明自动歌词对齐、可编辑、歌词动画及 MP4 导出 |
| 定价 | https://mv.fovea.si/pricing | 4.99 USD / 200 永久积分；9.99 USD / 月 / 600 积分；24.99 USD / 月 / 2500 积分 |
| 联系 | https://mv.fovea.si/contact | 有邮件支持、账单支持说明和技术问题入口 |
| 条款 | https://mv.fovea.si/terms | 有账号、版权、积分、续费、可用性说明 |
| 隐私 | https://mv.fovea.si/privacy | 有登录、素材、存储、付款记录及浏览器缓存说明 |
| 退款与取消 | https://mv.fovea.si/refunds | 区分取消续费、失败返还积分、现金退款及退款后的积分撤回 |

首页页脚直接链接定价、联系、三份政策页；就导航结构而言，联系入口在一次点击内。
邮件在公开 HTML 中被 Cloudflare 混淆保护；源码配置为 nafeiya@gmail.com，
本次未进行浏览器端邮件点击验收。

### 发现的问题及具体修复方向

1. 定价、联系、条款、隐私页面仍声明 Lemon Squeezy。
   在确认采用 Paddle 并完成接入后，同步修改这些页面及生成来源
   `scripts/build_marketing.py`，避免后续构建又恢复旧内容。
   在 Paddle 尚未接通时，不应写成已经由 Paddle 正式收款。
2. 条款中使用 Sonicflow Studio 品牌，但个人经营者与品牌的对应关系尚未核实。
   由经营者提供允许公开的真实身份说明后，增加明确的运营者声明；不能猜测或
   使用登录显示名替代法定身份。Paddle 指引允许个人经营者品牌，优先法律名称。
3. 公布价格和 Paddle live 目录是否一致尚未知；读取 live 后逐个核对金额、币种、
   税务模式、月周期及积分，不得把网站价格当作已存在的 Paddle 商品。
4. 退款政策已公开，但尚未与 Paddle 的适用购买条款和退款处理方式核对；
   接通后应补充其付款支持入口并核对条款，而不是承诺所有退款都自动获批。
5. Checkout 实际域名尚未确定，无法完成“所有 Checkout 域名”检查。
   若使用 mv.fovea.si 发起 Checkout，应单独提交这个子域名，不能假设
   fovea.si 根域名批准后自动包含所有子域名。

官方域名审核指引要求产品描述、价格、交付内容、可导航的三份政策、经营者名称
或个人品牌，以及在线 HTTPS 网站。本次只能报告可见状态，不能保证批准。

## Webhook IP 检查

已成功读取官方 `https://api.paddle.com/ips`，响应为 200，存在 `data.ipv4_cidrs`。
没有把当前地址列表硬编码进项目，也没有修改服务器防火墙。

在实施 IP allowlist 前，需要确认实际回调服务与代理链（例如 Cloudflare、HF），
由可信边缘识别连接来源；不能把请求可自行伪造的 X-Forwarded-For 当作白名单依据。
动态更新策略、缓存失效和可信代理配置必须与实际部署匹配。
无论是否使用 IP allowlist，仍须校验原始请求体的 Paddle-Signature。
当前没有 Paddle handler，不能把 Stripe 的签名协议或 secret 直接拿来替换。

## 下一步及所需输入

1. 确认 Paddle 沙盒代码是否位于别的分支、项目或客户端；提供位置即可，不要发密钥。
2. 将 sandbox API key 安全设置为 Codex 可读取的 PADDLE_SANDBOX_API_KEY。
   沙盒 MCP 不支持 OAuth；不要把该 key 写入 Git 或聊天。
3. 重新加载 Codex 的工具连接，确认两个 Paddle MCP 的 search / execute 工具可用。
4. 只读比较两边目录和设置，记录已经存在的项目及 source → destination ID 映射。
5. 完成 Paddle 自身的回调、充值、订阅、退款、重复通知及账户隔离验收。
6. 前提满足后，再按用户授权执行缺失的增量迁移。
   live 价格若有错误，先列出建议并请用户确认；不删除、归档或重建。
7. 展示支付方式、税务模式、结算币种差异，由用户选择后才写入。
8. 用户自行提交域名、完成正式 API key 和收款银行资料；不开始账号验证，
   不发起正式付款，不开放给真实客户。

## 官方依据

- [Paddle MCP：两种环境和认证方式](https://developer.paddle.com/sdks/ai/paddle-mcp/)
- [域名审核要求](https://www.paddle.com/help/start/account-verification/what-is-domain-verification)
- [账号验证流程](https://www.paddle.com/help/start/account-verification/what-is-account-verification)
- [当前 Webhook IP 源](https://api.paddle.com/ips)
