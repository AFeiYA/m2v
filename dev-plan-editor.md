# 卡拉OK时间轴编辑器 — 开发计划

> **状态:** Phase 1-3 ✅ 已完成，已统一到 SaaS 架构 | **更新日期:** 2026-03-29

## 一、目标

在现有 pipeline 基础上，提供 **Web 可视化时间轴编辑器**，让用户可以：

1. **看到** 波形 + 歌词字符的时间位置
2. **听到** 任意区间的音频回放，歌词实时高亮
3. **拖拽** 调整每个字/行的时间边界
4. **保存** 后一键重新生成 ASS / 视频

> ⚠️ **架构说明 (v2.0):** 编辑器不再作为独立服务，而是作为 `APIRouter` 挂载到统一的 `api_server.py`
> 中，共享认证/存储/数据库层。前端通过 `task_id` 访问文件，不再直接读写本地目录。

## 二、技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | **FastAPI APIRouter** (挂载到 api_server) | 与 SaaS API 共享认证/存储/DB，单端口服务 |
| 前端 | **单页 HTML + Vanilla JS** | 零构建工具，`frontend/` 文件夹直接 serve |
| 波形 | **WaveSurfer.js 7.x** | 浏览器波形渲染标杆，自带 Regions 插件 |
| 音频 | 通过存储层 API 获取 | 带 Bearer token 认证 |
| 数据 | `alignment.json` (现有格式) | 唯一数据源，通过 task_id 访问 |
| 认证 | JWT Bearer Token | 与仪表板共享 token (localStorage) |

依赖已合并到 `[project.optional-dependencies] web` 中，不再单独维护 `editor` extra。

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
│               浏览器  http://localhost:8000/editor       │
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
               │ REST API (Bearer)     │ GET audio
               ▼                       ▼
┌──────────────────────────────────────────────────────┐
│     api_server.py :8000 — 统一入口                    │
│     └─ editor_server.py (APIRouter, prefix=/api/editor) │
│                                                      │
│  GET  /api/editor/songs         → [用户的可编辑任务]  │
│  GET  /api/editor/tasks/{id}/align  → alignment JSON  │
│  PUT  /api/editor/tasks/{id}/align  → 校验+保存 JSON  │
│  GET  /api/editor/tasks/{id}/audio  → 音频流           │
│  POST /api/editor/tasks/{id}/regen  → 生成 ASS/MP4    │
│                                                      │
│  ✅ 所有路由 Depends(get_current_user) 认证            │
│  ✅ 文件读写通过 storage 抽象层 (Local/S3)            │
│  ✅ 按 task_id + user_id 文件隔离                     │
└──────────────────────────────────────────────────────┘
               │
               ▼  存储层 (storage.py)
    uploads/{task_id}/input.mp3       (音频)
    results/{task_id}/alignment.json  (数据)
    results/{task_id}/output.ass      (生成物)
    results/{task_id}/output.mp4      (生成物)
```

## 五、分期开发计划

### Phase 1 — 可视化预览 ✅ 已完成

> 目标：能看波形、看歌词位置、播放验证

**后端：**
- [x] `src/editor_server.py` — APIRouter 挂载到 api_server
  - `GET /api/editor/songs` 列出用户可编辑任务
  - `GET /api/editor/tasks/{id}/align` 读取 alignment JSON
  - `GET /api/editor/tasks/{id}/audio` 音频流
  - 所有路由带 JWT 认证 + 用户隔离
- [x] `src/api_server.py` 包含 editor_router，服务统一在 :8000
- [x] `src/main.py` `m2v serve` 子命令启动统一服务

**前端：**
- [x] `frontend/index.html` — 单页应用骨架 + token 守卫
- [x] `frontend/app.js` — WaveSurfer.js 波形 + Regions 行级色带 + Bearer 认证
- [x] `frontend/style.css` — 暗色主题

**验收标准：**
- 浏览器打开 `localhost:8765`，能看到波形 + 37 行歌词色带
- 点歌词能跳到对应位置播放
- 播放时当前字高亮

---

### Phase 2 — 拖拽编辑 + 保存 ✅ 已完成

> 目标：可以调整时间并保存

**后端：**
- [x] `PUT /api/editor/tasks/{id}/align` — 接收编辑后 JSON
  - 校验不变量 (连续性、start/end 一致性)
  - 写入前自动备份 `.bak`
  - 通过存储层读写，支持 Local/S3

**前端：**
- [x] **行级拖拽**：WaveSurfer Regions drag/resize
- [x] **字级拖拽**：拖边界自动级联相邻字
- [x] **微调按钮**：±10ms / ±50ms
- [x] **保存**：PUT 到后端，带 Bearer token
- [x] **Undo/Redo**：JSON 快照栈 (50步)

**验收标准：**
- 拖拽字边界后相邻字自动跟随
- 保存后刷新页面数据一致
- Ctrl+Z 可撤销

---

### Phase 3 — 重新生成 + 预览 ✅ 已完成

> 目标：一键从编辑后 JSON 生成 ASS/视频

**后端：**
- [x] `POST /api/editor/tasks/{id}/regen` — 重新生成
  - 参数：`{ "mode": "ass" | "video" }`
  - 下载 alignment → 生成 ASS → 上传结果
  - 通过存储层读写，结果可从仪表板下载

**前端：**
- [x] “重新生成 ASS” 按钮 → 调接口
- [x] “重新生成视频” 按钮 → 调接口 + 进度提示

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

## 六、文件结构

```
e:\m2v\
├── frontend/                    # 前端静态文件
│   ├── index.html               # 编辑器单页应用 (token 守卫)
│   ├── app.js                   # 编辑器核心逻辑 (WaveSurfer + Bearer auth)
│   ├── style.css                # 编辑器样式
│   ├── dashboard.html           # 用户仪表板
│   ├── dashboard.js             # 仪表板逻辑 (登录/上传/任务列表)
│   └── dashboard.css            # 仪表板样式
├── src/
│   ├── editor_server.py         # 编辑器 APIRouter (prefix=/api/editor)
│   ├── api_server.py            # 统一 FastAPI 应用 (include editor_router)
│   ├── auth.py                  # JWT 认证
│   ├── storage.py               # 文件存储抽象层
│   ├── models.py                # User + Task ORM
│   └── ...                      # 其他 pipeline 模块不变
└── pyproject.toml               # [web] extras 包含编辑器依赖
```

## 七、API 详细设计

> 所有 API 路由需要 `Authorization: Bearer <token>` 认证。

### `GET /api/editor/songs`
```json
[
  {
    "task_id": "a1b2c3d4-...",
    "stem": "害怕的人",
    "has_alignment": true,
    "has_audio": true,
    "lines_count": 37,
    "duration": 388.2,
    "status": "completed"
  }
]
```

### `GET /api/editor/tasks/{task_id}/align`
返回存储层中的 alignment JSON，仅限当前用户的任务。

### `PUT /api/editor/tasks/{task_id}/align`
请求体 = 编辑后的完整 alignment JSON。  
校验规则：
1. 每行 `words` 非空
2. 所有时间值 ≥ 0
3. 字级 `end ≥ start`
4. 自动修正 `line.start/end` 与首末字一致

失败返回 `422` + 错误详情。  
成功返回 `200` + `{ "status": "ok", "task_id": "..." }`。  
写入前自动备份 `.bak`。

### `GET /api/editor/tasks/{task_id}/audio`
- LocalStorage: `FileResponse` 直接返回音频
- S3Storage: `302 Redirect` 到预签名 URL

### `POST /api/editor/tasks/{task_id}/regen`
```json
// Request
{ "mode": "ass" }      // 或 "video"

// Response (成功)
{ "status": "ok", "mode": "ass", "task_id": "..." }
```

## 八、关键设计决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 架构集成 | **APIRouter 挂载到统一 api_server** | 单端口、共享认证/存储/DB，避免双服务架构 |
| 前端构建工具 | **无** (Vanilla JS) | 项目小，一个 HTML 搞定；避免 node/npm 依赖 |
| 数据格式 | 沿用 `alignment.json` | 不引入新格式，pipeline 零改动 |
| 文件访问 | 通过 `task_id` + 存储层 | 多用户隔离，不再直接读写本地目录 |
| 编辑粒度 | 字级 + 行级 | 字级是必须的（卡拉OK核心），行级方便批量操作 |
| 字间连续性 | 前端拖拽时强制保持 | 拖A字右边界 = 拖B字左边界，不允许行内间隙 |
| 备份策略 | 每次保存自动 `.bak` | 简单可靠，避免误操作 |
| 认证 | JWT Bearer Token (与仪表板共享) | 统一身份系统，localStorage 存储 |

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
# 安装 Web 依赖 (包含编辑器)
pip install -e ".[web]"

# 启动统一服务 (包含仪表板 + 编辑器)
m2v serve --port 8000
# → 仪表板: http://localhost:8000
# → 编辑器: http://localhost:8000/editor/{task_id}

# Docker 部署
docker compose --profile web up
```
