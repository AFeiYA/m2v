# Firebase 登录配置

Firebase 仅负责登录，项目为 `dc-test-731fa`，Web App 为
`1:961193736563:web:7b77569a14b8b9b4322d06`。业务数据使用现有 SQL 数据库，
媒体使用 R2，不需要创建 Firestore 数据库。

## 邮箱和 Google 登录

- 邮箱注册、登录和密码重置直接使用 Firebase Web SDK，密码不经过 Python API。
- `firebase.json` 中的 `auth.providers.emailPassword` 可用
  `firebase deploy --only auth --project dc-test-731fa` 启用；Google 的现有配置保留。
- 注册时可填写显示名称。邮箱验证状态来自 Firebase ID Token 的
  `email_verified`，注册成功不等于邮箱已验证。
- 后端继续校验同一个项目签发的 ID Token，并按 Firebase UID 查找或创建 SQL 用户。
- 原有本地账号的密码不会自动迁入 Firebase；Google 用户的 UID 不因授权域名变化而改变。

## 自定义授权域名 auth.fovea.si

主站仍在 Cloudflare Pages，授权处理页面由 Firebase Hosting 提供。
这只改变授权域名，不修改 Firebase 项目、用户 UID、数据库或 R2 路径。

配置顺序：

1. 在 Firebase Hosting 的 `dc-test-731fa` 站点绑定 `auth.fovea.si`。
2. Cloudflare DNS 添加 `CNAME auth -> dc-test-731fa.web.app`，使用 **DNS only**，
   不开启代理。添加 Firebase 实际提供的 `_acme-challenge.auth` TXT 验证记录。
   验证值由 Firebase 提供，不能复制其他项目的值。
3. 在 Authentication 的 Authorized domains 中加入 `auth.fovea.si`，保留主站域名。
4. 在现有 Google OAuth Web Client 的已授权重定向 URI 中加入
   `https://auth.fovea.si/__/auth/handler`，保留原有回调。
5. 等 Firebase 域名、证书就绪，确认 HTTPS 下 `/__/auth/handler` 能打开。
   再将 `frontend/firebase-config.js` 的 `authDomain` 改为 `auth.fovea.si`，
   经 CI 部署到 Pages。

证书仍在验证时，应保留原 `dc-test-731fa.firebaseapp.com` 配置，避免登录中断。
不能通过关闭 TLS 校验来启用新域名。授权页面上的应用名称由 Google OAuth
品牌配置控制，与授权域名、用户自己填写的显示名称是三个不同设置。

## 验证

- `node --test frontend/tests/*.test.cjs` 检查登录会话、邮箱注册和密码重置行为。
- 后端 `tests/test_saas_isolation.py` 检查 Firebase UID 对应业务用户、初始额度仅发一次，
  并检查未验证邮箱不会被标为已验证。
- 可在 `demo-*` 项目的 Firebase Auth Emulator 中验证注册、登录与错误密码；
  不使用生产账号或真实密码运行 CI。
