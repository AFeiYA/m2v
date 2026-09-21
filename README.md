# M2V (Music-to-Video) 自动化视听与卡拉OK制作管线

M2V 是一个专为 AI 音乐（Suno 等）及本地歌曲打造的**全自动化端到端视听制作与字幕对齐系统**。从 Suno 链接或本地音频出发，自动化完成人声分离、词级时间轴对齐、音乐乐段解析、影视级多行流动字幕与分镜视频合成。

---

## 🌟 核心特性

- ⚡ **Suno 一键直达**：直接输入 Suno 歌曲分享链接，全自动抓取音频与歌词、分离伴奏与人声、智能切分乐段并完成字级高精度时间轴对齐。
- 🎵 **音乐乐段结构化（Musical Sections）**：自动解析 `[Intro] (前奏)`, `[Verse] (主歌)`, `[Chorus] (副歌)`, `[Bridge] (桥段)`, `[Outro] (尾奏)`，建立具备视听导演视角的乐段骨架。
- 🎨 **Apple Music 级联动态字幕**：不仅支持经典 KTV 双行交替过光，更有复刻 Apple Music 的垂直平滑级联滚动聚焦、景深模糊渐变与 `\kf` 平滑渐变变色效果。
- 🛠️ **双独立可视化编辑器 (零数据库轻量运行)**：
  - **歌词时间轴精调 (`/`)**：双轨 WaveSurfer 人声/伴奏波形、段落徽标双击跳播、毫秒级逐字拖拽伸缩、微调面板、一键重新生成 ASS 字幕。
  - **视频分镜制作 (`/storyboard`)**：素材库浏览上传、镜头时间区间绑定、整句快速同步、全局背景切换与一键合成 MP4 视频。
- 📐 **Pydantic v2 强类型数据契约**：以 `AlignmentProject` 为核心标准 JSON Schema，内嵌时间戳倒挂自纠正校验，无缝桥接 LLM 影视剧本与分镜提示词生成。
- 📁 **专属歌曲目录管理**：遵循 `input/{song_name}/` 与 `output/{song_name}/` 结构，各歌曲工程独立归档，干净井然。

---

## 🚀 快速开始

### 1. 环境准备

推荐使用 Conda 管理 Python 3.11+ 环境，并确保系统已安装 FFmpeg：

```bash
# 1. 创建并激活 Conda 环境
conda create -n m2v python=3.11 -y
conda activate m2v

# 2. 安装项目依赖 (包含 PyTorch, WhisperX, Demucs, FastAPI 等)
pip install -e .
```

### 2. 启动本地双工作流编辑器（推荐）

无需配置数据库或 Docker，一条命令即可启动本地全功能 Web 编辑器：

```bash
python -m src.local_editor
```
- 服务启动后将自动在浏览器打开：
  - 🎤 **歌词与字幕精调**：`http://127.0.0.1:8000/`
  - 🎬 **视频分镜与素材合成**：`http://127.0.0.1:8000/storyboard`

在编辑器左上方直接粘贴 Suno 歌曲链接（如 `https://suno.com/song/...`），点击 **⚡ 导入对齐** 即可开始全流程处理。

---

## 💻 核心操作与 CLI 使用

### 1. 从 Suno 链接全自动拉取并对齐
```bash
# 下载、分轨、解析乐段并输出对齐工程
python -m src.suno_fetch https://suno.com/song/<song_id>
```

### 2. 本地全自动管线批处理
```bash
# 针对单首歌曲执行完整流程 (人声分离 → 词级对齐 → ASS压制 → 视频合成)
python -m src.main -i input/如其所是01/audio.wav -o output/

# 已经是纯人声干音，跳过 Demucs 分离
python -m src.main -i input/如其所是01/vocals.wav -o output/ --skip-separation

# 仅生成 ASS 字幕文件与对齐 JSON
python -m src.main -i input/如其所是01/audio.wav -o output/ --ass-only

# 复用已有对齐 JSON 直接生成 ASS/视频
python -m src.main -i input/如其所是01/audio.wav -o output/ --alignment-json output/如其所是01/如其所是01_alignment.json
```

### 3. LLM 影视分镜与提示词自动化
```bash
# 1. 根据对齐歌词自动生成导演 Prompt 模板
python -m src.llm_director -i output/如其所是01/如其所是01_alignment.json -a prompt

# 2. 将大模型生成的镜头与动效设计合并回工程
python -m src.llm_director -i output/如其所是01/如其所是01_alignment.json -a merge -r output/如其所是01/llm_response.json
```

---

## 📂 工程与输出目录规范

```text
m2v/
├── input/
│   └── {song_name}/                # 专属歌曲输入目录
│       ├── {song_name}.mp3         # 原始音频
│       └── {song_name}.txt         # 原始歌词（含乐段提示）
├── output/
│   └── {song_name}/                # 专属歌曲产物目录
│       ├── {song_name}_vocals.wav        # Demucs 提取的高保真人声干音
│       ├── {song_name}_instrumental.wav  # Demucs 提取的伴奏音频
│       ├── {song_name}_alignment.json    # Pydantic v2 标准视听工程文件
│       ├── {song_name}.ass               # Apple Music / KTV 双风格卡拉OK字幕
│       └── {song_name}.mp4               # 最终合成的卡拉OK宣传视频
└── assets/                         # 放置供分镜使用的图片/视频素材 (git忽略)
```

---

## 🏗️ 系统架构与数据模型

### 1. 数据契约引擎 (`src/storyboard_schema.py`)
整个系统的数据流均依托 Pydantic v2 构建严格的数据不变量约束：
- **`WordTimestamp`**：单个汉字/英文单词的起止秒数（保证 `end >= start`）。
- **`AlignedLine`**：整行歌词，内嵌校验器自动基于单字时间戳同步修正行 `start` 与 `end`，携带 `section` 乐段归属。
- **`MusicSection`**：前奏、主歌、副歌等乐段的绝对时域与情绪/风格元数据。
- **`ShotPlan`**：分镜镜头模型，兼备物理合成属性（`path`, `speed_align`）与影视属性（`scale`, `camera_movement`, `prompt_zh`, `prompt_en`）。
- **`AlignmentProject`**：聚合全部对齐信息与视觉圣经（Visual Bible）的根工程对象。

### 2. 前端模块解耦架构 (`frontend/local/`)
- **`common.js`**：双轨 WaveSurfer 波形播放、歌曲选择器、Suno 导入、状态通知、撤销/重做栈与底层时间工具。
- **`lyric_editor.js`**：词级编辑器专用逻辑（字级轴拖拽抓取、微调步进、乐段徽标渲染、整行伸缩、ASS 重新生成）。
- **`storyboard_editor.js`**：分镜制作专用逻辑（素材库弹窗/上传、镜头列表维护、整行时间同步、视频渲染配置）。

---

## 🧪 测试与质量保证

本项目包含完整的自动化测试集，覆盖歌词预处理、ASS 标签计算、LRC 转换以及对齐器核心：

```bash
pytest tests/
```
*(当前 28 项单元测试保持 100% 通过)*
