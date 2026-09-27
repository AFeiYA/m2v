# AI 特效歌词视频 — 完整开发文档 v1.0

> **定位**: 本文档是 `ai-effects-video-design.md` 设计稿的**工程落地版**，将设计概念转化为可编码、可测试、可分阶段交付的开发计划。  
> **重点补充**: 字体性格系统、智能转场系统、色彩统一管线 — 基于用户反馈新增的三大关键模块。

---

## 目录

1. [建议评估](#一建议评估)
2. [系统架构总览](#二系统架构总览)
3. [模块一：LLM 歌词分析引擎](#三模块一llm-歌词分析引擎)
4. [模块二：字体性格系统 ★ 新增](#四模块二字体性格系统--新增)
5. [模块三：AI 背景图生成](#五模块三ai-背景图生成)
6. [模块四：色彩统一管线 ★ 新增](#六模块四色彩统一管线--新增)
7. [模块五：智能转场系统 ★ 新增](#七模块五智能转场系统--新增)
8. [模块六：特效文字渲染](#八模块六特效文字渲染)
9. [模块七：FFmpeg 多层合成](#九模块七ffmpeg-多层合成)
10. [核心数据结构](#十核心数据结构)
11. [开发阶段与排期](#十一开发阶段与排期)
12. [文件清单与依赖](#十二文件清单与依赖)
13. [测试策略](#十三测试策略)
14. [风险与备选方案](#十四风险与备选方案)

---

## 一、建议评估

用户提出三条改进建议，逐条分析其合理性与实施方案：

### 1.1 字体性格系统（font_style 标签 + LLM 推荐）

| 维度 | 评估 |
|------|------|
| **合理性** | ⭐⭐⭐⭐⭐ 极其合理 |
| **理由** | 字体是视觉层级中仅次于颜色的第二强信息。宋体 = 古典/诗意，黑体 = 现代/力量，手写体 = 亲切/文艺，衬线体 = 优雅/正式。当前 `SubtitleConfig.font_name` 仅支持全局单一字体，无法根据歌曲情绪切换，导致所有歌都用"思源黑体"，视觉趋同。 |
| **现有差距** | `config.py` 中 `SubtitleConfig` 只有 `font_name: str = "思源黑体"` 和 `font_size: int = 56`，无法按段落/情绪切换字体。设计稿 4 个特效预设 (clean_minimal / neon_glow / cinematic / handwritten) 隐含了字体倾向，但未显式定义字体映射。 |
| **实施难度** | 🟢 低。核心是一个 mood → font 映射表 + LLM 输出字段扩展。ASS 格式原生支持 `\fn` 标签做行内字体切换。 |
| **结论** | ✅ 采纳。新增 `FontPersonality` 系统，在 LLM 分析阶段输出 `font_style` 标签，映射到具体字体族。 |

### 1.2 智能转场（FFmpeg xfade + 音频能量峰值触发）

| 维度 | 评估 |
|------|------|
| **合理性** | ⭐⭐⭐⭐⭐ 极其合理 |
| **理由** | 当前设计中背景图切换是硬切（段落 A 的最后一帧 → 段落 B 的第一帧），视觉上生硬不自然。专业 MV 在段落过渡时一定有转场动画（叠化/闪白/径向模糊等）。将转场时机绑定到音频能量峰值（如鼓点/重拍），可以让视觉切换与听觉节奏同步，产生"MV 感"。 |
| **现有差距** | `compositor.py` 目前只支持单一背景（图片/视频/纯黑），没有多背景拼接逻辑。设计稿优先级表中 P1 提到"交叉淡化"，但无具体实现方案。 |
| **实施难度** | 🟡 中。FFmpeg `xfade` 滤镜本身简单，但多段背景的 filter_complex 链会较复杂。音频能量检测可复用现有 Librosa（`subtitle.py` 已有 `_detect_beats()`）。 |
| **结论** | ✅ 采纳。新增 `TransitionEngine`，基于 Librosa 能量分析自动选择转场类型和时机，生成 FFmpeg xfade 滤镜链。 |

### 1.3 色彩统一管线（LUT / FFmpeg 色偏处理）

| 维度 | 评估 |
|------|------|
| **合理性** | ⭐⭐⭐⭐⭐ 极其合理 |
| **理由** | AI 图像生成（SDXL / DALL-E 3 / Flux）的最大痛点之一就是**色调一致性**。即使提示词包含相同的 color_palette，不同种子生成的图片在色温、饱和度、对比度上仍会有差异。连续播放时，观众会感知到"跳色"，破坏整体视觉统一感。 |
| **现有差距** | 整个管线没有任何色彩后处理环节。`compositor.py` 的 FFmpeg 命令只有 `scale` + `pad` + `subtitles`，无 color grading 滤镜。 |
| **实施难度** | 🟢 低-中。FFmpeg 内置 `colorbalance`、`eq`、`curves`、`lut3d` 滤镜，无需额外依赖。难点在于如何**自动判断**色偏方向并选择合适的 LUT。 |
| **结论** | ✅ 采纳。新增 `ColorUnifier` 模块，提供两级方案：(1) 预制 LUT 按 vibe 标签选择；(2) 统计分析各图直方图后自动校正到统一色调。 |

### 1.4 总结

三条建议均采纳。它们分别补强了**文字层**（字体）、**背景层**（转场 + 色彩）的视觉质量，与现有设计的 4 层架构完美契合：

```
Layer 4 (最上): 特效文字   ← 字体性格系统 加持
Layer 3:        氛围粒子
Layer 2:        AI 背景    ← 色彩统一 + 智能转场 加持
Layer 1 (最下): 纯色/渐变底板
```

---

## 二、系统架构总览

### 2.1 完整管线流程

```
alignment.json (编辑后) + audio.mp3
          │
          ▼
┌─────────────────────────────────────┐
│  Step 1: LLM 歌词分析引擎           │
│  - 情绪/氛围/色板/节奏分析            │
│  - 段落切分 + 场景描述               │
│  - ★ 字体性格推荐                   │
│  - ★ 转场类型建议                   │
│  输出: SongAnalysis                  │
└───────────┬─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Step 2: AI 背景图生成              │
│  - SDXL / DALL-E 3 / Flux          │
│  - 每段落生成 1 张场景图             │
│  输出: scenes/para_XX.png           │
└───────────┬─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Step 3: ★ 色彩统一管线             │
│  - 直方图分析 → 参考帧选择           │
│  - LUT 映射 / 自动色彩校正           │
│  - 饱和度/对比度/色温标准化          │
│  输出: scenes/para_XX_graded.png    │
└───────────┬─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Step 4: Ken Burns 动画             │
│  - 静态图 → 慢推/慢拉/平移视频片段  │
│  输出: scenes/para_XX.mp4           │
└───────────┬─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Step 5: ★ 智能转场 + 背景拼接      │
│  - 音频能量峰值检测                  │
│  - FFmpeg xfade 滤镜链构建          │
│  - 转场类型自动选择                  │
│  输出: background_full.mp4          │
└───────────┬─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Step 6: 特效文字渲染               │
│  - ★ 字体性格映射 → ASS \fn 标签   │
│  - PyonFX 高级特效模板              │
│  - \k 卡拉OK + \t 动画             │
│  输出: effects.ass                  │
└───────────┬─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Step 7: FFmpeg 多层合成            │
│  - background_full.mp4 (背景)       │
│  - atmosphere.mp4 (氛围层, 可选)     │
│  - effects.ass (字幕特效)            │
│  - audio.mp3 (音频)                 │
│  输出: final_output.mp4             │
└─────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
config.py
    ├── scene_gen.py        (LLM 分析 + 图片生成)
    │       │
    │       ▼
    │   font_system.py      (★ 字体性格系统)
    │       │
    │       ▼
    │   color_unifier.py    (★ 色彩统一管线)
    │       │
    │       ▼
    │   video_bg.py         (Ken Burns + 拼接)
    │       │
    │       ▼
    │   transition.py       (★ 智能转场系统)
    │
    ├── effects.py          (特效文字渲染)
    │
    ├── atmosphere.py       (氛围粒子, 可选)
    │
    └── fx_compositor.py    (FFmpeg 多层合成)
```

---

## 三、模块一：LLM 歌词分析引擎

### 3.1 文件: `src/scene_gen.py`

### 3.2 职责

接收 alignment JSON + 歌词文本，调用 LLM (GPT-4o / Claude) 进行深度分析，输出结构化的歌曲理解数据。

### 3.3 LLM Prompt 设计

```python
ANALYSIS_SYSTEM_PROMPT = """你是一位专业的音乐可视化导演。
分析给定的歌词，输出 JSON 格式的视觉方案。

你需要分析：
1. 整体情绪 (mood): 用 3-5 个英文关键词描述
2. 音乐流派 (genre): 具体流派
3. 色板 (color_palette): 4-6 个十六进制颜色，构成统一的视觉色调
4. ★ 字体性格 (font_style): 从以下选项中选择最契合歌曲气质的字体风格：
   - "serif"      (宋体/衬线体 — 古典、诗意、怀旧)
   - "sans"       (黑体/无衬线 — 现代、有力、干净)
   - "handwritten" (手写体 — 文艺、亲切、温暖)
   - "artistic"   (艺术字体 — 前卫、实验、独特)
   - "retro"      (复古字体 — 怀旧、港台、80年代)
5. ★ 建议转场风格 (transition_style): 
   - "dissolve"   (叠化 — 抒情、缓慢、柔和)
   - "flash"      (闪白 — 高能、节拍、冲击)
   - "wipe"       (擦除 — 叙事、线性、推进)
   - "fade_black" (渐黑 — 沉重、黑暗、分割)
   - "radial"     (径向 — 梦幻、发散、眩晕)
6. ★ 色彩基调 (color_temperature):
   - "warm"   (暖调 — 温馨/热情)
   - "cool"   (冷调 — 忧伤/深邃)
   - "neutral" (中性 — 自然/清晰)
7. 每个段落的场景描述 (scene descriptions)

输出必须是严格的 JSON。"""

ANALYSIS_USER_TEMPLATE = """歌曲: {title}
歌词:
{lyrics}

段落划分 (基于时间间隔):
{paragraph_info}

请输出完整的视觉分析 JSON。"""
```

### 3.4 LLM 输出结构

```json
{
  "mood": ["melancholic", "dark", "introspective", "lonely", "fearful"],
  "genre": "dark pop",
  "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560", "#533483"],
  "font_style": "sans",
  "font_weight": "bold",
  "transition_style": "flash",
  "color_temperature": "cool",
  "paragraphs": [
    {
      "id": 0,
      "mood_shift": "tense, fearful",
      "scene_description": "Dark urban alleyway at night, wet pavement reflecting neon signs, long shadows stretching across cracked concrete walls",
      "energy_level": 0.4,
      "suggested_transition_to_next": "dissolve"
    },
    {
      "id": 1,
      "mood_shift": "explosive, angry",
      "scene_description": "Shattered mirror fragments floating in dark void, each shard reflecting distorted city lights",
      "energy_level": 0.8,
      "suggested_transition_to_next": "flash"
    }
  ]
}
```

### 3.5 段落切分逻辑

```python
def split_paragraphs(
    alignment: dict,
    gap_threshold: float = 3.0,
    min_lines: int = 2,
    max_lines: int = 6,
) -> list[Paragraph]:
    """
    基于时间间隔自动切分段落。
    
    规则:
    1. 两行歌词间隔 > gap_threshold 秒 → 切分
    2. 单段不少于 min_lines 行
    3. 单段不超过 max_lines 行（超过强制切分）
    
    示例: 害怕的人 总共 ~40 行歌词 → 约 8 个段落
    """
    lines = alignment["lines"]
    paragraphs = []
    current_lines = []
    
    for i, line in enumerate(lines):
        current_lines.append(line)
        
        is_last = (i == len(lines) - 1)
        next_gap = (lines[i + 1]["start"] - line["end"]) if not is_last else 999
        
        should_split = (
            is_last
            or next_gap > gap_threshold
            or len(current_lines) >= max_lines
        )
        
        if should_split and len(current_lines) >= min_lines:
            paragraphs.append(Paragraph(
                id=len(paragraphs),
                lines=current_lines.copy(),
                start=current_lines[0]["start"],
                end=current_lines[-1]["end"],
            ))
            current_lines.clear()
    
    # 处理剩余行（不足 min_lines 的合并到上一段）
    if current_lines and paragraphs:
        paragraphs[-1].lines.extend(current_lines)
        paragraphs[-1].end = current_lines[-1]["end"]
    
    return paragraphs
```

### 3.6 场景提示词生成

```python
SCENE_PROMPT_TEMPLATE = """Based on this song analysis and paragraph context, 
generate a detailed image generation prompt.

Song mood: {mood}
Color palette: {colors}
Paragraph mood: {para_mood}  
Paragraph lyrics: {para_text}
Scene description: {scene_desc}

Requirements:
- Cinematic 16:9 composition
- No text, no letters, no words in the image
- Color palette must match: {colors}
- Style: {style_hint}
- Atmosphere: {atmosphere}

Output ONLY the image generation prompt, nothing else."""
```

---

## 四、模块二：字体性格系统 ★ 新增

### 4.1 文件: `src/font_system.py`

### 4.2 设计原理

字体选择对视觉情绪的影响仅次于颜色。当前系统全局使用"思源黑体"，无论歌曲是古风还是电子乐，视觉上毫无区分。

**字体 = 歌曲的视觉声线**：
- 宋体/衬线体 → 古典、诗意、有文化底蕴（类似于低沉的大提琴）
- 黑体/无衬线 → 现代、干净、有力量感（类似于电子合成器）
- 手写体 → 亲切、温暖、个人化（类似于木吉他弹唱）
- 艺术体 → 实验、前卫、视觉冲击（类似于 Glitch 电子）
- 复古体 → 怀旧、港台风、年代感（类似于老式卡带）

### 4.3 数据结构

```python
from dataclasses import dataclass, field
from enum import Enum


class FontStyle(str, Enum):
    """字体性格枚举"""
    SERIF = "serif"            # 宋体/衬线
    SANS = "sans"              # 黑体/无衬线
    HANDWRITTEN = "handwritten" # 手写体
    ARTISTIC = "artistic"       # 艺术字体
    RETRO = "retro"            # 复古字体


@dataclass
class FontProfile:
    """一种字体性格的完整定义"""
    style: FontStyle
    # 主字体 (歌词正文)
    primary_font: str
    # 备选字体 (主字体不可用时)
    fallback_fonts: list[str]
    # 标题/强调字体 (如歌名、高潮段)
    accent_font: str
    # 推荐字号比例 (相对于基准 font_size)
    size_scale: float = 1.0
    # 推荐字重
    bold: bool = False
    # 推荐字间距 (ASS Spacing 值)
    spacing: int = 2
    # 推荐描边粗细
    outline: float = 3.0
    # 推荐阴影距离
    shadow: float = 1.0


# ──────────────────────────────────────
# 预设字体配置
# ──────────────────────────────────────

FONT_PROFILES: dict[FontStyle, FontProfile] = {
    FontStyle.SERIF: FontProfile(
        style=FontStyle.SERIF,
        primary_font="思源宋体",
        fallback_fonts=["Noto Serif CJK SC", "Source Han Serif SC", "SimSun"],
        accent_font="华文行楷",
        size_scale=1.0,
        bold=False,
        spacing=3,
        outline=2.5,
        shadow=1.5,
    ),
    FontStyle.SANS: FontProfile(
        style=FontStyle.SANS,
        primary_font="思源黑体",
        fallback_fonts=["Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei"],
        accent_font="思源黑体 Bold",
        size_scale=1.0,
        bold=True,
        spacing=2,
        outline=3.0,
        shadow=1.0,
    ),
    FontStyle.HANDWRITTEN: FontProfile(
        style=FontStyle.HANDWRITTEN,
        primary_font="汉仪润圆",
        fallback_fonts=["方正手迹", "华文行楷", "Segoe Script"],
        accent_font="方正硬笔行书",
        size_scale=1.05,  # 手写体通常需要略大
        bold=False,
        spacing=1,
        outline=2.0,
        shadow=0.5,
    ),
    FontStyle.ARTISTIC: FontProfile(
        style=FontStyle.ARTISTIC,
        primary_font="造字工房悦黑",
        fallback_fonts=["方正综艺简体", "汉仪菱心体", "Impact"],
        accent_font="造字工房尚黑",
        size_scale=1.1,
        bold=True,
        spacing=4,
        outline=4.0,
        shadow=2.0,
    ),
    FontStyle.RETRO: FontProfile(
        style=FontStyle.RETRO,
        primary_font="方正北魏楷书",
        fallback_fonts=["华文隶书", "方正粗圆", "SimHei"],
        accent_font="方正粗圆简体",
        size_scale=1.0,
        bold=False,
        spacing=5,
        outline=3.5,
        shadow=2.0,
    ),
}
```

### 4.4 字体可用性检测

```python
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def get_system_fonts() -> set[str]:
    """获取系统已安装的字体列表"""
    fonts = set()
    try:
        # Windows: 使用 PowerShell
        result = subprocess.run(
            ["powershell", "-Command",
             "[System.Drawing.Text.InstalledFontCollection]::new().Families.Name"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            fonts = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except Exception:
        pass
    
    if not fonts:
        try:
            # Linux/macOS: fc-list
            result = subprocess.run(
                ["fc-list", "--format=%{family}\n"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    for name in line.split(","):
                        fonts.add(name.strip())
        except Exception:
            pass
    
    return fonts


def resolve_font(profile: FontProfile) -> str:
    """
    解析可用字体：优先主字体，不可用则依次尝试 fallback。
    
    Returns:
        实际可用的字体名称
    """
    system_fonts = get_system_fonts()
    
    # 如果无法获取系统字体列表，直接返回主字体（让 ASS 渲染器处理 fallback）
    if not system_fonts:
        return profile.primary_font
    
    # 优先主字体
    if profile.primary_font in system_fonts:
        return profile.primary_font
    
    # 尝试 fallback
    for font in profile.fallback_fonts:
        if font in system_fonts:
            return font
    
    # 都不可用，返回主字体（ASS 渲染器会使用默认字体）
    return profile.primary_font
```

### 4.5 ASS 字体集成

字体性格系统与 ASS 字幕的集成有两个层级：

#### 层级 1：全局字体（修改 Style 定义）

在 `generate_ass()` 中，根据 LLM 推荐的 `font_style` 修改 ASS 的 Style 行：

```python
def apply_font_to_style(style_line: str, profile: FontProfile) -> str:
    """
    修改 ASS Style 行中的字体相关属性。
    
    ASS Style Format:
    Style: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, 
           OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,
           ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, 
           Alignment, MarginL, MarginR, MarginV, Encoding
    """
    parts = style_line.split(",")
    if len(parts) < 23:
        return style_line
    
    resolved_font = resolve_font(profile)
    
    parts[1] = resolved_font                          # Fontname
    parts[7] = "-1" if profile.bold else "0"           # Bold
    parts[13] = str(profile.spacing)                   # Spacing
    parts[16] = f"{profile.outline:.1f}"               # Outline
    parts[17] = f"{profile.shadow:.1f}"                # Shadow
    
    return ",".join(parts)
```

#### 层级 2：段落级字体切换（ASS `\fn` 内联标签）

当歌曲有明显的情绪转折时（如前奏低沉 → 副歌爆发），可以在段落间切换字体：

```python
def create_dialogue_with_font(
    line: AlignedLine,
    paragraph_font: str | None,
    base_config: SubtitleConfig,
) -> str:
    """
    生成带字体切换的 Dialogue 行。
    
    如果段落字体与全局字体不同，在行首插入 \fn 标签。
    """
    start_time = seconds_to_ass_time(line.start)
    end_time = seconds_to_ass_time(line.end)
    
    # 字体切换前缀
    font_prefix = ""
    if paragraph_font and paragraph_font != base_config.font_name:
        font_prefix = f"{{\\fn{paragraph_font}}}"
    
    # 构建卡拉OK文本
    karaoke_text = font_prefix
    for word in line.words:
        duration_cs = seconds_to_centiseconds(word.end - word.start)
        karaoke_text += f"{{\\k{duration_cs}}}{word.word}"
    
    return f"Dialogue: 0,{start_time},{end_time},Karaoke,,0,0,0,,{karaoke_text}"
```

### 4.6 LLM → 字体映射流程

```
LLM 输出 font_style: "handwritten"
        │
        ▼
FONT_PROFILES["handwritten"]
  → primary: "汉仪润圆"
  → fallback: ["方正手迹", "华文行楷", ...]
        │
        ▼
resolve_font() → 检测系统安装字体
  → 返回: "华文行楷" (如果"汉仪润圆"未安装)
        │
        ▼
apply_font_to_style() → 修改 ASS Style 行
  → Style: Karaoke,华文行楷,56,...
```

### 4.7 字体包管理（Docker 环境）

在 Docker 部署时需要预装字体：

```dockerfile
# Dockerfile 新增
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    && rm -rf /var/lib/apt/lists/*

# 自定义字体（需用户提供或从字体仓库下载）
COPY assets/fonts/ /usr/share/fonts/custom/
RUN fc-cache -fv
```

`assets/fonts/` 目录结构：

```
assets/fonts/
├── serif/
│   └── SourceHanSerif-Regular.ttc
├── sans/
│   └── SourceHanSans-Bold.ttc
├── handwritten/
│   └── (用户自行添加)
├── artistic/
│   └── (用户自行添加)
└── retro/
    └── (用户自行添加)
```

### 4.8 config.py 扩展

```python
@dataclass
class FxSubtitleConfig(SubtitleConfig):
    """特效字幕配置 — 扩展基础配置"""
    # 字体性格 (LLM 推荐或用户指定)
    font_style: FontStyle = FontStyle.SANS
    # 是否允许段落间字体切换
    allow_paragraph_font_switch: bool = False
    # 自定义字体映射覆盖 (font_style → font_name)
    font_overrides: dict[str, str] = field(default_factory=dict)
    # 高潮段使用 accent 字体
    use_accent_for_climax: bool = True
```

---

## 五、模块三：AI 背景图生成

### 5.1 文件: `src/scene_gen.py`（与 LLM 分析同文件）

### 5.2 支持的图像生成后端

| 后端 | API | 分辨率 | 速度 | 成本/张 | 适用场景 |
|------|-----|--------|------|---------|---------|
| SDXL (本地) | diffusers | 1024×1024 | 15-30s | $0 | 有 GPU，离线 |
| DALL-E 3 | OpenAI API | 1792×1024 | 5-10s | $0.04 | 云端，简单 |
| Flux.1 (本地) | ComfyUI API | 1024×1024 | 10-20s | $0 | 高质量，需 12GB+ |
| Midjourney | 非官方 API | 1456×816 | 30-60s | $0.01 | 最佳画质 |

### 5.3 图片生成封装

```python
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ImageGenRequest:
    """图片生成请求"""
    prompt: str
    negative_prompt: str = "text, words, letters, watermark, signature, blurry, low quality"
    width: int = 1920
    height: int = 1080
    seed: int | None = None       # 固定种子可提高一致性
    style_preset: str | None = None


@dataclass
class ImageGenResult:
    """图片生成结果"""
    path: Path
    width: int
    height: int
    seed_used: int
    generation_time: float        # 秒


class ImageGenerator(ABC):
    """图片生成器抽象基类"""
    
    @abstractmethod
    async def generate(self, request: ImageGenRequest) -> ImageGenResult:
        ...


class DallE3Generator(ImageGenerator):
    """DALL-E 3 后端"""
    
    def __init__(self, api_key: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
    
    async def generate(self, request: ImageGenRequest) -> ImageGenResult:
        import time, httpx
        from pathlib import Path
        
        t0 = time.time()
        response = await self.client.images.generate(
            model="dall-e-3",
            prompt=request.prompt,
            size="1792x1024",
            quality="hd",
            n=1,
        )
        
        image_url = response.data[0].url
        
        # 下载图片
        async with httpx.AsyncClient() as http:
            img_resp = await http.get(image_url)
            output_path = Path(f"scenes/para_{request.seed or 0:02d}.png")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_resp.content)
        
        return ImageGenResult(
            path=output_path,
            width=1792, height=1024,
            seed_used=0,
            generation_time=time.time() - t0,
        )


class SDXLLocalGenerator(ImageGenerator):
    """本地 SDXL 后端 (通过 diffusers)"""
    
    def __init__(self, model_path: str = "stabilityai/stable-diffusion-xl-base-1.0"):
        self.model_path = model_path
        self._pipe = None
    
    def _load_pipe(self):
        if self._pipe is None:
            import torch
            from diffusers import StableDiffusionXLPipeline
            self._pipe = StableDiffusionXLPipeline.from_pretrained(
                self.model_path, torch_dtype=torch.float16
            ).to("cuda")
    
    async def generate(self, request: ImageGenRequest) -> ImageGenResult:
        import asyncio, time
        self._load_pipe()
        
        t0 = time.time()
        
        # diffusers 是同步的，放到线程池
        def _gen():
            import torch
            generator = torch.Generator("cuda")
            if request.seed is not None:
                generator.manual_seed(request.seed)
            
            image = self._pipe(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                width=request.width,
                height=request.height,
                num_inference_steps=30,
                generator=generator,
            ).images[0]
            return image
        
        image = await asyncio.to_thread(_gen)
        
        output_path = Path(f"scenes/para_{request.seed or 0:02d}.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        
        return ImageGenResult(
            path=output_path,
            width=request.width, height=request.height,
            seed_used=request.seed or 0,
            generation_time=time.time() - t0,
        )
```

### 5.4 批量并行生成

```python
async def generate_all_backgrounds(
    paragraphs: list[Paragraph],
    analysis: SongAnalysis,
    generator: ImageGenerator,
    output_dir: Path,
    max_concurrent: int = 3,
) -> list[Path]:
    """
    并行生成所有段落的背景图。
    
    Args:
        max_concurrent: 最大并发数 (避免 API rate limit)
    """
    import asyncio
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def gen_one(para: Paragraph) -> Path:
        async with semaphore:
            request = ImageGenRequest(
                prompt=para.scene_prompt,
                seed=para.id * 1000,  # 固定种子基数
                width=1920,
                height=1080,
            )
            result = await generator.generate(request)
            # 移动到统一目录
            final_path = output_dir / f"para_{para.id:02d}.png"
            result.path.rename(final_path)
            return final_path
    
    tasks = [gen_one(para) for para in paragraphs]
    results = await asyncio.gather(*tasks)
    return list(results)
```

---

## 六、模块四：色彩统一管线 ★ 新增

### 6.1 文件: `src/color_unifier.py`

### 6.2 问题分析

AI 图像生成的色彩不一致问题的具体表现：

| 现象 | 原因 | 视觉影响 |
|------|------|---------|
| 色温跳变 | 不同提示词/种子导致冷暖色调差异 | 画面连续播放时"闪色" |
| 饱和度不均 | 部分图过于鲜艳，部分偏灰 | 视觉重心不稳定 |
| 对比度差异 | 部分图高对比（HDR 感），部分偏平 | 切换时亮度跳变 |
| 亮度不一致 | 有的图偏亮有的偏暗 | 与字幕可读性冲突 |

### 6.3 三级色彩校正方案

#### 方案 A：预制 LUT 映射（最简单，推荐 Phase A 使用）

根据 LLM 分析的 `color_temperature` 标签，选择预制的 3D LUT 文件：

```python
from pathlib import Path
from enum import Enum


class ColorTemperature(str, Enum):
    WARM = "warm"
    COOL = "cool"
    NEUTRAL = "neutral"


# 预制 LUT 映射
LUT_MAP: dict[ColorTemperature, str] = {
    ColorTemperature.WARM:    "assets/luts/warm_cinematic.cube",
    ColorTemperature.COOL:    "assets/luts/cool_moonlight.cube",
    ColorTemperature.NEUTRAL: "assets/luts/neutral_film.cube",
}

# 每种 vibe 更细粒度的 LUT
VIBE_LUT_MAP: dict[str, str] = {
    "neon_city":     "assets/luts/neon_teal_orange.cube",
    "dreamy":        "assets/luts/dreamy_pastel.cube",
    "dark_moody":    "assets/luts/dark_contrast.cube",
    "vintage":       "assets/luts/vintage_film_grain.cube",
    "cyberpunk":     "assets/luts/cyber_purple_green.cube",
    "nature_calm":   "assets/luts/nature_green.cube",
}


def apply_lut_ffmpeg(
    input_path: Path,
    output_path: Path,
    lut_path: str,
) -> list[str]:
    """
    生成 FFmpeg 命令：对单张图片应用 3D LUT。
    
    FFmpeg lut3d 滤镜支持 .cube / .3dl / .dat 格式。
    """
    return [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", f"lut3d='{lut_path}'",
        "-q:v", "2",  # JPEG 质量
        str(output_path),
    ]
```

**LUT 文件来源**：
- 免费 LUT 包：[RocketStock Free LUTs](https://www.rocketstock.com/free-after-effects-templates/35-free-luts-for-color-grading-videos/)
- 自制：用 DaVinci Resolve 导出 .cube 文件
- 在线生成器：[Photoshop/Lightroom 预设 → LUT 转换](https://lutcreator.com/)

#### 方案 B：自动直方图匹配（中等复杂度，Phase B）

选择一张"参考帧"（通常是第一段的背景图），将其他图片的色彩分布匹配到参考帧：

```python
import numpy as np
from PIL import Image
from pathlib import Path


def select_reference_image(image_paths: list[Path]) -> Path:
    """
    选择参考图：取所有图片中亮度直方图最"中性"的一张。
    
    "中性" = 直方图均值最接近 128，标准差适中 (40-80)。
    """
    best_path = image_paths[0]
    best_score = float('inf')
    
    for path in image_paths:
        img = np.array(Image.open(path).convert("L"))  # 灰度
        mean = img.mean()
        std = img.std()
        # 得分 = |均值-128| + |标准差-60|，越小越"中性"
        score = abs(mean - 128) + abs(std - 60)
        if score < best_score:
            best_score = score
            best_path = path
    
    return best_path


def compute_color_stats(image_path: Path) -> dict:
    """计算图片的 RGB 通道统计量"""
    img = np.array(Image.open(image_path).convert("RGB")).astype(np.float32)
    stats = {}
    for i, channel in enumerate(["R", "G", "B"]):
        stats[f"{channel}_mean"] = img[:, :, i].mean()
        stats[f"{channel}_std"] = img[:, :, i].std()
    stats["brightness"] = np.mean(img)
    return stats


def generate_color_correction_filter(
    source_stats: dict,
    target_stats: dict,
) -> str:
    """
    生成 FFmpeg colorbalance + eq 滤镜参数，将 source 校正到 target。
    
    原理：
    1. 亮度校正：通过 eq 的 brightness 参数
    2. 色温校正：通过 colorbalance 的 rs/gs/bs (shadow), rm/gm/bm (midtone), rh/gh/bh (highlight)
    3. 对比度校正：通过 eq 的 contrast 参数
    """
    filters = []
    
    # 亮度差异
    brightness_diff = target_stats["brightness"] - source_stats["brightness"]
    brightness_adj = brightness_diff / 255.0  # 归一化到 -1.0 ~ 1.0
    brightness_adj = max(-0.3, min(0.3, brightness_adj))  # 限制范围
    
    # 对比度差异 (基于标准差比值)
    source_contrast = (source_stats["R_std"] + source_stats["G_std"] + source_stats["B_std"]) / 3
    target_contrast = (target_stats["R_std"] + target_stats["G_std"] + target_stats["B_std"]) / 3
    contrast_ratio = target_contrast / max(source_contrast, 1.0)
    contrast_ratio = max(0.7, min(1.5, contrast_ratio))
    
    if abs(brightness_adj) > 0.02 or abs(contrast_ratio - 1.0) > 0.05:
        filters.append(f"eq=brightness={brightness_adj:.3f}:contrast={contrast_ratio:.3f}")
    
    # 色偏校正 (RGB 通道均值差异 → colorbalance)
    r_diff = (target_stats["R_mean"] - source_stats["R_mean"]) / 255.0
    g_diff = (target_stats["G_mean"] - source_stats["G_mean"]) / 255.0
    b_diff = (target_stats["B_mean"] - source_stats["B_mean"]) / 255.0
    
    # 限制校正幅度
    r_diff = max(-0.2, min(0.2, r_diff))
    g_diff = max(-0.2, min(0.2, g_diff))
    b_diff = max(-0.2, min(0.2, b_diff))
    
    if any(abs(d) > 0.02 for d in [r_diff, g_diff, b_diff]):
        filters.append(
            f"colorbalance="
            f"rs={r_diff:.3f}:gs={g_diff:.3f}:bs={b_diff:.3f}:"
            f"rm={r_diff*0.5:.3f}:gm={g_diff*0.5:.3f}:bm={b_diff*0.5:.3f}"
        )
    
    return ",".join(filters) if filters else ""
```

#### 方案 C：AI 色彩一致性（高级，Phase C）

在图片生成阶段就确保一致性：

```python
# 策略 1: 共享种子基数 + ControlNet 色彩参考
# SDXL + IP-Adapter 方案：用第一张图作为风格参考

# 策略 2: 后处理统一 (使用 Pillow + color transfer)
def reinhard_color_transfer(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """
    Reinhard 色彩迁移算法。
    将 source 的色彩分布迁移到 target 的色彩空间。
    
    参考论文: "Color Transfer between Images" (Reinhard et al., 2001)
    """
    # 转到 LAB 色彩空间
    import cv2
    source_lab = cv2.cvtColor(source, cv2.COLOR_RGB2LAB).astype(np.float32)
    target_lab = cv2.cvtColor(target, cv2.COLOR_RGB2LAB).astype(np.float32)
    
    # 计算各通道均值和标准差
    for i in range(3):
        src_mean, src_std = source_lab[:,:,i].mean(), source_lab[:,:,i].std()
        tgt_mean, tgt_std = target_lab[:,:,i].mean(), target_lab[:,:,i].std()
        
        # 线性变换：(x - src_mean) * (tgt_std / src_std) + tgt_mean
        source_lab[:,:,i] = (source_lab[:,:,i] - src_mean) * (tgt_std / max(src_std, 1e-6)) + tgt_mean
    
    # 裁剪到有效范围
    source_lab = np.clip(source_lab, 0, 255).astype(np.uint8)
    result = cv2.cvtColor(source_lab, cv2.COLOR_LAB2RGB)
    return result
```

### 6.4 批量色彩统一流程

```python
async def unify_colors(
    image_paths: list[Path],
    output_dir: Path,
    color_temp: ColorTemperature,
    vibe: str | None = None,
    method: str = "lut",  # "lut" | "histogram" | "reinhard"
) -> list[Path]:
    """
    批量色彩统一。
    
    Args:
        image_paths: 原始图片路径列表
        output_dir:  输出目录
        color_temp:  色彩温度 (LLM 分析结果)
        vibe:        更细粒度的氛围标签
        method:      校正方法
    
    Returns:
        校正后的图片路径列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    graded_paths = []
    
    if method == "lut":
        # 方案 A: LUT 映射
        lut_path = VIBE_LUT_MAP.get(vibe) or LUT_MAP.get(color_temp, LUT_MAP[ColorTemperature.NEUTRAL])
        
        for img_path in image_paths:
            out_path = output_dir / f"{img_path.stem}_graded{img_path.suffix}"
            cmd = apply_lut_ffmpeg(img_path, out_path, lut_path)
            subprocess.run(cmd, capture_output=True, check=True)
            graded_paths.append(out_path)
    
    elif method == "histogram":
        # 方案 B: 直方图匹配
        ref_path = select_reference_image(image_paths)
        ref_stats = compute_color_stats(ref_path)
        
        for img_path in image_paths:
            out_path = output_dir / f"{img_path.stem}_graded{img_path.suffix}"
            
            if img_path == ref_path:
                # 参考帧只应用 LUT，不做直方图校正
                import shutil
                shutil.copy2(img_path, out_path)
            else:
                src_stats = compute_color_stats(img_path)
                filter_str = generate_color_correction_filter(src_stats, ref_stats)
                
                if filter_str:
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(img_path),
                        "-vf", filter_str,
                        "-q:v", "2",
                        str(out_path),
                    ]
                    subprocess.run(cmd, capture_output=True, check=True)
                else:
                    import shutil
                    shutil.copy2(img_path, out_path)
            
            graded_paths.append(out_path)
    
    return graded_paths
```

### 6.5 LUT 文件规范

```
assets/luts/
├── warm_cinematic.cube       # 暖色调 — 橙黄偏移, 暗部加青
├── cool_moonlight.cube       # 冷色调 — 蓝紫偏移, 高光加银
├── neutral_film.cube         # 中性 — 轻微去饱和, 胶片质感
├── neon_teal_orange.cube     # 霓虹 — 高饱和青橙对比
├── dreamy_pastel.cube        # 梦幻 — 低对比, 高亮部发白
├── dark_contrast.cube        # 暗黑 — 压暗部, 高对比
├── vintage_film_grain.cube   # 复古 — 褪色, 绿偏, 低饱和
└── cyber_purple_green.cube   # 赛博 — 紫绿互补, 高饱和
```

每个 .cube 文件是 33×33×33 的 3D 查找表，标准格式如下：

```
# Created by AI-FX Color Pipeline
TITLE "Warm Cinematic"
LUT_3D_SIZE 33
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0
# R G B
0.0039 0.0000 0.0078
0.0344 0.0117 0.0422
...
```

### 6.6 色彩统一的 FFmpeg 集成点

色彩校正发生在 Ken Burns 动画**之前**（先校色，再做动画，确保动画过程中色彩一致）：

```
原始图 → 色彩统一 → Ken Burns → 转场拼接 → 合成
         ^^^^^^^^
         这一步
```

---

## 七、模块五：智能转场系统 ★ 新增

### 7.1 文件: `src/transition.py`

### 7.2 设计原理

**为什么需要智能转场：**

背景图的切换点通常在段落交界处。如果直接硬切（Frame N = 图A, Frame N+1 = 图B），观众会感到视觉断裂。专业 MV 中，转场是连接两个画面的"胶水"，而好的转场应该**与音乐节奏同步**。

**核心创新：音频能量驱动转场时机和类型。**

```
传统做法: 段落结束时间 = 转场开始时间 (固定)
本系统:   寻找段落交界附近的能量峰值 → 用峰值时刻触发转场 (动态)
```

### 7.3 音频能量分析

```python
import numpy as np
from pathlib import Path
from dataclasses import dataclass


@dataclass
class EnergyPeak:
    """音频能量峰值点"""
    time: float           # 峰值时间 (秒)
    energy: float         # 能量值 (0-1 归一化)
    is_onset: bool        # 是否是 onset (音符起始点)
    is_beat: bool         # 是否在节拍上


@dataclass
class TransitionPoint:
    """转场触发点"""
    time: float           # 转场开始时间
    duration: float       # 转场持续时长 (秒)
    type: str             # 转场类型 (xfade 滤镜名)
    from_para: int        # 源段落 ID
    to_para: int          # 目标段落 ID
    energy: float         # 触发点的音频能量


def analyze_audio_energy(
    audio_path: Path,
    sr: int = 22050,
) -> tuple[np.ndarray, np.ndarray, list[EnergyPeak]]:
    """
    分析音频能量曲线，提取峰值点。
    
    Returns:
        times: 时间轴数组
        energy_curve: 归一化能量曲线 (0-1)
        peaks: 能量峰值列表
    """
    import librosa
    
    y, sr = librosa.load(str(audio_path), sr=sr)
    
    # 计算 RMS 能量 (每帧)
    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)
    
    # 归一化到 0-1
    rms_norm = rms / (rms.max() + 1e-8)
    
    # 检测 onset (音符起始点)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop_length)
    onset_times = set(librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length).tolist())
    
    # 检测节拍
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    beat_times = set(librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length).tolist())
    
    # 提取峰值 (使用 scipy)
    from scipy.signal import find_peaks
    peak_indices, properties = find_peaks(
        rms_norm,
        height=0.3,        # 最低能量阈值
        distance=sr // hop_length,  # 最小间隔 ~1秒
        prominence=0.1,     # 最小突出度
    )
    
    peaks = []
    for idx in peak_indices:
        t = times[idx]
        peaks.append(EnergyPeak(
            time=t,
            energy=float(rms_norm[idx]),
            is_onset=any(abs(t - ot) < 0.05 for ot in onset_times),
            is_beat=any(abs(t - bt) < 0.05 for bt in beat_times),
        ))
    
    return times, rms_norm, peaks
```

### 7.4 转场时机与类型决策

```python
# FFmpeg xfade 支持的转场类型
XFADE_TRANSITIONS = {
    # 柔和类 (适合抒情/慢歌)
    "dissolve":     {"energy_range": (0.0, 0.5), "duration": 1.5},
    "fadeblack":    {"energy_range": (0.0, 0.4), "duration": 2.0},
    "fadewhite":    {"energy_range": (0.3, 0.6), "duration": 1.0},
    "smoothleft":   {"energy_range": (0.2, 0.5), "duration": 1.2},
    "smoothright":  {"energy_range": (0.2, 0.5), "duration": 1.2},
    
    # 中等类 (适合中速歌曲)
    "wipeleft":     {"energy_range": (0.4, 0.7), "duration": 0.8},
    "wiperight":    {"energy_range": (0.4, 0.7), "duration": 0.8},
    "slideleft":    {"energy_range": (0.4, 0.7), "duration": 0.8},
    "slideright":   {"energy_range": (0.4, 0.7), "duration": 0.8},
    "circlecrop":   {"energy_range": (0.3, 0.7), "duration": 1.0},
    
    # 强烈类 (适合高能/快节奏)
    "radial":       {"energy_range": (0.6, 1.0), "duration": 0.5},
    "rectcrop":     {"energy_range": (0.5, 0.8), "duration": 0.6},
    "horzopen":     {"energy_range": (0.6, 1.0), "duration": 0.5},
    "vertopen":     {"energy_range": (0.6, 1.0), "duration": 0.5},
    "diagbl":       {"energy_range": (0.5, 0.9), "duration": 0.7},
    
    # 闪烁类 (适合 drop/高潮)
    "fade":         {"energy_range": (0.7, 1.0), "duration": 0.3},
    "distance":     {"energy_range": (0.7, 1.0), "duration": 0.4},
    "pixelize":     {"energy_range": (0.8, 1.0), "duration": 0.5},
}

# LLM 建议的转场风格 → 候选类型映射
STYLE_TO_TRANSITIONS: dict[str, list[str]] = {
    "dissolve":   ["dissolve", "fadeblack", "smoothleft", "smoothright"],
    "flash":      ["fadewhite", "fade", "distance", "radial"],
    "wipe":       ["wipeleft", "wiperight", "slideleft", "slideright"],
    "fade_black": ["fadeblack", "dissolve", "fadewhite"],
    "radial":     ["radial", "circlecrop", "distance", "pixelize"],
}


def decide_transition(
    para_gap_time: float,
    energy_at_gap: float,
    llm_style: str,
    llm_per_para_style: str | None = None,
) -> tuple[str, float]:
    """
    根据音频能量 + LLM 建议决定转场类型和持续时间。
    
    逻辑:
    1. LLM 给出了整体转场风格偏好 → 缩小候选集
    2. LLM 给出了段落级别建议 → 优先使用
    3. 在候选集中，根据能量值选择最匹配的类型
    4. 如果段落间隔太短 (< 0.5s)，强制使用最短转场
    
    Returns:
        (transition_name, duration)
    """
    # 确定候选集
    style = llm_per_para_style or llm_style
    candidates = STYLE_TO_TRANSITIONS.get(style, ["dissolve", "fadeblack"])
    
    # 根据能量匹配
    best_match = candidates[0]
    best_score = float('inf')
    best_duration = 1.0
    
    for name in candidates:
        if name not in XFADE_TRANSITIONS:
            continue
        info = XFADE_TRANSITIONS[name]
        low, high = info["energy_range"]
        # 得分 = 能量值到目标范围中心的距离
        center = (low + high) / 2
        score = abs(energy_at_gap - center)
        if score < best_score:
            best_score = score
            best_match = name
            best_duration = info["duration"]
    
    # 如果段落间隔太短，缩短转场
    if para_gap_time < best_duration:
        best_duration = max(0.3, para_gap_time * 0.8)
    
    return best_match, best_duration


def find_transition_points(
    paragraphs: list,
    peaks: list[EnergyPeak],
    energy_curve: np.ndarray,
    times: np.ndarray,
    llm_style: str,
    llm_paragraphs: list[dict],
) -> list[TransitionPoint]:
    """
    为每个段落交界处确定转场触发点。
    
    策略:
    1. 在段落 N 结束和段落 N+1 开始之间的时间窗口内寻找能量峰值
    2. 如果找到峰值 → 以峰值为转场中心点
    3. 如果没有峰值 → 使用段落 N 的结束时间
    """
    transitions = []
    
    for i in range(len(paragraphs) - 1):
        para_end = paragraphs[i].end
        next_start = paragraphs[i + 1].start
        gap_center = (para_end + next_start) / 2
        
        # 在间隔附近 ±1s 寻找峰值
        search_start = para_end - 1.0
        search_end = next_start + 1.0
        
        nearby_peaks = [
            p for p in peaks
            if search_start <= p.time <= search_end
        ]
        
        if nearby_peaks:
            # 选择能量最高的峰值
            best_peak = max(nearby_peaks, key=lambda p: p.energy)
            trigger_time = best_peak.time
            trigger_energy = best_peak.energy
        else:
            # 没有峰值，使用间隔中心点的能量
            idx = np.argmin(np.abs(times - gap_center))
            trigger_time = gap_center
            trigger_energy = float(energy_curve[idx])
        
        # 获取 LLM 段落级建议
        per_para_style = None
        if i < len(llm_paragraphs):
            per_para_style = llm_paragraphs[i].get("suggested_transition_to_next")
        
        # 决定转场类型
        gap_duration = next_start - para_end
        trans_type, trans_duration = decide_transition(
            gap_duration, trigger_energy, llm_style, per_para_style
        )
        
        transitions.append(TransitionPoint(
            time=trigger_time - trans_duration / 2,  # 转场中心 = 触发点
            duration=trans_duration,
            type=trans_type,
            from_para=i,
            to_para=i + 1,
            energy=trigger_energy,
        ))
    
    return transitions
```

### 7.5 FFmpeg xfade 滤镜链生成

这是本模块最核心的部分。多段背景视频的 xfade 拼接需要构建级联滤镜链：

```python
def build_xfade_filter_complex(
    segment_paths: list[Path],
    segment_durations: list[float],
    transitions: list[TransitionPoint],
) -> tuple[list[str], str]:
    """
    构建 FFmpeg filter_complex 参数，实现多段视频 + xfade 转场。
    
    FFmpeg xfade 语法:
      [0:v][1:v]xfade=transition=dissolve:duration=1:offset=9[v01];
      [v01][2:v]xfade=transition=fadeblack:duration=0.5:offset=18[v012];
      ...
    
    Args:
        segment_paths: 每段背景视频的路径
        segment_durations: 每段视频的时长 (秒)
        transitions: 转场点列表
    
    Returns:
        (input_args, filter_complex_string)
        input_args: FFmpeg -i 参数列表
        filter_complex_string: filter_complex 值
    """
    n = len(segment_paths)
    assert len(transitions) == n - 1, "转场数 = 段数 - 1"
    
    # 构建 -i 参数
    input_args = []
    for path in segment_paths:
        input_args.extend(["-i", str(path)])
    
    # 构建 filter_complex
    filter_parts = []
    
    # 累计偏移量
    cumulative_offset = 0.0
    
    for i in range(n - 1):
        trans = transitions[i]
        
        # 源标签
        if i == 0:
            src_label = "[0:v]"
        else:
            src_label = f"[v{i}]"
        
        # 目标标签
        next_label = f"[{i + 1}:v]"
        
        # 输出标签
        if i == n - 2:
            out_label = "[vout]"
        else:
            out_label = f"[v{i + 1}]"
        
        # offset = 当前段视频的结束时间 - 转场时长 (从段落末尾开始回溯)
        offset = cumulative_offset + segment_durations[i] - trans.duration
        
        filter_parts.append(
            f"{src_label}{next_label}xfade="
            f"transition={trans.type}:"
            f"duration={trans.duration:.3f}:"
            f"offset={offset:.3f}"
            f"{out_label}"
        )
        
        # 更新累计偏移 (xfade 会让总时长减少 duration)
        cumulative_offset += segment_durations[i] - trans.duration
    
    filter_complex = ";".join(filter_parts)
    
    return input_args, filter_complex


def build_transition_ffmpeg_cmd(
    segment_paths: list[Path],
    segment_durations: list[float],
    transitions: list[TransitionPoint],
    output_path: Path,
    fps: int = 30,
) -> list[str]:
    """
    构建完整的 FFmpeg 转场拼接命令。
    
    示例输出 (3段, 2个转场):
    ffmpeg -y 
        -i para_00.mp4 -i para_01.mp4 -i para_02.mp4 
        -filter_complex "
            [0:v][1:v]xfade=transition=dissolve:duration=1.5:offset=28.5[v1];
            [v1][2:v]xfade=transition=fadewhite:duration=0.5:offset=55.0[vout]
        "
        -map "[vout]" -c:v libx264 -crf 18 -pix_fmt yuv420p 
        -r 30 output.mp4
    """
    input_args, filter_complex = build_xfade_filter_complex(
        segment_paths, segment_durations, transitions
    )
    
    cmd = ["ffmpeg", "-y"]
    cmd.extend(input_args)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(output_path),
    ])
    
    return cmd
```

### 7.6 闪白转场的特殊处理

"闪白"是 MV 中高能量段落转换的经典转场效果（如 drop 前的白屏闪烁）：

```python
def add_flash_white_effect(
    filter_complex: str,
    flash_time: float,
    flash_duration: float = 0.15,
    intensity: float = 1.0,
) -> str:
    """
    在指定时刻添加闪白效果。
    
    原理: 叠加一个短暂的白色画面，从全白迅速衰减。
    FFmpeg 实现: geq 滤镜 + overlay + fade
    
    Args:
        filter_complex: 现有滤镜链
        flash_time: 闪白时刻 (秒)
        flash_duration: 闪白持续 (秒)
        intensity: 闪白强度 (0-1)
    """
    flash_filter = (
        f"color=white:s=1920x1080:d={flash_duration},"
        f"fade=t=out:st=0:d={flash_duration}:alpha=1,"
        f"setpts=PTS+{flash_time}/TB[flash];"
        f"[vout][flash]overlay=enable='between(t,{flash_time},{flash_time + flash_duration})'[vflash]"
    )
    
    return filter_complex.replace("[vout]", "[vout_pre]") + ";" + flash_filter
```

### 7.7 转场与能量的映射关系图

```
能量值    0.0 ─────── 0.3 ─────── 0.6 ─────── 0.8 ─────── 1.0
           │           │           │           │           │
转场类型   │  fadeblack │  dissolve │  wipeleft │  radial  │  pixelize
           │  dissolve │  smoothL  │  circleC  │  horzopen│  flash
           │           │  fadewhit │  slideR   │  diagbl  │  distance
           │           │           │           │           │
转场时长   │   2.0s    │   1.2s    │   0.8s    │   0.5s   │   0.3s
           │           │           │           │           │
视觉感受   │  缓慢沉浸 │  平滑过渡 │  有节奏感 │  冲击力  │  爆炸闪烁
```

---

## 八、模块六：特效文字渲染

### 8.1 文件: `src/effects.py`

### 8.2 PyonFX 特效模板系统

结合字体性格系统，每个模板预设对应一种视觉风格：

```python
from dataclasses import dataclass


@dataclass
class EffectTemplate:
    """特效模板定义"""
    name: str
    # 文字进场方式
    char_enter: str       # "fade" | "slide_up" | "typewriter" | "bounce" | "blur_in"
    # 颜色扫过方式 (\k 类型)
    color_sweep: str      # "k" (硬切) | "kf" (渐变) | "ko" (边框渐变)
    # 行进场/退场
    line_enter: str       # "fade_in" | "slide_from_bottom" | "expand_center"
    line_exit: str        # "fade_out" | "slide_to_top" | "shrink_center"
    # 颜色方案 (ASS &HAABBGGRR)
    primary_color: str    # 未唱颜色
    secondary_color: str  # 已唱颜色
    outline_color: str
    glow_enabled: bool
    glow_color: str | None
    shadow_offset: float
    # ★ 关联字体性格
    font_style: str       # FontStyle 值


EFFECT_PRESETS: dict[str, EffectTemplate] = {
    "clean_minimal": EffectTemplate(
        name="简约白",
        char_enter="fade",
        color_sweep="kf",
        line_enter="fade_in",
        line_exit="fade_out",
        primary_color="&H00FFFFFF",
        secondary_color="&H0000CCFF",
        outline_color="&H64000000",
        glow_enabled=False,
        glow_color=None,
        shadow_offset=1.0,
        font_style="sans",
    ),
    "neon_glow": EffectTemplate(
        name="霓虹光",
        char_enter="blur_in",
        color_sweep="kf",
        line_enter="expand_center",
        line_exit="shrink_center",
        primary_color="&H00FFAA00",
        secondary_color="&H0000FFFF",
        outline_color="&H00FF00FF",
        glow_enabled=True,
        glow_color="&H6000FFFF",
        shadow_offset=0.0,
        font_style="artistic",
    ),
    "cinematic": EffectTemplate(
        name="电影感",
        char_enter="fade",
        color_sweep="kf",
        line_enter="slide_from_bottom",
        line_exit="slide_to_top",
        primary_color="&H00E0E0E0",
        secondary_color="&H0060C0FF",
        outline_color="&H00202020",
        glow_enabled=False,
        glow_color=None,
        shadow_offset=2.0,
        font_style="serif",
    ),
    "handwritten_warm": EffectTemplate(
        name="手写温暖",
        char_enter="typewriter",
        color_sweep="k",
        line_enter="fade_in",
        line_exit="fade_out",
        primary_color="&H00F0F0FF",
        secondary_color="&H0080C0FF",
        outline_color="&H00303060",
        glow_enabled=False,
        glow_color=None,
        shadow_offset=0.5,
        font_style="handwritten",
    ),
    "retro_karaoke": EffectTemplate(
        name="复古卡拉OK",
        char_enter="slide_up",
        color_sweep="k",
        line_enter="slide_from_bottom",
        line_exit="slide_to_top",
        primary_color="&H00FFFFFF",
        secondary_color="&H000000FF",
        outline_color="&H00000000",
        glow_enabled=True,
        glow_color="&H400000FF",
        shadow_offset=3.0,
        font_style="retro",
    ),
}
```

### 8.3 PyonFX ASS 生成

```python
def generate_fx_ass(
    alignment: dict,
    analysis: dict,
    template: EffectTemplate,
    font_profile: FontProfile,
    output_path: Path,
) -> Path:
    """
    使用 PyonFX 生成高级特效 ASS 字幕。
    
    相比基础 generate_ass():
    - 逐字动画 (fade/slide/typewriter)
    - 发光/阴影特效
    - ★ 字体性格集成
    - 行进场/退场动画
    """
    from pyonfx import Ass, Line, Word, Char
    
    resolved_font = resolve_font(font_profile)
    
    # 创建基础 ASS
    ass = Ass(str(output_path))
    
    # 设置样式
    style = ass.styles["Default"]
    style.fontname = resolved_font
    style.fontsize = int(font_profile.size_scale * 56)
    style.bold = font_profile.bold
    style.spacing = font_profile.spacing
    style.outline = font_profile.outline
    style.shadow = font_profile.shadow
    style.primary_color = template.primary_color
    style.secondary_color = template.secondary_color
    style.outline_color = template.outline_color
    
    # 根据模板生成特效
    for line_data in alignment["lines"]:
        _generate_line_effects(ass, line_data, template, font_profile)
    
    ass.save()
    return output_path


def _generate_line_effects(ass, line_data: dict, template: EffectTemplate, font_profile: FontProfile):
    """为单行生成特效标签"""
    
    # 行进场
    enter_tags = {
        "fade_in":           "\\fad(300,200)",
        "slide_from_bottom": "\\move(960,600,960,540)\\fad(200,150)",
        "expand_center":     "\\t(0,200,\\fscx100\\fscy100)\\fscx0\\fscy0",
    }
    
    # 字符进场
    char_tags = {
        "fade":       lambda i, n: f"\\alpha&HFF&\\t({i*30},{i*30+150},\\alpha&H00&)",
        "slide_up":   lambda i, n: f"\\move(0,10,0,0)\\t({i*20},{i*20+100},\\alpha&H00&)",
        "typewriter": lambda i, n: f"\\alpha&HFF&\\t({i*60},{i*60+10},\\alpha&H00&)",
        "blur_in":    lambda i, n: f"\\blur8\\alpha&HFF&\\t({i*40},{i*40+200},\\blur0\\alpha&H00&)",
        "bounce":     lambda i, n: f"\\fscx0\\fscy0\\t({i*25},{i*25+100},\\fscx110\\fscy110)\\t({i*25+100},{i*25+150},\\fscx100\\fscy100)",
    }
    
    line_enter = enter_tags.get(template.line_enter, "")
    char_enter_fn = char_tags.get(template.char_enter, lambda i, n: "")
    
    # 发光层 (如果启用)
    if template.glow_enabled and template.glow_color:
        # 在原始字幕下方添加一层模糊发光
        # Layer 0: 发光层 (blur + 半透明颜色)
        # Layer 1: 正常文字层
        pass  # 实际实现见 PyonFX 模板
    
    return line_enter, char_enter_fn
```

---

## 九、模块七：FFmpeg 多层合成

### 9.1 文件: `src/fx_compositor.py`

### 9.2 合成层级

```
┌─────────────────────────────────────────────┐
│  Layer 3: effects.ass (字幕特效)             │  ← subtitles 滤镜
├─────────────────────────────────────────────┤
│  Layer 2: atmosphere.mp4 (粒子/光效)         │  ← overlay (alpha blend)
├─────────────────────────────────────────────┤
│  Layer 1: background_full.mp4               │  ← 底层 (已转场 + 已调色)
│  (Ken Burns + xfade 转场 + 色彩统一)         │
├─────────────────────────────────────────────┤
│  Audio: audio.mp3 (原曲/人声)                │
└─────────────────────────────────────────────┘
```

### 9.3 完整合成命令

```python
def build_final_composite_cmd(
    background_video: Path,
    atmosphere_video: Path | None,
    effects_ass: Path,
    audio: Path,
    output: Path,
    config: CompositorConfig,
) -> list[str]:
    """
    构建最终的多层合成 FFmpeg 命令。
    """
    w, h = config.resolution
    sub_escaped = _escape_ffmpeg_path(effects_ass)
    
    if atmosphere_video and atmosphere_video.exists():
        # 三层合成: 背景 + 氛围 + 字幕
        return [
            "ffmpeg", "-y",
            "-i", str(background_video),
            "-i", str(atmosphere_video),
            "-i", str(audio),
            "-filter_complex",
            f"[0:v][1:v]overlay=format=auto[bg_atmos];"
            f"[bg_atmos]subtitles='{sub_escaped}'[vout]",
            "-map", "[vout]",
            "-map", "2:a",
            "-c:v", config.video_codec,
            "-crf", str(config.crf),
            "-c:a", config.audio_codec,
            "-b:a", config.audio_bitrate,
            "-pix_fmt", config.pixel_format,
            "-r", str(config.fps),
            "-shortest",
            "-movflags", "+faststart",
            str(output),
        ]
    else:
        # 两层合成: 背景 + 字幕
        return [
            "ffmpeg", "-y",
            "-i", str(background_video),
            "-i", str(audio),
            "-vf", f"subtitles='{sub_escaped}'",
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", config.video_codec,
            "-crf", str(config.crf),
            "-c:a", config.audio_codec,
            "-b:a", config.audio_bitrate,
            "-pix_fmt", config.pixel_format,
            "-r", str(config.fps),
            "-shortest",
            "-movflags", "+faststart",
            str(output),
        ]
```

### 9.4 Ken Burns 动画生成

```python
def create_ken_burns_video(
    image_path: Path,
    output_path: Path,
    duration: float,
    zoom_from: float = 1.0,
    zoom_to: float = 1.12,
    pan_direction: str = "left",  # "left" | "right" | "up" | "down"
    fps: int = 30,
    resolution: tuple[int, int] = (1920, 1080),
) -> list[str]:
    """
    将静态图片转为 Ken Burns 动画视频。
    
    Ken Burns 效果 = 缓慢推拉 + 平移，让静态图片"活"起来。
    
    FFmpeg 实现: zoompan 滤镜
    zoompan=z='min(zoom+0.0015,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=900:s=1920x1080:fps=30
    """
    w, h = resolution
    total_frames = int(duration * fps)
    
    # 计算每帧的 zoom 增量
    zoom_step = (zoom_to - zoom_from) / total_frames
    
    # 平移方向
    pan_expr = {
        "left":  f"x='max(0, iw/2-(iw/zoom/2) - ({w}*0.1*(on/{total_frames})))'",
        "right": f"x='min(iw-iw/zoom, iw/2-(iw/zoom/2) + ({w}*0.1*(on/{total_frames})))'",
        "up":    f"y='max(0, ih/2-(ih/zoom/2) - ({h}*0.1*(on/{total_frames})))'",
        "down":  f"y='min(ih-ih/zoom, ih/2-(ih/zoom/2) + ({h}*0.1*(on/{total_frames})))'",
    }
    
    zoom_expr = f"z='min(zoom+{zoom_step:.6f},{zoom_to})'"
    x_expr = pan_expr.get(pan_direction, pan_expr["left"])
    y_expr = "y='ih/2-(ih/zoom/2)'" if pan_direction in ("left", "right") else "y='ih/2-(ih/zoom/2)'"
    
    if pan_direction in ("up", "down"):
        x_expr = "x='iw/2-(iw/zoom/2)'"
        y_expr = pan_expr[pan_direction]
    
    filter_str = (
        f"zoompan={zoom_expr}:{x_expr}:{y_expr}"
        f":d={total_frames}:s={w}x{h}:fps={fps}"
    )
    
    return [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", filter_str,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
```

---

## 十、核心数据结构

### 10.1 扩展后的 fx_project.json

```json
{
  "version": "2.0",
  "song": {
    "title": "害怕的人",
    "alignment_json": "害怕的人_alignment.json",
    "audio": "害怕的人.mp3"
  },
  "analysis": {
    "mood": ["dark", "fearful", "lonely", "introspective"],
    "genre": "dark pop",
    "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560", "#533483"],
    "tempo_bpm": 128,
    "energy_curve": [0.3, 0.5, 0.8, 0.6, 0.9, 0.4],
    "font_style": "sans",
    "font_weight": "bold",
    "transition_style": "flash",
    "color_temperature": "cool"
  },
  "paragraphs": [
    {
      "id": 0,
      "lines": [0, 1, 2, 3],
      "start": 35.343,
      "end": 65.2,
      "text": "影子在墙上 张开贪婪的巨口\n...",
      "scene_prompt": "dark urban alleyway at night, neon reflections on wet pavement...",
      "background_image": "scenes/para_00.png",
      "background_graded": "scenes/para_00_graded.png",
      "background_video": "scenes/para_00.mp4",
      "ken_burns": {
        "zoom_from": 1.0,
        "zoom_to": 1.12,
        "pan": "left"
      },
      "font_override": null,
      "transition_to_next": {
        "type": "dissolve",
        "duration": 1.5,
        "trigger_time": 64.8,
        "trigger_energy": 0.45
      }
    },
    {
      "id": 1,
      "lines": [4, 5, 6, 7],
      "start": 66.5,
      "end": 95.0,
      "text": "...",
      "scene_prompt": "shattered mirror fragments floating in void...",
      "background_image": "scenes/para_01.png",
      "background_graded": "scenes/para_01_graded.png",
      "background_video": "scenes/para_01.mp4",
      "ken_burns": {
        "zoom_from": 1.05,
        "zoom_to": 1.0,
        "pan": "right"
      },
      "font_override": "artistic",
      "transition_to_next": {
        "type": "fadewhite",
        "duration": 0.3,
        "trigger_time": 94.7,
        "trigger_energy": 0.82
      }
    }
  ],
  "font": {
    "style": "sans",
    "resolved_primary": "思源黑体",
    "resolved_accent": "思源黑体 Bold",
    "allow_paragraph_switch": true,
    "paragraph_fonts": {
      "0": "sans",
      "1": "artistic",
      "2": "sans"
    }
  },
  "color_grading": {
    "method": "lut",
    "lut_file": "assets/luts/cool_moonlight.cube",
    "reference_image": "scenes/para_00.png",
    "adjustments": {
      "brightness": 0.0,
      "contrast": 1.0,
      "saturation": 1.05
    }
  },
  "transitions": {
    "global_style": "flash",
    "points": [
      {
        "from": 0,
        "to": 1,
        "type": "dissolve",
        "duration": 1.5,
        "offset": 64.8
      },
      {
        "from": 1,
        "to": 2,
        "type": "fadewhite",
        "duration": 0.3,
        "offset": 94.7
      }
    ]
  },
  "effects": {
    "template": "neon_glow",
    "overrides": {
      "glow_color": "&H6000FFFF",
      "enter_duration": 180
    }
  },
  "atmosphere": {
    "preset": "rain",
    "intensity": 0.7
  },
  "output": {
    "resolution": [1920, 1080],
    "fps": 30,
    "codec": "libx264",
    "crf": 18
  }
}
```

### 10.2 Python 数据类

```python
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


class FontStyle(str, Enum):
    SERIF = "serif"
    SANS = "sans"
    HANDWRITTEN = "handwritten"
    ARTISTIC = "artistic"
    RETRO = "retro"


class ColorTemperature(str, Enum):
    WARM = "warm"
    COOL = "cool"
    NEUTRAL = "neutral"


@dataclass
class KenBurnsConfig:
    zoom_from: float = 1.0
    zoom_to: float = 1.12
    pan: str = "left"


@dataclass
class TransitionConfig:
    type: str = "dissolve"
    duration: float = 1.0
    trigger_time: float = 0.0
    trigger_energy: float = 0.5


@dataclass
class ParagraphFx:
    id: int
    lines: list[int]
    start: float
    end: float
    text: str
    scene_prompt: str = ""
    background_image: Path | None = None
    background_graded: Path | None = None
    background_video: Path | None = None
    ken_burns: KenBurnsConfig = field(default_factory=KenBurnsConfig)
    font_override: FontStyle | None = None
    transition_to_next: TransitionConfig | None = None


@dataclass
class SongAnalysis:
    mood: list[str]
    genre: str
    color_palette: list[str]
    tempo_bpm: float
    energy_curve: list[float]
    font_style: FontStyle = FontStyle.SANS
    transition_style: str = "dissolve"
    color_temperature: ColorTemperature = ColorTemperature.NEUTRAL


@dataclass
class ColorGradingConfig:
    method: str = "lut"                # "lut" | "histogram" | "reinhard"
    lut_file: str | None = None
    reference_image: Path | None = None
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0


@dataclass 
class FxProjectConfig:
    """完整的特效工程配置"""
    song_title: str
    alignment_json: Path
    audio: Path
    analysis: SongAnalysis
    paragraphs: list[ParagraphFx]
    font_style: FontStyle = FontStyle.SANS
    color_grading: ColorGradingConfig = field(default_factory=ColorGradingConfig)
    effect_template: str = "clean_minimal"
    atmosphere_preset: str | None = None
    atmosphere_intensity: float = 0.5
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 30
    crf: int = 18
```

### 10.3 FxPipeline 完整实现

```python
class FxPipeline:
    """AI 特效视频完整生成管线"""
    
    def __init__(
        self,
        image_generator: ImageGenerator,
        llm_client,  # OpenAI / Anthropic client
        config: FxProjectConfig | None = None,
    ):
        self.image_gen = image_generator
        self.llm = llm_client
        self.config = config
    
    async def run(
        self,
        alignment_json: Path,
        audio: Path,
        output: Path,
        work_dir: Path | None = None,
    ) -> Path:
        """
        完整管线执行。
        
        Step 1: LLM 歌词分析 (含字体/转场/色温推荐)     ~5s
        Step 2: 段落切分                                  <1s
        Step 3: 场景提示词生成                            ~3s
        Step 4: AI 背景图生成 (并行)                      ~30-60s
        Step 5: ★ 色彩统一                               ~5s
        Step 6: Ken Burns 动画                            ~10s
        Step 7: ★ 智能转场 + 背景拼接                     ~15s
        Step 8: 特效 ASS 生成 (含字体性格)                 ~5s
        Step 9: 氛围层渲染 (可选)                          ~10s
        Step 10: FFmpeg 多层合成                           ~30-60s
        
        总计: ~2-3 分钟 (大部分时间在 AI 图片生成)
        """
        import json, asyncio
        
        if work_dir is None:
            work_dir = output.parent / "fx_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = work_dir / "scenes"
        scenes_dir.mkdir(exist_ok=True)
        
        alignment = json.loads(alignment_json.read_text(encoding="utf-8"))
        
        # ── Step 1: LLM 分析 ──
        log.info("Step 1/10: LLM 歌词分析...")
        analysis = await self.analyze_lyrics(alignment, audio)
        
        # ── Step 2: 段落切分 ──
        log.info("Step 2/10: 段落切分...")
        paragraphs = self.split_paragraphs(alignment, analysis)
        log.info("  切分为 %d 个段落", len(paragraphs))
        
        # ── Step 3: 场景提示词 ──
        log.info("Step 3/10: 场景提示词生成...")
        for para in paragraphs:
            para.scene_prompt = await self.generate_scene_prompt(para, analysis)
        
        # ── Step 4: AI 背景图生成 ──
        log.info("Step 4/10: AI 背景图生成 (%d 张)...", len(paragraphs))
        image_paths = await generate_all_backgrounds(
            paragraphs, analysis, self.image_gen, scenes_dir
        )
        for i, path in enumerate(image_paths):
            paragraphs[i].background_image = path
        
        # ── Step 5: ★ 色彩统一 ──
        log.info("Step 5/10: 色彩统一...")
        grading_config = ColorGradingConfig(
            method="lut",
            lut_file=LUT_MAP.get(analysis.color_temperature),
        )
        graded_paths = await unify_colors(
            image_paths,
            scenes_dir / "graded",
            analysis.color_temperature,
            method=grading_config.method,
        )
        for i, path in enumerate(graded_paths):
            paragraphs[i].background_graded = path
        
        # ── Step 6: Ken Burns 动画 ──
        log.info("Step 6/10: Ken Burns 动画...")
        segment_paths = []
        segment_durations = []
        for para in paragraphs:
            duration = para.end - para.start
            video_path = scenes_dir / f"para_{para.id:02d}.mp4"
            cmd = create_ken_burns_video(
                para.background_graded or para.background_image,
                video_path,
                duration=duration,
                zoom_from=para.ken_burns.zoom_from,
                zoom_to=para.ken_burns.zoom_to,
                pan_direction=para.ken_burns.pan,
            )
            _run_ffmpeg(cmd)
            para.background_video = video_path
            segment_paths.append(video_path)
            segment_durations.append(duration)
        
        # ── Step 7: ★ 智能转场 + 背景拼接 ──
        log.info("Step 7/10: 智能转场分析...")
        times, energy_curve, peaks = analyze_audio_energy(audio)
        
        transitions = find_transition_points(
            paragraphs, peaks, energy_curve, times,
            analysis.transition_style,
            []  # LLM 段落级建议
        )
        log.info("  确定 %d 个转场点", len(transitions))
        for t in transitions:
            log.info("    %s @ %.1fs (%.1fs, energy=%.2f)",
                     t.type, t.time, t.duration, t.energy)
        
        bg_full = work_dir / "background_full.mp4"
        if len(segment_paths) > 1:
            cmd = build_transition_ffmpeg_cmd(
                segment_paths, segment_durations, transitions, bg_full
            )
            _run_ffmpeg(cmd)
        else:
            import shutil
            shutil.copy2(segment_paths[0], bg_full)
        
        # ── Step 8: 特效 ASS 生成 (含字体性格) ──
        log.info("Step 8/10: 特效字幕生成...")
        font_profile = FONT_PROFILES[analysis.font_style]
        template = EFFECT_PRESETS.get(self.config.effect_template if self.config else "clean_minimal")
        
        effects_ass = work_dir / "effects.ass"
        generate_fx_ass(alignment, analysis.__dict__, template, font_profile, effects_ass)
        
        # ── Step 9: 氛围层 (可选) ──
        atmosphere_video = None
        # TODO: Phase B 实现粒子渲染
        
        # ── Step 10: 最终合成 ──
        log.info("Step 10/10: 最终合成...")
        compositor_config = CompositorConfig(
            resolution=self.config.resolution if self.config else (1920, 1080),
            fps=self.config.fps if self.config else 30,
            crf=self.config.crf if self.config else 18,
        )
        cmd = build_final_composite_cmd(
            bg_full, atmosphere_video, effects_ass, audio, output, compositor_config
        )
        _run_ffmpeg(cmd)
        
        log.info("✅ 特效视频生成完成: %s", output)
        return output
```

---

## 十一、开发阶段与排期

### Phase A: MVP — 核心管线 (7-10 天)

> **目标**: 输入一首歌 → 输出带 AI 背景 + 卡拉OK特效的视频

| 天数 | 任务 | 输出文件 | 验收标准 |
|------|------|---------|---------|
| D1 | LLM 歌词分析 + 提示词生成 | `src/scene_gen.py` | 输入歌词 → 输出完整 JSON 分析 |
| D2 | AI 图片生成 (DALL-E 3 + 本地 SDXL) | `src/scene_gen.py` | 输入提示词 → 输出 1920×1080 图片 |
| D3 | ★ 字体性格系统 | `src/font_system.py` | 5 种 FontStyle 全部可用，字体检测正常 |
| D4 | ★ 色彩统一 (LUT 方案) | `src/color_unifier.py` | 8 张不同风格 AI 图 → 统一色调输出 |
| D5 | Ken Burns 动画 | `src/video_bg.py` | 静态图 → 12s 推拉动画视频 |
| D6 | ★ 智能转场 + 背景拼接 | `src/transition.py` | 多段视频 → xfade 转场拼接 |
| D7 | PyonFX 特效模板 (3 个预设) | `src/effects.py` | 生成带动画特效的 ASS |
| D8 | FFmpeg 多层合成 | `src/fx_compositor.py` | 背景 + 字幕 + 音频 → 最终 MP4 |
| D9 | FxPipeline 集成 + 端到端测试 | `src/fx_pipeline.py` | 一键运行全流程 |
| D10 | 调优 + Bug 修复 + 文档 | - | 3 首歌全流程通过 |

### Phase B: 进阶功能 (7-10 天)

| 任务 | 描述 |
|------|------|
| 直方图匹配色彩校正 | 方案 B 自动校正 |
| 氛围粒子层 | 雨/雪/光斑/烟雾 |
| Canvas 文字渲染引擎 | 突破 ASS 限制，逐帧渲染 |
| 段落级字体切换 | LLM 分析情绪转折 → 字体切换 |
| AI 视频背景 | Kling/Runway 首帧扩展 |
| 更多特效模板 (5+) | 社区投稿/用户自定义 |

### Phase C: SaaS 集成 (5-7 天)

| 任务 | 描述 |
|------|------|
| 仪表板"AI 特效"选项 | 上传时可选择风格 |
| Celery Worker 集成 | 后台异步执行 FxPipeline |
| 进度回调 | WebSocket 实时推送 |
| fx_project.json 在线编辑 | Web UI 调整参数 |
| 模板市场 | 用户分享特效预设 |

---

## 十二、文件清单与依赖

### 12.1 新增文件

| 文件 | 职责 | LOC 预估 |
|------|------|---------|
| `src/scene_gen.py` | LLM 分析 + 提示词 + 图片生成 | ~350 |
| `src/font_system.py` | ★ 字体性格系统 | ~200 |
| `src/color_unifier.py` | ★ 色彩统一管线 | ~250 |
| `src/transition.py` | ★ 智能转场系统 | ~300 |
| `src/effects.py` | PyonFX 特效模板 | ~300 |
| `src/video_bg.py` | Ken Burns + 视频处理 | ~150 |
| `src/fx_compositor.py` | 多层 FFmpeg 合成 | ~200 |
| `src/fx_pipeline.py` | 完整管线编排 | ~250 |
| `assets/luts/*.cube` | 预制 LUT 文件 (8 个) | - |
| `assets/fonts/` | 字体文件目录 | - |

### 12.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| `src/config.py` | 新增 `FxSubtitleConfig`, `FxProjectConfig`, `ColorGradingConfig` |
| `src/subtitle.py` | 新增 `\fn` 字体切换支持 |
| `pyproject.toml` | 新增 `[project.optional-dependencies] fx = [...]` |
| `Dockerfile` | 新增字体安装 |

### 12.3 新增依赖

```toml
[project.optional-dependencies]
fx = [
    "pyonfx>=0.11.0",        # ASS 高级特效引擎
    "openai>=1.0",            # GPT-4o / DALL-E 3 API
    "anthropic>=0.30",        # Claude API (可选)
    "httpx>=0.27",            # HTTP 客户端
    "Pillow>=10.0",           # 图片处理
    "numpy>=1.26",            # 数值计算
    "scipy>=1.12",            # 信号处理 (find_peaks)
    "opencv-python>=4.9",     # 色彩迁移 (Reinhard, 可选)
    "librosa>=0.10",          # 音频分析 (已在主依赖中)
]
```

---

## 十三、测试策略

### 13.1 单元测试

```python
# tests/test_font_system.py
class TestFontSystem:
    def test_all_profiles_defined(self):
        """确保每种 FontStyle 都有对应的 FontProfile"""
        for style in FontStyle:
            assert style in FONT_PROFILES
    
    def test_resolve_font_returns_string(self):
        """resolve_font 总是返回字符串"""
        for profile in FONT_PROFILES.values():
            result = resolve_font(profile)
            assert isinstance(result, str)
            assert len(result) > 0
    
    def test_font_style_in_effect_presets(self):
        """每个特效预设都关联了字体性格"""
        for preset in EFFECT_PRESETS.values():
            assert preset.font_style in [s.value for s in FontStyle]


# tests/test_transition.py
class TestTransition:
    def test_decide_transition_returns_valid_type(self):
        """decide_transition 返回有效的 xfade 类型"""
        trans_type, duration = decide_transition(2.0, 0.5, "dissolve")
        assert trans_type in XFADE_TRANSITIONS
        assert duration > 0
    
    def test_xfade_filter_complex_format(self):
        """filter_complex 格式正确"""
        paths = [Path(f"seg_{i}.mp4") for i in range(3)]
        durations = [30.0, 30.0, 30.0]
        transitions = [
            TransitionPoint(29.0, 1.0, "dissolve", 0, 1, 0.5),
            TransitionPoint(58.0, 0.5, "fadewhite", 1, 2, 0.8),
        ]
        input_args, fc = build_xfade_filter_complex(paths, durations, transitions)
        assert len(input_args) == 6  # 3 × (-i, path)
        assert "xfade" in fc
        assert "dissolve" in fc
        assert "fadewhite" in fc
    
    def test_short_gap_reduces_duration(self):
        """短间隔时转场时长自动缩短"""
        trans_type, duration = decide_transition(0.3, 0.5, "dissolve")
        assert duration <= 0.3


# tests/test_color_unifier.py
class TestColorUnifier:
    def test_generate_correction_filter_no_change(self):
        """相同统计量 → 不需要校正"""
        stats = {"R_mean": 128, "G_mean": 128, "B_mean": 128,
                 "R_std": 60, "G_std": 60, "B_std": 60, "brightness": 128}
        result = generate_color_correction_filter(stats, stats)
        assert result == ""
    
    def test_brightness_correction(self):
        """亮度差异 → 生成 eq 滤镜"""
        dark = {"R_mean": 80, "G_mean": 80, "B_mean": 80,
                "R_std": 50, "G_std": 50, "B_std": 50, "brightness": 80}
        bright = {"R_mean": 160, "G_mean": 160, "B_mean": 160,
                  "R_std": 50, "G_std": 50, "B_std": 50, "brightness": 160}
        result = generate_color_correction_filter(dark, bright)
        assert "eq=" in result
        assert "brightness=" in result
```

### 13.2 集成测试

```python
# tests/test_fx_pipeline.py (需要 API key，标记为 slow)
import pytest

@pytest.mark.slow
@pytest.mark.integration
class TestFxPipeline:
    async def test_full_pipeline(self, sample_alignment, sample_audio):
        """端到端测试：alignment + audio → 特效视频"""
        pipeline = FxPipeline(
            image_generator=SDXLLocalGenerator(),
            llm_client=openai_client,
        )
        output = Path("test_output/fx_test.mp4")
        result = await pipeline.run(sample_alignment, sample_audio, output)
        
        assert result.exists()
        assert result.stat().st_size > 1_000_000  # > 1MB
```

### 13.3 视觉验证清单

| # | 验证项 | 通过标准 |
|---|--------|---------|
| 1 | 字体匹配歌曲情绪 | 古风 → 宋体, 电子 → 黑体, 民谣 → 手写 |
| 2 | 色调一致性 | 连续播放无明显"跳色" |
| 3 | 转场自然度 | 转场与节拍同步，无生硬硬切 |
| 4 | 字幕可读性 | 字幕在任何背景上清晰可读 |
| 5 | Ken Burns 流畅度 | 无卡顿/跳帧 |
| 6 | 整体专业感 | 非技术人员观看不觉违和 |

---

## 十四、风险与备选方案

### 14.1 字体系统风险

| 风险 | 概率 | 影响 | 缓解方案 |
|------|------|------|---------|
| 用户系统缺少推荐字体 | 高 | 回退到默认字体 | `resolve_font()` 多级 fallback + Docker 预装 |
| 手写体中文支持不完整 | 中 | 部分字符显示异常 | 字体可用性检测 + 强制 fallback |
| ASS `\fn` 渲染器兼容性 | 低 | libass 版本差异 | 固定 libass 版本 (Docker) |

### 14.2 转场系统风险

| 风险 | 概率 | 影响 | 缓解方案 |
|------|------|------|---------|
| FFmpeg xfade 多段拼接复杂度 | 中 | filter_complex 链过长报错 | 超过 8 段时分批拼接 |
| 音频能量检测误差 | 低 | 转场时机偏离节拍 | 增大搜索窗口 + 人工覆盖选项 |
| Librosa 加载大文件慢 | 低 | 超时 | 只加载前 30s 用于 tempo 检测，按需加载全曲 |

### 14.3 色彩统一风险

| 风险 | 概率 | 影响 | 缓解方案 |
|------|------|------|---------|
| LUT 风格与 AI 图片不匹配 | 中 | 调色后反而更奇怪 | 提供"不调色"选项 + 多 LUT 预览 |
| 直方图匹配导致过度校正 | 中 | 色彩失真 | 限制校正幅度 (max ±0.2) |
| .cube 文件格式兼容性 | 低 | FFmpeg lut3d 报错 | 标准化 LUT 文件 (33×33×33) |

---

## 附录：一句话总结各模块

| 模块 | 一句话 |
|------|--------|
| LLM 分析 | 读懂歌词的心，翻译成视觉语言 |
| ★ 字体性格 | 给歌词穿上合适的衣服 — 宋体是旗袍，黑体是西装 |
| AI 背景 | 用 AI 画出歌词描述的每一幕场景 |
| ★ 色彩统一 | 让所有场景仿佛来自同一部电影 |
| ★ 智能转场 | 场景切换与鼓点同步，呼吸感自然 |
| 特效文字 | 逐字发光、飘入、弹跳 — 文字也在跳舞 |
| FFmpeg 合成 | 背景 + 氛围 + 文字 + 音频 = 一支完整的 MV |
