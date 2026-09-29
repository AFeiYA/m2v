# 《m2v 运动设计与动画生成生产白皮书 (MOTION_GUIDE.md)》
> **m2v: Motion Design, Kinetic Typography & Codegen Safety Guidelines**  
> *Target Audience: AI Agents (Claude, GPT, Gemini), Motion Designers & Core Engineers*  
> *Version: 1.0.0 | Date: 2026-09-29*

---

## 1. 核心综述 (Overview)

本白皮书是 `suno2MV` (m2v) 的核心执行契约。所有自主编程 Agent（如使用 Claude Code、Codex）在生成分镜数据、编写动态 Scene 代码、或配置预设时，**必须严格遵守本规范中的全部 10 项铁律**。

任何违反本规范的代码或数据均被视为非法输入并将在质检（QA）阶段被自动拦截。

---

## 2. 生产管线 10 大铁律 (The 10 Golden Rules)

### 规则 1：时间绝对纯函数法则 (Time Contract)
- **铁律**：每一帧必须是时间 $t$（以秒为单位的绝对浮点数）的纯函数：
  $$\text{Frame} = F(t, \text{scene}, \text{assets}, \text{seed})$$
- **严禁**：严禁在渲染循环内部跨帧累加内部状态（例如 `time += dt` 或 `x += speed`）。
- **判定标准**：无论执行 `renderAt(14.25)` 一千次，还是按倒序 `renderAt(20.0) -> renderAt(5.0)` 调用，得到的画面像素和图层状态必须 100% 绝对一致。

### 规则 2：确定性伪随机法则 (Seeded Determinism)
- **铁律**：严禁在运动、微倾角、粒子生成中使用裸 `Math.random()`！
- **正确做法**：必须使用基于作用域标识符的哈希伪随机发生器：
  ```javascript
  const seed = `${scene_id}:${phrase_id}:${word_id}`;
  const rotation = seededRandom(seed, -6.0, 6.0); // 确定性范围在 -6° 到 +6°
  ```
- **目的**：确保用户在时间轴反复拖拽（Scrubbing）寻道或截帧对比时，字体与粒子绝对不产生抽搐和突变。

### 规则 3：双时钟主从解耦法则 (Dual-Clock Transport)
- **实时预览 (Preview Mode)**：
  - 音频是绝对主时钟（Master Clock），动效是绝对从时钟（Slave Motion）；
  - `renderAt(wavesurfer.getCurrentTime())`；严禁动效自己跑内部定时器。
- **离线导出 (Export Mode)**：
  - 抛弃物理时间，按严格的帧号步进：`t = frame_index / FPS`；
  - 无论单帧渲染需要 5ms 还是 3 秒，导出的成片在时间轴上绝不掉帧、绝不漂移。

### 规则 4：状态求值与渲染介质解耦法则 (State Decoupling)
- **铁律**：运动预设（Preset）只负责数学计算，严禁直接操作 DOM 或直接写画布。
- **契约定义**：
  ```typescript
  interface MotionState {
    x: number;          // 像素或百分比偏移
    y: number;
    scale: number;      // 1.0 为原始基准
    rotation: number;   // 旋转角度 (度)
    opacity: number;    // 0.0 ~ 1.0
    blur: number;       // 像素高斯模糊半径
    fontWeight: number; // 100 ~ 900
    letterSpacing: string;
    color: string;
    backgroundColor?: string;
  }
  ```
- **优势**：同一个预设可以零修改地同时驱动前端 DOM 实时预览、Canvas 离线截图、以及无头 Worker 导出。

### 规则 5：词组分块与强调权重法则 (Phrase Chunking & Emphasis)
- **铁律**：文字动效严禁按整句（Line）死板呈现，也严禁按单字（Char）碎裂闪烁；
- **分块粒度**：按听觉呼吸切分成 2~4 个汉字（或 1~3 个英文单词）的短语块（Phrase）；
- **强调权重 (`emphasis: 0.0 ~ 1.0`)**：
  - 弱音词 (`emphasis < 0.4`)：保持轻量细体，位移平缓；
  - 强音词 (`emphasis > 0.8`)：触发字重突变（Heavy/Black）、微镜头震荡与荧光色块高亮。

### 规则 6：构图安全区协议 (Composition Safe Zones)
- **铁律**：动感文字和贴纸图层永远不得侵入画面的**主体保护区（Protected Regions）**；
- 必须根据 `layout_contract.primary_subject_zone`（如 `center_right`）自动将文字排版避让锚定在推荐安全区（如 `bottom_left` 或 `vertical_left`）。

### 规则 7：底层视觉资产的零文字污染 (Zero-Text Mandate)
- **铁律**：在为底层 AI 图像/视频生成提示词（FLUX / Veo / LTX）时，**绝对严禁包含任何 `text, subtitles, words, letters, lyrics` 词汇**；
- 一切文字、排版、卡片由代码层确定性绘制，底模只负责纯粹的物理光学与三维实体。

### 规则 8：音乐物理动力学咬合 (Music-Driven Physics)
- 动效的物理参数（弹性阻尼、缩放回弹、粒子扩散速度）应当动态读取 `audio.json` 中的声学特征：
  - 遇到底鼓/瞬态（Kick / Onset）：触发 `scale_punch` 与瞬态微晃动；
  - 遇到副歌高能量区（High RMS Energy）：提高色块饱和度与字符错位位移幅度。

### 规则 9：动态代码生成的安全沙箱 (Codegen Safety Sandbox)
当大模型在 **Level 4** 动态生成自定义 `Scene` 类时，必须遵从：
1. 必须继承标准基类 `BaseMotionScene` 并实现 `evaluate(t)`；
2. 严禁修改全局原型链或污染外部作用域；
3. 画布绘制前后必须对称执行 `ctx.save()` 与 `ctx.restore()`；
4. 资源加载失败时必须具备 Fallback 保底机制（自动回退到极简文本预设）。

### 规则 10：视觉质检联络图机制 (Contact Sheet Visual QA)
- 在任何长篇 MV 最终压制之前，Agent 必须自动生成关键帧矩阵图（Contact Sheet Strip）；
- 抽样检查：
  - 是否有文字重叠或溢出屏幕边缘；
  - 是否有对比度过低导致不可读的情况；
  - 是否有安全区穿透。

---

## 3. 标准预设数学定义 (Standard Preset Math Specs)

### 3.1 `swiss_minimal` (瑞士先锋大字呼吸流)
- **适用场景**：流行、R&B、电子、独立民谣
- **字号定位**：`fontSize: clamp(48px, 8vw, 120px)`，极简无衬线字体；
- **进场缓动**：$t \in [0, 0.25]$，采用 `cubic-bezier(0.16, 1, 0.3, 1)`（超平滑物理减速）；
- **字重突变**：进入激活瞬态时，`fontWeight` 从 300 跃迁至 900；
- **退场**：被下一个词组沿 Y 轴向上推挤滑出（Stagger Slide），同时 `opacity` 衰减。

### 3.2 `street_pop` (潮流贴纸与荧光色块)
- **适用场景**：说唱 (Rap/Trap)、快节奏流行、摇滚
- **旋转微倾**：`rotation = seededRandom(cue_id, -6, 6)`；
- **弹性下砸**：进场伴随 Overshoot 回弹（`scale: 1.25 -> 1.0`）；
- **底色包裹**：词组背后带有粗黑描边（`text-stroke: 4px #000`）或荧光黄底色块（`background: #FFE600`）。

### 3.3 `neon_glow` (赛博复古流光与景深虚实)
- **适用场景**：复古合成器波 (Synthwave)、慢板抒情、赛博主题
- **流光扫字**：文字透明度保持 0.4，随 `t` 推进在当前字形笔画上叠加移动的线性光斑（Linear Gradient Mask）；
- **焦平面切换**：非当前词组施加 `filter: blur(8px)` 高斯虚化，当前词组恢复 0px 极度锐利。

---
*本规范即日起生效，作为 m2v 生产管线的全局强制标准。*
