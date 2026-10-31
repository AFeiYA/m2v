# Fovea Studio — YouTube 频道素材包

制作日期：2026-10-30。状态：素材已生成；尚未上传频道，尚未录制和发布教程。

## 先用哪些文件

1. 创建或切换到正确的 **Fovea Studio** 频道。
2. 打开 YouTube Studio → 自定义 / Customization → Profile（不同语言和版本菜单名称可能不同）。
3. 上传下面的头像与横幅，把 `channel-copy-en.txt` 中对应的英文文案复制到公开资料。
4. 第一条教程录制完成后，上传视频并使用教程缩略图。

| 位置 | 文件 | 尺寸 / 用法 |
| --- | --- | --- |
| 频道头像 | `assets/channel-avatar-800.png` | 800×800；沿用网站图标，重要图形位于圆形裁切范围内。 |
| 频道横幅 | `assets/channel-banner-2560x1440.png` | 2560×1440；名称、定位、网址集中在中央安全区，实际文件小于 6 MB。 |
| 横幅裁切参考 | `assets/banner-safe-area-guide.png` | 仅预览，带白色安全框；**不要上传这个文件**。 |
| 视频水印 | `assets/video-watermark-150.png` | 150×150，透明背景；在 Studio 提供该入口时使用。 |
| 首条教程缩略图 | `assets/tutorial-01-thumbnail-3840x2160.jpg` | 3840×2160，16:9；小于 2 MB，采用当前渲染器截图。 |
| 缩略图轻量备选 | `assets/tutorial-01-thumbnail-1280x720.jpg` | 同一设计的轻量版本。 |
| 三种效果介绍图 | `assets/three-lyric-styles-1920x1080.png` | 1920×1080；可在教程中作为短暂说明页。 |
| 总览 | `assets/kit-preview.jpg` | 方便审阅整套风格，不是上传横幅或缩略图的源文件。 |
| 频道信息 | `channel-copy-en.txt` | 名称、handle 候选、英文简介、客服邮箱、网站链接、播放列表。 |
| 首条教程 | `tutorial-01-en.md` | 英文旁白、镜头表、标题、简介、置顶评论草稿。 |

头像、横幅、缩略图均使用现有 Fovea 深色与荧光绿风格，没有替换品牌图标。SVG 可编辑源文件保存在 `source/`。

## 截图的来源和适用范围

| 文件 | 来源 | 可以证明什么 / 如何使用 |
| --- | --- | --- |
| `screenshots/01-public-homepage.png` | `https://mv.fovea.si/`，公开首页整页实拍 | 网站真实首页；为窄窗口截图，可作页面参考，不是桌面工作台截图。 |
| `screenshots/02-apple-scroll-demo.png` | 当前仓库的 `RemotionPreview` + `marketing-demo.ts` | 720×1280，Apple Scroll 的真实渲染器画面。 |
| `screenshots/03-dual-line-karaoke-demo.png` | 同上 | 1280×720，Dual-line Karaoke 的真实渲染器画面。 |
| `screenshots/04-kinetic-poster-demo.png` | 同上 | 720×1280，Kinetic Posters 的真实渲染器画面。 |
| `screenshots/05-motion-workspace-staging-reference.png` | 已登录的 staging Motion Studio，裁去账号侧栏 | 工作台界面参考。保留了真实未保存提示，未修改用户工程；**不要作为正式版功能验收或直接替代公开站点录屏**。 |

三种效果图截取自本地真实渲染器，并裁去画布外空白。示例歌词为项目自带的原创演示文本，时间戳是合成数据；演示 artist 显示改为 Fovea Studio。截图用于展示排版与过光状态，**不用于宣称 AI 对齐准确率、完整音画同步、导出速度或 MP4 验收已完成**。

这些图片没有包含账号余额、邮箱、密钥和浏览器地址栏中的工程 ID。staging 界面仍包含歌曲和作者显示名；对外宣传优先使用三张原创示例画面，或按下面清单录制一套公开版本操作。

## 录屏还要补哪几段

静态图片已备齐；下列动态证据应在公开视频制作时录制，不用截图冒充：

- [ ] 使用有权使用的音频与歌词，在公开站点实际创建歌曲并完成一次对齐。
- [ ] Lyric Studio 播放波形、选词试听、修改一个时间点并保存。
- [ ] Motion Studio 切换三种模式、调整画幅、预览并保存。
- [ ] 真实导出一个 MP4，播放核对声音、高亮及画幅。
- [ ] 按实际导出通道演示下载；只有确实已保存到云端的视频才展示 My Exports。
- [ ] 录屏隐去个人邮箱、余额、测试环境标识；按最终剪辑制作英文字幕。

还没录到的片段不标记“已完成”。当前素材包不是一次实际视频渲染验收。

## 可复用和修改

- `source/create-assets.cjs`：从已有 Logo 和截图重建所有图形，依赖 `sharp`。
- `source/capture-samples.ts`：调用现有项目渲染器的截图入口，无需改产品代码。
- `source/*.svg`：横幅、头像、缩略图等可编辑源文件。
- `asset-manifest.json`：成品尺寸和文件大小。

在仓库根目录、有 `sharp` 的环境中运行 `node docs/marketing/youtube/source/create-assets.cjs`。也可用 `SHARP_MODULE` 指向已有的 sharp 模块目录。不要将本地运行环境绝对路径或任何凭据写进频道资料。

## 官方规格参考

- [YouTube：管理频道品牌信息](https://support.google.com/youtube/answer/10456525?hl=en)：横幅建议 2560×1440、最大 6 MB；安全区按最小尺寸同比例换算后约 1544×423。
- [YouTube：添加视频缩略图](https://support.google.com/youtube/answer/72431?hl=en)：当前页面建议高分辨率 3840×2160。此包同时提供较小版本，两个 JPG 均控制在 2 MB 内。

发布时以 Studio 当前实际提示为准。候选 handle 尚未验证可用性，不表示频道已经创建。
