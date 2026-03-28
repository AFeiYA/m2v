# Auto-Karaoke MV Generator — 开发计划

> **版本:** v1.0 | **日期:** 2026-03-28 | **状态:** 规划中

---

## 一、项目目标

将 Suno 生成的 MP3 音频 + 本地歌词文件（TXT/LRC），通过全自动 Python 管线，产出具有**专业卡拉OK逐字变色效果**、背景画面与音乐节奏匹配的宣传视频（MP4）。

---

## 二、技术栈评估与选型（2026.03 版）

### 2.1 最终技术选型

| 维度 | 选定组件 | 版本 | 选型理由 |
|------|---------|------|---------|
| 人声分离 | **Demucs v4** (`htdemucs_ft`) | v4 (锁定) | SDR 9.0dB SOTA，`--two-stems=vocals` 直出干声/伴奏。⚠️ 已归档但模型稳定可用 |
| 对齐引擎 | **WhisperX** | v3.8.4+ | 20.9k⭐，活跃维护，wav2vec2 phoneme 级对齐精度最高 |
| ASR 模型 | **Whisper large-v3** | — | WhisperX 底层调用，多语言支持好 |
| 字幕格式 | **ASS** (`\k` 标签) | — | 唯一支持卡拉OK变色的通用字幕格式 |
| 字幕特效 | **PyonFX** (可选) | v0.11.0 | Python ASS KFX 库，用于高级动画 |
| 节奏检测 | **Librosa** | v0.11.0 | 稳定维护，onset_detect / beat_track |
| 视频合成 | **FFmpeg** (主) | 7.x | 纯命令行 `-vf subtitles=`，性能最优 |
| 视频合成 | **MoviePy v2** (可选) | v2.2.1 | 仅在需要逐帧 Python 特效时引入 |
| 歌词预处理 | **cn2an** + **OpenCC** | — | 数字转文字 + 繁简转换 |
| 容器化 | **Docker** + NVIDIA Container Toolkit | — | 基础镜像 `nvidia/cuda:12.8.0-runtime-ubuntu22.04` |
| 语言 | **Python 3.11+** | — | 生态兼容性最佳 |

### 2.2 被否决的方案

| 组件 | 否决理由 |
|------|---------|
| whisper-timestamped | DTW on attention weights 精度低于 WhisperX phoneme 对齐；AGPL-3.0 传染协议 |
| Montreal Forced Aligner | 依赖 Kaldi/Conda，安装复杂，面向语音非歌唱 |
| NUS AutoLyrixAlign | 6年未更新，代码托管在 Google Drive，不可生产使用 |
| MoviePy 作为主合成器 | 逐帧处理比纯 FFmpeg 慢 10x+，本项目核心合成需求一条 FFmpeg 命令即可 |

### 2.3 关键风险登记

| # | 风险 | 严重度 | 触发条件 | 缓解措施 |
|---|------|--------|---------|---------|
| R1 | WhisperX 对歌唱对齐偏差 | 🔴 高 | 拖音/颤音/和声段落 | Demucs 干声提取 + forced alignment（非自由转写）+ fallback 均分时长 |
| R2 | 中文字级对齐边界模糊 | 🟡 中 | 中文无空格分词 | 使用中文 wav2vec2 模型，按字符而非词对齐 |
| R3 | 歌词含数字/符号无法对齐 | 🟡 中 | 歌词中出现 "2024"、"$" 等 | 歌词预处理管线：cn2an 数字转文字、去除不可发音符号 |
| R4 | Demucs 已归档停更 | 🟡 中 | 遇到模型 bug 无人修 | 锁定版本 + 备选 `audio-separator` 库（封装 MDX-Net） |
| R5 | GPU 显存不足 | 🟢 低 | 显存 < 6GB | WhisperX 支持 `compute_type="int8"`；Demucs 支持 CPU 回退 |

---

## 三、系统架构

### 3.1 管线流程图

```
输入: song.mp3 + song.txt (或 .lrc)
  │
  ▼
┌─────────────────────────────────────┐
│  Module 1: Lyrics Preprocessor      │
│  歌词预处理器                        │
│  · 读取 TXT/LRC                     │
│  · 数字→文字 (cn2an)                │
│  · 繁→简 (OpenCC, 可选)             │
│  · 去除不可发音符号                   │
│  → cleaned_lyrics.txt               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Module 2: Vocal Extractor          │
│  人声分离器                          │
│  · Demucs v4 htdemucs_ft            │
│  · --two-stems=vocals               │
│  → vocals.wav + instrumental.wav    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Module 3: Alignment Engine         │
│  词级对齐引擎                        │
│  · WhisperX large-v3                │
│  · Forced alignment (非自由转写)     │
│  · 输入: vocals.wav + cleaned_lyrics │
│  → word_timestamps.json             │
│    [{word, start, end}, ...]        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Module 4: Subtitle Generator       │
│  ASS 卡拉OK字幕生成器               │
│  · JSON → ASS \k 标签               │
│  · 样式定义 (字体/颜色/描边/位置)    │
│  · 可选: Librosa 节奏点 → \t 动画   │
│  → karaoke.ass                      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Module 5: Video Compositor         │
│  视频合成器                          │
│  · FFmpeg: 背景 + 音频 + ASS → MP4  │
│  · 支持: 静态图循环 / 视频背景       │
│  · 编码: libx264 crf 18 + aac       │
│  → final_video.mp4                  │
└─────────────────────────────────────┘
```

### 3.2 目录结构

```
m2v/
├── README.md
├── dev-plan.md              # 本文档
├── music2video.md           # 原始方案
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml           # 项目依赖 (Poetry/PDM)
├── src/
│   ├── __init__.py
│   ├── main.py              # CLI 入口 & 批量处理调度
│   ├── config.py            # 全局配置 (模型路径/默认样式/输出参数)
│   ├── preprocessor.py      # Module 1: 歌词预处理
│   ├── separator.py         # Module 2: Demucs 人声分离
│   ├── aligner.py           # Module 3: WhisperX 词级对齐
│   ├── subtitle.py          # Module 4: ASS 字幕生成
│   ├── compositor.py        # Module 5: FFmpeg 视频合成
│   └── utils.py             # 工具函数 (文件发现/格式转换/日志)
├── assets/
│   └── default_bg.jpg       # 默认背景图
├── templates/
│   └── default_style.ass    # ASS 样式模板
├── tests/
│   ├── test_preprocessor.py
│   ├── test_aligner.py
│   ├── test_subtitle.py
│   └── fixtures/            # 测试用音频/歌词片段
├── input/                   # 用户放置 mp3 + txt 的目录
└── output/                  # 生成结果目录
```

---

## 四、模块详细设计

### 4.1 Module 1: 歌词预处理器 (`preprocessor.py`)

**输入:** `.txt` 或 `.lrc` 文件路径  
**输出:** 清洗后的纯文本（按行分段）

| 步骤 | 操作 | 依赖 |
|------|------|------|
| 1 | 检测文件编码 (UTF-8/GBK) | `chardet` |
| 2 | LRC 格式解析：提取纯文本，保留行级时间戳（如有） | 正则 `\[\d{2}:\d{2}\.\d{2}\]` |
| 3 | 数字转中文文字 | `cn2an` (`"2024年"` → `"二零二四年"`) |
| 4 | 繁体转简体（可配置） | `OpenCC` (`s2t` / `t2s`) |
| 5 | 去除不可发音符号 | 正则：保留 `\w`、中文、基本标点 |
| 6 | 输出按行分割的纯文本列表 | — |

### 4.2 Module 2: 人声分离器 (`separator.py`)

**输入:** MP3 文件路径  
**输出:** `vocals.wav` + `instrumental.wav`

```python
# 核心调用
def separate_vocals(mp3_path: str, output_dir: str) -> tuple[str, str]:
    """
    使用 Demucs v4 htdemucs_ft 分离人声和伴奏。
    --two-stems=vocals 模式，仅输出 vocals + no_vocals。
    返回 (vocals_path, instrumental_path)。
    """
```

**关键参数:**
- 模型: `htdemucs_ft` (fine-tuned，质量最高)
- 模式: `--two-stems=vocals`
- 输出格式: WAV 16bit 44.1kHz
- GPU 不足时自动回退 CPU (`--device cpu`)

### 4.3 Module 3: 词级对齐引擎 (`aligner.py`)

**输入:** `vocals.wav` + 清洗后歌词文本  
**输出:** `word_timestamps.json`

```python
def align_lyrics(vocals_path: str, lyrics_lines: list[str], language: str = "zh") -> list[dict]:
    """
    使用 WhisperX forced alignment 获取词级时间戳。
    返回: [{"word": "我", "start": 1.20, "end": 1.55}, ...]
    """
```

**关键逻辑:**
1. 加载 Whisper `large-v3` 模型，先做一次转写获取 segment 时间范围
2. 加载语言对应的 wav2vec2 对齐模型（中文: `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`）
3. 调用 `whisperx.align()` 传入原始歌词文本（forced alignment，非自由转写）
4. **Fallback 策略:** 若某行对齐失败（无 word_segments 返回），按该行总时长均分给每个字符

**输出格式:**
```json
{
  "lines": [
    {
      "text": "我站在风中等你",
      "start": 12.50,
      "end": 15.80,
      "words": [
        {"word": "我", "start": 12.50, "end": 12.85},
        {"word": "站", "start": 12.85, "end": 13.20},
        {"word": "在", "start": 13.20, "end": 13.50},
        {"word": "风", "start": 13.50, "end": 13.90},
        {"word": "中", "start": 13.90, "end": 14.25},
        {"word": "等", "start": 14.25, "end": 14.80},
        {"word": "你", "start": 14.80, "end": 15.80}
      ]
    }
  ]
}
```

### 4.4 Module 4: ASS 字幕生成器 (`subtitle.py`)

**输入:** `word_timestamps.json` + 样式配置  
**输出:** `karaoke.ass`

**ASS 卡拉OK核心语法:**
```
{\k<centiseconds>}字符
```
其中 `\k50` 表示该字符变色持续 500ms（单位：厘秒）。

**字幕样式模板:**
```ini
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,思源黑体,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,30,30,40,1
```

| 颜色参数 | 含义 | 默认值 |
|---------|------|--------|
| PrimaryColour | 变色前（未唱） | 白色 `&H00FFFFFF` |
| SecondaryColour | 变色后（已唱） | 黄色 `&H0000FFFF` |
| OutlineColour | 描边 | 黑色 `&H00000000` |
| BackColour | 阴影 | 半透明黑 `&H80000000` |

**可选增强 — 节奏同步动画:**
```python
def add_beat_effects(ass_content: str, audio_path: str) -> str:
    """
    使用 Librosa 检测鼓点，在 beat 位置插入 ASS \t 缩放动画。
    效果: 字幕在鼓点处微微放大再回缩，产生节奏感。
    """
```

### 4.5 Module 5: 视频合成器 (`compositor.py`)

**输入:** 背景素材 + 原始音频 + `karaoke.ass`  
**输出:** `final_video.mp4`

**模式 A — 静态图片背景:**
```bash
ffmpeg -loop 1 -i background.jpg -i original.mp3 \
  -vf "subtitles=karaoke.ass:force_style='Fontsize=48'" \
  -c:v libx264 -tune stillimage -crf 18 \
  -c:a aac -b:a 192k \
  -shortest -pix_fmt yuv420p \
  output.mp4
```

**模式 B — 视频背景 (循环):**
```bash
ffmpeg -stream_loop -1 -i background.mp4 -i original.mp3 \
  -vf "subtitles=karaoke.ass" \
  -c:v libx264 -crf 18 \
  -c:a aac -b:a 192k \
  -shortest -pix_fmt yuv420p \
  output.mp4
```

**输出规格:**
- 分辨率: 1920×1080 (可配置)
- 编码: H.264 CRF 18 (视觉无损)
- 音频: AAC 192kbps
- 格式: MP4 (faststart)

---

## 五、开发计划（分阶段）

### Phase 1: MVP — 核心管线 (Week 1-2)

> **目标:** 能跑通 MP3+TXT → 卡拉OK MP4 的完整流程

| # | 任务 | 预估 | 交付物 | 验收标准 |
|---|------|------|--------|---------|
| 1.1 | Docker 环境搭建 | 2d | `Dockerfile` + `docker-compose.yml` | `nvidia-smi` 可用，WhisperX/Demucs 可 import |
| 1.2 | 歌词预处理器 | 1d | `preprocessor.py` + 单元测试 | TXT/LRC 正确解析，数字转文字通过 |
| 1.3 | Demucs 人声分离封装 | 1d | `separator.py` + 单元测试 | 输入 MP3 → 输出 vocals.wav + instrumental.wav |
| 1.4 | WhisperX 词级对齐封装 | 2d | `aligner.py` + 单元测试 | 中文歌曲词级 JSON 输出，每字有 start/end |
| 1.5 | ASS 卡拉OK字幕生成 | 2d | `subtitle.py` + 样式模板 | 生成的 .ass 在 mpv/FFmpeg 中正确渲染变色 |
| 1.6 | FFmpeg 视频合成 | 1d | `compositor.py` | 静态图背景 + ASS 字幕 → 完整 MP4 |
| 1.7 | CLI 入口 & 批量处理 | 1d | `main.py` | `python main.py --input ./input --output ./output` 跑通 |

### Phase 2: 质量优化 (Week 3)

> **目标:** 对齐精度和视觉效果达到可发布水平

| # | 任务 | 预估 | 说明 |
|---|------|------|------|
| 2.1 | 对齐 Fallback 策略 | 1d | 对齐失败行 → 均分时长；异常检测（如某字 duration < 50ms） |
| 2.2 | Librosa 节奏检测集成 | 1d | onset_detect → beat 时间点 JSON |
| 2.3 | 节奏同步字幕动画 | 1d | ASS `\t` 标签实现 beat 处缩放脉冲 |
| 2.4 | 多样式支持 | 1d | 提供 3-5 套预设卡拉OK样式 (颜色/字体/位置) |
| 2.5 | 视频背景循环模式 | 0.5d | 支持视频素材作为背景循环播放 |
| 2.6 | 端到端测试 | 0.5d | 3首不同风格歌曲的完整测试 |

### Phase 3: 进阶功能 (Week 4+)

> **目标:** 可选的增值功能

| # | 任务 | 优先级 | 说明 |
|---|------|--------|------|
| 3.1 | 音节级拆分 | P1 | 中文 `pypinyin`，英文 `pyphen`，提升节奏感 |
| 3.2 | 双语字幕 | P2 | DeepL API 翻译 + 双行 ASS 布局 |
| 3.3 | AI 背景视频生成 | P3 | SVD / Luma API 根据歌词生成循环背景 |
| 3.4 | Web UI | P3 | Gradio/Streamlit 简易界面，上传 → 下载 |
| 3.5 | 手动校正界面 | P2 | 对齐结果可视化 + 拖拽微调时间戳 |

---

## 六、Docker 环境规格

```dockerfile
# 基础镜像
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

# 系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python 环境
RUN pip install --no-cache-dir \
    torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128 \
    whisperx>=3.8.4 \
    demucs>=4.0.0 \
    librosa>=0.11.0 \
    cn2an \
    opencc-python-reimplemented \
    chardet

WORKDIR /app
COPY . .
ENTRYPOINT ["python", "src/main.py"]
```

**硬件要求:**
| 配置 | 最低 | 推荐 |
|------|------|------|
| GPU | NVIDIA 6GB VRAM | NVIDIA 8GB+ VRAM |
| RAM | 8GB | 16GB |
| 磁盘 | 10GB (模型缓存) | 20GB |
| CUDA | 12.x | 12.8 |

---

## 七、参考项目

| 项目 | 星标 | 参考价值 |
|------|------|---------|
| [karaoke-gen](https://github.com/nomadkaraoke/karaoke-gen) | 111⭐ / 446 releases | 最成熟的开源卡拉OK生成器；歌词校正流程、ASS 输出格式 |
| [UltraSinger](https://github.com/rakuri255/UltraSinger) | 492⭐ | 使用 Demucs + WhisperX 同栈；音节拆分逻辑 |
| [PyonFX](https://github.com/CoffeeStraw/PyonFX) | 179⭐ | Python ASS 特效库；高级卡拉OK动画参考 |
| [WhisperX](https://github.com/m-bain/whisperX) | 20.9k⭐ | 对齐引擎文档与 API 用法 |

---

## 八、验收标准（MVP）

- [ ] 输入：1 首 Suno MP3 (3-5分钟) + 对应中文歌词 TXT
- [ ] 自动完成人声分离（< 2分钟，GPU）
- [ ] 自动完成词级对齐（< 1分钟，GPU）
- [ ] 生成 ASS 字幕，在 mpv 播放器中验证变色效果正确
- [ ] 合成 1080p MP4 视频，卡拉OK变色与歌唱同步
- [ ] 全流程一条命令完成，无需人工干预
- [ ] Docker 容器内可复现运行
