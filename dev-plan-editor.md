# 卡拉OK时间轴编辑器 — 开发计划

## 一、目标

在现有 pipeline 基础上，加一个 **本地 Web 编辑器**，让用户可以：

1. **看到** 波形 + 歌词字符的时间位置
2. **听到** 任意区间的音频回放，歌词实时高亮
3. **拖拽** 调整每个字/行的时间边界
4. **保存** 后一键重新生成 ASS / 视频

## 二、技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | **FastAPI + Uvicorn** | 轻量，async 友好，Python 生态统一 |
| 前端 | **单页 HTML + Vanilla JS** | 零构建工具，`frontend/` 文件夹直接 serve |
| 波形 | **WaveSurfer.js 7.x** | 浏览器波形渲染标杆，自带 Regions 插件 |
| 音频 | 原始 MP3 / 分离 vocals.wav | 通过 HTTP Range 流式传输 |
| 数据 | `alignment.json` (现有格式) | 唯一数据源，不引入新格式 |

新增依赖放 `[project.optional-dependencies]`，核心 pipeline 不受影响：

```toml
[project.optional-dependencies]
editor = ["fastapi>=0.115", "uvicorn[standard]>=0.32"]
```

## 三、数据契约

唯一编辑对象：`output/{stem}_alignment.json`

```jsonc
{
  "lines": [
    {
      "text": "影子在墙上 张开贪婪的巨口",   // 显示文本（只读）
      "start": 35.343,                      // 行起始 = words[0].start
      "end": 43.305,                        // 行结束 = words[-1].end
      "words": [
        { "word": "影", "start": 35.343, "end": 35.703 },
        { "word": "子", "start": 35.703, "end": 35.843 },
        // ... 标点 start==end (零时长)
      ]
    }
  ]
}
```

**不变量（保存时校验）：**
- `words[i].end == words[i+1].start`（行内连续）
- `line.start == words[0].start`, `line.end == words[-1].end`
- 行间允许间隙（段落间奏）

## 四、系统架构

```
┌───────────────────────────────────────────────────────┐
│               浏览器  http://localhost:8765            │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  WaveSurfer.js 全曲波形                         │  │
│  │  ├─ 可缩放/滚动                                 │  │
│  │  └─ Regions 标注每行的 start~end 范围           │  │
│  ├─────────────────────────────────────────────────┤  │
│  │  选中行 → 字级时间轴                            │  │
│  │  每个字 = 一个可左右拖拽的色块                   │  │
│  │  拖拽字边界 → 自动级联相邻字                     │  │
│  ├─────────────────────────────────────────────────┤  │
│  │  操作区                                         │  │
│  │  [▶ 播放选区] [⏪-50ms] [⏩+50ms] [↩ 撤销]     │  │
│  │  [💾 保存] [🔄 重新生成 ASS] [📹 重新生成视频]  │  │
│  └─────────────────────────────────────────────────┘  │
└──────────────┬───────────────────────┬────────────────┘
               │ REST API              │ GET audio
               ▼                       ▼
┌──────────────────────────────────────────────────────┐
│        FastAPI  (src/editor_server.py)                │
│                                                      │
│  GET  /api/songs                → [{stem, has_audio}]│
│  GET  /api/songs/{stem}/align   → alignment JSON     │
│  PUT  /api/songs/{stem}/align   → 校验+保存 JSON     │
│  GET  /api/songs/{stem}/audio   → 流式音频           │
│  POST /api/songs/{stem}/regen   → 调后端生成 ASS/MP4 │
│                                                      │
│  GET  /                         → frontend/index.html│
│  GET  /static/...               → 前端静态资源       │
└──────────────────────────────────────────────────────┘
               │
               ▼  读写文件
    output/{stem}_alignment.json   (数据)
    input/{stem}.mp3               (音频)
    output/{stem}.ass              (生成物)
    output/{stem}.mp4              (生成物)
```

## 五、分期开发计划

### Phase 1 — 可视化预览（2 天）

> 目标：能看波形、看歌词位置、播放验证

**后端：**
- [ ] `src/editor_server.py` — FastAPI 应用
  - `GET /api/songs` 扫描 output 目录，返回所有 `*_alignment.json` 对应的 stem
  - `GET /api/songs/{stem}/align` 读取并返回 alignment JSON
  - `GET /api/songs/{stem}/audio` 用 `FileResponse` 流式返回 MP3
  - 静态文件挂载 `frontend/`
- [ ] `src/main.py` 添加 `m2v edit` 子命令，启动 uvicorn

**前端：**
- [ ] `frontend/index.html` — 单页应用骨架
- [ ] `frontend/app.js` — 核心逻辑
  - 加载 WaveSurfer.js (CDN)，渲染全曲波形
  - 用 Regions 插件为每行歌词画出色带
  - 左侧歌词列表：点击某行 → 波形跳转 + 高亮
  - 播放按钮：播放选中行的区间
- [ ] `frontend/style.css` — 简洁暗色主题

**验收标准：**
- 浏览器打开 `localhost:8765`，能看到波形 + 37 行歌词色带
- 点歌词能跳到对应位置播放
- 播放时当前字高亮

---

### Phase 2 — 拖拽编辑 + 保存（2 天）

> 目标：可以调整时间并保存

**后端：**
- [ ] `PUT /api/songs/{stem}/align` — 接收编辑后 JSON
  - 校验不变量 (连续性、start/end 一致性)
  - 写入前自动备份 `*_alignment.json.bak`
  - 写入新文件

**前端：**
- [ ] **行级拖拽**：WaveSurfer Regions 的 drag/resize → 更新 `line.start/end`
  - 行缩放时，内部字等比缩放
- [ ] **字级拖拽**：选中行后展开字级时间轴
  - 每个字 = 一个色块，拖拽边界
  - 拖字的右边界 = 同时移动下一字的左边界（保持连续）
  - 标点（零时长）不可拖，跟随前一字
- [ ] **微调按钮**：选中字后 `←→` 键或按钮 ±10ms / ±50ms
- [ ] **保存按钮**：PUT 到后端，显示成功/失败提示
- [ ] **Undo/Redo**：内存中保存 JSON 快照栈（最多 50 步）

**验收标准：**
- 拖拽字边界后相邻字自动跟随
- 保存后刷新页面数据一致
- Ctrl+Z 可撤销

---

### Phase 3 — 重新生成 + 预览（1 天）

> 目标：一键从编辑后 JSON 生成 ASS/视频

**后端：**
- [ ] `POST /api/songs/{stem}/regen` — 后台任务
  - 参数：`{ "mode": "ass" | "video" }`
  - 调用现有 `generate_ass()` / `compose_video()`
  - 返回状态 + 文件下载链接
- [ ] 复用 `--alignment-json` 已有逻辑，无需修改 pipeline 核心

**前端：**
- [ ] "重新生成 ASS" 按钮 → 调接口 → 下载 .ass
- [ ] "重新生成视频" 按钮 → 调接口 → 进度提示 → 下载 .mp4
- [ ] （可选）内嵌视频播放器直接预览生成的 MP4

**验收标准：**
- 编辑 → 保存 → 重新生成 ASS → 用外部播放器验证字幕对齐
- 全流程不需要命令行操作

---

### Phase 4 — 体验优化（持续）

- [ ] **智能吸附**：拖拽时自动吸附到波形能量突变点（onset detection）
- [ ] **批量偏移**：选中多行/多字，整体 ±Nms
- [ ] **快捷键**：Space 播放/暂停，J/K 上/下行，A/D 选中字 ←→
- [ ] **minimap**：波形上方显示全曲缩略图 + 当前视口位置
- [ ] **多歌曲切换**：侧边栏列表，支持多个 stem
- [ ] **自动分段着色**：根据 `paragraph` 字段给不同段落不同底色

## 六、文件结构（新增部分）

```
e:\m2v\
├── frontend/                    # 新增: 前端静态文件
│   ├── index.html               # 单页应用
│   ├── app.js                   # 核心逻辑 (~500行)
│   ├── style.css                # 样式
│   └── lib/                     # 第三方 JS (也可用 CDN)
│       └── wavesurfer.min.js
├── src/
│   ├── editor_server.py         # 新增: FastAPI 后端
│   ├── main.py                  # 修改: 添加 edit 子命令
│   └── ...                      # 不变
└── pyproject.toml               # 修改: 添加 [editor] optional deps
```

## 七、API 详细设计

### `GET /api/songs`
```json
[
  {
    "stem": "害怕的人",
    "has_alignment": true,
    "has_audio": true,
    "lines_count": 37,
    "duration": 388.2
  }
]
```

### `GET /api/songs/{stem}/align`
直接返回 `alignment.json` 原文。

### `PUT /api/songs/{stem}/align`
请求体 = 编辑后的完整 alignment JSON。  
校验规则：
1. 每行 `words` 非空
2. 行内 `words[i].end == words[i+1].start` (容差 ±1ms)
3. `line.start == words[0].start`, `line.end == words[-1].end`
4. 所有时间值 ≥ 0

失败返回 `422` + 错误详情。  
成功返回 `200` + `{ "backup": "xxx.bak" }`。

### `GET /api/songs/{stem}/audio`
`Content-Type: audio/mpeg`，支持 `Range` 请求。

### `POST /api/songs/{stem}/regen`
```json
// Request
{ "mode": "ass" }      // 或 "video"

// Response (成功)
{
  "status": "ok",
  "file": "害怕的人.ass",
  "download": "/api/songs/害怕的人/download/ass"
}
```

## 八、关键设计决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 前端构建工具 | **无** (Vanilla JS) | 项目小，一个 HTML 搞定；避免 node/npm 依赖 |
| 数据格式 | 沿用 `alignment.json` | 不引入新格式，pipeline 零改动 |
| 编辑粒度 | 字级 + 行级 | 字级是必须的（卡拉OK核心），行级方便批量操作 |
| 字间连续性 | 前端拖拽时强制保持 | 拖A字右边界 = 拖B字左边界，不允许行内间隙 |
| 备份策略 | 每次保存自动 `.bak` | 简单可靠，避免误操作 |
| Pipeline 集成 | 通过 `--alignment-json` | 现有 CLI 已支持，后端直接调用 |

## 九、开发顺序建议

```
Phase 1 (预览) ──→ Phase 2 (编辑) ──→ Phase 3 (生成) ──→ Phase 4 (优化)
     2天                 2天                1天              持续
```

**建议从 Phase 1 开始**：先做出能看波形 + 歌词的页面。  
能看到问题在哪，比盲调 JSON 效率高十倍。  
Phase 2 的拖拽编辑是核心价值，但要求 Phase 1 的基础。

**启动命令（最终形态）：**
```bash
# 安装编辑器依赖
pip install -e ".[editor]"

# 启动编辑器
m2v edit --input ./input --output ./output --port 8765
# → 浏览器打开 http://localhost:8765
```
