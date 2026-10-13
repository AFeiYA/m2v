# 页面地址

页面统一使用小写英文与连字符，一项功能一个入口：

| 页面 | 地址 |
| --- | --- |
| 首页与任务列表 | `/` |
| 歌词编辑 | `/lyric-editor` |
| 编辑指定任务 | `/lyric-editor/{task_id}` |
| 动效导演 | `/motion-studio` |
| 作品库 | `/gallery` |
| 分镜 | `/storyboard` |
| 动效实验页 | `/motion-lab` |

旧的 `/local/...`、`/editor`、`/lyric_editor`、`/motion_studio`、
`/motion_studio_director` 和 `/motion` 不再作为页面入口，不保留兼容跳转。
未知地址显示 404，用户可以从首页重新进入。

Cloudflare Pages 直接通过根目录同名 HTML 文件提供页面；不要把干净路径
重写到 `.html`。Pages 会自动把 HTML 地址规范化为无扩展名地址，二者组合
会产生指向自身的 308 重定向循环。

部署脚本把根目录页面链接复制成实际文件，排除内部 `local/*.html`，保留
`/static/*`、`/motion/*` 和样式资源。`/lyric-editor/*` 只重写到无扩展名的
`/lyric-editor`。构建阶段拒绝可能产生循环的 HTML 重写规则。

页面地址变化不影响 `/api/...` 接口、数据库记录、音频或已保存的任务。
