/* ============================================================
   M2V 时间轴编辑器 — 前端核心逻辑
   ============================================================ */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  stem: null,            // 当前歌曲名
  taskId: null,          // 当前任务 ID (SaaS 模式)
  alignment: null,       // { lines: [...] }
  selectedLine: -1,      // 选中行号
  selectedWord: -1,      // 选中字索引
  undoStack: [],
  redoStack: [],
  dirty: false,
};

// WaveSurfer instance
let ws = null;

// DOM caches
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  // Cache DOM elements
  dom.songSelect     = $("#song-select");
  dom.btnSave        = $("#btn-save");
  dom.btnUndo        = $("#btn-undo");
  dom.btnRedo        = $("#btn-redo");
  dom.btnRegenAss    = $("#btn-regen-ass");
  dom.btnRegenVideo  = $("#btn-regen-video");
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

  // Line editing controls in word panel
  dom.lineEditControls  = $("#line-edit-controls");
  dom.btnLineNudgeLeftBig  = $("#btn-line-nudge-left-big");
  dom.btnLineNudgeLeft     = $("#btn-line-nudge-left");
  dom.btnLineNudgeRight    = $("#btn-line-nudge-right");
  dom.btnLineNudgeRightBig = $("#btn-line-nudge-right-big");
  dom.btnLineExpand  = $("#btn-line-expand");
  dom.btnLineShrink  = $("#btn-line-shrink");

  // Init
  initWaveSurfer();
  bindEvents();
  loadSongList();
});

// ---------------------------------------------------------------------------
// WaveSurfer
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Event Binding
// ---------------------------------------------------------------------------
function bindEvents() {
  // Song selector
  dom.songSelect.addEventListener("change", () => {
    const taskId = dom.songSelect.value;
    const opt = dom.songSelect.selectedOptions[0];
    const stem = opt?.dataset?.stem || taskId;
    if (taskId) loadSong(taskId, stem);
  });

  // Toolbar
  dom.btnSave.addEventListener("click", saveAlignment);
  dom.btnUndo.addEventListener("click", undo);
  dom.btnRedo.addEventListener("click", redo);
  dom.btnRegenAss.addEventListener("click", () => regen("ass"));
  dom.btnRegenVideo.addEventListener("click", () => regen("video"));

  // Playback
  dom.btnPlayPause.addEventListener("click", togglePlay);
  dom.btnPlayLine.addEventListener("click", playSelectedLine);

  // Zoom
  dom.zoomSlider.addEventListener("input", () => {
    if (ws) ws.zoom(Number(dom.zoomSlider.value));
  });

  // Word controls
  dom.btnShiftLeft.addEventListener("click",  () => nudgeWord(-0.05));
  dom.btnNudgeLeft.addEventListener("click",  () => nudgeWord(-0.01));
  dom.btnNudgeRight.addEventListener("click", () => nudgeWord(0.01));
  dom.btnShiftRight.addEventListener("click", () => nudgeWord(0.05));
  dom.btnEvenSplit.addEventListener("click",  evenSplitLine);
  dom.btnPlayWord.addEventListener("click",   playSelectedWord);

  // Line-level controls (in word panel header)
  dom.btnLineNudgeLeftBig.addEventListener("click",  () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.2); });
  dom.btnLineNudgeLeft.addEventListener("click",     () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.05); });
  dom.btnLineNudgeRight.addEventListener("click",    () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.05); });
  dom.btnLineNudgeRightBig.addEventListener("click", () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.2); });
  dom.btnLineExpand.addEventListener("click",  () => { if (state.selectedLine >= 0) resizeLine(state.selectedLine, -0.05, 0.05); });
  dom.btnLineShrink.addEventListener("click",  () => { if (state.selectedLine >= 0) resizeLine(state.selectedLine, 0.05, -0.05); });

  // Keyboard shortcuts
  document.addEventListener("keydown", handleKey);
}

function handleKey(e) {
  // Don't handle if focused on an input
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;

  const ctrl = e.ctrlKey || e.metaKey;
  switch (true) {
    case e.code === "Space":
      e.preventDefault(); togglePlay(); break;
    case ctrl && e.code === "KeyS":
      e.preventDefault(); saveAlignment(); break;
    case ctrl && e.code === "KeyZ" && !e.shiftKey:
      e.preventDefault(); undo(); break;
    case ctrl && (e.code === "KeyY" || (e.code === "KeyZ" && e.shiftKey)):
      e.preventDefault(); redo(); break;
    case e.code === "ArrowLeft" && !ctrl:
      e.preventDefault(); nudgeWord(-0.01); break;
    case e.code === "ArrowRight" && !ctrl:
      e.preventDefault(); nudgeWord(0.01); break;
    case e.code === "KeyA" && !ctrl:
      e.preventDefault(); nudgeWord(-0.05); break;
    case e.code === "KeyD" && !ctrl:
      e.preventDefault(); nudgeWord(0.05); break;
    case e.code === "ArrowUp":
      e.preventDefault(); selectAdjacentLine(-1); break;
    case e.code === "ArrowDown":
      e.preventDefault(); selectAdjacentLine(1); break;
    case e.code === "Enter":
      e.preventDefault(); playSelectedLine(); break;
    case e.code === "Tab" && !ctrl:
      e.preventDefault();
      selectAdjacentWord(e.shiftKey ? -1 : 1);
      break;
    // Line-level: [ ] shift line, Shift+[ ] expand/shrink
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

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function api(url, options = {}) {
  try {
    // 自动注入 JWT Token
    const token = localStorage.getItem("m2v_token");
    if (token) {
      options.headers = options.headers || {};
      if (typeof options.headers === "object" && !(options.headers instanceof Headers)) {
        options.headers["Authorization"] = `Bearer ${token}`;
      }
    }
    const resp = await fetch(url, options);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      // detail 可能是字符串、{errors: [...]}、或 [{msg:...}, ...]
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

// ---------------------------------------------------------------------------
// Song List & Loading
// ---------------------------------------------------------------------------
async function loadSongList() {
  try {
    const resp = await api("/api/editor/songs");
    const songs = await resp.json();
    dom.songSelect.innerHTML = "";

    if (songs.length === 0) {
      dom.songSelect.innerHTML = `<option value="">无可用歌曲</option>`;
      return;
    }

    songs.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.task_id;
      opt.dataset.stem = s.stem;
      opt.textContent = `${s.stem}  (${s.lines_count}行, ${s.duration}s)`;
      dom.songSelect.appendChild(opt);
    });

    // 从 URL 中获取 task_id，否则加载第一首
    const urlTaskId = new URLSearchParams(window.location.search).get("task_id")
      || window.location.pathname.split("/editor/")[1];
    const target = urlTaskId
      ? songs.find(s => s.task_id === urlTaskId) || songs[0]
      : songs[0];
    dom.songSelect.value = target.task_id;
    loadSong(target.task_id, target.stem);
  } catch {
    dom.songSelect.innerHTML = `<option value="">加载失败</option>`;
  }
}

async function loadSong(taskId, stem) {
  stem = stem || taskId;
  status(`加载 ${stem}…`);
  state.stem = stem;
  state.taskId = taskId;
  state.selectedLine = -1;
  state.selectedWord = -1;
  state.undoStack = [];
  state.redoStack = [];
  state.dirty = false;

  // Load alignment
  try {
    const resp = await api(`/api/editor/tasks/${encodeURIComponent(taskId)}/align`);
    state.alignment = await resp.json();
  } catch {
    state.alignment = null;
    return;
  }

  // Load audio
  try {
    const token = localStorage.getItem("m2v_token");
    const audioUrl = `/api/editor/tasks/${encodeURIComponent(taskId)}/audio`;
    // WaveSurfer needs auth header for fetching audio
    ws.load(audioUrl, undefined, undefined, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch (e) {
    status("音频加载失败: " + e.message, true);
  }

  // Render
  renderLyrics();
  clearWordPanel();
  status(`已加载: ${stem}`);
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
    // 逐字渲染，便于播放时高亮当前字
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
      </span>
    `;
    row.addEventListener("click", (e) => {
      // Don't select line when clicking inputs/buttons
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      selectLine(i);
    });
    row.addEventListener("dblclick", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      if (ws) {
        ws.setTime(line.start);
        ws.play();
        dom.btnPlayPause.textContent = "⏸ 暂停";
      }
    });
    dom.lyricsList.appendChild(row);
  });

  // Bind line-level time input events
  dom.lyricsList.querySelectorAll(".time-input").forEach(input => {
    input.addEventListener("change", handleLineTimeInput);
    input.addEventListener("keydown", (e) => {
      if (e.code === "Enter") { e.target.blur(); }
      e.stopPropagation(); // Don't trigger global shortcuts
    });
    input.addEventListener("focus", (e) => e.target.select());
  });

  // Bind line nudge buttons
  dom.lyricsList.querySelectorAll(".line-nudge-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.idx);
      const delta = Number(btn.dataset.delta);
      nudgeLine(idx, delta);
    });
  });
}

function selectLine(idx) {
  state.selectedLine = idx;
  state.selectedWord = -1;

  // Highlight
  $$(".lyric-row").forEach((row, i) => {
    row.classList.toggle("selected", i === idx);
  });

  // Seek waveform
  const line = state.alignment.lines[idx];
  if (ws && line) {
    ws.setTime(line.start);
  }

  // Show line editing controls
  if (dom.lineEditControls) {
    dom.lineEditControls.style.display = idx >= 0 ? "flex" : "none";
  }

  // Render words
  renderWords(idx);
}

function selectAdjacentLine(delta) {
  const lines = state.alignment?.lines || [];
  if (!lines.length) return;
  let next = state.selectedLine + delta;
  next = Math.max(0, Math.min(next, lines.length - 1));
  selectLine(next);

  // Scroll into view
  const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${next}"]`);
  if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function highlightPlayingLine() {
  if (!ws || !state.alignment) return;
  const t = ws.getCurrentTime();
  const lines = state.alignment.lines;

  // --- 行级高亮 + 字级高亮 ---
  let activeLineIdx = -1;

  $$(".lyric-row").forEach((row, i) => {
    const line = lines[i];
    const playing = line && t >= line.start && t <= line.end;
    row.classList.toggle("playing", playing);
    if (playing) activeLineIdx = i;
  });

  // 逐字高亮: 歌词面板中的 .lyric-char
  $$(".lyric-char").forEach((span) => {
    const li = Number(span.dataset.line);
    const wi = Number(span.dataset.word);
    const line = lines[li];
    if (!line) { span.classList.remove("sung", "singing"); return; }
    const w = line.words[wi];
    if (!w) { span.classList.remove("sung", "singing"); return; }

    if (t >= w.end) {
      span.classList.add("sung");
      span.classList.remove("singing");
    } else if (t >= w.start) {
      span.classList.add("singing");
      span.classList.remove("sung");
    } else {
      span.classList.remove("sung", "singing");
    }
  });

  // 字面板高亮: 右侧 word-bar
  if (activeLineIdx >= 0 && activeLineIdx === state.selectedLine) {
    const line = lines[activeLineIdx];
    $$(".word-bar").forEach((bar) => {
      const wi = Number(bar.dataset.idx);
      const w = line.words[wi];
      if (!w) { bar.classList.remove("bar-singing"); return; }
      bar.classList.toggle("bar-singing", t >= w.start && t < w.end);
    });
  }

  // 自动滚动到当前播放行
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

  // Find line time range for proportional sizing
  const lineStart = line.start;
  const lineEnd   = line.end;
  const lineDur   = lineEnd - lineStart || 1;

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
      <div class="drag-handle" title="拖拽调整 | 双击=设为当前播放位置"></div>
    `;

    // Click to select
    bar.addEventListener("click", (e) => {
      if (e.target.classList.contains("drag-handle")) return;
      selectWord(i);
    });

    // Double-click to play
    bar.addEventListener("dblclick", () => {
      if (ws) {
        ws.setTime(w.start);
        ws.play();
        dom.btnPlayPause.textContent = "⏸ 暂停";
        // Stop at word end
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
    });

    // Drag handle for resizing + double-click to snap to playhead
    setupDragHandle(bar, i, lineIdx);

    // Double-click on drag handle: snap split point to current playhead
    const handle = bar.querySelector(".drag-handle");
    if (handle) {
      handle.addEventListener("dblclick", (e) => {
        e.preventDefault();
        e.stopPropagation();
        snapSplitToPlayhead(lineIdx, i);
      });
    }

    container.appendChild(bar);
  });

  dom.wordTimeline.appendChild(container);

  // Select first word by default
  if (words.length > 0 && state.selectedWord < 0) {
    selectWord(0);
  }
}

function clearWordPanel() {
  dom.wordTitle.textContent = "点击左侧歌词行查看字级时间";
  dom.wordTimeline.innerHTML = "";
}

function selectWord(idx) {
  state.selectedWord = idx;
  $$(".word-bar").forEach((bar, i) => {
    bar.classList.toggle("selected", i === idx);
  });
}

function selectAdjacentWord(delta) {
  if (state.selectedLine < 0) return;
  const words = state.alignment?.lines[state.selectedLine]?.words || [];
  if (!words.length) return;
  let next = state.selectedWord + delta;
  next = Math.max(0, Math.min(next, words.length - 1));
  selectWord(next);
}

// ---------------------------------------------------------------------------
// Drag-to-resize word boundary
// ---------------------------------------------------------------------------

/** Double-click a split handle → snap that boundary to the current playhead position.
 *  For the last word, sets word.end + line.end to the playhead. */
function snapSplitToPlayhead(lineIdx, wordIdx) {
  if (!ws) return;
  const line = state.alignment.lines[lineIdx];
  if (!line) return;
  const words = line.words;
  const isLast = (wordIdx === words.length - 1);

  const t = ws.getCurrentTime();

  if (isLast) {
    // Last word: snap its end (and line end) to playhead
    const minVal = words[wordIdx].start + 0.01;
    const clamped = Math.round(Math.max(minVal, t) * 1000) / 1000;

    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;

    pushUndo();
    words[wordIdx].end = clamped;
    line.end = clamped;

    renderLyrics();
    selectLine(lineIdx);
    selectWord(wordIdx);
    markDirty();
    status(`✂ 行尾 → ${fmtTimeShort(clamped)}`);
  } else {
    // Middle word: snap the boundary between wordIdx and wordIdx+1
    const minVal = words[wordIdx].start + 0.01;
    const maxVal = words[wordIdx + 1].end - 0.01;
    const clamped = Math.round(Math.max(minVal, Math.min(maxVal, t)) * 1000) / 1000;

    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;

    pushUndo();
    words[wordIdx].end = clamped;
    words[wordIdx + 1].start = clamped;

    syncLineFromWords(lineIdx);
    renderWords(lineIdx);
    selectWord(wordIdx);
    markDirty();
    status(`✂ 分割点 ${wordIdx + 1}|${wordIdx + 2} → ${fmtTimeShort(clamped)}`);
  }
}

function setupDragHandle(bar, wordIdx, lineIdx) {
  const handle = bar.querySelector(".drag-handle");
  if (!handle) return;

  let startX = 0;
  let startEnd = 0;
  let containerWidth = 0;
  let lineDur = 0;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();

    const line = state.alignment.lines[lineIdx];
    const words = line.words;
    if (wordIdx >= words.length - 1) return; // Can't drag last word's right edge

    pushUndo();

    startX = e.clientX;
    startEnd = words[wordIdx].end;
    const container = bar.parentElement;
    containerWidth = container.getBoundingClientRect().width;
    lineDur = line.end - line.start;

    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      const dt = (dx / containerWidth) * lineDur;
      const newEnd = Math.round((startEnd + dt) * 1000) / 1000;

      // Clamp: must stay between current word start + 10ms and next word end - 10ms
      const minEnd = words[wordIdx].start + 0.01;
      const maxEnd = words[wordIdx + 1].end - 0.01;
      const clamped = Math.max(minEnd, Math.min(maxEnd, newEnd));

      words[wordIdx].end = clamped;
      words[wordIdx + 1].start = clamped;

      renderWords(lineIdx);
      selectWord(wordIdx);
      markDirty();
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
// Word Editing Operations
// ---------------------------------------------------------------------------
function nudgeWord(delta) {
  if (state.selectedLine < 0 || state.selectedWord < 0) return;

  const line = state.alignment.lines[state.selectedLine];
  const words = line.words;
  const idx = state.selectedWord;
  if (!words[idx]) return;

  pushUndo();

  // Shift the selected word's boundaries
  // Adjust start (and previous word's end)
  const newStart = Math.round((words[idx].start + delta) * 1000) / 1000;
  const newEnd   = Math.round((words[idx].end + delta) * 1000) / 1000;

  // Clamp checks
  if (newStart < 0 || newEnd < 0) return;
  if (idx > 0 && newStart < words[idx - 1].start + 0.01) return;
  if (idx < words.length - 1 && newEnd > words[idx + 1].end - 0.01) return;

  // Update previous word's end if exists
  if (idx > 0) {
    words[idx - 1].end = newStart;
  }
  // Update next word's start if exists
  if (idx < words.length - 1) {
    words[idx + 1].start = newEnd;
  }

  words[idx].start = newStart;
  words[idx].end = newEnd;

  syncLineFromWords(state.selectedLine);
  renderWords(state.selectedLine);
  selectWord(idx);
  markDirty();
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
    w.start = Math.round(t * 1000) / 1000;
    t += dur;
    w.end = Math.round(t * 1000) / 1000;
  });

  // Fix rounding
  words[words.length - 1].end = line.end;

  renderWords(state.selectedLine);
  markDirty();
}

function syncLineFromWords(lineIdx) {
  const line = state.alignment.lines[lineIdx];
  const words = line.words;
  if (!words.length) return;
  line.start = words[0].start;
  line.end = words[words.length - 1].end;

  // Update lyrics panel time display
  const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${lineIdx}"]`);
  if (row) {
    const timeSpan = row.querySelector(".lyric-time");
    if (timeSpan) {
      timeSpan.textContent = `${fmtTime(line.start)} → ${fmtTime(line.end)}`;
    }
  }
}

// ---------------------------------------------------------------------------
// Line-level Editing
// ---------------------------------------------------------------------------

function nudgeLine(lineIdx, delta) {
  const line = state.alignment.lines[lineIdx];
  if (!line) return;

  pushUndo();

  const newStart = Math.round((line.start + delta) * 1000) / 1000;
  const newEnd   = Math.round((line.end + delta) * 1000) / 1000;
  if (newStart < 0) return;

  // Shift all word timestamps
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
  if (newEnd - newStart < 0.1) return; // Min line duration 100ms

  pushUndo();

  const newDur = newEnd - newStart;
  const ratio = newDur / oldDur;

  // Proportionally redistribute all words
  line.words.forEach(w => {
    const relStart = (w.start - oldStart) / oldDur;
    const relEnd   = (w.end - oldStart) / oldDur;
    w.start = Math.round((newStart + relStart * newDur) * 1000) / 1000;
    w.end   = Math.round((newStart + relEnd * newDur) * 1000) / 1000;
  });
  line.start = newStart;
  line.end = newEnd;

  // Fix rounding: first word starts at line start, last word ends at line end
  line.words[0].start = newStart;
  line.words[line.words.length - 1].end = newEnd;

  renderLyrics();
  selectLine(lineIdx);
  markDirty();
}

function handleLineTimeInput(e) {
  const input = e.target;
  const idx = Number(input.dataset.idx);
  const field = input.dataset.field; // "start" or "end"
  const line = state.alignment?.lines[idx];
  if (!line) return;

  const parsed = parseTimeInput(input.value);
  if (parsed === null) {
    // Invalid input — revert
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
  // Format: m:ss.xxx or ss.xxx or just seconds
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

// ---------------------------------------------------------------------------
// Playback helpers
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Undo / Redo
// ---------------------------------------------------------------------------
function pushUndo() {
  state.undoStack.push(JSON.stringify(state.alignment));
  // Cap undo history
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
  document.title = "● M2V 时间轴编辑器";
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------
async function saveAlignment() {
  if (!state.taskId || !state.alignment) return;
  status("保存中…");

  try {
    await api(`/api/editor/tasks/${encodeURIComponent(state.taskId)}/align`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.alignment),
    });
    state.dirty = false;
    document.title = "M2V 时间轴编辑器";
    status("✅ 已保存");
  } catch {
    // error displayed by api()
  }
}

// ---------------------------------------------------------------------------
// Regen
// ---------------------------------------------------------------------------
async function regen(mode) {
  if (!state.taskId) return;
  status(mode === "video" ? "生成视频中…（可能较慢）" : "生成 ASS…");

  try {
    const resp = await api(`/api/editor/tasks/${encodeURIComponent(state.taskId)}/regen`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const result = await resp.json();
    status(`✅ 已生成: ${result.file}`);
  } catch {
    // error displayed by api()
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function isPunct(ch) {
  return /^[\s，。、！？；：""''（）《》…—·\-,.!?;:'"()\[\]{}]$/.test(ch);
}

// Warn before leaving with unsaved changes
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
