# Suno2MV (M2V) 全业务工作流与开发进度文档

> **版本:** v0.6+ (Animatic Studio & Dual-Modal Director)  
> **更新日期:** 2026-09-23  
> **项目定位:** *Turn a song into a directed, editable music video.* 从一首歌出发，通过音乐智能感知与影视语法导演编排，生成动态故事板（Animatic）与歌词特效视频。

---

## 第一部分：全系统端到端工作流架构 (End-to-End Workflow)

Suno2MV 采用 **“数据契约驱动、先动态预演后高成本生成 (Animatic before Video Generation)”** 的核心理念。全流程分为六大阶段：

```mermaid
flowchart TD
    subgraph S0["Stage 0: 音频准备与预处理"]
        A1["Suno URL / 本地音频 (MP3/WAV/M4A)"] --> A2["音频完整性校验 (ffprobe 截断探测)"]
        A2 --> A3["人声伴奏分离 (Demucs / MPS硬件加速)"]
        A2 --> A4["歌词清洗与编曲标记提取 (preprocessor)"]
    end

    subgraph S1["Stage 1: 音乐智能感知与字级对齐"]
        A3 --> B1["WhisperX 强制词级对齐 (ARM NEON / CUDA)"]
        A3 --> B2["音频特征提取 (BPM / 鼓点 / 能量跃迁 / 乐段)"]
        B1 & B2 --> B3["生成工程总契约 (AlignmentProject JSON)"]
    end

    subgraph S2["Stage 2: AI 导演视听编排 (双模态)"]
        B3 --> C0{"导演工作流选择"}
        C0 -->|"模式 A: 离线快速草稿"| C1["RuleBasedDirector 规则导演 (1秒编译 30+ 影视级 Shots)"]
        C0 -->|"模式 B: 大模型深度模式"| C2["导出专业提示词 (Shifted 相对时间戳 + 构图规范)"]
        C2 --> C3["大模型推理 (Claude 3.7 / GPT-4o / DeepSeek)"]
        C3 --> C4["Web 一键 JSON 回填 (提示词注入 + ASS特效覆盖)"]
    end

    subgraph S3["Stage 3: 动态预演 (Animatic Studio)"]
        C1 & C4 --> D1["批量渲染电影质感分镜卡片 (Pillow / 16:9 / 构图线 / HUD)"]
        D1 --> D2["Web 动态样片监看台 (双轨波形 / 卡点切镜 / Ken Burns 动效)"]
        D2 --> D3["镜头检视微调 (景别 / 运镜 / 动作 / 提示词)"]
    end

    subgraph S4["Stage 4: 视频模型调度 (规划中)"]
        D3 --> E1["Model Router 调度 (Veo / Seedance / Wan2.2)"]
        E1 --> E2["多 Take 候选对比与选择 (Takes Selection)"]
    end

    subgraph S5["Stage 5: 特效字幕与成片混流"]
        D3 & E2 --> F1["Apple Music 级联滚动 / KTV 逐字变色 ASS 生成"]
        F1 --> F2["FFmpeg 硬件音画混流压制 (4K / 1080p MP4)"]
    end
```

---

### 阶段详解

#### Stage 0: 音频准备与预处理 (Ingestion & Audio Prep)
1. **音频获取与导入**：
   - **Suno 爬取 (`suno_fetch.py`)**：支持输入 Suno 歌曲链接，自动提取歌词、流派 Prompt、元数据，并优先下载纯净 MP3 音频（绕过 Suno CDN 对 M4A-Opus 的截断反爬限制），支持自动扫描 `~/Downloads` 目录直接导入。
   - **本地音频导入**：直接放入 `input/{song_name}/` 目录。
2. **格式与完整性安全校验 (`utils.py -> is_valid_audio_file`)**：
   - 调用 `ffprobe` 深度探测音频文件头与实际时长，拦截因网络中断导致的 0 字节或破损文件。
3. **人声与伴奏分离 (`separator.py`)**：
   - 调度 Demucs (`htdemucs_ft` 模型) 分离为 `vocals.wav` 与 `instrumental.wav`。
   - **硬件自适应加速**：macOS 平台自动探测并启用 Apple Silicon GPU Metal 加速 (`mps`)；Linux/Windows 自动切换 `cuda` 或回退 `cpu`。
4. **歌词预处理 (`preprocessor.py`)**：
   - 剔除无效元数据标签，自动识别 `[Intro]`, `[Verse]`, `[Chorus]`, `[间奏]`, `[Solo]` 等编曲说明行。

#### Stage 1: 音乐智能感知与字级对齐 (Music Intelligence)
1. **WhisperX 强制词级对齐 (`aligner.py`)**：
   - 基于 CTranslate2 运行 Whisper 模型转写，再利用 wav2vec2 音频模型进行字级（毫秒精度）强制时间对齐。
   - 保留音乐艺术拖长音与唱腔延音的自然时间轴。
2. **音频智能特征提取 (`audio_analyzer.py`)**：
   - 利用 Librosa 分析音轨：
     - **BPM & 节拍序列**：获取每拍时间点与小节下潜点（Downbeats）。
     - **鼓点打击事件 (Drum Hits)**：分析底鼓（Kick）、军鼓（Snare）瞬间冲击力。
     - **能量曲线 (Energy Curve)**：全曲时域响度采样序列。
     - **推荐切刀点 (Cut Candidates)**：在鼓点下潜、乐段过渡与能量跳变处生成影视剪辑候选点。
3. **输出标准契约**：生成全曲统一数据结构 `output/{song_name}/{song_name}_alignment.json`。

#### Stage 2: AI 导演视听编排 (AI Director - Dual Modes)
Suno2MV 提供**双模态协同**设计：

| 模式 | 运行方式 | 优势与适用场景 | 关键产出 |
| :--- | :--- | :--- | :--- |
| **⚡ 模式 A: 离线快速规则草稿 (`RuleBasedDirector`)** | 纯本地 Python 算法推理（无需联网、无需 API Key、0 成本、1 秒完成） | 适合初期快速立项、离线无网环境、验证音乐节奏与乐段卡点 | 1 页纸导演阐述（Treatment）、视觉圣经（Visual Bible）、30+ 连贯分镜 ShotPlan |
| **🤖 模式 B: 大模型深度模式 (`LLMDirector`)** | Web 弹窗一键导出 Prompt，粘贴至 Claude 3.7 / GPT-4o / DeepSeek，再一键 JSON 回填 | 适合追求院线级 MV 质感、精妙隐喻构图、专业中英文视频提示词与歌词粒子光效 | 包含光影镜头语言的视频生成 Prompt、语义词组拆分动画、ASS 风格覆盖参数 |

#### Stage 3: 动态预演 (Animatic Studio & 零成本验片)
1. **影视级分镜样片卡片渲染 (`storyboard_renderer.py`)**：
   - 使用 Pillow 生成 16:9 电影质感卡片：
     - 电影 2.39:1 宽银幕遮幅（Letterbox）。
     - 三分法则构图辅助线（Rule of Thirds Grid）与焦点十字准星。
     - 顶部专业 HUD 栏（分镜号、乐段、时长、景别 `[WS/MCU/CU]`、运镜 `[PAN/TRACKING]`、机位）。
     - 底部影视级动作描述与发光歌词字幕条。
2. **Web 端动态监看工作台 (`/storyboard`)**：
   - **双轨同步音频播放**：人声/伴奏多轨混音与实时波形缩放。
   - **实时镜头切换与 Ken Burns 运镜**：播放到指定时间点自动切换镜头画面，并施加平滑推拉/平移动画。
   - **交互式检视面板 (Inspector)**：点击任意镜头即可实时微调景别、动作、提示词，并即时同步更新工程。

#### Stage 4: 视频模型调度与多 Take 管理 (规划中)
- 接入 Veo 3.1、Seedance 2.5、Wan2.2 等视频生成模型 API。
- 每个分镜支持生成多个 Take 候选，供导演对比挑选与局部重抽。

#### Stage 5: 特效字幕与成片混流 (Mastering & Output)
1. **Apple Music 级联滚动字幕 (`subtitle.py`)**：
   - 实现高保真垂直滚动聚焦布局，随歌曲播放实现果冻状弹性位移与淡入淡出。
   - 支持 `\kf` 平滑平移变色与 `\k` 逐字跳变变色。
2. **FFmpeg 高清混流压制**：
   - 支持一键导出独立 `.ass` 字幕文件。
   - 或使用 FFmpeg 硬件加速将伴奏、人声、背景分镜/视频与动态字幕合成为最终 MP4 交付成片。

---

## 第二部分：当前开发进度与里程碑 (Development Progress)

### 总体进度概览

| 阶段里程碑 | 核心内容 | 完成度 | 状态 |
| :--- | :--- | :---: | :---: |
| **M1: 基础工程与音频字幕管线** | Suno爬取、Demucs分离、WhisperX词级对齐、Apple Music ASS字幕渲染 | 100% | ✅ 已完成并稳定 |
| **M2: 领域模型与音乐智能引擎** | Pydantic v2 领域模型、Librosa 鼓点分析、切刀点提取、乐段骨架 | 100% | ✅ 已完成并稳定 |
| **M3: 动态故事板工作室 (Animatic Studio)** | Web 播放监看台、Pillow 卡片渲染、双轨波形、实时检视器 | 100% | ✅ 已完成并上线 |
| **M4: Web 大模型双模态导演集成** | Prompt 一键生成与导出、大模型 JSON 回填、分镜样片即时重绘刷新 | 100% | ✅ 本次已完成并实盘验证 |
| **M5: 视频大模型路由器 (Model Router)** | 统一生成抽象层、对接 Veo / Seedance / Wan2.2、多 Take 管理对比 | 20% | 🚧 架构设计就绪，接口对接中 |
| **M6: NLE 非线性时间轴与高级剪辑** | 剪辑切点微调、转场特效、多镜头时间轴吸附与重排 | 35% | 🚧 基础模型就绪，UI 交互开发中 |

---

### 已完成的核心特性详情 (Changelog & Completed Features)

#### 1. 视听智能与硬件支持
- [x] **macOS Apple Silicon Metal 加速**：Demucs 在 M 系列芯片上自动启用 `mps` 硬件后端，处理速度提升 3~5 倍。
- [x] **音频鲁棒性检测**：新增 `ffprobe` 格式嗅探，自动修复并兼容 Suno MP3 格式下载与本地快速导入。
- [x] **智能音乐特征工程**：支持 BPM 自动估算、Downbeat 重拍定位、RMS 能量分布曲线采样与硬切剪辑点推荐。
- [x] **艺术长音与延音保护**：保持歌词对齐时序自然度，忠实保留史诗唱段与传统戏腔的长音表达。

#### 2. AI 导演引擎 (Director Engine)
- [x] **确定性离线规则引擎 (`RuleBasedDirector`)**：
  - 基于歌词意象自动识别海洋、夜空、都市、自然四大叙事母题。
  - 自动构建包含角色特征（appearance/wardrobe）与场景设定（spatial_layout/lighting）的 Visual Bible。
  - 影视语法编译网：自动规划 ECU/CU/MCU/MS/WS 景别跳跃与 10 种专业摄影机运动。
- [x] **Web 端大模型提词与回填模态 (`LLMDirector Modal`)**：
  - 新增 `POST /api/director/llm_prompt` 接口，自动生成带 0.500s 相对时间戳的标准化结构 Prompt。
  - 新增 `POST /api/director/llm_merge` 接口，一键回填 JSON 数据，自动重新生成高清分镜卡片。
  - 弹窗原生支持一键复制 Prompt、JSON 粘贴回填与实时状态反馈。

#### 3. 动态故事板工作室 (Animatic Studio Web UI)
- [x] **双模态监看播放器**：支持静态分镜推拉验片（Animatic）与传统分镜表格视图自由切换。
- [x] **双轨波形音频引擎**：集成 WaveSurfer.js，支持人声/伴奏独立静音、缩放与毫秒级指针同步。
- [x] **专业 HUD 摄影参数显示**：播放过程中在画面顶部动态展示当前分镜号、景别、运镜动效。
- [x] **实时镜头检视器 (Inspector Panel)**：支持在网页端直接修改 Shot 的景别、运镜、动作、提示词。

#### 4. 测试与工程质量
- [x] **全自动化测试套件**：涵盖对齐算法、音频特征分析、导演引擎、Pydantic 契约、本地 API 路由与字幕生成，全量 **49 项单元测试通过**。
- [x] **纯前端兼容性**：消除全局变量冲突，全面通过 Node.js 语法校验。

---

## 第三部分：下一步研发路线图 (Roadmap)

### 近期计划 (Next 2-4 Weeks)
1. **对接视频生成模型 API (Model Router)**：
   - 编写统一抽象基类 `VideoProvider`。
   - 接入第一批生视频服务（首选：Google Veo 3.1 / 字节跳动 Seedance / 本地 Wan2.2 开源模型）。
2. **多 Take 候选与对比视图 (Takes Comparison)**：
   - 在分镜检视面板中展示一个镜头的多个生成候选（Take A, Take B, Take C）。
   - 支持导演打分、A/B 播放对比与一键选定最终素材。
3. **NLE 剪辑时间轴拖拽交互**：
   - 在底部时间轴上支持拖拽切刀点，自由拉长或缩短分镜时长并自动磁吸相邻镜头。

### 中远期规划 (Next 2-3 Months)
1. **多模态角色一致性控制 (LoRA / FaceID / Reference Image)**：
   - 在 Visual Bible 中生成角色三视图，并在调用视频生成时作为第一帧或角色参考图自动注入。
2. **高级动态特效渲染 (PyonFX / WebGL Shader)**：
   - 在现有 Apple Music / KTV 字幕基础上，引入光效粒子、笔画手写动画与歌词重力消散效果。
3. **云端 SaaS 多任务调度部署**：
   - 统一封装为 Docker 镜像，支持云端异步任务排队与批量生成。
