# 动效导演接口：整曲与单句

第一版直接使用用户选择的外部 LLM：生成提示词 → LLM 返回 JSON → 只校验 → 应用保存 → 同引擎预览/MP4。服务不自动发送原曲、歌词或账号密钥。

## 单句接口

所有请求使用 `Content-Type: application/json`，歌曲 ID 为扫描目录内的相对工程路径，如 `04tuZiDongV1/04tuZiDongV1_alignment.json`。

| 接口 | 功能 | 是否保存 |
|---|---|---|
| POST `/api/motion/director/line/input` | 单句上下文、提示词、JSON Schema、可校验的响应样例 | 否 |
| POST `/api/motion/director/line/validate` | 校验返回方案，绑定 alignment 时间，返回词组时间与合并预览方案 | 否 |
| POST `/api/motion/director/line/apply` | 再次校验并合并到最新方案，只替换目标句 | 是 |

输入请求：

```json
{
  "project_id": "04tuZiDongV1/04tuZiDongV1_alignment.json",
  "line_id": "line_0013",
  "style": "impact",
  "instruction": "整句保留，按词组突出兔子洞，否定转折落在没有，成功作为结尾强调"
}
```

响应提供 `input`、`prompt`、`response_example`、`can_apply`、`warnings`。`input.target.words[].word_index` 是当前句的零基字词索引；同时提供实际起止时间、拍点、平均能量、相邻句与已有方案。

LLM 返回 `motion-line-response-v1`：`source_signature`、`base_cue_signature` 原样返回，`cue` 只引用目标句。新提示词仅返回 `cue.poster.nodes`，不输出旧的 groups/template 等兼容字段。节点完整引用原字词，设计层级、入场与驻留，不填写坐标或 start/end。旧格式仍可读取。

校验/应用请求：

```json
{
  "project_id": "04tuZiDongV1/04tuZiDongV1_alignment.json",
  "line_id": "line_0013",
  "response": { "这里放上述接口提示词所要求的完整 LLM 返回 JSON": "不要把请求包装层交给 LLM" }
}
```

这里的 `response` 示例仅说明包装位置，不是合法导演响应。实际响应形状见 input 接口返回的 `response_example` 或 `examples/rabbit-hole-line-response.json`。

校验返回 `valid`、`applied`、`cue`、`compiled_nodes`（兼容别名 compiled_groups）、`plan`；编译后的 start/end 只从原字词计算。422 表示数据/引用/范围错误；409 表示目标句在生成提示词后已修改、被锁定或原方案已移除。其他句子在此期间的修改不会被覆盖。应用成功后再次使用同一旧响应可能得到 409，需要重新获取输入。

## 整曲接口

保留 POST `/api/motion/director/input` 生成整曲提示词，新增 POST `/api/motion/director/validate` 无副作用校验，PUT `/api/motion/plan` 保存。请求同样支持 `instruction` 创作偏好。整曲方案仍需覆盖所有有效句，锁定条目及随机种子保持不变。

## 提示词与能力边界

提示词约束统一：整句作为一个场景保留，LLM 理解语义后分 1–6 组，空格仅作为提示；短组使用简洁动作，长音允许缓慢运动；音乐响应服从歌词时间。不把逐字重击当作所有句子的默认表达。

Studio 使用 Remotion 执行逐块入场、落位、驻留与 cut/fade；pdoom 保留在实验链路。三维字组、隧道、景深仍属于后续渲染模板；提示词不会引导 LLM 返回不存在的模板。原 `spatial-direction-draft-v1` 样例仍是空间设计草案，新的单句响应样例可被当前接口校验/应用。

## 海报导演：先意图，再编译

整曲与单句提示词现在使用同一海报规划约束。整曲返回 `visual_language`（整曲方向、背景/前景/强调色、节奏语言）；每个未锁定 cue 必须返回 `poster`。锁定 cue 原样保留。LLM 输出 Schema 要求海报字段；持久化与读取仍兼容没有海报的旧方案。

`poster.version=motion-poster-direction-v1`，`status=draft`。这是语义设计稿，不是已编译的像素排版，与静态样例 `motion-poster-v1` 区分：

- `layout`：hero-stack / center-stack / staggered，仅选择排版规则。
- `nodes`：原文字词引用、primary/secondary/support 层级（必须且只有一个 primary）、强调词、foreground/accent/muted 色彩角色。
- `entrance`、`settle_fraction`：入场策略与相对时长比例；不输出绝对时间。
- `visibility=cumulative`、`final_hold=available-tail`：进入后保留，使用原时间轴可用尾部阅读，不拉长歌曲。
- `transition_out=cut/fade` 与 `transition_note`：句间衔接策略。

坐标、尺寸、字号、旋转角度与执行代码不属于 LLM 协议，会被拒绝。排版编译器读取意图，按实际字体、画幅、安全区与包围盒计算几何；运动绑定器读取 alignment 生成可执行时间。海报预览、Remotion Player 与 MP4 使用同一编译器与节点时间。status=draft 表示导演源数据，不表示不能执行。

Studio 现使用 React / Remotion 4.0.530。Canvas 测量文字，SVG 文本按编译包围盒绘制；节点由帧号驱动位置、透明度和缩放。服务器通过 @remotion/renderer 输出视频，再用 FFmpeg 合成原曲。原 Canvas/Three.js 导出脚本仍供实验与兼容验证。

### 句界规范

一个有效 alignment `line_id` 对应一个 cue、一张最终海报。普通空格、全角空格、逗号只辅助理解语义，不会产生新海报；词组是时间激活单位，节点是同一海报内部排版对象。导演先理解整句，再说明节点之间的对照/转折等视觉关系。句间转场只发生在 line_id 之间。“天花板在脚下　地板在云端抽离”的单句提示词样例见 `examples/ceiling-floor-line-prompt.txt`。


## 驻留与速度约束

节点可设置 hold=none/drift、beat_reaction=none/pulse；pulse 仅允许 primary。微动在整句节点落位后开启，drift 振幅为画布高度 0.2%，pulse 最大 1.2% 缩放。超过 6 字/秒的句子、短于 0.16 秒的节点会把位移/缩放入场降级为淡入；密集句关闭驻留与回弹。支持固定段落与平均能量作为导演依据，尚无可靠音高、音色、混响或延迟尾部提取，提示词禁止臆造这些数据。

整曲提示词加入八条全局原则（阅读地图、语义权重、发声触发、余响阅读、句内连续、密度克制、高潮对比、归位终态）。LLM 负责意图；代码负责时间锚点、幅度和几何边界。尚不支持未唱文字的低对比预显示、跨句推挤或真实声学尾响绑定。

## 歌词语义关系

`poster.relations` 可省略（旧方案默认 `[]`），每项包含 `kind`、`node_indices`、`intent`。kind 为 guidance/contrast/negation/repetition/spatial，分别表示引导、对照、否定、重复、空间意象。引用从零开始的 `poster.nodes` 索引，不是 alignment 的 word_indices。引用必须存在、唯一；引导按阅读引导方向排列，引导/对照至少引用两个节点；其他关系可在一个文字块内部。没有明确关系时为空，不能强行凑齐五类。校验只保证引用和协议正确，语义判断仍由导演与人工复核。

关系作为导演意图保存、导入、下载，并在 Studio 逐句调整区展示。当前不会自动改变排版或新增动画，也不接受坐标、时间或任意代码。旧无关系方案的单句签名保持不变；添加或修改关系会更新签名，防止旧返回覆盖新意图。具体五节点示例见 `examples/rabbit-hole-line-response.json`。

Studio 的 cut/fade 已接入按下一句起点编译的有限驻留与交接，原 end 不变，详见 motion-studio-director.md。横竖屏无需另写导演数据，竖屏几何由编译器生成。
