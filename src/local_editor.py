"""
本地时间轴编辑器 — 轻量 FastAPI 服务（无数据库）

用法:
    python -m src.local_editor
    python -m src.local_editor --dir E:/m2v/output --port 8765

功能:
    - 自动扫描目录内的 *_alignment.json 文件
    - 完整复刻 Web 编辑器 UI（波形图 + 行列表 + 字级时间轴）
    - 保存时自动备份 (.bak)，支持撤销/重做
    - 一键重新生成 .ass
"""
from __future__ import annotations

import argparse
import json
import shutil
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from src.aligner import AlignmentResult
from src.subtitle import generate_ass
from src.config import SubtitleConfig
from src.utils import log

# ── 默认值，按需修改 ──────────────────────────────────────
DEFAULT_DIR   = r"E:\m2v\output"   # 扫描 alignment.json 的目录
DEFAULT_HOST  = "127.0.0.1"
DEFAULT_PORT  = 8765
# ─────────────────────────────────────────────────────────

app = FastAPI(title="M2V 本地编辑器", docs_url=None, redoc_url=None)

# 运行时配置（由 main() 注入）
_scan_dir: Path = Path(DEFAULT_DIR)


# ======================================================================
# API
# ======================================================================

@app.get("/api/files")
def list_files():
    """列出目录内所有 *_alignment.json 文件"""
    files = sorted(_scan_dir.glob("*_alignment.json"))
    result = []
    for f in files:
        stem = f.stem.replace("_alignment", "")
        audio = _find_audio(stem)
        result.append({
            "name": stem,
            "json_path": str(f),
            "audio_path": str(audio) if audio else None,
        })
    return result


@app.get("/api/alignment")
def get_alignment(path: str):
    """读取 alignment.json"""
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"文件不存在: {path}")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.put("/api/alignment")
async def save_alignment(path: str, request: Request):
    """保存编辑后的 alignment.json（先备份）"""
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"文件不存在: {path}")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "无效的 JSON")

    errors = _validate(data)
    if errors:
        raise HTTPException(422, {"errors": errors})

    bak = p.with_suffix(".json.bak")
    shutil.copy2(p, bak)

    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info("保存完成: %s", p.name)
    return {"status": "ok", "backup": str(bak)}


@app.post("/api/regen")
async def regen_ass(request: Request):
    """从 alignment.json 重新生成 .ass"""
    body = await request.json()
    json_path = Path(body.get("json_path", ""))
    audio_path_str = body.get("audio_path") or ""

    if not json_path.exists():
        raise HTTPException(404, f"JSON 不存在: {json_path}")

    try:
        alignment = AlignmentResult.load_json(json_path)
        stem = json_path.stem.replace("_alignment", "")
        ass_path = json_path.parent / f"{stem}.ass"
        audio_path = Path(audio_path_str) if audio_path_str else None
        generate_ass(alignment, ass_path, SubtitleConfig(), audio_path=audio_path)
        log.info("ASS 重新生成: %s", ass_path.name)
        return {"status": "ok", "ass_path": str(ass_path)}
    except Exception as e:
        log.error("重新生成失败: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.get("/api/audio")
def stream_audio(path: str):
    """提供音频文件流（支持 Range 请求）"""
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"音频文件不存在: {path}")
    suffix = p.suffix.lower()
    media_types = {".mp3": "audio/mpeg", ".wav": "audio/wav",
                   ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}
    media_type = media_types.get(suffix, "audio/mpeg")
    return FileResponse(p, media_type=media_type, headers={"Accept-Ranges": "bytes"})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_UI_HTML)


# ======================================================================
# 辅助
# ======================================================================

def _find_audio(stem: str) -> Path | None:
    exts = [".wav", ".mp3", ".flac", ".m4a", ".ogg"]
    search_dirs = [_scan_dir, _scan_dir.parent / "input", _scan_dir.parent]
    for d in search_dirs:
        for ext in exts:
            p = d / f"{stem}{ext}"
            if p.exists():
                return p
    return None


def _validate(data: dict) -> list[str]:
    errors = []
    lines = data.get("lines")
    if not isinstance(lines, list):
        return ["'lines' 必须是数组"]
    for i, line in enumerate(lines):
        words = line.get("words", [])
        if words:
            line["start"] = words[0].get("start", line.get("start", 0))
            line["end"] = words[-1].get("end", line.get("end", 0))
        for j, w in enumerate(words):
            if w.get("end", 0) < w.get("start", 0) - 0.01:
                errors.append(
                    f"第{i+1}行第{j+1}字'{w.get('word','')}': "
                    f"end({w.get('end',0):.2f}) < start({w.get('start',0):.2f})"
                )
    return errors[:20]


# ======================================================================
# 嵌入式 Web UI  ── 完整复刻原版 index.html / style.css / app.js
# ======================================================================

_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M2V 时间轴编辑器</title>
<script src="https://unpkg.com/wavesurfer.js@7"></script>
<style>
:root {
  --bg:          #1a1a2e;
  --bg-panel:    #16213e;
  --bg-hover:    #0f3460;
  --bg-selected: #533483;
  --text:        #e0e0e0;
  --text-dim:    #888;
  --accent:      #e94560;
  --accent-soft: #e9456033;
  --border:      #333;
  --word-bg:     #1a3a5c;
  --word-active: #e94560;
  --word-hover:  #2a5a8c;
  --success:     #4caf50;
  --warning:     #ff9800;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  background: var(--bg); color: var(--text);
  overflow: hidden; height: 100vh;
  display: flex; flex-direction: column;
}
header {
  display: flex; align-items: center; gap: 16px;
  padding: 8px 16px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
header h1 { font-size: 18px; white-space: nowrap; }
#song-select {
  background: var(--bg); color: var(--text);
  border: 1px solid var(--border); padding: 4px 8px;
  border-radius: 4px; font-size: 14px; min-width: 200px;
}
#toolbar { display: flex; align-items: center; gap: 8px; margin-left: auto; }
#toolbar button {
  background: var(--bg-hover); color: var(--text);
  border: 1px solid var(--border); padding: 4px 12px;
  border-radius: 4px; cursor: pointer; font-size: 13px; white-space: nowrap;
}
#toolbar button:hover { background: var(--accent); }
.sep { color: var(--text-dim); }
#status-msg { font-size: 12px; color: var(--text-dim); min-width: 160px; }
main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#waveform-section { flex-shrink: 0; border-bottom: 1px solid var(--border); background: #0d1117; }
#waveform { height: 128px; }
#waveform-controls {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 16px; background: var(--bg-panel);
  border-top: 1px solid var(--border);
}
#waveform-controls button {
  background: var(--bg-hover); color: var(--text);
  border: 1px solid var(--border); padding: 3px 10px;
  border-radius: 4px; cursor: pointer; font-size: 13px;
}
#waveform-controls button:hover { background: var(--accent); }
#time-display { font-family: monospace; font-size: 13px; color: var(--text-dim); }
#zoom-slider { width: 120px; vertical-align: middle; }
#editor-container { flex: 1; display: flex; overflow: hidden; }
#lyrics-panel { width: 45%; overflow-y: auto; border-right: 1px solid var(--border); }
#lyrics-list { padding: 4px 0; }
.lyric-row {
  display: flex; align-items: center;
  padding: 6px 12px; cursor: pointer;
  border-bottom: 1px solid #222; gap: 8px;
  transition: background 0.1s;
}
.lyric-row:hover { background: var(--bg-hover); }
.lyric-row.selected { background: var(--bg-selected); }
.lyric-row.playing { background: var(--accent-soft); }
.lyric-num { font-size: 11px; color: var(--text-dim); width: 24px; text-align: right; flex-shrink: 0; }
.lyric-time-edit { display: flex; align-items: center; gap: 3px; margin-left: auto; flex-shrink: 0; }
.time-input {
  font-family: monospace; font-size: 11px;
  color: var(--text); background: var(--bg);
  border: 1px solid var(--border); border-radius: 3px;
  padding: 2px 4px; width: 80px; text-align: center;
}
.time-input:focus { border-color: var(--accent); outline: none; background: #1e1e3e; }
.time-arrow { color: var(--text-dim); font-size: 11px; }
.line-dur { font-family: monospace; font-size: 10px; color: var(--text-dim); width: 32px; text-align: right; }
.line-nudge-btn {
  background: var(--bg-hover); color: var(--text);
  border: 1px solid var(--border); border-radius: 3px;
  padding: 1px 5px; cursor: pointer; font-size: 11px; line-height: 1;
}
.line-nudge-btn:hover { background: var(--accent); }
.lyric-text { font-size: 15px; flex: 1; }
.lyric-char { transition: color 0.05s, text-shadow 0.05s; }
.lyric-char.sung { color: var(--accent); }
.lyric-char.singing { color: #ffdd57; text-shadow: 0 0 8px #ffdd57aa; }
#line-edit-controls { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
#line-edit-controls button {
  background: var(--bg-hover); color: var(--text);
  border: 1px solid var(--border); padding: 2px 8px;
  border-radius: 4px; cursor: pointer; font-size: 12px; white-space: nowrap;
}
#line-edit-controls button:hover { background: var(--accent); }
#word-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#word-panel-header {
  padding: 8px 12px; background: var(--bg-panel);
  border-bottom: 1px solid var(--border); font-size: 14px;
}
#word-timeline { flex: 1; overflow-x: auto; overflow-y: hidden; padding: 12px; position: relative; }
.word-bar-container { display: flex; align-items: stretch; height: 48px; margin-bottom: 8px; }
.word-bar {
  display: flex; align-items: center; justify-content: center;
  background: var(--word-bg); border: 1px solid var(--border);
  border-radius: 3px; font-size: 16px; cursor: pointer;
  position: relative; user-select: none; min-width: 16px;
  transition: background 0.1s;
}
.word-bar:hover { background: var(--word-hover); }
.word-bar.selected { background: var(--word-active); border-color: #fff; }
.word-bar.bar-singing { background: #ffdd57; color: #000; box-shadow: 0 0 10px #ffdd5788; }
.word-bar.punct { background: transparent; border: 1px dashed var(--border); font-size: 12px; color: var(--text-dim); min-width: 8px; }
.word-bar .word-dur { position: absolute; bottom: 2px; font-size: 9px; color: var(--text-dim); font-family: monospace; }
.word-bar .drag-handle {
  position: absolute; right: -4px; top: 0; bottom: 0;
  width: 8px; cursor: col-resize; z-index: 2;
}
.word-bar .drag-handle:hover { background: var(--accent); opacity: 0.6; border-radius: 2px; }
.word-bar .drag-handle:active { background: #ff0; opacity: 0.8; }
#word-controls {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: var(--bg-panel);
  border-top: 1px solid var(--border);
}
#word-controls button {
  background: var(--bg-hover); color: var(--text);
  border: 1px solid var(--border); padding: 3px 10px;
  border-radius: 4px; cursor: pointer; font-size: 13px;
}
#word-controls button:hover { background: var(--accent); }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: #444; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #666; }
</style>
</head>
<body>
<header>
  <h1>🎤 M2V 时间轴编辑器</h1>
  <div id="song-selector">
    <select id="song-select"><option value="">加载中…</option></select>
  </div>
  <div id="toolbar">
    <button id="btn-save" title="Ctrl+S">💾 保存</button>
    <button id="btn-undo" title="Ctrl+Z">↩ 撤销</button>
    <button id="btn-redo" title="Ctrl+Y">↪ 重做</button>
    <span class="sep">|</span>
    <button id="btn-regen-ass">🔄 生成 ASS</button>
    <span class="sep">|</span>
    <span id="status-msg"></span>
  </div>
</header>

<main>
  <section id="waveform-section">
    <div id="waveform"></div>
    <div id="waveform-controls">
      <button id="btn-play-pause" title="Space">▶ 播放</button>
      <button id="btn-play-line" title="Enter">▶ 播放选中行</button>
      <span id="time-display">0:00.000 / 0:00.000</span>
      <label>缩放: <input id="zoom-slider" type="range" min="10" max="500" value="50"></label>
    </div>
  </section>

  <div id="editor-container">
    <section id="lyrics-panel">
      <div id="lyrics-list"></div>
    </section>

    <section id="word-panel">
      <div id="word-panel-header">
        <span id="word-panel-title">点击左侧歌词行查看字级时间</span>
        <div id="line-edit-controls" style="display:none">
          <button id="btn-line-nudge-left-big" title="整行前移 200ms">⬅ -200ms</button>
          <button id="btn-line-nudge-left" title="整行前移 50ms">◁ -50ms</button>
          <button id="btn-line-nudge-right" title="整行后移 50ms">▷ +50ms</button>
          <button id="btn-line-nudge-right-big" title="整行后移 200ms">➡ +200ms</button>
          <span class="sep">|</span>
          <button id="btn-line-expand" title="行时长+100ms">↔ 展开</button>
          <button id="btn-line-shrink" title="行时长-100ms">⇿ 收缩</button>
        </div>
      </div>
      <div id="word-timeline"></div>
      <div id="word-controls">
        <button id="btn-shift-left" title="A">⬅ -50ms</button>
        <button id="btn-nudge-left" title="←">◁ -10ms</button>
        <button id="btn-nudge-right" title="→">▷ +10ms</button>
        <button id="btn-shift-right" title="D">➡ +50ms</button>
        <span class="sep">|</span>
        <button id="btn-even-split">⚖ 均分本行</button>
        <button id="btn-play-word">▶ 播放选中字</button>
      </div>
    </section>
  </div>
</main>

<script>
// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  allFiles: [],
  currentFile: null,   // { name, json_path, audio_path }
  alignment: null,
  selectedLine: -1,
  selectedWord: -1,
  undoStack: [],
  redoStack: [],
  dirty: false,
};

let ws = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  dom.songSelect          = $("#song-select");
  dom.btnSave             = $("#btn-save");
  dom.btnUndo             = $("#btn-undo");
  dom.btnRedo             = $("#btn-redo");
  dom.btnRegenAss         = $("#btn-regen-ass");
  dom.statusMsg           = $("#status-msg");
  dom.waveform            = $("#waveform");
  dom.btnPlayPause        = $("#btn-play-pause");
  dom.btnPlayLine         = $("#btn-play-line");
  dom.timeDisplay         = $("#time-display");
  dom.zoomSlider          = $("#zoom-slider");
  dom.lyricsList          = $("#lyrics-list");
  dom.wordTitle           = $("#word-panel-title");
  dom.wordTimeline        = $("#word-timeline");
  dom.btnShiftLeft        = $("#btn-shift-left");
  dom.btnNudgeLeft        = $("#btn-nudge-left");
  dom.btnNudgeRight       = $("#btn-nudge-right");
  dom.btnShiftRight       = $("#btn-shift-right");
  dom.btnEvenSplit        = $("#btn-even-split");
  dom.btnPlayWord         = $("#btn-play-word");
  dom.lineEditControls    = $("#line-edit-controls");
  dom.btnLineNudgeLeftBig  = $("#btn-line-nudge-left-big");
  dom.btnLineNudgeLeft     = $("#btn-line-nudge-left");
  dom.btnLineNudgeRight    = $("#btn-line-nudge-right");
  dom.btnLineNudgeRightBig = $("#btn-line-nudge-right-big");
  dom.btnLineExpand       = $("#btn-line-expand");
  dom.btnLineShrink       = $("#btn-line-shrink");

  initWaveSurfer();
  bindEvents();
  loadFileList();
});

// ---------------------------------------------------------------------------
// WaveSurfer
// ---------------------------------------------------------------------------
function initWaveSurfer() {
  ws = WaveSurfer.create({
    container: dom.waveform,
    waveColor: "#4a90d9", progressColor: "#e94560",
    cursorColor: "#fff", height: 128,
    barWidth: 2, barGap: 1, barRadius: 2,
    normalize: true, backend: "WebAudio",
  });
  ws.on("ready", () => { updateTimeDisplay(); status("音频已加载"); });
  ws.on("audioprocess", () => { updateTimeDisplay(); highlightPlayingLine(); });
  ws.on("timeupdate", () => { updateTimeDisplay(); highlightPlayingLine(); });
  ws.on("seeking", () => { updateTimeDisplay(); });
  ws.on("finish", () => { dom.btnPlayPause.textContent = "▶ 播放"; });
}

function updateTimeDisplay() {
  if (!ws) return;
  const cur = ws.getCurrentTime(), dur = ws.getDuration() || 0;
  dom.timeDisplay.textContent = `${fmtTime(cur)} / ${fmtTime(dur)}`;
}

function fmtTime(s) {
  const m = Math.floor(s / 60), sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------
function bindEvents() {
  dom.songSelect.addEventListener("change", () => {
    const idx = dom.songSelect.value;
    if (idx !== "") loadSong(parseInt(idx));
  });
  dom.btnSave.addEventListener("click", saveAlignment);
  dom.btnUndo.addEventListener("click", undo);
  dom.btnRedo.addEventListener("click", redo);
  dom.btnRegenAss.addEventListener("click", regenAss);
  dom.btnPlayPause.addEventListener("click", togglePlay);
  dom.btnPlayLine.addEventListener("click", playSelectedLine);
  dom.zoomSlider.addEventListener("input", () => { if (ws) ws.zoom(Number(dom.zoomSlider.value)); });
  dom.btnShiftLeft.addEventListener("click",  () => nudgeWord(-0.05));
  dom.btnNudgeLeft.addEventListener("click",  () => nudgeWord(-0.01));
  dom.btnNudgeRight.addEventListener("click", () => nudgeWord(0.01));
  dom.btnShiftRight.addEventListener("click", () => nudgeWord(0.05));
  dom.btnEvenSplit.addEventListener("click",  evenSplitLine);
  dom.btnPlayWord.addEventListener("click",   playSelectedWord);
  dom.btnLineNudgeLeftBig.addEventListener("click",  () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.2); });
  dom.btnLineNudgeLeft.addEventListener("click",     () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.05); });
  dom.btnLineNudgeRight.addEventListener("click",    () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.05); });
  dom.btnLineNudgeRightBig.addEventListener("click", () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.2); });
  dom.btnLineExpand.addEventListener("click",  () => { if (state.selectedLine >= 0) resizeLine(state.selectedLine, -0.05, 0.05); });
  dom.btnLineShrink.addEventListener("click",  () => { if (state.selectedLine >= 0) resizeLine(state.selectedLine, 0.05, -0.05); });
  document.addEventListener("keydown", handleKey);
}

function handleKey(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const ctrl = e.ctrlKey || e.metaKey;
  switch (true) {
    case e.code === "Space":        e.preventDefault(); togglePlay(); break;
    case ctrl && e.code === "KeyS": e.preventDefault(); saveAlignment(); break;
    case ctrl && e.code === "KeyZ" && !e.shiftKey: e.preventDefault(); undo(); break;
    case ctrl && (e.code === "KeyY" || (e.code === "KeyZ" && e.shiftKey)): e.preventDefault(); redo(); break;
    case e.code === "ArrowLeft" && !ctrl:  e.preventDefault(); nudgeWord(-0.01); break;
    case e.code === "ArrowRight" && !ctrl: e.preventDefault(); nudgeWord(0.01); break;
    case e.code === "KeyA" && !ctrl: e.preventDefault(); nudgeWord(-0.05); break;
    case e.code === "KeyD" && !ctrl: e.preventDefault(); nudgeWord(0.05); break;
    case e.code === "ArrowUp":   e.preventDefault(); selectAdjacentLine(-1); break;
    case e.code === "ArrowDown": e.preventDefault(); selectAdjacentLine(1); break;
    case e.code === "Enter":     e.preventDefault(); playSelectedLine(); break;
    case e.code === "Tab" && !ctrl: e.preventDefault(); selectAdjacentWord(e.shiftKey ? -1 : 1); break;
    case e.code === "BracketLeft" && !ctrl && !e.shiftKey:  e.preventDefault(); if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.05); break;
    case e.code === "BracketRight" && !ctrl && !e.shiftKey: e.preventDefault(); if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.05); break;
    case e.code === "BracketLeft" && !ctrl && e.shiftKey:   e.preventDefault(); if (state.selectedLine >= 0) resizeLine(state.selectedLine, -0.05, 0.05); break;
    case e.code === "BracketRight" && !ctrl && e.shiftKey:  e.preventDefault(); if (state.selectedLine >= 0) resizeLine(state.selectedLine, 0.05, -0.05); break;
  }
}

// ---------------------------------------------------------------------------
// File List & Loading
// ---------------------------------------------------------------------------
async function loadFileList() {
  try {
    const r = await fetch("/api/files");
    state.allFiles = await r.json();
    dom.songSelect.innerHTML = state.allFiles.length === 0
      ? `<option value="">未找到 alignment.json</option>`
      : `<option value="">— 请选择 —</option>` +
        state.allFiles.map((f, i) =>
          `<option value="${i}">${f.name}${f.audio_path ? " 🎵" : ""}</option>`
        ).join("");
    if (state.allFiles.length === 1) loadSong(0);
  } catch(e) {
    dom.songSelect.innerHTML = `<option value="">加载失败</option>`;
    status("文件列表加载失败: " + e, true);
  }
}

async function loadSong(idx) {
  const file = state.allFiles[idx];
  state.currentFile = file;
  state.selectedLine = -1;
  state.selectedWord = -1;
  state.undoStack = [];
  state.redoStack = [];
  state.dirty = false;
  dom.songSelect.value = idx;
  status(`加载 ${file.name}…`);

  try {
    const r = await fetch("/api/alignment?path=" + encodeURIComponent(file.json_path));
    if (!r.ok) throw new Error(await r.text());
    state.alignment = await r.json();
  } catch(e) {
    status("对齐数据加载失败: " + e, true);
    state.alignment = null;
    return;
  }

  if (file.audio_path) {
    try {
      const audioUrl = "/api/audio?path=" + encodeURIComponent(file.audio_path);
      await ws.load(audioUrl);
    } catch(e) {
      status("音频加载失败: " + e, true);
    }
  }

  renderLyrics();
  clearWordPanel();
  status(`已加载: ${file.name} (${state.alignment.lines.length} 行)`);
  document.title = `${file.name} — M2V 编辑器`;
}

// ---------------------------------------------------------------------------
// Lyrics Panel
// ---------------------------------------------------------------------------
function renderLyrics() {
  const lines = state.alignment?.lines || [];
  dom.lyricsList.innerHTML = "";

  lines.forEach((line, i) => {
    const row = document.createElement("div");
    row.className = "lyric-row";
    row.dataset.idx = i;
    const charSpans = line.words.map((w, wi) =>
      `<span class="lyric-char" data-line="${i}" data-word="${wi}">${escHtml(w.word)}</span>`
    ).join("");
    const dur = (line.end - line.start).toFixed(1);
    row.innerHTML = `
      <span class="lyric-num">${i + 1}</span>
      <span class="lyric-text">${charSpans}</span>
      <span class="lyric-time-edit">
        <input type="text" class="time-input line-start-input" value="${fmtTimeShort(line.start)}" data-field="start" data-idx="${i}" title="行起始时间">
        <span class="time-arrow">→</span>
        <input type="text" class="time-input line-end-input" value="${fmtTimeShort(line.end)}" data-field="end" data-idx="${i}" title="行结束时间">
        <span class="line-dur">${dur}s</span>
        <button class="line-nudge-btn" data-idx="${i}" data-delta="-0.1" title="整行前移100ms">◁</button>
        <button class="line-nudge-btn" data-idx="${i}" data-delta="0.1" title="整行后移100ms">▷</button>
      </span>`;
    row.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      selectLine(i);
    });
    row.addEventListener("dblclick", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      if (ws) { ws.setTime(line.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停"; }
    });
    dom.lyricsList.appendChild(row);
  });

  dom.lyricsList.querySelectorAll(".time-input").forEach(input => {
    input.addEventListener("change", handleLineTimeInput);
    input.addEventListener("keydown", (e) => { if (e.code === "Enter") e.target.blur(); e.stopPropagation(); });
    input.addEventListener("focus", (e) => e.target.select());
  });

  dom.lyricsList.querySelectorAll(".line-nudge-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      nudgeLine(Number(btn.dataset.idx), Number(btn.dataset.delta));
    });
  });
}

function selectLine(idx, options = {}) {
  const { seek = true, scroll = false } = options;
  state.selectedLine = idx;
  state.selectedWord = -1;
  $$(".lyric-row").forEach((row, i) => row.classList.toggle("selected", i === idx));
  const line = state.alignment.lines[idx];
  if (seek && ws && line) ws.setTime(line.start);
  if (scroll) {
    const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${idx}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  if (dom.lineEditControls) dom.lineEditControls.style.display = idx >= 0 ? "flex" : "none";
  renderWords(idx);
}

function selectAdjacentLine(delta) {
  const lines = state.alignment?.lines || [];
  if (!lines.length) return;
  let next = Math.max(0, Math.min(state.selectedLine + delta, lines.length - 1));
  selectLine(next, { scroll: true });
}

function highlightPlayingLine() {
  if (!ws || !state.alignment) return;
  const t = ws.getCurrentTime();
  const lines = state.alignment.lines;
  let activeLineIdx = -1;

  $$(".lyric-row").forEach((row, i) => {
    const line = lines[i];
    const playing = line && t >= line.start && t <= line.end;
    row.classList.toggle("playing", playing);
    if (playing) activeLineIdx = i;
  });

  $$(".lyric-char").forEach((span) => {
    const li = Number(span.dataset.line), wi = Number(span.dataset.word);
    const line = lines[li]; if (!line) { span.classList.remove("sung","singing"); return; }
    const w = line.words[wi]; if (!w) { span.classList.remove("sung","singing"); return; }
    if (t >= w.end) { span.classList.add("sung"); span.classList.remove("singing"); }
    else if (t >= w.start) { span.classList.add("singing"); span.classList.remove("sung"); }
    else { span.classList.remove("sung","singing"); }
  });

  if (activeLineIdx >= 0 && activeLineIdx !== state.selectedLine)
    selectLine(activeLineIdx, { seek: false, scroll: true });

  if (activeLineIdx >= 0 && activeLineIdx === state.selectedLine) {
    const line = lines[activeLineIdx];
    $$(".word-bar").forEach((bar) => {
      const wi = Number(bar.dataset.idx), w = line.words[wi];
      if (!w) { bar.classList.remove("bar-singing"); return; }
      bar.classList.toggle("bar-singing", t >= w.start && t < w.end);
    });
  }

  if (activeLineIdx >= 0) {
    const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${activeLineIdx}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

// ---------------------------------------------------------------------------
// Word Panel
// ---------------------------------------------------------------------------
function renderWords(lineIdx) {
  const line = state.alignment?.lines[lineIdx];
  if (!line) { clearWordPanel(); return; }

  const lineDurMs = ((line.end - line.start) * 1000).toFixed(0);
  dom.wordTitle.textContent = `第 ${lineIdx + 1} 行 [${fmtTimeShort(line.start)} → ${fmtTimeShort(line.end)}, ${lineDurMs}ms]: ${line.text}`;
  const words = line.words || [];
  const lineStart = line.start, lineEnd = line.end, lineDur = lineEnd - lineStart || 1;

  dom.wordTimeline.innerHTML = "";
  const container = document.createElement("div");
  container.className = "word-bar-container";

  words.forEach((w, i) => {
    const dur = w.end - w.start;
    const widthPct = (dur / lineDur) * 100;
    const bar = document.createElement("div");
    bar.className = "word-bar" + (isPunct(w.word) ? " punct" : "");
    bar.style.width = `${Math.max(widthPct, 1)}%`;
    bar.dataset.idx = i;
    bar.title = `${w.word}  ${fmtTime(w.start)} → ${fmtTime(w.end)}  (${(dur * 1000).toFixed(0)}ms)`;
    bar.innerHTML = `
      <span>${escHtml(w.word)}</span>
      <span class="word-dur">${(dur * 1000).toFixed(0)}</span>
      <div class="drag-handle" title="拖拽调整 | 双击=设为当前播放位置"></div>`;

    bar.addEventListener("click", (e) => {
      if (e.target.classList.contains("drag-handle")) return;
      selectWord(i);
    });
    bar.addEventListener("dblclick", () => {
      if (ws) {
        ws.setTime(w.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停";
        const stopAt = w.end;
        const check = () => { if (ws.getCurrentTime() >= stopAt) { ws.pause(); dom.btnPlayPause.textContent = "▶ 播放"; } else if (ws.isPlaying()) requestAnimationFrame(check); };
        requestAnimationFrame(check);
      }
    });

    setupDragHandle(bar, i, lineIdx);
    const handle = bar.querySelector(".drag-handle");
    if (handle) handle.addEventListener("dblclick", (e) => { e.preventDefault(); e.stopPropagation(); snapSplitToPlayhead(lineIdx, i); });

    container.appendChild(bar);
  });

  dom.wordTimeline.appendChild(container);
  if (words.length > 0 && state.selectedWord < 0) selectWord(0);
}

function clearWordPanel() {
  dom.wordTitle.textContent = "点击左侧歌词行查看字级时间";
  dom.wordTimeline.innerHTML = "";
}

function selectWord(idx) {
  state.selectedWord = idx;
  $$(".word-bar").forEach((bar, i) => bar.classList.toggle("selected", i === idx));
}

function selectAdjacentWord(delta) {
  if (state.selectedLine < 0) return;
  const words = state.alignment?.lines[state.selectedLine]?.words || [];
  if (!words.length) return;
  selectWord(Math.max(0, Math.min(state.selectedWord + delta, words.length - 1)));
}

// ---------------------------------------------------------------------------
// Drag to resize
// ---------------------------------------------------------------------------
function snapSplitToPlayhead(lineIdx, wordIdx) {
  if (!ws) return;
  const line = state.alignment.lines[lineIdx];
  if (!line) return;
  const words = line.words;
  const isLast = (wordIdx === words.length - 1);
  const t = ws.getCurrentTime();

  if (isLast) {
    const clamped = Math.round(Math.max(words[wordIdx].start + 0.01, t) * 1000) / 1000;
    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;
    pushUndo();
    words[wordIdx].end = clamped; line.end = clamped;
    renderLyrics(); selectLine(lineIdx); selectWord(wordIdx); markDirty();
    status(`✂ 行尾 → ${fmtTimeShort(clamped)}`);
  } else {
    const minVal = words[wordIdx].start + 0.01, maxVal = words[wordIdx + 1].end - 0.01;
    const clamped = Math.round(Math.max(minVal, Math.min(maxVal, t)) * 1000) / 1000;
    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;
    pushUndo();
    words[wordIdx].end = clamped; words[wordIdx + 1].start = clamped;
    syncLineFromWords(lineIdx); renderWords(lineIdx); selectWord(wordIdx); markDirty();
    status(`✂ 分割点 ${wordIdx + 1}|${wordIdx + 2} → ${fmtTimeShort(clamped)}`);
  }
}

function setupDragHandle(bar, wordIdx, lineIdx) {
  const handle = bar.querySelector(".drag-handle");
  if (!handle) return;
  let startX = 0, startEnd = 0, containerWidth = 0, lineDur = 0;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault(); e.stopPropagation();
    const line = state.alignment.lines[lineIdx];
    const words = line.words;
    if (wordIdx >= words.length - 1) return;
    pushUndo();
    startX = e.clientX; startEnd = words[wordIdx].end;
    containerWidth = bar.parentElement.getBoundingClientRect().width;
    lineDur = line.end - line.start;

    const onMove = (ev) => {
      const dx = ev.clientX - startX, dt = (dx / containerWidth) * lineDur;
      const newEnd = Math.round((startEnd + dt) * 1000) / 1000;
      const minEnd = words[wordIdx].start + 0.01, maxEnd = words[wordIdx + 1].end - 0.01;
      const clamped = Math.max(minEnd, Math.min(maxEnd, newEnd));
      words[wordIdx].end = clamped; words[wordIdx + 1].start = clamped;
      renderWords(lineIdx); selectWord(wordIdx); markDirty();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      syncLineFromWords(lineIdx);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

// ---------------------------------------------------------------------------
// Word Editing
// ---------------------------------------------------------------------------
function nudgeWord(delta) {
  if (state.selectedLine < 0 || state.selectedWord < 0) return;
  const line = state.alignment.lines[state.selectedLine];
  const words = line.words, idx = state.selectedWord;
  if (!words[idx]) return;
  pushUndo();
  const newStart = Math.round((words[idx].start + delta) * 1000) / 1000;
  const newEnd   = Math.round((words[idx].end + delta) * 1000) / 1000;
  if (newStart < 0 || newEnd < 0) return;
  if (idx > 0 && newStart < words[idx - 1].start + 0.01) return;
  if (idx < words.length - 1 && newEnd > words[idx + 1].end - 0.01) return;
  if (idx > 0) words[idx - 1].end = newStart;
  if (idx < words.length - 1) words[idx + 1].start = newEnd;
  words[idx].start = newStart; words[idx].end = newEnd;
  syncLineFromWords(state.selectedLine);
  renderWords(state.selectedLine); selectWord(idx); markDirty();
}

function evenSplitLine() {
  if (state.selectedLine < 0) return;
  const line = state.alignment.lines[state.selectedLine];
  const words = line.words;
  if (!words.length) return;
  pushUndo();
  const totalDur = line.end - line.start;
  const charCount = words.reduce((sum, w) => sum + w.word.length, 0);
  let t = line.start;
  words.forEach((w) => {
    const dur = (w.word.length / charCount) * totalDur;
    w.start = Math.round(t * 1000) / 1000; t += dur;
    w.end = Math.round(t * 1000) / 1000;
  });
  words[words.length - 1].end = line.end;
  renderWords(state.selectedLine); markDirty();
}

function syncLineFromWords(lineIdx) {
  const line = state.alignment.lines[lineIdx];
  const words = line.words;
  if (!words.length) return;
  line.start = words[0].start; line.end = words[words.length - 1].end;
  const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${lineIdx}"]`);
  if (row) {
    const si = row.querySelector(`.line-start-input`);
    const ei = row.querySelector(`.line-end-input`);
    if (si) si.value = fmtTimeShort(line.start);
    if (ei) ei.value = fmtTimeShort(line.end);
    const dur = row.querySelector(".line-dur");
    if (dur) dur.textContent = (line.end - line.start).toFixed(1) + "s";
  }
}

// ---------------------------------------------------------------------------
// Line Editing
// ---------------------------------------------------------------------------
function nudgeLine(lineIdx, delta) {
  const line = state.alignment.lines[lineIdx];
  if (!line) return;
  pushUndo();
  const newStart = Math.round((line.start + delta) * 1000) / 1000;
  if (newStart < 0) return;
  line.words.forEach(w => {
    w.start = Math.round((w.start + delta) * 1000) / 1000;
    w.end   = Math.round((w.end + delta) * 1000) / 1000;
  });
  line.start = newStart;
  line.end = Math.round((line.end + delta) * 1000) / 1000;
  renderLyrics(); selectLine(lineIdx); markDirty();
}

function resizeLine(lineIdx, startDelta, endDelta) {
  const line = state.alignment.lines[lineIdx];
  if (!line || !line.words.length) return;
  const oldStart = line.start, oldEnd = line.end, oldDur = oldEnd - oldStart;
  if (oldDur <= 0) return;
  let newStart = Math.round((oldStart + startDelta) * 1000) / 1000;
  let newEnd   = Math.round((oldEnd + endDelta) * 1000) / 1000;
  if (newStart < 0) newStart = 0;
  if (newEnd - newStart < 0.1) return;
  pushUndo();
  const newDur = newEnd - newStart;
  line.words.forEach(w => {
    const relStart = (w.start - oldStart) / oldDur;
    const relEnd   = (w.end - oldStart) / oldDur;
    w.start = Math.round((newStart + relStart * newDur) * 1000) / 1000;
    w.end   = Math.round((newStart + relEnd * newDur) * 1000) / 1000;
  });
  line.start = newStart; line.end = newEnd;
  line.words[0].start = newStart;
  line.words[line.words.length - 1].end = newEnd;
  renderLyrics(); selectLine(lineIdx); markDirty();
}

function handleLineTimeInput(e) {
  const input = e.target;
  const idx = Number(input.dataset.idx), field = input.dataset.field;
  const line = state.alignment?.lines[idx];
  if (!line) return;
  const parsed = parseTimeInput(input.value);
  if (parsed === null) {
    input.value = fmtTimeShort(line[field]);
    status("时间格式错误，请输入 m:ss.xxx 或 秒数", true); return;
  }
  if (field === "start") resizeLine(idx, parsed - line.start, 0);
  else resizeLine(idx, 0, parsed - line.end);
}

function parseTimeInput(str) {
  str = str.trim();
  const match = str.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const mins = match[1] ? Number(match[1]) : 0;
  const total = mins * 60 + Number(match[2]);
  return total >= 0 ? Math.round(total * 1000) / 1000 : null;
}

function fmtTimeShort(s) {
  const m = Math.floor(s / 60), sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------
function togglePlay() {
  if (!ws) return;
  if (ws.isPlaying()) { ws.pause(); dom.btnPlayPause.textContent = "▶ 播放"; }
  else { ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停"; }
}

function playSelectedLine() {
  if (state.selectedLine < 0 || !ws) return;
  const line = state.alignment.lines[state.selectedLine];
  if (!line) return;
  ws.setTime(line.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停";
  const stopAt = line.end;
  const check = () => { if (ws.getCurrentTime() >= stopAt) { ws.pause(); dom.btnPlayPause.textContent = "▶ 播放"; } else if (ws.isPlaying()) requestAnimationFrame(check); };
  requestAnimationFrame(check);
}

function playSelectedWord() {
  if (state.selectedLine < 0 || state.selectedWord < 0 || !ws) return;
  const w = state.alignment.lines[state.selectedLine]?.words?.[state.selectedWord];
  if (!w) return;
  ws.setTime(w.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停";
  const stopAt = w.end;
  const check = () => { if (ws.getCurrentTime() >= stopAt) { ws.pause(); dom.btnPlayPause.textContent = "▶ 播放"; } else if (ws.isPlaying()) requestAnimationFrame(check); };
  requestAnimationFrame(check);
}

// ---------------------------------------------------------------------------
// Undo / Redo
// ---------------------------------------------------------------------------
function pushUndo() {
  state.undoStack.push(JSON.stringify(state.alignment));
  if (state.undoStack.length > 100) state.undoStack.shift();
  state.redoStack = [];
}

function undo() {
  if (!state.undoStack.length) { status("无可撤销操作"); return; }
  state.redoStack.push(JSON.stringify(state.alignment));
  state.alignment = JSON.parse(state.undoStack.pop());
  renderLyrics();
  if (state.selectedLine >= 0) { renderWords(state.selectedLine); selectLine(state.selectedLine); }
  markDirty(); status("已撤销");
}

function redo() {
  if (!state.redoStack.length) { status("无可重做操作"); return; }
  state.undoStack.push(JSON.stringify(state.alignment));
  state.alignment = JSON.parse(state.redoStack.pop());
  renderLyrics();
  if (state.selectedLine >= 0) { renderWords(state.selectedLine); selectLine(state.selectedLine); }
  markDirty(); status("已重做");
}

function markDirty() {
  state.dirty = true;
  document.title = "● " + (state.currentFile?.name || "M2V") + " — 时间轴编辑器";
}

// ---------------------------------------------------------------------------
// Save / Regen
// ---------------------------------------------------------------------------
async function saveAlignment() {
  if (!state.currentFile || !state.alignment) return;
  status("保存中…");
  try {
    const r = await fetch("/api/alignment?path=" + encodeURIComponent(state.currentFile.json_path), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.alignment),
    });
    const j = await r.json();
    if (!r.ok) {
      const errs = j.detail?.errors || [JSON.stringify(j.detail)];
      status("校验错误: " + errs.join("; "), true);
    } else {
      state.dirty = false;
      document.title = (state.currentFile?.name || "M2V") + " — 时间轴编辑器";
      status("✅ 已保存");
    }
  } catch(e) { status("保存失败: " + e, true); }
}

async function regenAss() {
  if (!state.currentFile) return;
  status("生成 ASS 中…");
  try {
    const r = await fetch("/api/regen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ json_path: state.currentFile.json_path, audio_path: state.currentFile.audio_path || "" }),
    });
    const j = await r.json();
    if (!r.ok) status("生成失败: " + (j.detail || JSON.stringify(j)), true);
    else status("✅ ASS 已生成: " + j.ass_path);
  } catch(e) { status("生成失败: " + e, true); }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function status(msg, isError = false) {
  dom.statusMsg.textContent = msg;
  dom.statusMsg.style.color = isError ? "var(--accent)" : "var(--text-dim)";
  if (!isError) setTimeout(() => { dom.statusMsg.textContent = ""; }, 4000);
}
function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function isPunct(ch) {
  return /^[\s，。、！？；：""''（）《》…—·\-,.!?;:'"()\[\]{}]$/.test(ch);
}
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
});
</script>
</body>
</html>
"""


# ======================================================================
# 启动
# ======================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.local_editor",
        description="本地时间轴编辑器（轻量 FastAPI，无数据库）",
    )
    parser.add_argument("--dir", "-d", default=DEFAULT_DIR,
                        help=f"alignment.json 所在目录，默认: {DEFAULT_DIR}")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global _scan_dir
    _scan_dir = Path(args.dir).expanduser().resolve()
    if not _scan_dir.exists():
        print(f"[警告] 目录不存在，将创建: {_scan_dir}")
        _scan_dir.mkdir(parents=True, exist_ok=True)

    url = f"http://{args.host}:{args.port}"
    print(f"M2V 本地编辑器启动: {url}")
    print(f"扫描目录: {_scan_dir}")
    print("Ctrl+C 退出")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
