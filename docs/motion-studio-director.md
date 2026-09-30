# Motion Studio：歌词海报到动画

当前分支 `codex/motion-studio-director` 采用 Python 音频与导演接口 + React/Remotion 帧渲染。

## 用户流程

1. 选择已有 alignment 歌曲工程，选择横屏/竖屏及分辨率。
2. 读取保存的导演方案或自动生成基础方案。没有海报设计的旧句子使用基础海报排版，不需要覆盖旧工程即可预览。
3. 下载整曲/单句 LLM 提示词，粘贴返回 JSON，先校验再应用。当前仍由用户选择外部 LLM，没有自动发送歌词或账号密钥。
4. 选择句子，点击顶栏“当前句海报”查看最终静态排版，下载 PNG 或编译后的 JSON。
5. “播放当前句动画”按演唱锚点逐块进入，落位后保留，结束后停留在完整海报供复核；整曲播放正常执行退出。
6. 调整海报模板、节点主次、入场、驻留及主视觉拍点回弹，保存后导出片段或完整 MP4。

## 同一份排版和时间

`poster-layout.ts` 根据实际字体度量，计算安全区、槽位、换行与字号。提供主标题层级、居中层叠、左右错落三种规则，支持 16:9 / 9:16。所有文字框占用独立槽位；进入位移和缩放有限，密集快唱自动降级为淡入。

`lyric-video.tsx` 是预览与导出的共同 Remotion 组件。文字通过 SVG 按编译基线绘制，动画完全由帧号及 alignment 锚点求值，不使用 CSS transition/animation。静态 PNG 使用相同几何结果。音频是实时预览的主时钟，跳转完成后同步 Player 的帧号。

整句 cumulative 拼成海报，入场只有 none/fade/slide-up/slide-left/scale-in；驻留 none/drift，主视觉可选 pulse；退场 cut/fade。入场必须在原句时间内落位，不延长歌曲。没有词对齐时使用整句锚点。代码不推测音高、混响尾长或歌词未提供的节奏。

## 导出

`render-remotion.mjs` 使用构建好的合成组件与 @remotion/renderer 输出 H.264 30fps 视频，再由 FFmpeg 合成原曲 AAC。尺寸取用户选定画幅/分辨率；片段使用原歌曲绝对起点。

导出同时一个任务，有进度、取消及错误提示。成片、源方案快照与完成记录保存在歌曲 motion_exports；完成记录和下载在服务重启后保留，运行中任务不自动恢复。

Motion Lab 保留原 pdoom/Three.js 实验渲染；Studio 海报模式暂不执行 pdoom 后处理、三维文字、自适应运动模糊或跨句推挤转场。Remotion 提供组件与逐帧工具，排版与美术效果仍需模板和视觉验证。

接口、版本兼容与提示词见 `motion-director-api.md`。Remotion 商用许可遵循官方说明：https://www.remotion.dev/docs/license/pricing 。Docker/云部署尚未在本机实测。
