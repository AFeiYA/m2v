# Motion Studio：保留 Gradio / ZeroGPU 云部署

继续使用 README 的 `sdk: gradio`、`app_file: app.py`。不切换 Docker，不改 ZeroGPU 人声分离入口。Vercel 提供浏览器页面，`/api/*` 继续代理到原 HF Space。

## 发布流程

1. GitHub 仓库 Actions Secrets 配置 `HF_TOKEN`（目标 `LucaZhou/suno2mv-api` 写权限）。
2. HF Space Settings Secrets 配置 `GEMINI_API_KEY`；Variables 可设置 `M2V_LLM_MODEL`、`M2V_LLM_FALLBACK_MODEL`。无需上传本地 `.env`。
3. 分支对 main 提 PR。CI 验证 Python、前端、实际短片渲染、Gradio 路由与运行依赖准备。
4. 合并 main 后，CI 下载测试阶段已构建的 `frontend/local/motion`、`frontend/local/remotion`，创建仅用于 HF 同步的资源提交，推送目标 Space。此提交不推回 GitHub。HF 侧单独提交的修改可能被同步覆盖。
5. HF 按 requirements.txt/packages.txt 安装依赖，运行 app.py。检测到 HF 的 SPACE_ID 时，启动准备器检查资源、Node >=22、Chromium、FFmpeg，并按锁文件安装 npm 生产依赖，然后继续原 Gradio 启动和 FastAPI 路由挂载。
6. Vercel 使用仓库根目录或 `frontend/local` 作为项目目录，分别使用对应的 vercel.json。两者均构建 Motion 资源，支持 `/motion_studio`、`/motion_lab`、`/motion/studio.js`；API 仍请求 HF。需在 Vercel 完成一次新部署。

Node 不可用/低于 22 时，启动准备器从 nodejs.org 下载固定 v22.23.3 Linux x64/arm64 包，校验官方 SHA256 后安装到用户缓存，无需 root。首次启动有依赖下载时间；网络、安装或资源缺失会明确失败，查看 HF 启动日志。npm 锁文件改变后重新安装。本地 app.py 启动不自动安装；可用 M2V_PREPARE_MOTION_RUNTIME=1 显式验证。Chromium 由 packages.txt 安装；CHROME_PATH 未设置时自动查找。

## 验收

- HF Space 构建成功且日志显示“Motion Studio 渲染环境就绪”。Actions 的同步成功只代表推送成功，不代表 HF 已启动。
- 打开 `/motion_studio` 与 `/motion_lab`，确认 JS 无 404/503。
- 导入短音频并对齐，调用 Gemini，确认草稿可验证并应用。
- 横竖屏分别导出 3–5 秒 MP4，确认音频、帧数、中文字幕及下载正常。
- 主模型仅 HTTP 429 时切换后备；503 不作为额度耗尽。

## 当前边界

- 本地歌曲、对齐文件和 `.env` 不会随代码部署。旧工程中的本地绝对音频路径需要迁移或重新导入。
- 默认 input/output 是临时磁盘，重启可能丢失；未接持久存储。
- 导演/导出任务状态在进程内存中，启动采用单进程；不支持重启续跑或多进程任务协调。
- Chromium/FFmpeg 导出使用 CPU，不使用 ZeroGPU。整曲性能需要在实际 Space 验证。
- 当前共享文件编辑器未实现多人项目隔离，适用于受限测试。
- 平台账号/硬件资格以 HF Settings 与官方政策为准。代码保留 Gradio 不代表自动获取 GPU 权限。
