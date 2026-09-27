# Suno2MV (M2V) 人工测试与验收操作手册 (Manual Verification & Testing Guide)

> **文档版本:** v1.0 (AI-Native MV Production System)  
> **适用版本:** Suno2MV v0.6+ (Animatic Studio, Multi-Pass Director & Multi-Track Timeline)  
> **更新日期:** 2026-09-23  
> **测试人员:** 导演、QA 工程师、全栈开发者、产品经理  
> **测试基准项目:** `output/匠心入梦/` 与本地示例工程

---

## 一、 系统架构理念与测试目的

### 1.1 核心理念转变
传统 AI 视频工具的逻辑是：`Suno 音频/歌词 -> 一个庞大 Prompt -> 直接生成 AI 视频`。这种做法导致：
1. 模型同时承担排版、字动效、构图、机位，极度不可控；
2. 视频模型直接生成中文字幕，文字糊烂变异；
3. 一句歌词切一个镜头，视听语言支离破碎，缺乏电影乐段大幕（Sequence）感；
4. 无法在生成昂贵的 AI 视频前进行视听节奏与导演方案预演。

**Suno2MV 工业化架构**的核心是 **“AI 原生影视制作系统 (AI-Native MV Production System)”**：
```text
Song (音频+歌词)
  ↓ [Song Intelligence] (BPM / 鼓点 / 乐段 / 字级对齐)
Creative Director & Sequence Planner (Pass A: 宏观 Treatment + 4~6个乐段叙事大幕 + 4大圣经)
  ↓
Shot Planner (Pass B: 微观分镜 + 景别机位 + 构图安全区契约)
  ↓
Continuity Director (Pass C: 镜头因果链 + 蒙太奇转场 + 母题视觉复沓)
  ↓
16:9 Cinema Animatic Studio (前置预演门禁: 音画双向同步 + Ken Burns 运镜 + 安全区 HUD)
  ↓
Dual-Track Decoupled Generation (双轨解耦: 画面纯净视频 + 动态排版动效)
  ↓
PromptCompilers (模型编译器: 针对 Veo / Kling / Seedance / Wan 差异化编译)
  ↓
Multi-Track Timeline Engine (NLE 多轨工程: 音频轨 + 视频轨/Take替代 + 歌词轨)
  ↓
Final Master MV (4K/1080p 工业级成片)
```

### 1.2 本手册测试范围
本手册覆盖 **从音频源导入 -> 三阶段导演生成 -> Web 监看台 Animatic 交互 -> 双轨解耦提示词 -> 多模型编译 -> 多轨时间轴组装** 的完整人工功能测试与验收流程。

---

## 二、 测试环境与前置准备

### 2.1 环境依赖项检查
在终端执行以下命令，确认环境依赖已就绪：
```bash
# 1. 确认 Python 与 uv 环境
uv --version
python3 --version

# 2. 确认音视频多媒体基础工具 (FFmpeg / ffprobe)
ffmpeg -version
ffprobe -version

# 3. 运行自动化单元测试套件，确认 59+ 项测试全绿
uv run --extra dev --extra editor pytest
```
> **通过标准**: `59 passed` 无任何 Error 或 Failure。

### 2.2 启动 Web 本地监看服务
在项目根目录启动 Local Editor 服务：
```bash
uv run python -m src.local_editor --no-browser --port 8000
```
- 控制台输出出现：`Uvicorn running on http://127.0.0.1:8000`
- 在浏览器打开：`http://127.0.0.1:8000`
- 打开浏览器开发者工具（F12 / Console 面板），准备观察网络请求与交互日志。

---

## 三、 详细测试用例与操作步骤

---

### 测试用例 1: 歌曲源统一抽象与资产探测 (`SongSource` 验证)

- **测试目的**: 验证系统能智能解析 Suno 导出目录（多轨音频/stems）或本地普通音频文件，并建立统一的输入元数据契约。
- **涉及模块**: `src/song_source.py`, `tests/test_production_architecture.py`

#### 操作步骤：
1. **场景 A (Suno 导出完整目录)**:
   - 检查或创建测试工程目录 `input/test_suno_song/`，包含 `song.wav`, `song_vocals.wav`, `song_instrumental.wav`，以及 `stems/drums.wav`。
   - 终端运行探测命令：
     ```bash
     uv run python -c "
     from src.song_source import detect_and_load_song_source
     src = detect_and_load_song_source('output/匠心入梦')
     print(f'Suno 探测成功: Title={src.title}, Vocals={src.vocals_path.exists()}, Inst={src.instrumental_path.exists()}')
     "
     ```
2. **场景 B (单音频本地文件自动降级)**:
   - 终端运行探测单个音频文件：
     ```bash
     uv run python -c "
     from src.song_source import detect_and_load_song_source
     src = detect_and_load_song_source('output/匠心入梦/匠心入梦_vocals.wav')
     print(f'单音频探测成功: Title={src.title}, HasIsolated={src.has_isolated_audio}')
     "
     ```

#### 验收标准：
- [ ] 完整 Suno 目录能自动关联人声干音、伴奏及 stems。
- [ ] 单个本地音频能自动降级处理，不抛出异常。
- [ ] `validate()` 方法校验文件真实存在性，缺失时给出清晰报错提示。

---

### 测试用例 2: 工业级三阶段 AI 导演编排 (Multi-Pass Director Engine 验证)

- **测试目的**: 验证 AI 导演分阶段（Pass A 宏观 -> Pass B 微观 -> Pass C 连续性）协同推理，破除“一句歌词一个镜头”的机械切割，形成乐段大幕和镜头图谱。
- **涉及模块**: `src/directors/creative_director.py`, `shot_planner.py`, `continuity_director.py`, `director_engine.py`

#### 操作步骤：
1. 终端执行真实工程的三阶段导演编排管道：
   ```bash
   uv run python -c "
   from pathlib import Path
   from src.storyboard_schema import AlignmentProject
   from src.director_engine import direct_project

   p = Path('output/匠心入梦/匠心入梦_alignment.json')
   proj = AlignmentProject.load_json(p)
   enriched = direct_project(proj)
   print(f'Treatment: {enriched.treatment.logline}')
   print(f'Sequences: {len(enriched.sequences)} 幕')
   print(f'Shots: {len(enriched.storyboard)} 个镜头')
   print(f'Visual Bible 角色数: {len(enriched.bibles.visual.characters)}')
   print(f'Motif 数量: {len(enriched.bibles.motifs.motifs)}')
   "
   ```

#### 验收标准：
- [ ] **Pass A 宏观企划 (CreativeDirector)**:
  - 生成 `treatment`（包含一句话故事 `logline`、视觉隐喻 `visual_metaphors`、三幕大纲 `acts`）。
  - 生成 `sequences`（通常 3~6 个乐段大幕，如序章、发展、高潮、尾声）。
  - 生成 4 大圣经：`VisualBible`, `AssetBible`, `MotifBible`, `TypographyBible`。
  - 生成 `temporal_direction` 时域张力曲线。
- [ ] **Pass B 微观分镜 (ShotPlanner)**:
  - 镜头依循音乐节拍点与乐段大幕组织，每个镜头平均时长通常在 2.0s ~ 4.5s 之间。
  - 每个镜头均具备摄影参数：`scale` (景别)、`camera_motion` (机位运镜)、`lens_mm` (焦段)。
  - 每个镜头初始化了构图安全区契约 `layout_contract` (`CompositionSafeZones`)。
- [ ] **Pass C 连续性蒙太奇 (ContinuityDirector)**:
  - 镜头间存在逻辑链：`previous_shot_id`, `next_shot_id` 自动串联。
  - 具备影视转场规格 `incoming_transition` / `outgoing_transition`。
  - 镜头包含了导演设计意图说明 `director_motivation` 与镜头衔接理由 `transition_motivation`。

---

### 测试用例 3: 16:9 Cinema Animatic 试听监看台与播放体验验证

- **测试目的**: 验证 Web 端 16:9 影院级视口渲染、Ken Burns 运镜平滑运动、双轨波形音画同步卡点播放。
- **涉及模块**: `frontend/local/storyboard.html`, `frontend/local/storyboard_editor.js`

#### 操作步骤：
1. 在浏览器访问 `http://127.0.0.1:8000/storyboard?project=output/匠心入梦/匠心入梦_alignment.json`。
2. 观察屏幕正上方的 **16:9 Cinema Animatic Viewport**。
3. 点击播放按钮或按下键盘 **空格键 (Space)**。
4. 观察画面、波形指针、字幕预览和分镜列表滚动。
5. 在下方的音频波形图上任意点击进行 **Seek (跳跃定位)**。

```text
┌──────────────────────────────────────────────────────────────┐
│  🎬 16:9 CINEMA ANIMATIC VIEWPORT                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ [Shot #01] [CU] [PushIn]               [SEQ_01: 序章]   │  │
│  │                                                        │  │
│  │               (Ken Burns 动态平滑运动)                  │  │
│  │                                                        │  │
│  │  [00:02.40 / 03:45.00]           [FPS: 30]             │  │
│  └────────────────────────────────────────────────────────┘  │
│  [▶ 播放] [📐 安全区 开关] [🤖 AI 导演提示词] [💾 保存工程]    │
└──────────────────────────────────────────────────────────────┘
```

#### 验收标准：
- [ ] **16:9 严格长宽比**: 视口强制保持 16:9 比例，两旁或上下带有专业电影信箱暗黑遮罩。
- [ ] **Ken Burns 运镜动态渲染**:
  - 当镜头运镜为 `PushIn` / `ZoomIn` 时，画面平滑放大（Scale 1.0 -> 1.15）。
  - 当镜头运镜为 `PullOut` / `ZoomOut` 时，画面平滑缩小（Scale 1.15 -> 1.0）。
  - 当镜头为 `PanLeft` / `PanRight` 时，画面呈现轻微横移。
  - 切换镜头时动效瞬间重置，无残影跳跃。
- [ ] **HUD 状态徽章**: 画面四角实时显示分镜编号（如 `#01`）、景别（如 `MCU`）、机位动作（如 `PushIn`）、所属序列（如 `SEQ_01`）、当前播放时间点与总时长。
- [ ] **音画精准卡点**: 播放进度指针到达镜头切换点时，Animatic 画面即刻精准切镜，无肉眼可察觉的音画延迟或顿挫。
- [ ] **双向联动**: 点击分镜列表卡片，播放器立即 Seek 到该镜头的 `start` 时间；波形拖拽时，视口画面即时更新为对应时间的镜头静态帧。

---

### 测试用例 4: 影视构图安全区 (Safe Zones) 与九宫格交互核验

- **测试目的**: 验证构图安全区、黄金分割三分法则网格、主体焦点十字星及歌词避让安全区可视化渲染。
- **涉及模块**: `frontend/local/storyboard_editor.js` (`renderSafeZonesOverlay`, `toggleSafeZones`)

#### 操作步骤：
1. 在监看台工具栏找到并点击 **`📐 安全区`** 切换按钮。
2. 观察 16:9 视口内部的网格叠加层。
3. 检查右侧镜头检视器 (Inspector) 中的 **“构图安全区契约 (Safe Zones Contract)”** 选项：
   - 切换主体落焦区域（如从 `center` 切换为 `center_right`）。
   - 切换排版避让区域（如勾选 `bottom_banner`、`top_banner`）。
4. 再次点击 `📐 安全区` 按钮，验证网格能够流畅隐藏与显现。

#### 验收标准：
- [ ] **三分法则网格 (Rule of Thirds)**: 视口上均匀呈现 4 条极细微半透明青色引导线（横竖各两等分三格）。
- [ ] **主体落焦点 (Subject Focal Crosshair)**: 根据该镜头的 `primary_subject_x` 与 `primary_subject_y`（默认 (0.5, 0.5) 或指定位置），在视口上绘制带动态呼吸感的金色十字十字准星标。
- [ ] **字幕避让区域 (Text Safe Region)**: 根据 `preferred_text_regions`，在画面底部（或指定方位）渲染出柔和半透明绿色的文字安全带（带文字标识 `SUBTITLE SAFE ZONE`）。
- [ ] **解耦契约直观性**: 能够直观看到主体十字星与文字避让带互不遮挡，保证后续生成的排版动效不遮挡主体人脸或核心道具。

---

### 测试用例 5: 镜头检视、导演阐述说明与参数微调

- **测试目的**: 验证导演审核员能够在 Inspector 中查看每个镜头的导演构思动机、前后连接语言，并手工调整摄影参数。
- **涉及模块**: `frontend/local/storyboard.html`, `frontend/local/storyboard_editor.js`

#### 操作步骤：
1. 在分镜列表中点击任意分镜（如第 2 个分镜）。
2. 查看右侧检视面板（Inspector）：
   - 观察序列徽章（如 `SEQ_01`）与视觉张力指示条。
   - 展开 **“🎯 导演构思与视听语法”** 折叠栏。
   - 检查：
     - **镜头设计理由 (Director Motivation)**
     - **衔接转换动势 (Transition Motivation)**
     - **转场类型 (Transition)** 下拉选择（`cut`, `dissolve`, `fade_to_black`, `whip_pan` 等）
3. 调整景别（如将 `Medium` 调整为 `CloseUp`），调整运镜（如将 `Static` 调整为 `SlowPan`）。
4. 点击检视面板下方的 **“💾 保存镜头修改”**。
5. 刷新网页，确认修改后的参数被正确持久化。

#### 验收标准：
- [ ] 导演动机与视听衔接语言显示完整清晰，帮助导演明确该镜头的戏剧功能。
- [ ] 景别、机位、镜头转场参数修改后，实时在分镜卡片和 HUD 上同步。
- [ ] 刷新后读取工程 JSON，修改内容保持一致，无数据丢失。

---

### 测试用例 6: 双轨解耦提示词体系与大模型工作流 (Dual-Track LLM Workflow)

- **测试目的**: 验证将视觉画面与歌词动效解耦为两个独立工作流，大模型提示词生成严格禁止中文字幕直接渲染，并验证回填抗溢出机制。
- **涉及模块**: `src/llm_director.py`, `src/local_editor.py` (`POST /api/project/llm-fillback`)

#### 操作步骤：
1. 在 Web 工具栏点击 **“🤖 AI 导演提示词”** 按钮打开模态窗口。
2. 观察模式下拉选择框（Mode Selector）：
   - `影视级双轨联合导演 (Dual-Track 推荐)`
   - `纯视觉分镜画面导演 (Shot Plan Only)`
   - `歌词动效排版导演 (Typography Only)`
3. 选择 **“影视级双轨联合导演”**，点击 **“生成导演提示词”**。
4. 检查生成的 Prompt 文本内容：
   - 搜索关键字 `NEGATIVE PROMPTS` 或 `NO SUBTITLES`。
   - 确认包含严禁在生成提示词中出现文字渲染的强指令：
     ```text
     "DO NOT generate any subtitles, Chinese characters, lyrics, or watermarks in video prompts."
     ```
   - 确认包含乐段大幕划分、时域张力、构图安全区、转场衔接。
5. 复制 Prompt 并在大模型（如 Claude 3.7 / GPT-4o）生成 JSON 响应（或使用测试 mock 数据）：
   ```json
   {
     "visual_bible": {
       "title": "匠心入梦·特别导演版",
       "color_palette": ["#1A365D", "#D69E2E", "#E2E8F0"]
     },
     "storyboard": [
       {
         "shot_id": 1,
         "scale": "CloseUp",
         "camera_motion": "PushIn",
         "prompt_zh": "老师傅饱经风霜的双手抚摸温润瓷土，金色彩绘笔尖泛着微光",
         "prompt_en": "Close up of an aged master craftsman gentle hands shaping wet azure porcelain clay",
         "director_motivation": "强调岁月痕迹与匠人初心，以指尖微观建立全片情感基调"
       }
     ]
   }
   ```
6. 将 JSON 粘贴到回填文本域，点击 **“确认回填至工程”**。
7. 观察回填结果日志与分镜列表变化。

#### 验收标准：
- [ ] 生成的提示词严格执行双轨解耦，画面提示词无任何中文字幕污染。
- [ ] 提示词包含相对时间戳（如 `+0.00s ~ +4.20s`），消除大模型因绝对时间戳漂移导致的认知混乱。
- [ ] 回填接口成功解析 JSON，智能合并到现有分镜中，不破坏已有音频与对齐信息。
- [ ] 回填防御了历史出现过的 `File name too long (Errno 63)` 等异常路径错误。

---

### 测试用例 7: 异构视频生成大模型提示词编译器验证 (PromptCompilers)

- **测试目的**: 验证通用的抽象分镜 `ShotPlan` 能针对不同的底层视频模型（Google Veo、Kling、ByteDance Seedance、Alibaba Wan）编译出专属的语法、参数与严苛负向词。
- **涉及模块**: `src/compilers/veo_compiler.py`, `kling_compiler.py`, `seedance_compiler.py`, `wan_compiler.py`, `src/compilers/__init__.py`

#### 操作步骤：
1. 终端运行编译器多模型输出对比测试脚本：
   ```bash
   uv run python -c "
   from src.storyboard_schema import ShotPlan, CompositionSafeZones, GlobalBibles, VisualBible
   from src.compilers import compile_shot_for_model, list_supported_compilers

   shot = ShotPlan(
       shot_id=1,
       id='shot_001',
       start=0.0,
       end=4.0,
       shot_size='MCU',
       camera_motion='slow_dolly_in',
       lens_mm=50,
       prompt_en='A ceramic master sculpting fine porcelain clay under soft window light.',
       action='指尖抚平旋转的瓷土胎壁',
       layout_contract=CompositionSafeZones(primary_subject_x=0.7, primary_subject_y=0.5)
   )
   bibles = GlobalBibles(visual=VisualBible(forbidden_elements=['modern cars', 'neon lamps']))

   for model in list_supported_compilers():
       res = compile_shot_for_model(shot, model, bibles=bibles)
       print('='*50)
       print(f'Model: {model} -> Target: {res.model_name}')
       print(f'Prompt: {res.prompt}')
       print(f'Negative: {res.negative_prompt[:80]}...')
       print(f'Extra Params: {res.extra_params}')
   "
   ```

#### 验收标准：
- [ ] **Google Veo 编译器 (`veo`)**:
  - 输出格式包含 `Cinematic style: ...`、`50mm anamorphic lens`、`MCU shot`。
  - 携带安全区视觉落焦参数：`extra_params['safe_zone']['primary_subject_zone'] == 'center_right'`。
- [ ] **Kling 编译器 (`kling`)**:
  - 输出包含快手可灵特定的镜头控制字典：`extra_params['camera_control']['zoom'] > 0`。
- [ ] **ByteDance Seedance 编译器 (`seedance`)**:
  - 精确输出目标生成时长 `duration_seconds: 4.0`，中英双语动作与视觉描述融合。
- [ ] **Alibaba Wan 编译器 (`wan`)**:
  - 包含万相特定中文视觉修辞与影调提示词，如 `MCU 景别, 50mm 镜头, slow_dolly_in 运镜`。
- [ ] **全模型负向词硬性约束**:
  - 所有模型的 `negative_prompt` **必须 100% 包含** `"text", "subtitles", "captions", "Chinese characters", "watermark"` 以及 VisualBible 设定的 `forbidden_elements`。

---

### 测试用例 8: 多轨非线性剪辑时间轴引擎验证 (`TimelineEngine`)

- **测试目的**: 验证系统在导出与合成前，将多轨资产（音轨、视频轨/静态帧/多Take、排版特效轨）组装为标准的 NLE 工业级多轨时间轴，并进行无缝完整性检查。
- **涉及模块**: `src/timeline_engine.py`, `src/storyboard_schema.py` (`MultiTrackTimeline`)

#### 操作步骤：
1. 终端运行时间轴构建与完整性自检：
   ```bash
   uv run python -c "
   from pathlib import Path
   from src.storyboard_schema import AlignmentProject, Take
   from src.timeline_engine import TimelineEngine

   proj = AlignmentProject.load_json('output/匠心入梦/匠心入梦_alignment.json')
   
   # 模拟将第 1 个分镜关联一个生成好的高精视频 Take
   proj.storyboard[0].takes = [
       Take(id='take_001_v1', shot_id=proj.storyboard[0].id, video_path='output/匠心入梦/clips/shot_001.mp4', selected=True)
   ]
   proj.storyboard[0].selected_take_id = 'take_001_v1'

   timeline = TimelineEngine.build_from_project(proj)
   summary = TimelineEngine.export_summary(timeline)
   issues = TimelineEngine.validate_integrity(timeline)

   print(f'Timeline Duration: {timeline.duration:.2f}s')
   print(f'Video Clips: {len(timeline.video_track)}')
   print(f'Shot 1 Media Source: {timeline.video_track[0].source_media_path}')
   print(f'Typography Clips: {len(timeline.typography_track)}')
   print(f'Integrity Issues: {issues}')
   "
   ```

#### 验收标准：
- [ ] **多轨分离**: 成功构建包含 `audio_tracks`、`video_track`、`typography_track` 的 `MultiTrackTimeline` 实体。
- [ ] **Take 视频平滑替换**: 未生成的镜头自动使用静态分镜卡片（`preview_image`），生成选定 Take 后的镜头无缝指向对应视频文件（如 `clips/shot_001.mp4`），时间轴物理结构保持恒定。
- [ ] **时域零缝隙校验**: `validate_integrity()` 返回空列表 `[]`，确认镜头间没有未覆盖的时间空洞（Gaps）或异常重叠（Overlaps）。
- [ ] **向下兼容性**: `len(proj.timeline)` 与 `proj.timeline[0]` 均正常工作，完全向下兼容原有合成器接口。

---

### 测试用例 9: 最终成片压制与成品视听质量验收 (Master Export)

- **测试目的**: 验证最终通过合成器与 FFmpeg 压制输出的成片视频质量，确保纯净视频与排版动效完美融合。
- **涉及模块**: `src/storyboard_renderer.py`, `src/subtitle.py`, `src/cli.py`

#### 操作步骤：
1. 执行一键压制命令（渲染 Animatic 预演工程视频）：
   ```bash
   uv run python -m src.cli render --project output/匠心入梦/匠心入梦_alignment.json --output output/匠心入梦/匠心入梦_master_animatic.mp4
   ```
2. 使用系统播放器（QuickTime / VLC / IINA）打开生成的 `匠心入梦_master_animatic.mp4`。
3. 从头至尾进行全片视听检查。

#### 验收标准：
- [ ] **画面纯净**: 原始画面中无任何大模型幻觉出现的乱码文字、字幕残影或不可读水印。
- [ ] **动效字幕**: 字幕由专业 ASS / 渲染器生成，排版优雅，字级高亮/变色与歌声演唱严格毫秒级同步。
- [ ] **视听卡点**: 音乐重拍、鼓点与乐段转换处，画面镜头切换精准对齐。
- [ ] **音画同步**: 全片从开头到尾声，人声与画面无渐进式不同步漂移现象。
- [ ] **播放流畅**: 视频在标准播放器中流畅播放，无丢帧、花屏或音视频时钟撕裂。

---

## 四、 人工测试验收 Checklist (Check-off Table)

测试人员请根据实际测试结果勾选下列验收清单：

| 模块 / 环节 | 测试项编号 | 测试验证内容 | 验收结果 (Pass/Fail) | 备注 / 审核人 |
| :--- | :--- | :--- | :--- | :--- |
| **基础环境** | TC-001 | 依赖项完整性与 59 项自动化单元测试全绿 | [ ] Pass | |
| **基础环境** | TC-002 | Web Editor 本地服务正常启动，API 探针畅通 | [ ] Pass | |
| **输入源** | TC-003 | Suno 目录多轨探测与本地单音频适配 | [ ] Pass | |
| **AI 导演** | TC-004 | Pass A 宏观 Treatment、乐段序列大幕与 4 大圣经生成 | [ ] Pass | |
| **AI 导演** | TC-005 | Pass B 微观分镜景别、机位、安全区契约生成 | [ ] Pass | |
| **AI 导演** | TC-006 | Pass C 连续性蒙太奇、镜头图谱与导演构思说明生成 | [ ] Pass | |
| **Animatic 监看** | TC-007 | 16:9 影院级视口渲染与暗黑电影信箱黑边 | [ ] Pass | |
| **Animatic 监看** | TC-008 | Ken Burns 运镜平滑运动渲染与动效重置 | [ ] Pass | |
| **Animatic 监看** | TC-009 | 音画双向同步、波形 Seek 与分镜列表联动 | [ ] Pass | |
| **安全区** | TC-010 | 三分法则辅助网格开关与渲染 | [ ] Pass | |
| **安全区** | TC-011 | 主体视觉焦点十字星与歌词避让安全区叠加显示 | [ ] Pass | |
| **安全区** | TC-012 | 检视器安全区参数修改并保存生效 | [ ] Pass | |
| **镜头检视** | TC-013 | 查看导演构思意图与前后转场动机 | [ ] Pass | |
| **镜头检视** | TC-014 | 景别、运镜、转场下拉微调与持久化保存 | [ ] Pass | |
| **双轨提示词** | TC-015 | 双轨解耦提示词生成，严格隔离文字提示词 | [ ] Pass | |
| **双轨提示词** | TC-016 | 大模型 JSON 回填容错，无文件名过长或崩溃异常 | [ ] Pass | |
| **模型编译器** | TC-017 | Veo / Kling / Seedance / Wan 专属参数与负向词隔离 | [ ] Pass | |
| **时间轴引擎** | TC-018 | MultiTrack 时间轴构建、Take 视频替换与零缝隙校验 | [ ] Pass | |
| **最终成片** | TC-019 | 最终成片无错乱内嵌字幕，音画卡点精准，播放流畅 | [ ] Pass | |

---

## 五、 常见问题排查与 FAQ

### Q1: 监看台播放时有音频但画面不动？
- **排查**: 检查分镜的 `start` 和 `end` 时间戳是否在音频时长范围内；检查该分镜的 `preview_image` 图片文件是否存在于 `output/{project}/storyboard/` 目录下。若图片丢失，可点击镜头卡片上的“重新生成分镜图”按钮。

### Q2: 大模型回填提示 `File name too long (Errno 63)`？
- **排查**: 确认代码已使用最新版本。旧版曾发生将大模型整段提示词误传为文件名的异常，现已在 `src/local_editor.py` 与 `src/storyboard_schema.py` 中增加了对路径长度和文件存在的安全校验。

### Q3: 为什么生成的视频提示词里严禁写中文字幕？
- **排查**: 现阶段视频生成大模型（如 Runway Gen-3、Sora、Kling、Veo、Wan）在渲染复杂中文汉字时极易产生笔画扭曲、乱码或伪文字。Suno2MV 采用影视工业正规方案：画面模型仅负责纯净视听画面；中文排版与动态字效由专门的 ASS / 渲染引擎在上层独立绘制，通过安全区避让契约实现完美融合。

### Q4: 想要重新对某一个镜头重绘不同画风，如何操作？
- **排查**: 在监看台中选中该镜头，在 Inspector 中修改 `prompt_en` 或构图参数，点击单镜重新渲染，系统会生成新的 Take 候选供比对。
