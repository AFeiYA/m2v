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

LLM 返回 `motion-line-response-v1`：`source_signature`、`base_cue_signature` 原样返回，`cue` 只引用目标句。`cue.groups` 的每组包含 `text`、`word_indices`、`action`、`emphasis` 和 `intensity`，不包含 start/end。actions 仅 reveal/push/settle/hold。索引必须顺序、完整、唯一地覆盖原字词；词组文字必须匹配引用文本；whole_line_visible 必须为 true。

校验/应用请求：

```json
{
  "project_id": "04tuZiDongV1/04tuZiDongV1_alignment.json",
  "line_id": "line_0013",
  "response": { "这里放上述接口提示词所要求的完整 LLM 返回 JSON": "不要把请求包装层交给 LLM" }
}
```

这里的 `response` 示例仅说明包装位置，不是合法导演响应。实际响应形状见 input 接口返回的 `response_example` 或 `examples/rabbit-hole-line-response.json`。

校验返回 `valid`、`applied`、`cue`、`compiled_groups`、`plan`；编译后的 start/end 只从原字词计算。422 表示数据/引用/范围错误；409 表示目标句在生成提示词后已修改、被锁定或原方案已移除。其他句子在此期间的修改不会被覆盖。应用成功后再次使用同一旧响应可能得到 409，需要重新获取输入。

## 整曲接口

保留 POST `/api/motion/director/input` 生成整曲提示词，新增 POST `/api/motion/director/validate` 无副作用校验，PUT `/api/motion/plan` 保存。请求同样支持 `instruction` 创作偏好。整曲方案仍需覆盖所有有效句，锁定条目及随机种子保持不变。

## 提示词与能力边界

提示词约束统一：整句作为一个场景保留，LLM 理解语义后分 1–6 组，空格仅作为提示；短组使用简洁动作，长音允许缓慢运动；音乐响应服从歌词时间。不把逐字重击当作所有句子的默认表达。

现有运行能力是平面词组突出、揭示、回位、停留，加 pdoom 后处理。三维字组、隧道、景深仍属于后续渲染模板；提示词不会引导 LLM 返回不存在的模板。原 `spatial-direction-draft-v1` 样例仍是空间设计草案，新的单句响应样例可被当前接口校验/应用。
