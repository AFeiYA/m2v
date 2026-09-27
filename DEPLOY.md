# 🚀 Suno2MV 云端极速部署指南 (0 元成本架构)

本项目采用 **Vercel (前端 CDN) + Hugging Face Spaces (后端容器)** 分离架构，实现永久 0 元服务器费用部署。

---

## 架构拓扑
```
用户浏览器 ➔ https://mv.fovea.si (Vercel)
               ├── 静态资源与页面 (HTML / CSS / JS) 由 Vercel 免费 CDN 全球加速
               └── /api/* 请求通过 vercel.json 自动反向代理到 ➔ https://<你的Space名>.hf.space (Hugging Face)
```

---

## 第一部分：部署后端 (Hugging Face Spaces)

Hugging Face Spaces 免费提供 **2 vCPU + 16GB 内存 + 50GB 磁盘** 的 Python/Gradio 算力环境（100% 永久免费，无需绑定信用卡）。

### 步骤：
1. 打开 [Hugging Face Spaces](https://huggingface.co/spaces)，点击 **Create new Space**；
2. 填写 Space 信息：
   - **Space name**: 例如 `suno2mv-api` (或任意名称)
   - **License**: MIT
   - **Select the Space SDK**: 选择 **Gradio**
   - **Choose a Gradio template**: 选择 **Blank**
   - **Space hardware**: 选择 **Free (2 vCPU · 16GB · CPU basic)**
   - **Visibility**: Public (或 Private 均可)
3. 点击底部 **Create Space** 按钮；
4. 将当前 `deploy/cloud` 分支的代码推送到 Hugging Face：
   ```bash
   # 添加 Hugging Face 为远程仓库 (HF 页面会提供你的具体 git 链接)
   git remote add hf https://huggingface.co/spaces/<你的HF用户名>/<你的Space名>

   # 推送当前分支到 HF 的 main 分支
   git push hf deploy/cloud:main -f
   ```
5. Hugging Face 会自动读取 `Dockerfile` 开始构建，约 2~3 分钟构建完成后，状态变为 **Running**；
6. 复制 Space 的公网直链地址（通常形如 `https://<你的HF用户名>-<你的Space名>.hf.space`）。

---

## 第二部分：部署前端 (Vercel) 并绑定域名

### 步骤：
1. 打开 `vercel.json`，将 `YOUR_BACKEND_APP.hf.space` 替换为你刚刚获取的真实 Hugging Face 域名：
   ```json
   {
     "version": 2,
     "rewrites": [
       {
         "source": "/api/:match*",
         "destination": "https://<你的HF用户名>-<你的Space名>.hf.space/api/:match*"
       },
       ...
     ]
   }
   ```
   提交并推送到 GitHub 的 `deploy/cloud` 分支。

2. 登录 [Vercel](https://vercel.com/)，点击 **Add New Project**，绑定同一个 GitHub 仓库；
3. 选择构建分支为：**`deploy/cloud`**；
4. Framework Preset 选择 **Other**，Root Directory 保持根目录 `./`；
5. 点击 **Deploy**，几秒钟内完成部署！

### 绑定自定义子域名 (如 mv.fovea.si)：
1. 在 Vercel 项目控制台，进入 **Settings** ➔ **Domains**；
2. 输入 `mv.fovea.si`，点击 **Add**；
3. 按照提示在你的 DNS 托管商（如 Cloudflare / 阿里云 / 腾讯云）添加一条 `CNAME` 解析记录：
   - **主机记录 / 名称**: `mv`
   - **记录类型**: `CNAME`
   - **记录值**: `cname.vercel-dns.com`
4. 等待 1~2 分钟 DNS 生效，Vercel 会自动签发免费 HTTPS 证书。

---

## 验证上线
打开浏览器访问：`https://mv.fovea.si`
- 界面即刻秒开；
- 粘贴任意公开的 Suno 歌曲链接（例如 `https://suno.com/s/3pkzqXgDSlZq9xcm`）；
- 点击【⚡ 导入对齐】，即可全自动完成歌词抓取、高清音频分离与词级卡拉OK对齐！
