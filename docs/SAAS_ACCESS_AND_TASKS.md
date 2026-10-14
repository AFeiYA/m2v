# SaaS 接口隔离与任务失败处理

## 本地编辑器与云端任务接口

`python -m src.local_editor` 默认绑定 `127.0.0.1`，保留本地目录编辑流程。

Gradio/Hugging Face 入口挂载路由时启用 SaaS 模式。原 `/api/files`、
`/api/alignment`、`/api/asset_file`、`/api/suno/import` 等按服务器目录操作的接口
返回 403，包括携带登录令牌的请求。这些接口没有工程归属信息，不能作为共享服务入口。
本地插件或旧页面若连接云端，需要迁移到下面的用户任务接口；添加令牌本身不足以开启旧接口。

云端使用 `/api/upload`、`/api/tasks/from-suno` 创建任务，通过 `/api/tasks`
和 `/api/editor` 查询、下载、编辑自己的产物。读取他人任务返回 404。

## 调度、扣费、退款

创建任务与原子扣减额度先在同一事务提交，然后才能发送 Celery 任务或启动本机线程。
未安装 Celery 或发送队列失败时，线程调用同一个无绑定参数的处理函数。

处理失败、线程启动失败统一执行 `fail_task_and_refund`：在同一事务将未完成任务
转为 failed，并退还其 `cost_credits`。重复失败回调和已完成任务不会再次退款。
后台线程使用独立连接，避免在多个事件循环之间共享数据库连接池。

Gradio 启动建表与 ASGI 请求也可能使用不同事件循环，因此公共数据库引擎使用
`NullPool`，每个会话关闭时释放连接，不复用启动循环中的 asyncpg 连接。

线程兜底不提供持久队列保证：服务进程被终止后，正在执行的线程不会继续运行。

## 令牌

下载使用共享的 access-token 验证和任务归属检查，不接受 refresh token。
仪表板下载请求通过公共 API 请求封装刷新过期令牌，并且不将令牌写入下载 URL。
Google 登录清除旧本地 refresh token；Google 会话刷新失败时不会切换到本地账号。

## 云端双轨编辑器

云端编辑器按 `task_id` 调用 `/api/editor`；本地目录接口继续隔离。
歌曲列表返回真实的 `has_vocals` / `has_instrumental`，缺失分离音轨返回 404，
前端只显示标注为原曲的单轨，不用原曲冒充人声和伴奏。
编辑器在 401 时刷新同一账号的令牌，音轨与短视频使用认证请求获取 Blob，
不将长效登录令牌写入播放和下载链接。

- `POST /api/editor/tasks/{task_id}/lyric-video`：按比例、主题与裁剪区间导出。
- `POST /api/editor/tasks/{task_id}/analyze`：单独分析原曲，无需重新对齐。
- `GET /api/editor/jobs/{job_id}`：查询当前用户的后台操作。
- `GET /api/editor/jobs/{job_id}/video`：检查用户与原任务归属后下载成片。

导出前保存未提交的歌词修改，保存失败则不启动渲染。分析完成后重新读取已保存歌词，
仅合并音频特征，避免覆盖分析期间的编辑。后台操作限制每个服务事件循环同时执行两项。
操作状态通过 TaskStore 保留七天；重启后未完成操作标记 interrupted，用户可重新提交。
这些操作使用进程内后台执行，并非可在重启后继续执行的持久队列。

## 数据库密码中的特殊字符

实际密码可以包含 `@`。在连接 URL 中其密码部分应表示为 `%40`。
Settings 支持 PostgreSQL 连接串规范化，已转义的 `%40` 不会再次编码成 `%2540`。
不要将真实连接串或密码放到文档、测试或 Git 仓库中。


### Suno 重复导入与歌词版本

`POST /api/tasks/from-suno` 先解析歌曲元数据，按用户、Suno 歌曲 ID、导入歌词摘要和处理设置判断是否复用。短分享链接和完整歌曲链接可以指向同一工程；用户提交的链接仍用于展示，不能从歌曲 ID 反向编造分享短码。

- 歌词和设置未变：复用进行中任务或有对齐结果的已完成任务，不重新下载、对齐或扣额度。手动编辑的时间轴仍保留。
- 歌词或设置变更：新建任务版本，不覆盖旧工程；原导入歌词摘要保存在 `config_snapshot`，不使用编辑后的时间轴充当原歌词快照。
- 失败或结果文件缺失：允许重新创建任务。
- API 可传 `lyrics_text` 使用修改后的歌词，或 `force_realign=true` 明确重跑；新任务按正常规则计费。当前编辑器保存时间轴不会自动提交重新对齐，前端尚未提供这两个参数的专用入口。
- 同一用户同时提交相同内容：数据库唯一键防止重复创建、扣额度。旧任务按其歌曲链接和原始歌词文件逐步补齐身份与摘要，无需数据库迁移。


编辑器媒体读取：人声、伴奏、原曲和编辑器视频下载在检查任务归属后，由后端读取私有存储并返回文件；不向浏览器重定向到 R2，不依赖 bucket 的 CORS 或公开域名。媒体临时副本在响应完成后删除。此方式会经过后端传输文件，当前尚未实现远端逐块流式读取。


### Cloudflare Pages 的 Motion Studio 静态资源

Cloudflare Pages 发布目录是 `frontend`。Motion 页面依赖构建后的 JavaScript，不能使用空构建命令。Pages 的构建命令设置为 `cd frontend/motion && npm ci && npm run build:pages`，根目录为仓库根目录，输出目录仍为 `frontend`。构建只生成浏览器播放器与实验室脚本，不构建后端 Remotion 渲染包。

`frontend/_redirects` 为 `/motion-lab.css`、`/motion/*` 与 Motion 页面别名提供明确映射，必须位于首页兜底规则之前。部署后资源应返回 CSS/JavaScript；HTTP 200 但内容为首页 HTML 仍属于资源加载失败。


### 由 GitHub CI 统一部署前端（替代 Pages 自行构建）

现有 CI 已构建并测试 Motion 资源，`deploy-to-pages` 下载同一份 `motion-assets` 产物，将静态前端直接部署至现有 Pages 项目，不重复安装依赖或构建。部署包排除 Motion 源码、测试、node_modules 和后端 Remotion 渲染包。

一次性在 GitHub Actions 配置 Secrets `CLOUDFLARE_API_TOKEN`（选定账户的 Cloudflare Pages Edit 权限）和 `CLOUDFLARE_ACCOUNT_ID`，以及 Variable `CLOUDFLARE_PAGES_PROJECT_NAME`（现有 Pages 项目的真实名称，不是域名或 R2 bucket）。未设置项目名时该部署 job 不启用。

启用 CI 部署后，关闭该 Pages 项目 Git 集成的生产及预览自动部署，避免未构建的 Git 源文件覆盖 CI 上传的产物；无需修改现有域名或新建 Pages 项目。之后 push main → CI 检查与构建 → HF 和 Pages 分别自动部署。

### Chrome 插件 1.6

官方云端插件使用相同的账号任务与编辑器导出接口，不再放行旧的共享
`/api/plugin/export_video`、`/api/plugin/export_audio` 或 `/api/lyric_video/task_status`。
它们在本地服务仍可用。原曲 MP3 兜底接口继续检查有效登录与公开歌曲。
导出支持 UUID `request_id`，按用户、原歌曲任务、操作类型确定重试标识；
相同请求复用已有结果，不同设置重用编号返回 409。视频操作仍由现有后台
任务执行，服务重启会明确中断未完成任务，并非可自动续算的持久队列。
