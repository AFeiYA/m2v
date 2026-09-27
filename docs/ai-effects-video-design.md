# AI 特效歌词视频 — 设计文档

> **日期:** 2026-03-29 | **状态:** 设计中 | **前置:** alignment JSON 编辑器已完成

---

## 一、问题定义

当前管线的最终输出是 **ASS 卡拉OK 字幕 + FFmpeg 合成视频**。视觉效果局限于：

| 能力 | 当前状态 | 瓶颈 |
|------|---------|------|
| 字幕渲染 | ASS `\k` 逐字变色 | 仅颜色切换，无粒子/光效/3D |
| 字幕动画 | `\t` 缩放脉冲 (beat) | ASS 动画能力有限 (无路径/粒子/模糊) |
| 背景 | 静态图/循环视频/纯黑 | 与歌词内容无关，无氛围感 |
| 整体 | "KTV 点播机" 水平 | 离 B站/抖音 Lyric MV 有明显差距 |

**目标:** 利用编辑好的 alignment JSON (精确到字的时间轴) + AI 能力，生成**媲美专业 Lyric Video** 的特效视频。

---

## 二、对标分析 — 好看的歌词视频长什么样

观察 B站/YouTube 上高播放量的 Lyric MV，视觉层次通常有 4 层：

```
Layer 4 (顶层)    文字特效 — 粒子飞散/光晕/笔画描边动画/3D 翻转
Layer 3           歌词排版 — 动态布局/运镜推拉/段落切换转场
Layer 2           氛围前景 — 粒子/光斑/雨雪/烟雾 (半透明叠加)
Layer 1 (底层)    背景画面 — 与歌词意境匹配的插画/照片/AI 生成画面
```

**关键观察:**
1. "好看" 的核心不是某一个炫技特效，而是 **全层次的氛围一致性**
2. 文字出场/消失需要有 **仪式感** (淡入/展开/弹跳/手写感)
3. 背景每 4-8 句换一次场景，与歌词 **语义段落** 对齐
4. 颜色主调随歌曲情绪变化 (安静→暗蓝 / 高潮→暖橙)

---

## 三、技术路线评估

### 路线 A: ASS 极限特效 (PyonFX)

```
alignment.json → PyonFX Python 脚本 → 高级 ASS 字幕 → FFmpeg 合成
```

| 维度 | 评估 |
|------|------|
| 原理 | PyonFX 可生成数千行 ASS 代码，每个字拆成像素级 `\clip` + `\t` + `\move` |
| 效果上限 | 粒子飞散、光晕展开、弹跳出场、颜色渐变波纹 — 接近 AE 70% |
| AI 结合 | ❌ 难以引入 AI，仅模板化参数调节 |
| 渲染速度 | ⚡ 极快 (FFmpeg 硬解码 ASS) |
| 复杂度 | 🟡 需手写 PyonFX 脚本，每种特效一个模板 |
| 背景 | ❌ 不解决背景问题 |

**结论:** 适合做**文字特效引擎**，但单独不够。

---

### 路线 B: 程序化视频生成 (Remotion / Motion Canvas)

```
alignment.json → React/TS 组件 → Remotion 渲染 → MP4
```

| 维度 | 评估 |
|------|------|
| 原理 | React 组件 = 视频帧，`useCurrentFrame()` 驱动动画，支持 CSS/SVG/Canvas/WebGL |
| 效果上限 | ∞ (Web 技术的全部能力: Three.js 3D、GSAP 动画、Lottie、SVG 路径) |
| AI 结合 | ✅ AI 生成 React 组件代码 / 生成背景图作为 props |
| 渲染速度 | 🟡 逐帧渲染，5分钟视频 ~3-10分钟 (有 GPU 加速可用 Lambda) |
| 复杂度 | 🔴 需引入 Node.js 生态，技术栈跨度大 |
| 背景 | ✅ 可内嵌任何 Web 动画/AI 图片 |

**结论:** 上限最高，但引入了完整的 Node.js/React 技术栈。

---

### 路线 C: Python Canvas 渲染 (Pillow / Skia / Cairo + MoviePy)

```
alignment.json → Python 逐帧渲染 → PNG 序列 → FFmpeg 合成
```

| 维度 | 评估 |
|------|------|
| 原理 | Python 绘图库逐帧渲染文字 + 特效 → 图片序列 → FFmpeg 编码 |
| 效果上限 | 2D 特效足够 (发光/粒子/渐变/运动模糊)，3D 需 Blender Python API |
| AI 结合 | ✅ 同 Python 生态，直接调 SD/DALL-E API 生成背景 |
| 渲染速度 | 🔴 纯 CPU 逐帧极慢；用 GPU (Skia/Wand) 可优化 |
| 复杂度 | 🟡 纯 Python 可控，但需手写渲染引擎 |
| 背景 | ✅ 每帧可叠加任意背景图 |

**结论:** 与现有 Python 生态统一，可控性好，但性能差。

---

### 路线 D: AI 视频生成 (端到端)

```
alignment.json + 歌词文本 → 提示词 → AI 视频模型 → MP4
```

| 维度 | 评估 |
|------|------|
| 原理 | 用 Kling / Runway / Sora / Pika 等 AI 模型直接生成视频 |
| 效果上限 | 画面惊艳，但 **文字渲染极差** — AI 生成模型无法精准渲染汉字 |
| AI 结合 | ✅ 全 AI |
| 渲染速度 | 🔴 API 调用等待 + 显存消耗巨大 |
| 复杂度 | 🟢 调 API 简单 |
| 精度 | ❌ **致命缺陷: 无法保证逐字时间精度**，生成的视频中文字是画面的一部分，不可编辑 |

**结论:** 不能直接用于歌词视频（文字精度不可控）。但可用于 **生成背景画面**。

---

### 🏆 路线 E: 混合架构 (推荐)

```
                    ┌──────────────────────┐
                    │  alignment.json      │
                    │  (编辑后的时间轴)      │
                    └──────┬───────────────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │ AI 背景生成   │ │ 氛围层   │ │ 文字特效引擎  │
    │              │ │ 粒子/光效 │ │              │
    │ SD/DALL-E/   │ │          │ │ PyonFX ASS   │
    │ Kling        │ │ Python   │ │ 或 Canvas    │
    │ 按段落生成    │ │ 渲染     │ │ 逐帧渲染     │
    └──────┬───────┘ └────┬─────┘ └──────┬───────┘
           │              │              │
           ▼              ▼              ▼
    ┌──────────────────────────────────────────┐
    │         FFmpeg 多层合成                    │
    │                                          │
    │  背景视频 + 氛围叠加 + 字幕/特效 → MP4     │
    └──────────────────────────────────────────┘
```

**核心思路: AI 管画面，代码管文字，FFmpeg 管合成。**

每一层做自己最擅长的事，避免让 AI 做它做不好的事（精确文字渲染）。

---

## 四、混合架构详细设计

### 4.1 Layer 1 — AI 背景生成

**输入:** 歌词文本 (按段落)  
**输出:** 每段落一张/一段背景画面

#### 方案 A: AI 图片 → Ken Burns 动画 (推荐起步)

```python
# 伪代码
for paragraph in lyrics_paragraphs:
    prompt = llm_generate_prompt(paragraph.text, song_mood)
    # → "暗色调城市夜景，霓虹灯倒影在雨中，孤独感，电影质感，16:9"
    
    image = sd_generate(prompt, width=1920, height=1080)
    # → paragraph_01.png
    
    # Ken Burns: 静态图 + 缓慢缩放/平移 → 伪运镜
    video_clip = ken_burns(image, duration=paragraph.duration, 
                           zoom_from=1.0, zoom_to=1.15, 
                           pan_direction="left")
```

**技术选择:**

| 方案 | 成本 | 质量 | 速度 |
|------|------|------|------|
| Stable Diffusion XL (本地) | 免费 | ⭐⭐⭐⭐ | ~5s/张 (GPU) |
| DALL-E 3 API | $0.04/张 | ⭐⭐⭐⭐⭐ | ~8s/张 |
| Midjourney API | $0.01/张 | ⭐⭐⭐⭐⭐ | ~30s/张 |
| Flux (本地/Replicate) | 免费/$0.003 | ⭐⭐⭐⭐ | ~10s/张 |

5 分钟歌曲约 6-10 个段落 → 6-10 张图 → 成本可控。

#### 方案 B: AI 视频背景 (进阶)

```python
# 用 AI 图片做首帧，生成 4-8 秒短视频
for paragraph in lyrics_paragraphs:
    first_frame = sd_generate(prompt, ...)
    video_clip = kling_img2video(first_frame, duration=6)
    # → 带微动的电影感画面 (云飘动/雨滴下落/光影变化)
```

| 方案 | 成本 | 质量 | 速度 |
|------|------|------|------|
| Kling 1.6 API | ~$0.14/5s | ⭐⭐⭐⭐⭐ | ~120s/段 |
| Runway Gen-3 | ~$0.25/5s | ⭐⭐⭐⭐ | ~60s/段 |
| Pika 2.0 | ~$0.10/5s | ⭐⭐⭐⭐ | ~90s/段 |
| AnimateDiff (本地) | 免费 | ⭐⭐⭐ | ~60s/段 (GPU) |

10 个段落 → 总成本 $1-2.5 / 总时间 10-20分钟，可接受。

#### Prompt 工程 — LLM 自动生成画面提示词

这是整个方案最关键的 AI 环节：

```python
def generate_scene_prompt(paragraph_text: str, song_info: dict) -> str:
    """
    用 LLM 根据歌词段落自动生成画面描述提示词。
    
    song_info = {
        "title": "害怕的人",
        "mood": "暗黑, 恐惧, 孤独",        # 可由 LLM 从全文推断
        "genre": "暗黑流行",
        "color_palette": ["#1a1a2e", "#16213e", "#e94560"],
    }
    """
    system = """你是一个专业的 Lyric MV 视觉导演。
    根据歌词内容生成 Stable Diffusion 画面提示词。
    要求:
    - 不要出现任何文字/字母
    - 画面要与歌词意境匹配
    - 保持与整首歌的色调一致
    - 输出英文提示词
    - 风格: 电影感, 宽屏 16:9
    """
    
    response = llm.chat(system, f"歌曲: {song_info['title']}\n歌词段落:\n{paragraph_text}")
    return response  
    # → "dark urban alleyway at night, neon reflections on wet pavement, 
    #    silhouette of a lonely figure, cinematic lighting, moody atmosphere,
    #    teal and orange color grade, 16:9 aspect ratio, photorealistic"
```

#### 段落切分逻辑

alignment JSON 本身没有段落标记，需要自动推断：

```python
def split_paragraphs(alignment: dict) -> list[Paragraph]:
    """
    根据行间时间间隙自动切分段落。
    间隙 > 3秒 → 新段落 (间奏/停顿)
    或按固定行数: 每 4 行一个段落
    """
    paragraphs = []
    current = []
    
    for i, line in enumerate(alignment["lines"]):
        current.append(line)
        
        is_last = (i == len(alignment["lines"]) - 1)
        gap_to_next = (alignment["lines"][i+1]["start"] - line["end"]) if not is_last else 999
        
        if gap_to_next > 3.0 or len(current) >= 4 or is_last:
            paragraphs.append(Paragraph(
                lines=current,
                start=current[0]["start"],
                end=current[-1]["end"],
                text="\n".join(l["text"] for l in current),
            ))
            current = []
    
    return paragraphs
```

---

### 4.2 Layer 2 — 氛围粒子层

轻量级 Python 渲染，生成半透明叠加层：

```python
# 粒子类型 (根据歌曲氛围自动选择)
ATMOSPHERE_PRESETS = {
    "rain":     {"count": 200, "speed": 8, "angle": 85, "color": (180, 200, 255, 40)},
    "snow":     {"count": 80,  "speed": 1, "angle": 88, "color": (255, 255, 255, 60)},
    "firefly":  {"count": 30,  "speed": 0.5, "trail": True, "color": (255, 220, 100, 80)},
    "dust":     {"count": 50,  "speed": 0.3, "color": (255, 255, 255, 30)},
    "bokeh":    {"count": 15,  "radius": (20, 60), "color": "dynamic"},
    "embers":   {"count": 40,  "speed": -2, "color": (255, 140, 50, 50)},  # 上飘
}

def render_atmosphere(
    preset: str,
    duration: float,
    fps: int = 30,
    resolution: tuple = (1920, 1080),
) -> Path:
    """渲染氛围粒子层 → 透明 WebM/MOV"""
    ...
```

这层不需要 AI，纯程序生成但视觉贡献很大。

---

### 4.3 Layer 3 — 文字特效引擎

这是核心差异化层。从 alignment JSON 出发，有两条子路线：

#### 子路线 3A: PyonFX 高级 ASS (推荐 MVP)

改造现有 `subtitle.py`，增加特效模板系统：

```python
@dataclass
class EffectTemplate:
    """文字特效模板"""
    name: str
    # 字出场动画
    char_enter: str       # "fade" | "drop" | "typewriter" | "bounce" | "glow_expand"
    enter_duration: int   # 毫秒
    # 字变色方式
    color_sweep: str      # "k" (标准) | "kf" (淡入变色) | "ko" (描边先行)
    # 行出场/退场
    line_enter: str       # "fade_up" | "slide_left" | "scale_center"
    line_exit: str        # "fade_out" | "slide_up"
    # 颜色
    colors: dict          # primary, secondary, glow, shadow
    # 装饰效果
    glow: bool            # 已唱字发光
    shadow_depth: int     # 3D 阴影层数
    outline_anim: bool    # 描边动画

# 预设特效模板
EFFECT_PRESETS = {
    "clean_minimal": EffectTemplate(
        name="简约",
        char_enter="fade", enter_duration=200,
        color_sweep="kf",
        line_enter="fade_up", line_exit="fade_out",
        colors={"primary": "&H00FFFFFF", "secondary": "&H0060CFFF"},
        glow=False, shadow_depth=0, outline_anim=False,
    ),
    "neon_glow": EffectTemplate(
        name="霓虹发光",
        char_enter="glow_expand", enter_duration=150,
        color_sweep="kf",
        line_enter="scale_center", line_exit="fade_out",
        colors={"primary": "&H00FFFFFF", "secondary": "&H00FF60FF", 
                "glow": "&H6000FFFF"},
        glow=True, shadow_depth=2, outline_anim=True,
    ),
    "cinematic": EffectTemplate(
        name="电影感",
        char_enter="typewriter", enter_duration=80,
        color_sweep="k",
        line_enter="slide_left", line_exit="slide_up",
        colors={"primary": "&H00E0E0E0", "secondary": "&H0000BFFF"},
        glow=False, shadow_depth=3, outline_anim=False,
    ),
    "handwritten": EffectTemplate(
        name="手写感",
        char_enter="stroke_reveal", enter_duration=300,
        color_sweep="ko",
        line_enter="fade_up", line_exit="fade_out",
        colors={"primary": "&H00F0F0F0", "secondary": "&H0080FFFF"},
        glow=True, shadow_depth=0, outline_anim=True,
    ),
}
```

**PyonFX ASS 能实现的高级效果示例:**

```
# 1. 逐字淡入出场 (fade)
{\alpha&HFF&\t(0,200,\alpha&H00&)\k50}字

# 2. 发光效果 (已唱字外发光)
{\blur8\3c&H00FFFF&\bord5\t(0,50,\blur0\bord2)}

# 3. 弹跳出场 (bounce)
{\move(960,600,960,540)\t(0,150,1,0.5,\fscx110\fscy110)\t(150,250,\fscx100\fscy100)}

# 4. 描边先行变色 (\ko)
{\ko50}字  → 描边先变色，然后填充跟上

# 5. 3D 阴影 (多层 Dialogue 偏移)
Dialogue: 0,...,Shadow,,8,8,0,,{\c&H000000&\alpha&H80&}文字
Dialogue: 1,...,Main,,0,0,0,,{\k50}文字
```

#### 子路线 3B: Canvas 逐帧渲染 (进阶)

当 ASS 表达能力不够时，用 Python 逐帧渲染透明文字层：

```python
from PIL import Image, ImageDraw, ImageFont

def render_text_frame(
    frame_time: float,
    lines: list[AlignedLine],
    effect: EffectTemplate,
    resolution: tuple = (1920, 1080),
) -> Image:
    """渲染单帧文字层 (RGBA 透明背景)"""
    img = Image.new("RGBA", resolution, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 找到当前应显示的行
    active_lines = [l for l in lines if l.start - 0.5 <= frame_time <= l.end + 0.5]
    
    for line in active_lines:
        for word in line.words:
            progress = _calc_word_progress(word, frame_time)
            # progress: 0.0 (未唱) → 1.0 (已唱完)
            
            color = _interpolate_color(
                effect.colors["primary"], 
                effect.colors["secondary"], 
                progress
            )
            alpha = _calc_enter_alpha(word, frame_time, effect)
            glow = _calc_glow(word, frame_time, effect) if effect.glow else None
            
            _draw_word(draw, word, color, alpha, glow, effect)
    
    return img
```

性能优化: 只有文字变化的帧需要重新渲染，可做关键帧 + 插值。

---

### 4.4 Layer 4 — FFmpeg 多层合成

```bash
ffmpeg -y \
  -i background_stitched.mp4 \          # Layer 1: AI 背景 (拼接后)
  -i atmosphere.webm \                   # Layer 2: 粒子层 (透明)
  -i text_effects.mov \                  # Layer 3: 文字层 (透明) [仅 Canvas 模式]
  -i audio.mp3 \
  -filter_complex "
    [0:v][1:v]overlay=0:0[bg_atmo];
    [bg_atmo][2:v]overlay=0:0[final]
  " \
  -map "[final]" -map 3:a \
  -c:v libx264 -crf 18 -c:a aac -b:a 192k \
  output.mp4
```

如果用 PyonFX ASS 模式 (子路线 3A)，则更简单:

```bash
ffmpeg -y \
  -i background_stitched.mp4 \          # Layer 1: AI 背景
  -i atmosphere.webm \                   # Layer 2: 粒子层
  -i audio.mp3 \
  -filter_complex "
    [0:v][1:v]overlay=0:0,
    subtitles='karaoke_fx.ass'
  " \
  output.mp4
```

---

### 4.5 AI 智能化环节汇总

| 环节 | AI 做什么 | 模型 | 输入 | 输出 |
|------|----------|------|------|------|
| 歌曲分析 | 推断情绪/氛围/色调 | GPT-4o / Claude | 歌词全文 | mood, color_palette, genre |
| 场景提示词 | 为每段落生成画面描述 | GPT-4o / Claude | 段落歌词 + 歌曲情绪 | SD/DALL-E prompt |
| 背景图生成 | 生成匹配意境的画面 | SDXL / Flux / DALL-E 3 | prompt | 1920×1080 PNG |
| 背景视频 (可选) | 图片转微动视频 | Kling / Runway / AnimateDiff | 首帧图 + prompt | 4-8s MP4 |
| 氛围推荐 | 推荐粒子效果 | GPT-4o | 歌曲情绪 | preset name |
| 特效推荐 | 推荐文字特效模板 | GPT-4o | 歌曲情绪 + 风格 | template name |
| 色彩方案 | 生成协调的配色 | GPT-4o | 歌曲情绪 | hex colors |

---

## 五、实现方案 — 分阶段路线图

### Phase A: PyonFX 特效模板 + 静态 AI 背景 (MVP)

> 最小可用版本，利用现有架构，不引入新渲染引擎。

```
alignment.json
    │
    ├─→ [LLM] 分析歌词 → 情绪/色调/段落
    │
    ├─→ [LLM] 生成每段落画面提示词
    │       │
    │       └─→ [SD/DALL-E] 生成背景图 × N
    │               │
    │               └─→ [FFmpeg] Ken Burns 动画 → 拼接成背景视频
    │
    ├─→ [PyonFX] 选择特效模板 → 生成高级 ASS
    │
    └─→ [FFmpeg] 背景视频 + ASS 字幕 + 音频 → 最终 MP4
```

**新增模块:**

| 文件 | 职责 |
|------|------|
| `src/scene_gen.py` | LLM 歌词分析 + 提示词生成 + 图片 API 调用 |
| `src/effects.py` | 特效模板系统 + PyonFX ASS 生成 |
| `src/atmosphere.py` | 粒子/氛围层渲染 (可选) |
| `src/video_bg.py` | Ken Burns 动画 + 背景拼接 |
| `src/fx_compositor.py` | 多层 FFmpeg 合成 |

**新增依赖:**

```toml
[project.optional-dependencies]
fx = [
    "pyonfx>=0.11.0",       # ASS 高级特效
    "openai>=1.0",           # GPT-4o API (提示词生成)
    "httpx>=0.27",           # HTTP 客户端 (图片 API)
    "Pillow>=10.0",          # 图片处理
    "numpy>=1.26",           # 数值计算 (粒子系统)
]
```

**预估工作量:** 5-7 天

**效果预期:** 从 "KTV 点播机" → "带 AI 插画的质感 Lyric Video"

---

### Phase B: Canvas 渲染 + 氛围粒子 + AI 视频背景

> 突破 ASS 表达限制，加入粒子层和 AI 视频背景。

新增能力:
- Python Canvas 文字渲染引擎 (透明层 → FFmpeg 叠加)
- 粒子/光效氛围层
- AI 图生视频 (Kling/Runway 首帧扩展)

**预估工作量:** 7-10 天  
**效果预期:** 接近 B站 中上水准的 Lyric MV

---

### Phase C: 全自动 + Web 集成

> 集成到 SaaS 平台，用户一键生成。

- 仪表板新增 "AI 特效视频" 选项
- 上传时可选择特效模板 / 视觉风格
- Celery Worker 执行: LLM分析 → 背景生成 → 特效渲染 → 合成
- 进度条: "正在分析歌词氛围..." → "正在生成背景画面 3/8..." → "正在渲染特效..." → "合成视频中..."

---

## 六、核心数据结构设计

### 6.1 特效工程文件 (fx_project.json)

一首歌的完整特效配置，可复用/微调：

```json
{
  "version": "1.0",
  "song": {
    "title": "害怕的人",
    "alignment_json": "害怕的人_alignment.json",
    "audio": "害怕的人.mp3"
  },
  "analysis": {
    "mood": "dark, fearful, lonely",
    "genre": "dark pop",
    "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
    "tempo_bpm": 128,
    "energy_curve": [0.3, 0.5, 0.8, 0.6, 0.9, 0.4]
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
      "background_video": null,
      "ken_burns": {"zoom_from": 1.0, "zoom_to": 1.12, "pan": "left"}
    }
  ],
  "effects": {
    "template": "neon_glow",
    "overrides": {
      "glow_color": "&H6000FFFF",
      "enter_duration": 180
    }
  },
  "atmosphere": {
    "preset": "rain",
    "intensity": 0.7,
    "transitions": [
      {"at": 120.0, "to": "firefly", "duration": 3.0}
    ]
  },
  "output": {
    "resolution": [1920, 1080],
    "fps": 30,
    "codec": "libx264",
    "crf": 18
  }
}
```

### 6.2 生成流程 Pipeline

```python
class FxPipeline:
    """AI 特效视频生成管线"""
    
    async def run(self, alignment_json: Path, audio: Path, output: Path):
        # Step 1: LLM 歌词分析 (5s)
        analysis = await self.analyze_lyrics(alignment_json)
        
        # Step 2: 段落切分 (<1s)
        paragraphs = self.split_paragraphs(alignment_json, analysis)
        
        # Step 3: 生成场景提示词 (3s)
        for para in paragraphs:
            para.scene_prompt = await self.generate_scene_prompt(para, analysis)
        
        # Step 4: 生成背景图 (并行, 30-60s)
        await asyncio.gather(*[
            self.generate_background(para) for para in paragraphs
        ])
        
        # Step 5: Ken Burns + 拼接背景视频 (10s)
        bg_video = self.stitch_backgrounds(paragraphs, audio_duration)
        
        # Step 6: 生成特效 ASS / Canvas 渲染 (5-30s)
        effects_layer = self.render_effects(alignment_json, analysis)
        
        # Step 7: 氛围层渲染 (可选, 10s)
        atmosphere = self.render_atmosphere(analysis, audio_duration)
        
        # Step 8: FFmpeg 多层合成 (30-60s)
        self.composite(bg_video, atmosphere, effects_layer, audio, output)
```

---

## 七、关键问题与解答

### Q1: 为什么不直接用 AI 生成带字幕的视频?

**AI 视频模型无法精确渲染文字。** Sora/Kling/Runway 生成的画面中，文字是像素级的"画"出来的，无法保证：
- 字符正确性 (中文尤其容易错)
- 逐字时间精度 (alignment JSON 的精度是 10ms 级)
- 样式一致性 (每帧文字可能漂移)

所以必须: **AI 画背景，代码画文字，两层叠加**。

### Q2: 用户需要什么程度的控制?

分两个层级:
1. **一键模式**: 选一个预设风格 (霓虹/电影/简约/手写) → 全自动
2. **自定义模式**: 编辑 `fx_project.json` → 微调每个段落的背景/特效/氛围

### Q3: 成本怎么控制?

| 方案 | 单首歌成本 | 说明 |
|------|----------|------|
| 本地 SDXL + PyonFX | ≈ $0 | 需自有 GPU (6GB+ VRAM) |
| DALL-E 3 + PyonFX | ≈ $0.30-0.50 | ~8张图 × $0.04 |
| DALL-E 3 + Kling 视频 | ≈ $1.50-3.00 | 图片 + 视频生成 |
| 全本地 (SD + AnimateDiff) | ≈ $0 | 需 12GB+ VRAM，质量略低 |

### Q4: 与现有管线的关系?

```
现有管线 (不变):
  MP3 + TXT → Demucs → WhisperX → alignment.json → ASS → FFmpeg → MP4 (基础版)
                                        │
                                        ▼
新增 FX 管线 (可选):            alignment.json (编辑后)
                                        │
                                        ▼
                              AI 分析 + 背景生成 + 特效渲染 → MP4 (特效版)
```

alignment.json 是两条管线的 **分叉点**。编辑器编辑的结果，既可以走传统 ASS 路线出基础版，也可以走 FX 管线出特效版。

---

## 八、优先级排序

| 优先级 | 任务 | 价值 | 复杂度 |
|--------|------|------|--------|
| P0 | PyonFX 特效模板系统 (4-5 个预设) | ⭐⭐⭐⭐⭐ | 🟡 |
| P0 | LLM 歌词分析 + 背景提示词生成 | ⭐⭐⭐⭐⭐ | 🟢 |
| P0 | AI 图片生成 (SD/DALL-E) + Ken Burns | ⭐⭐⭐⭐ | 🟢 |
| P1 | 背景拼接 + 转场 (交叉淡化) | ⭐⭐⭐⭐ | 🟢 |
| P1 | FFmpeg 多层合成流水线 | ⭐⭐⭐⭐ | 🟡 |
| P1 | 氛围粒子层 (雨/雪/光斑) | ⭐⭐⭐ | 🟡 |
| P2 | AI 视频背景 (Kling/Runway) | ⭐⭐⭐⭐ | 🟡 |
| P2 | Canvas 逐帧文字渲染引擎 | ⭐⭐⭐ | 🔴 |
| P2 | Web 集成 (仪表板 + Worker) | ⭐⭐⭐ | 🟡 |
| P3 | 用户可编辑 fx_project.json | ⭐⭐ | 🟡 |
| P3 | 模板商城 / 社区分享 | ⭐⭐ | 🔴 |

---

## 九、一句话总结

> **alignment JSON 是时间轴的黄金数据 — AI 负责画面美学，代码负责文字精度，FFmpeg 负责合成。三者各司其职，叠加出专业级 Lyric MV。**
