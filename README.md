# Suno2MV (M2V) — AI Music Video Director & Editor

> **Turn a song into a directed, editable music video.**
> 从一首歌出发，深度解析音乐结构、节奏与情感曲线，生成导演方案与视觉圣经，建立卡点分镜与动态故事板（Animatic），进而调度前沿视频模型生成镜头、对比 Takes 并完成专业剪辑合成。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/managed_by-uv-orange.svg)](https://github.com/astral-sh/uv)
[![Architecture](https://img.shields.io/badge/schema-Pydantic_v2-brightgreen.svg)](https://docs.pydantic.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 💡 产品哲学与核心定位

### 1. 从“自动卡拉OK生成器”到“AI 音乐录影带导演”
过去的 M2V 解决的是：`音频 → 歌词对齐 → 卡拉OK字幕 → 简单素材编排 → 压制视频`。
升级后的 **Suno2MV** 真正聚焦的是：
$$\text{Song} \xrightarrow{\text{Music Intelligence}} \text{AI Director} \xrightarrow{\text{Visual Bible}} \text{Storyboard} \xrightarrow{\text{Animatic}} \text{Shot Generation} \xrightarrow{\text{AI Editor}} \text{Final MV}$$

- **关键词是 Directed + Editable，而非单纯的 Automatic**：纯黑盒自动化生成极易产生“画面虽美、人物走样、毫无故事、镜头重复、节奏随机”的废片。Suno2MV 致力于提供专业导演视角与每一层可干预的编辑能力。
- **Animatic before Video Generation（先动态分镜，后生成视频）**：在调用算力昂贵的视频大模型前，先在 30 秒内用极低成本的静态分镜把整首歌剪辑排列，配合音乐播放验证节奏与叙事。只有故事立住了，才投入视频生成。
- **Model Router（模型解耦，工作流为王）**：模型每半年就会迭代，产品的真正壁垒在于从音乐到影视镜头语言的编译中枢。通过统一的 `VideoProvider` 抽象层，灵活路由至 Veo 3.1、Seedance 2.5、Runway Gen-4.5、Luma Ray3 或本地 Wan2.2。

---

## 🎬 2026 影视级 AI 生产管线

| 阶段 | 核心任务 | AI / 技术驱动 | 交付产物 |
| :--- | :--- | :--- | :--- |
| **1. Creative Brief** | 确定 MV 类型（叙事/视觉氛围/演出）、核心冲突与基调 | LLM Director | 创作简报与 5 维问卷偏好 |
| **2. Music Intelligence** | 提取 BPM、乐段结构、鼓点下潜、能量跃迁与情感弧线 | Demucs + Librosa | 双层音频驱动数据契约 |
| **3. Treatment** | 撰写一页纸导演方案、段落剧本与视觉隐喻 | LLM Director | 1-Page Director Treatment |
| **4. Visual Bible** | 锚定固定角色、场景、服装、影调与摄影镜头参数 | Image AI / Keyframes | 视觉圣经（设定图包与规范词） |
| **5. Storyboard** | 依节拍卡点生成 30~50 个分镜，规划景别与运镜 | LLM + 静态生图 | 结构化 Shot 列表与镜头草图 |
| **6. Animatic (Magic Moment)** | 静态分镜按真实音乐时间线排列，实时同步播放验片 | Web Timeline Editor | **全片动态分镜样片（0 视频成本）** |
| **7. Shot Generation** | 针对确认分镜，通过 Model Router 并发生成多个 Takes | Veo / Seedance / Wan | 多候选 Takes（含参考控制） |
| **8. Creative Editing** | 镜头对比挑选（Take Selection）、局部重抽与微调 | 交互式剪辑台 | 锁定 Final Cut 镜头序列 |
| **9. Finishing & Mastering** | 流动字幕（Apple Music / KTV）、转场特效、音画混流压制 | FFmpeg + ASS Engine | 4K/1080p 影视级最终 MV |

---

## 🏗️ 核心领域模型（Domain Schema）

系统全面依托 Pydantic v2 构建严格的影视工程数据体系，实现数据契约驱动：

```text
Project (根工程)
├── Song                   # 音频源信息 (上传音频 / Suno 导出 / 官方 API)
├── SongAnalysis           # 音乐智能 (Sections, Downbeats, Drums/Bass Energy, Vocal Activity, Emotions)
├── CreativeBrief          # 导演意图 (类型: 叙事/氛围/演唱, 风格, 角色设定)
├── VisualBible            # 视觉圣经
│   ├── Characters         # 角色设定 (容貌/发型/服装/固定饰品 + 参考三视图)
│   ├── Locations          # 场景库 (光影/氛围/空间特征)
│   ├── Photography        # 摄影风格 (焦段、机位、颗粒感、色彩倾向)
│   └── StyleTokens        # 统一注入的影视级风格锚点
├── Treatment              # 导演阐述与乐段叙事大纲
├── Sequences & Shots      # 影视镜头序列
│   └── Shot               # 最小影视单元 (起止时间、乐段、景别、运镜、角色引用、机位运动)
├── Generations            # 生成实体解耦层
│   └── Takes              # Shot 1 对应 Take A, Take B, Take C (模型来源、Prompt、成本、评分)
├── Timeline               # 最终剪辑时间线 (选定的 Takes、切镜点)
└── Subtitles              # 词级卡拉OK与 Apple Music 级联动态字幕
```

---

## ⚡ 双层音乐智能（Dual-Layer Music Intelligence）

Suno2MV 拒绝简单的“按歌词字面生视频”或“机械节拍切镜”，而是把音乐和歌词拆分为两个互锁的导演维度：

1. **叙事层（Lyrics & Narrative Layer）**：
   - 提取歌词隐喻、叙事进展与情感基调。
   - 决定：*镜头中发生什么故事、出场角色、场景变迁、情绪色彩。*
2. **视听律动层（Music & Cinematography Layer）**：
   - 基于 Demucs 分离出的 `drums.wav`、`bass.wav` 与 Librosa 分析。
   - **Drums Onset**：决定硬切剪刀点（Cut Points）。
   - **Bass / Energy Jump**：在副歌（Chorus）爆发时触发广角俯冲、镜头拉升或视觉粒子膨胀。
   - **Vocal Silence**：自动规划空镜、环境过渡镜头（B-roll）。

---

## 🖥️ 核心交互：Animatic Editor

工作流的核心主界面不是单纯的 Prompt 输入框，而是**动态故事板监看台**：

```text
┌────────────────────────────────────────────────────────────────────────┐
│  Suno2MV — AI Director & Animatic Studio                               │
├──────────────────────────┬─────────────────────────────────────────────┤
│                          │  ▶ PREVIEW (Animatic / Video Player)        │
│  STORYBOARD (Shots)      │                                             │
│  [Shot 01] Intro (Wide)  │                                             │
│  [Shot 02] Verse 1 (MCU) │         [ 静态分镜平滑推拉预演 / 视频 ]        │
│  [Shot 03] Verse 1 (CU)  │                                             │
│  [Shot 04] Chorus (Crane)│                                             │
├──────────────────────────┴─────────────────────────────────────────────┤
│  TIMELINE & MUSIC INTELLIGENCE                                         │
│  Sections: [ Intro ]  [  Verse 1  ]  [ Pre-Cho ]  [     Chorus     ]   │
│  Energy:   ▂▃▅▃       ▃▄▅▄▃          ▄▅▆▇        ████████████████      │
│  Shots:    | Shot 1 |   Shot 2   |   Shot 3   |        Shot 4        | │
│  Lyrics:   "海浪淹没我的名字..."                                         │
└────────────────────────────────────────────────────────────────────────┘
```

- **单镜头检视器**：点击任意 Shot，一键查看绑定的角色、场景、运镜要求；
- **多 Take 选拔**：在同一个 Shot 下横向对比不同模型生成的 Take A / Take B / Take C，挑出最佳画面；
- **非破坏性试错**：随意调整镜头入点/出点，无需全片重新渲染。

---

## 🗺️ 产品演进路线图（Roadmap）

我们严格按照影视工程的本质规律安排迭代顺序，将验证核心体验前置，将重资产与重营销机制后置：

```mermaid
flowchart LR
    D[0.3 Director<br>音乐分析与方案] --> B[0.4 Bible<br>视觉圣经设定]
    B --> S[0.5 Storyboard<br>卡点分镜设计]
    S --> A[0.6 Animatic<br>动态预演播放器]
    A --> G[0.7 Generator<br>Model Router]
    G --> E[0.8 Editor<br>多Take剪辑]
    E --> C[0.9 Continuity<br>一致性控制]
    C --> F[1.0 Final MV<br>完整工业交付]
    F --> P[1.1 Performance<br>口型与演唱]
    P --> Cloud[1.2 SaaS & Cloud<br>商业化部署]
```

- **v0.3 Director**：升级音频特征分析，打通 1 页纸导演方案与乐段情绪曲线自动提取。
- **v0.4 Visual Bible**：角色三视图、场景库与摄影影调设定（Prompt Tokenizer & Keyframe Pack）。
- **v0.5 Storyboard**：依据节拍卡点自动规划 30~50 个规范分镜（景别、运镜、叙事目的）。
- **v0.6 Animatic (🎯 MVP 垂直切片)**：**零视频生成成本**，静态分镜图铺满时间线，实现完整 MV 动态播放与节奏验片。
- **v0.7 Generator & Model Router**：集成统一 VideoProvider，接入主流商用模型与本地加速方案。
- **v0.8 Editor**：支持多 Take 抽卡、横向对比、局部重生与非破坏性剪辑。
- **v0.9 Continuity**：引入 Character Reference、首尾帧过渡与前后镜头光影一致性锁定。
- **v1.0 Final MV**：ASS 级联流动歌词动态合成、影视调色与多分辨率高质量渲染导出。
- **v1.1 Performance MV**：接入 Wan2.2 Animate / Lip-sync，支持虚拟角色高保真对唇演唱。
- **v1.2 SaaS & Multi-Tenant**：任务排队、计费配额、云端渲染集群与团队协同。

---

## 🚀 快速上手

本项目全面支持现代 Python 包管理器 [uv](https://github.com/astral-sh/uv)，毫秒级依赖解析与环境隔离。

### 1. 环境准备

确保系统已安装 **FFmpeg**（macOS 建议通过 Homebrew，Windows 建议下载 release-full）：
```bash
# macOS
brew install ffmpeg

# 验证 FFmpeg
ffmpeg -version
```

### 2. 使用 uv 初始化与安装

```bash
# 克隆代码
git clone git@github.com:AFeiYA/m2v.git suno2MV
cd suno2MV

# 1. 使用 Python 3.11 极速创建虚拟环境
uv venv --python 3.11

# 2. 一键安装核心依赖与本地 Web 工作台套件
uv sync --extra editor --extra dev
```

### 3. 启动本地双工作流编辑器

无需配置数据库或 Docker，一条命令即可启动本地全功能创作工作台：

```bash
uv run python -m src.local_editor
```

- 打开浏览器访问：
  - 🎤 **歌词时间轴精调 (`/`)**：双轨 WaveSurfer 人声/伴奏波形、段落徽标跳播、字级拖拽。
  - 🎬 **动态分镜与视听合成 (`/storyboard`)**：镜头设计、音乐乐段绑定与视频合成。

### 4. 核心 CLI 工具使用

```bash
# 导入本地音频并执行全流程处理
uv run python -m src.main -i input/my_song/audio.wav -o output/

# 生成导演提示词模板与方案
uv run python -m src.llm_director -i output/my_song/my_song_alignment.json -a prompt

# 运行自动化测试集
uv run pytest tests/
```

---

## 📂 工程与产物目录规范

```text
suno2MV/
├── input/                          # 歌曲原始输入
│   └── {song_name}/
│       ├── audio.wav (或 mp3)      # 原始音频
│       └── lyrics.txt              # 歌词（含乐段标识如 [Verse], [Chorus]）
├── output/                         # 歌曲产物归档
│   └── {song_name}/
│       ├── {song_name}_vocals.wav        # Demucs 提取的高保真人声干音
│       ├── {song_name}_instrumental.wav  # Demucs 提取的纯伴奏音频
│       ├── {song_name}_analysis.json     # 音乐智能与节拍能量分析结果
│       ├── {song_name}_treatment.md      # AI 导演方案与视觉圣经设定
│       ├── {song_name}_storyboard/       # 生成的分镜静态图 (Animatic 阶段)
│       ├── {song_name}_shots/            # 生成的多 Take 视频片段
│       ├── {song_name}.ass               # Apple Music / KTV 级流动变色字幕
│       └── {song_name}.mp4               # 最终影视级 MV
└── assets/                         # 视觉圣经公用参考库、素材库
```

---

## 🤝 贡献与讨论

我们坚信 AI 正在重塑视听艺术的创作流程。欢迎致力于 AI 导演、计算机音乐智能、视频一致性控制与现代剪辑工具链的开发者提交 Issue 与 PR！
