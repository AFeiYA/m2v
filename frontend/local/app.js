/* ============================================================
   M2V 本地时间轴编辑器 — 前端核心逻辑 (本地单机版)
   ============================================================ */

const state = {
  stem: null,            // 歌曲名
  jsonPath: null,        // JSON 文件绝对路径
  audioPath: null,       // 音频文件绝对路径
  alignment: null,       // { lines: [...] }
  selectedLine: -1,      // 选中行号
  selectedWord: -1,      // 选中字索引
  undoStack: [],
  redoStack: [],
  dirty: false,
};

let ws = null;
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  // 缓存 DOM 节点
  dom.songSelect     = $("#song-select");
  dom.btnSave        = $("#btn-save");
  dom.btnUndo        = $("#btn-undo");
  dom.btnRedo        = $("#btn-redo");
  dom.btnRegenAss    = $("#btn-regen-ass");
  dom.statusMsg      = $("#status-msg");
  dom.waveform       = $("#waveform");
  dom.btnPlayPause   = $("#btn-play-pause");
  dom.btnPlayLine    = $("#btn-play-line");
  dom.timeDisplay    = $("#time-display");
  dom.zoomSlider     = $("#zoom-slider");
  dom.lyricsList     = $("#lyrics-list");
  dom.wordTitle      = $("#word-panel-title");
  dom.wordTimeline   = $("#word-timeline");
  dom.btnShiftLeft   = $("#btn-shift-left");
  dom.btnNudgeLeft   = $("#btn-nudge-left");
  dom.btnNudgeRight  = $("#btn-nudge-right");
  dom.btnShiftRight  = $("#btn-shift-right");
  dom.btnEvenSplit   = $("#btn-even-split");
  dom.btnPlayWord    = $("#btn-play-word");

  dom.lineEditControls  = $("#line-edit-controls");
  dom.btnLineNudgeLeftBig  = $("#btn-line-nudge-left-big");
  dom.btnLineNudgeLeft     = $("#btn-line-nudge-left");
  dom.btnLineNudgeRight    = $("#btn-line-nudge-right");
  dom.btnLineNudgeRightBig = $("#btn-line-nudge-right-big");
  dom.btnLineExpand  = $("#btn-line-expand");
  dom.btnLineShrink  = $("#btn-line-shrink");

  initWaveSurfer();
  bindEvents();
  loadSongList();
});

function initWaveSurfer() {
  ws = WaveSurfer.create({
    container: dom.waveform,
    waveColor:     "#4a90d9",
    progressColor: "#e94560",
    cursorColor:   "#fff",
    height: 128,
    barWidth: 2,
    barGap: 1,
    barRadius: 2,
    normalize: true,
    backend: "WebAudio",
  });

  ws.on("ready", () => {
    updateTimeDisplay();
    status("音频已加载");
  });

  ws.on("audioprocess", () => {
    updateTimeDisplay();
    highlightPlayingLine();
  });

  ws.on("timeupdate", () => {
    updateTimeDisplay();
    highlightPlayingLine();
  });

  ws.on("seeking", () => {
    updateTimeDisplay();
  });

  ws.on("finish", () => {
    dom.btnPlayPause.textContent = "▶ 播放";
  });
}

function updateTimeDisplay() {
  if (!ws) return;
  const cur = ws.getCurrentTime();
  const dur = ws.getDuration() || 0;
  dom.timeDisplay.textContent = `${fmtTime(cur)} / ${fmtTime(dur)}`;
}

function fmtTime(s) {
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

function bindEvents() {
  dom.songSelect.addEventListener("change", () => {
    const jsonPath = dom.songSelect.value;
    const opt = dom.songSelect.selectedOptions[0];
    const audioPath = opt?.dataset?.audio || "";
    const stem = opt?.dataset?.stem || "未知";
    if (jsonPath) loadSong(jsonPath, audioPath, stem);
  });

  dom.btnSave.addEventListener("click", saveAlignment);
  dom.btnUndo.addEventListener("click", undo);
  dom.btnRedo.addEventListener("click", redo);
  dom.btnRegenAss.addEventListener("click", () => regen("ass"));

  dom.btnPlayPause.addEventListener("click", togglePlay);
  dom.btnPlayLine.addEventListener("click", playSelectedLine);

  dom.zoomSlider.addEventListener("input", () => {
    if (ws) ws.zoom(Number(dom.zoomSlider.value));
  });

  dom.btnShiftLeft.addEventListener("click",  () => nudgeWord(-0.05));
  dom.btnNudgeLeft.addEventListener("click",  () => nudgeWord(-0.01));
  dom.btnNudgeRight.addEventListener("click", () => nudgeWord(0.01));
  dom.btnShiftRight.addEventListener("click", () => nudgeWord(0.05));
  dom.btnEvenSplit.addEventListener("click",  evenSplitLine);
  dom.btnPlayWord.addEventListener("click",   playSelectedWord);

  dom.btnLineNudgeLeftBig.addEventListener("click",  () => nudgeLine(state.selectedLine, -0.2));
  dom.btnLineNudgeLeft.addEventListener("click",     () => nudgeLine(state.selectedLine, -0.05));
  dom.btnLineNudgeRight.addEventListener("click",    () => nudgeLine(state.selectedLine, 0.05));
  dom.btnLineNudgeRightBig.addEventListener("click", () => nudgeLine(state.selectedLine, 0.2));
  dom.btnLineExpand.addEventListener("click",        () => resizeLine(state.selectedLine, -0.05, 0.05));
  dom.btnLineShrink.addEventListener("click",        () => resizeLine(state.selectedLine, 0.05, -0.05));

  document.addEventListener("keydown", handleGlobalKeyDown);
}

function handleGlobalKeyDown(e) {
  const activeEl = document.activeElement;
  if (activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "SELECT")) {
    return;
  }

  const ctrl = e.ctrlKey || e.metaKey;

  switch (true) {
    case e.code === "Space":
      e.preventDefault();
      togglePlay();
      break;
    case e.code === "Enter":
      e.preventDefault();
      playSelectedLine();
      break;
    case e.code === "KeyZ" && ctrl:
      e.preventDefault();
      undo();
      break;
    case e.code === "KeyY" && ctrl:
      e.preventDefault();
      redo();
      break;
    case e.code === "KeyS" && ctrl:
      e.preventDefault();
      saveAlignment();
      break;
    case e.code === "ArrowLeft" && !ctrl:
      e.preventDefault();
      nudgeWord(-0.01);
      break;
    case e.code === "ArrowRight" && !ctrl:
      e.preventDefault();
      nudgeWord(0.01);
      break;
    case e.code === "ArrowLeft" && ctrl:
      e.preventDefault();
      nudgeWord(-0.05);
      break;
    case e.code === "ArrowRight" && ctrl:
      e.preventDefault();
      nudgeWord(0.05);
      break;
    case e.code === "BracketLeft" && !ctrl && !e.shiftKey:
      e.preventDefault();
      if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.05);
      break;
    case e.code === "BracketRight" && !ctrl && !e.shiftKey:
      e.preventDefault();
      if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.05);
      break;
    case e.code === "BracketLeft" && !ctrl && e.shiftKey:
      e.preventDefault();
      if (state.selectedLine >= 0) resizeLine(state.selectedLine, -0.05, 0.05);
      break;
    case e.code === "BracketRight" && !ctrl && e.shiftKey:
      e.preventDefault();
      if (state.selectedLine >= 0) resizeLine(state.selectedLine, 0.05, -0.05);
      break;
  }
}

// ── API 工具函数 ──
async function api(url, options = {}) {
  try {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      let msg = resp.statusText;
      if (typeof err.detail === "string") {
        msg = err.detail;
      } else if (Array.isArray(err.detail)) {
        msg = err.detail.map(e => e.msg || JSON.stringify(e)).join("; ");
      } else if (err.detail?.errors) {
        msg = err.detail.errors.join("; ");
      } else if (err.errors) {
        msg = err.errors.join("; ");
      } else if (typeof err.detail === "object") {
        msg = JSON.stringify(err.detail);
      }
      throw new Error(msg);
    }
    return resp;
  } catch (e) {
    status(`❌ ${e.message}`, true);
    throw e;
  }
}

function status(msg, isError = false) {
  dom.statusMsg.textContent = msg;
  dom.statusMsg.style.color = isError ? "var(--accent)" : "var(--text-dim)";
  if (!isError) setTimeout(() => { dom.statusMsg.textContent = ""; }, 4000);
}

// ── 歌曲列表与加载 ──
async function loadSongList() {
  try {
    const resp = await api("/api/files");
    const files = await resp.json();
    dom.songSelect.innerHTML = "";

    if (files.length === 0) {
      dom.songSelect.innerHTML = `<option value="">无可用歌曲 (请确认 output 目录有 json 文件)</option>`;
      return;
    }

    files.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.json_path;
      opt.dataset.audio = f.audio_path || "";
      opt.dataset.stem = f.name;
      opt.textContent = f.name;
      dom.songSelect.appendChild(opt);
    });

    const target = files[0];
    dom.songSelect.value = target.json_path;
    loadSong(target.json_path, target.audio_path, target.name);
  } catch (e) {
    dom.songSelect.innerHTML = `<option value="">加载失败: ${e.message}</option>`;
  }
}

async function loadSong(jsonPath, audioPath, stem) {
  status(`加载 ${stem}…`);
  state.stem = stem;
  state.jsonPath = jsonPath;
  state.audioPath = audioPath;
  state.selectedLine = -1;
  state.selectedWord = -1;
  state.undoStack = [];
  state.redoStack = [];
  state.dirty = false;

  try {
    const resp = await api(`/api/alignment?path=${encodeURIComponent(jsonPath)}`);
    state.alignment = await resp.json();
  } catch (e) {
    state.alignment = null;
    return;
  }

  if (audioPath) {
    try {
      const audioUrl = `/api/audio?path=${encodeURIComponent(audioPath)}`;
      const audioResp = await api(audioUrl);
      const audioBlob = await audioResp.blob();
      await ws.loadBlob(audioBlob);
    } catch (e) {
      status("音频加载失败: " + e.message, true);
    }
  } else {
    status("⚠️ 未找到匹配的音频文件 (请将 MP3 放入 input 或 output 目录)", true);
  }

  renderLyrics();
  clearWordPanel();
  status(`已加载: ${stem}`);
}

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

    row.innerHTML = `
      <span class="lyric-num">${i + 1}</span>
      <span class="lyric-text">${charSpans}</span>
      <div class="lyric-time-edit" onclick="event.stopPropagation()">
        <input class="time-input" type="text" data-idx="${i}" data-field="start" value="${fmtTimeShort(line.start)}">
        <span class="time-arrow">→</span>
        <input class="time-input" type="text" data-idx="${i}" data-field="end" value="${fmtTimeShort(line.end)}">
        <span class="line-dur">${(line.end - line.start).toFixed(2)}s</span>
      </div>
    `;

    row.addEventListener("click", () => selectLine(i));
    dom.lyricsList.appendChild(row);
  });

  // Bind change events to all inputs
  $$(".time-input").forEach((inp) => {
    inp.addEventListener("change", handleLineTimeInput);
  });
}

function selectLine(idx) {
  state.selectedLine = idx;
  $$(".lyric-row").forEach((r, i) => {
    r.classList.toggle("selected", i === idx);
  });

  const line = state.alignment?.lines[idx];
  if (!line) return;

  // Sync wavesurfer cursor to line start
  if (ws && !ws.isPlaying()) {
    ws.setTime(line.start);
  }

  renderWords(idx);
}

function highlightPlayingLine() {
  if (!ws || !state.alignment) return;
  const t = ws.getCurrentTime();
  const lines = state.alignment.lines;

  let activeLineIdx = -1;
  lines.forEach((line, i) => {
    const isPlaying = t >= line.start && t <= line.end;
    const el = $$(".lyric-row")[i];
    if (el) el.classList.toggle("playing", isPlaying);
    if (isPlaying) activeLineIdx = i;

    // Highlight characters
    line.words.forEach((w, wi) => {
      const charEl = $(`.lyric-char[data-line="${i}"][data-word="${wi}"]`);
      if (charEl) {
        charEl.classList.toggle("sung", t > w.end);
        charEl.classList.toggle("singing", t >= w.start && t <= w.end);
      }
    });
  });

  // Highlight word bars in word timeline
  if (activeLineIdx === state.selectedLine) {
    const line = lines[activeLineIdx];
    line.words.forEach((w, wi) => {
      const bar = $(`.word-bar[data-idx="${wi}"]`);
      if (bar) {
        bar.classList.toggle("bar-singing", t >= w.start && t <= w.end);
      }
    });
  }
}

function clearWordPanel() {
  dom.wordTitle.textContent = "点击左侧歌词行查看字级时间";
  dom.wordTimeline.innerHTML = "";
  dom.lineEditControls.style.display = "none";
}

function renderWords(lineIdx) {
  const line = state.alignment.lines[lineIdx];
  if (!line) return;

  dom.wordTitle.textContent = `第 ${lineIdx + 1} 行字级时间线`;
  dom.lineEditControls.style.display = "flex";
  dom.wordTimeline.innerHTML = "";

  const container = document.createElement("div");
  container.className = "word-bar-container";

  const duration = line.end - line.start;
  if (duration <= 0) return;

  line.words.forEach((w, wi) => {
    const bar = document.createElement("div");
    const isP = isPunct(w.word);
    bar.className = `word-bar ${isP ? "punct" : ""}`;
    bar.dataset.idx = wi;

    const widthPercent = ((w.end - w.start) / duration) * 100;
    bar.style.width = `${widthPercent}%`;

    bar.innerHTML = `
      <span class="word-text">${escHtml(w.word)}</span>
      <span class="word-dur">${(w.end - w.start).toFixed(2)}s</span>
      <div class="drag-handle"></div>
    `;

    // Click to select word
    bar.addEventListener("click", (e) => {
      e.stopPropagation();
      selectWord(wi);
    });

    // Double click to snap to cursor
    bar.querySelector(".drag-handle").addEventListener("dblclick", (e) => {
      e.stopPropagation();
      snapWordEndToPlayhead(wi);
    });

    // Drag to resize word
    setupDrag(bar.querySelector(".drag-handle"), wi);

    container.appendChild(bar);
  });

  dom.wordTimeline.appendChild(container);
  state.selectedWord = -1;
  updateWordSelectionUI();
}

function selectWord(idx) {
  state.selectedWord = idx;
  updateWordSelectionUI();
}

function updateWordSelectionUI() {
  $$(".word-bar").forEach((b, i) => {
    b.classList.toggle("selected", i === state.selectedWord);
  });
}

function setupDrag(handle, wordIdx) {
  let startX = 0;
  let startWidth = 0;
  let timelineWidth = 0;
  const lineIdx = state.selectedLine;

  const onMouseDown = (e) => {
    e.preventDefault();
    e.stopPropagation();
    startX = e.clientX;
    const bar = handle.parentElement;
    startWidth = bar.offsetWidth;
    timelineWidth = dom.wordTimeline.offsetWidth - 24;

    pushUndo();

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  const onMouseMove = (e) => {
    const dx = e.clientX - startX;
    const dt = (dx / timelineWidth) * (state.alignment.lines[lineIdx].end - state.alignment.lines[lineIdx].start);
    adjustWordBoundary(lineIdx, wordIdx, dt);
  };

  const onMouseUp = () => {
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
    renderLyrics();
    selectLine(lineIdx);
  };

  handle.addEventListener("mousedown", onMouseDown);
}

function adjustWordBoundary(lineIdx, wordIdx, dt) {
  const line = state.alignment.lines[lineIdx];
  if (!line) return;

  const w = line.words[wordIdx];
  const nextW = line.words[wordIdx + 1];

  let targetEnd = w.end + dt;

  // Bounds check
  const minDur = 0.02; // 20ms
  if (targetEnd < w.start + minDur) targetEnd = w.start + minDur;

  if (nextW) {
    if (targetEnd > nextW.end - minDur) targetEnd = nextW.end - minDur;
    nextW.start = targetEnd;
  } else {
    // Last word boundary changes line end
    if (targetEnd > line.start + 60) targetEnd = line.start + 60; // max 1 min per line
  }

  w.end = targetEnd;

  // Re-render word timeline
  const oldLineEnd = line.end;
  if (!nextW) {
    line.end = targetEnd;
  }

  // Proportionally resize the visual width of bars
  const totalDur = line.end - line.start;
  line.words.forEach((word, idx) => {
    const bar = $(`.word-bar[data-idx="${idx}"]`);
    if (bar) {
      const widthPercent = ((word.end - word.start) / totalDur) * 100;
      bar.style.width = `${widthPercent}%`;
      bar.querySelector(".word-dur").textContent = `${(word.end - word.start).toFixed(2)}s`;
    }
  });

  markDirty();
}

function snapWordEndToPlayhead(wordIdx) {
  if (!ws) return;
  const lineIdx = state.selectedLine;
  const line = state.alignment.lines[lineIdx];
  const w = line.words[wordIdx];
  const nextW = line.words[wordIdx + 1];
  const t = ws.getCurrentTime();

  pushUndo();

  let targetEnd = t;
  const minDur = 0.02;

  if (targetEnd < w.start + minDur) targetEnd = w.start + minDur;

  if (nextW) {
    if (targetEnd > nextW.end - minDur) targetEnd = nextW.end - minDur;
    nextW.start = targetEnd;
  } else {
    line.end = targetEnd;
  }

  w.end = targetEnd;

  renderLyrics();
  selectLine(lineIdx);
  markDirty();
}

function nudgeWord(delta) {
  if (state.selectedLine < 0 || state.selectedWord < 0) {
    status("请先选中一个字", true);
    return;
  }
  const lineIdx = state.selectedLine;
  const wordIdx = state.selectedWord;
  const line = state.alignment.lines[lineIdx];
  const w = line.words[wordIdx];
  const nextW = line.words[wordIdx + 1];

  pushUndo();

  let targetEnd = w.end + delta;
  const minDur = 0.02;

  if (targetEnd < w.start + minDur) targetEnd = w.start + minDur;

  if (nextW) {
    if (targetEnd > nextW.end - minDur) targetEnd = nextW.end - minDur;
    nextW.start = targetEnd;
  } else {
    line.end = targetEnd;
  }

  w.end = targetEnd;

  renderLyrics();
  selectLine(lineIdx);
  selectWord(wordIdx);
  markDirty();
}

function evenSplitLine() {
  if (state.selectedLine < 0) return;
  const lineIdx = state.selectedLine;
  const line = state.alignment.lines[lineIdx];
  if (!line || !line.words.length) return;

  pushUndo();

  const duration = line.end - line.start;
  const count = line.words.length;
  const chunk = duration / count;

  line.words.forEach((w, i) => {
    w.start = Math.round((line.start + i * chunk) * 1000) / 1000;
    w.end   = Math.round((line.start + (i + 1) * chunk) * 1000) / 1000;
  });

  renderLyrics();
  selectLine(lineIdx);
  markDirty();
  status("整行字级已均分");
}

function nudgeLine(lineIdx, delta) {
  const line = state.alignment.lines[lineIdx];
  if (!line || !line.words.length) return;

  pushUndo();

  const newStart = Math.round((line.start + delta) * 1000) / 1000;
  const newEnd   = Math.round((line.end + delta) * 1000) / 1000;
  if (newStart < 0) return;

  line.words.forEach(w => {
    w.start = Math.round((w.start + delta) * 1000) / 1000;
    w.end   = Math.round((w.end + delta) * 1000) / 1000;
  });
  line.start = newStart;
  line.end = newEnd;

  renderLyrics();
  selectLine(lineIdx);
  markDirty();
}

function resizeLine(lineIdx, startDelta, endDelta) {
  const line = state.alignment.lines[lineIdx];
  if (!line || !line.words.length) return;

  const oldStart = line.start;
  const oldEnd = line.end;
  const oldDur = oldEnd - oldStart;
  if (oldDur <= 0) return;

  let newStart = Math.round((oldStart + startDelta) * 1000) / 1000;
  let newEnd   = Math.round((oldEnd + endDelta) * 1000) / 1000;
  if (newStart < 0) newStart = 0;
  if (newEnd - newStart < 0.1) return;

  pushUndo();

  const newDur = newEnd - newStart;
  const ratio = newDur / oldDur;

  line.words.forEach(w => {
    const relStart = (w.start - oldStart) / oldDur;
    const relEnd   = (w.end - oldStart) / oldDur;
    w.start = Math.round((newStart + relStart * newDur) * 1000) / 1000;
    w.end   = Math.round((newStart + relEnd * newDur) * 1000) / 1000;
  });
  line.start = newStart;
  line.end = newEnd;

  line.words[0].start = newStart;
  line.words[line.words.length - 1].end = newEnd;

  renderLyrics();
  selectLine(lineIdx);
  markDirty();
}

function handleLineTimeInput(e) {
  const input = e.target;
  const idx = Number(input.dataset.idx);
  const field = input.dataset.field;
  const line = state.alignment?.lines[idx];
  if (!line) return;

  const parsed = parseTimeInput(input.value);
  if (parsed === null) {
    input.value = fmtTimeShort(line[field]);
    status("时间格式错误，请输入 m:ss.xxx 或 秒数", true);
    return;
  }

  if (field === "start") {
    const startDelta = parsed - line.start;
    const endDelta = 0;
    resizeLine(idx, startDelta, endDelta);
  } else {
    const startDelta = 0;
    const endDelta = parsed - line.end;
    resizeLine(idx, startDelta, endDelta);
  }
}

function parseTimeInput(str) {
  str = str.trim();
  const match = str.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const mins = match[1] ? Number(match[1]) : 0;
  const secs = Number(match[2]);
  const total = mins * 60 + secs;
  return total >= 0 ? Math.round(total * 1000) / 1000 : null;
}

function fmtTimeShort(s) {
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

function togglePlay() {
  if (!ws) return;
  if (ws.isPlaying()) {
    ws.pause();
    dom.btnPlayPause.textContent = "▶ 播放";
  } else {
    ws.play();
    dom.btnPlayPause.textContent = "⏸ 暂停";
  }
}

function playSelectedLine() {
  if (state.selectedLine < 0 || !ws) return;
  const line = state.alignment.lines[state.selectedLine];
  if (!line) return;

  ws.setTime(line.start);
  ws.play();
  dom.btnPlayPause.textContent = "⏸ 暂停";

  const stopAt = line.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause();
      dom.btnPlayPause.textContent = "▶ 播放";
    } else if (ws.isPlaying()) {
      requestAnimationFrame(check);
    }
  };
  requestAnimationFrame(check);
}

function playSelectedWord() {
  if (state.selectedLine < 0 || state.selectedWord < 0 || !ws) return;
  const w = state.alignment.lines[state.selectedLine]?.words?.[state.selectedWord];
  if (!w) return;

  ws.setTime(w.start);
  ws.play();
  dom.btnPlayPause.textContent = "⏸ 暂停";

  const stopAt = w.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause();
      dom.btnPlayPause.textContent = "▶ 播放";
    } else if (ws.isPlaying()) {
      requestAnimationFrame(check);
    }
  };
  requestAnimationFrame(check);
}

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
  if (state.selectedLine >= 0) {
    renderWords(state.selectedLine);
    selectLine(state.selectedLine);
  }
  markDirty();
  status("已撤销");
}

function redo() {
  if (!state.redoStack.length) { status("无可重做操作"); return; }
  state.undoStack.push(JSON.stringify(state.alignment));
  state.alignment = JSON.parse(state.redoStack.pop());
  renderLyrics();
  if (state.selectedLine >= 0) {
    renderWords(state.selectedLine);
    selectLine(state.selectedLine);
  }
  markDirty();
  status("已重做");
}

function markDirty() {
  state.dirty = true;
  document.title = "● M2V 本地时间轴编辑器";
}

async function saveAlignment() {
  if (!state.jsonPath || !state.alignment) return;
  status("保存中…");

  try {
    await api(`/api/alignment?path=${encodeURIComponent(state.jsonPath)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.alignment),
    });
    state.dirty = false;
    document.title = "M2V 本地时间轴编辑器";
    status("✅ 已保存");
  } catch {
    // error displayed by api()
  }
}

async function regen(mode) {
  if (!state.jsonPath) return;
  status("重新生成 ASS 中…");

  try {
    const resp = await api("/api/regen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.jsonPath,
        audio_path: state.audioPath
      }),
    });
    const result = await resp.json();
    status(`✅ ASS 已生成: ${result.ass_path}`);
  } catch {
    // error displayed by api()
  }
}

function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function isPunct(ch) {
  return /^[\s，。、！？；：""''（）《》…—·\-,.!?;:'"()\[\]{}]$/.test(ch);
}

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
