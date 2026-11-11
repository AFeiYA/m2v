# 🎄 圣诞公有领域翻唱专辑策划与全平台发行指南
**专辑企划名称**: *A Cozy Christmas: Public Domain Carols Vol. 1*  
**发行平台**: DistroKid (上线 Spotify, Apple Music, YouTube Music, Amazon Music, TikTok 等)  
**衍生视频**: YouTube 4K 伴奏卡拉OK长视频 + 9:16 Shorts 引流短视频  
**生成时间**: 2026-11-11  

---

## 📋 10 首收录曲目总表 (100% 公有领域，零版税成本)

| 序号 | 英文歌名 | 中文名称 | 原创作者 / 作曲 | 创作年份 | 推荐 BPM / 调性 | 伴奏素材目录 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **Silent Night** | 平安夜 | Franz Xaver Gruber | 1818 | 80 BPM / Bb Major | `projects/christmas_album/01_Silent_Night/` |
| 2 | **Jingle Bells** | 铃儿响叮当 | James Lord Pierpont | 1857 | 120 BPM / F Major | `projects/christmas_album/02_Jingle_Bells/` |
| 3 | **Deck the Halls** | 装饰大厅 / 红烛泪 | Traditional Welsh Melody | 1862 | 96 BPM / D Major | `projects/christmas_album/03_Deck_the_Halls/` |
| 4 | **We Wish You a Merry Christmas** | 祝你圣诞快乐 | Traditional English Carol | 1500 | 128 BPM / Ab Major | `projects/christmas_album/04_We_Wish_You_a_Merry_Christmas/` |
| 5 | **Joy to the World** | 普世欢腾 | George Frideric Handel / Lowell Mason | 1719 | 92 BPM / D Major | `projects/christmas_album/05_Joy_to_the_World/` |
| 6 | **Hark! The Herald Angels Sing** | 听啊！天使高声唱 / 新生王歌 | Felix Mendelssohn | 1739 | 88 BPM / F Major | `projects/christmas_album/06_Hark_The_Herald_Angels_Sing/` |
| 7 | **O Tannenbaum (O Christmas Tree)** | 噢，圣诞树 | Traditional German Melody | 1824 | 76 BPM / G Major | `projects/christmas_album/07_O_Tannenbaum_O_Christmas_Tree/` |
| 8 | **The First Noel** | 第一支圣诞歌 | Traditional English Carol | 1823 | 84 BPM / D Major | `projects/christmas_album/08_The_First_Noel/` |
| 9 | **God Rest Ye Merry, Gentlemen** | 愿上帝赐予你们平安，先生们 | Traditional English Carol | 1650 | 104 BPM / E Minor | `projects/christmas_album/09_God_Rest_Ye_Merry,_Gentlemen/` |
| 10 | **O Holy Night** | 圣善夜 | Adolphe Adam | 1847 | 68 BPM / C Major | `projects/christmas_album/10_O_Holy_Night/` |

---

## 🚀 DistroKid 独家发行避坑策略 (省钱 + 100% 收益)

在 DistroKid 提交新专辑时，请严格按照以下步骤操作，**不需要花钱买任何翻唱许可！**

1. **Cover Song 勾选问题（千万别选 Cover Song 付费选项！）**：
   - 普通翻唱（如周杰伦、Taylor Swift）需要向 DistroKid 支付每年 **$12/首** 的翻唱版权管理费（Mechanical License）。
   - **但是！这 10 首歌曲是 100% 公有领域（Public Domain）！**
   - 在询问 *“Did you write this song, or is it a cover?”* 时：
     - 选择 **“Another artist wrote it (cover song)”** 之后，系统问到曲目性质时，选择 **“Public Domain / Traditional”**（公有领域传统歌曲）。
     - 或者直接在 Songwriter 处填写真实的原创作者（如 `Franz Xaver Gruber`，`Public Domain`）。
     - **DistroKid 不会对公有领域歌曲收取任何版税或许可费！**

2. **收益与 YouTube Content ID (Content ID Collection)**：
   - **Spotify / Apple Music**: 所有的流媒体播放分成 100% 全归您。
   - **YouTube 官方 Content ID**: 当您在 DistroKid 勾选 YouTube Content ID 时，DistroKid 会为您重新录制的**母带录音（Master）**建立指纹。全网任何人用您翻唱的这版圣诞歌，广告收益都会自动打入您的 DistroKid 账户！

---

## 🎹 两种高效翻唱制作方案

### 方案 A：Suno AI 快速定制多样化流行风格 (效率最高)
在 Suno 中使用我们为您整理好的 `lyrics.txt`，搭配以下黄金 Prompt 组合：
* **流行木吉他温暖民谣风**: `Acoustic folk pop, warm nylon guitar, intimate close female vocals, cozy winter fireplace, 85 bpm, emotional`
* **爵士咖啡馆轻音乐风**: `Christmas jazz lounge, smooth upright bass, brushed drums, Rhodes piano, soulful saxophone, late night`
* **现代流行治愈风 (Coldplay风格)**: `Cinematic piano pop, arena drums, anthemic uplifting chorus, atmospheric ambient pads, passionate vocals`

### 方案 B：在 DAW (Logic / Ableton / FL Studio) 配合伴奏翻唱
每个子文件夹中都为您下载并转码好了高品质的 **`.wav` 无损参考音轨** 与 **`.mp3` 伴奏**，直接拖入工程即可录制自己的人声或重新挂音色编曲。

---

## 🎬 M2V 卡拉OK与歌词视频制作流水线

制作好音频后，一键生成全网分发视频：
1. **16:9 横屏全曲（长视频）**:
   - 导入 M2V，选择 `director` 或 `apple` 动效排版；
   - 封面选用暖色调圣诞雪夜或壁炉视觉；
   - 导出后直接运行自动上传命令：
     ```bash
     python tools/upload_youtube.py "视频路径.mp4" --public
     ```
   - **结果**：全球 100% 正常播放，无任何唱片公司索赔，广告分成 100% 归您！

2. **9:16 竖屏高潮副歌（Shorts 引流短视频）**:
   - 截取 30~45 秒的高潮合唱部分；
   - 自动防雷脚本会自动放行（时长 <= 60s），并在短视频流量池爆发式吸粉！
