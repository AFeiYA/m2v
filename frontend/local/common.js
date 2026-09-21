// ===========================================================================
// M2V Local Editor — Common Module (Player, Song Selector, Status, Utilities)
// ===========================================================================

const state = {
  allFiles: [],
  currentFile: null,   // { name, json_path, audio_path, audio_tracks }
  alignment: null,
  selectedLine: -1,
  selectedWord: -1,
  undoStack: [],
  redoStack: [],
  dirty: false,
};

let ws = null;        // primary WaveSurfer (vocals or original fallback)
let wsInst = null;    // secondary WaveSurfer (instrumental)
let vocalsReady = false, instReady = false;
let trackMuted = { vocals: false, instrumental: false };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const dom = {};

// ---------------------------------------------------------------------------
// WaveSurfer (dual-track)
// ---------------------------------------------------------------------------
function initWaveSurfer() {
  if (!dom.waveformVocals) return;

  ws = WaveSurfer.create({
    container: dom.waveformVocals,
    waveColor: "#4a90d9", progressColor: "#e94560",
    cursorColor: "#fff", height: 72,
    barWidth: 2, barGap: 1, barRadius: 2,
    normalize: true,
  });

  if (dom.waveformInst) {
    wsInst = WaveSurfer.create({
      container: dom.waveformInst,
      waveColor: "#50c878", progressColor: "#ff9800",
      cursorColor: "#fff", height: 72,
      barWidth: 2, barGap: 1, barRadius: 2,
      normalize: true,
    });
  }

  ws.on("ready", () => {
    vocalsReady = true;
    updateTimeDisplay();
    status("人声轨已加载");
  });

  ws.on("audioprocess", () => {
    syncInstToVocals();
    updateTimeDisplay();
    if (window.onPlaybackTick) window.onPlaybackTick();
  });

  ws.on("timeupdate", () => {
    updateTimeDisplay();
    if (window.onPlaybackTick) window.onPlaybackTick();
  });

  ws.on("seeking", () => {
    syncInstToVocals();
    updateTimeDisplay();
  });

  ws.on("finish", () => {
    if (wsInst && instReady) wsInst.pause();
    if (dom.btnPlayPause) dom.btnPlayPause.textContent = "▶ 播放";
  });

  if (wsInst) {
    wsInst.on("ready", () => {
      instReady = true;
      status("伴奏轨已加载");
    });
  }
}

function syncInstToVocals() {
  if (!wsInst || !instReady || !vocalsReady) return;
  const t = ws.getCurrentTime();
  const instT = wsInst.getCurrentTime();
  if (Math.abs(t - instT) > 0.15) wsInst.setTime(t);
}

function toggleMuteTrack(track) {
  trackMuted[track] = !trackMuted[track];
  const instance = track === "vocals" ? ws : wsInst;
  const btn = track === "vocals" ? dom.btnMuteVocals : dom.btnMuteInst;
  const row = track === "vocals" ? dom.trackVocals : dom.trackInst;
  if (instance) instance.setVolume(trackMuted[track] ? 0 : 1);
  if (btn) {
    btn.classList.toggle("active", !trackMuted[track]);
    btn.classList.toggle("muted", trackMuted[track]);
  }
  if (row) {
    row.classList.toggle("muted", trackMuted[track]);
  }
  status(trackMuted[track] ? `${track} 已静音` : `${track} 已取消静音`);
}

function updateTimeDisplay() {
  if (!ws || !dom.timeDisplay) return;
  const cur = ws.getCurrentTime(), dur = ws.getDuration() || 0;
  dom.timeDisplay.textContent = `${fmtTime(cur)} / ${fmtTime(dur)}`;
}

function togglePlay() {
  if (!ws) return;
  if (ws.isPlaying()) {
    ws.pause();
    if (wsInst && instReady) wsInst.pause();
    if (dom.btnPlayPause) dom.btnPlayPause.textContent = "▶ 播放";
  } else {
    if (wsInst && instReady) { wsInst.setTime(ws.getCurrentTime()); wsInst.play(); }
    ws.play();
    if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
  }
}

function playSelectedLine() {
  if (state.selectedLine < 0 || !ws) return;
  const line = state.alignment?.lines?.[state.selectedLine];
  if (!line) return;
  ws.setTime(line.start);
  ws.play();
  if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
  if (wsInst && instReady) { wsInst.setTime(line.start); wsInst.play(); }
  const stopAt = line.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause();
      if (wsInst && instReady) wsInst.pause();
      if (dom.btnPlayPause) dom.btnPlayPause.textContent = "▶ 播放";
    } else if (ws.isPlaying()) {
      requestAnimationFrame(check);
    }
  };
  requestAnimationFrame(check);
}

// ---------------------------------------------------------------------------
// File Loading & Song Switching
// ---------------------------------------------------------------------------
async function loadFileList(preferredTitle) {
  try {
    const r = await fetch("/api/files");
    state.allFiles = await r.json();
    if (dom.songSelect) {
      dom.songSelect.innerHTML = state.allFiles.length === 0
        ? `<option value="">未找到 alignment.json</option>`
        : `<option value="">— 请选择 —</option>` +
          state.allFiles.map((f, i) =>
            `<option value="${i}">${f.name}${f.audio_path ? " 🎵" : ""}</option>`
          ).join("");
    }

    const targetSong = preferredTitle || new URLSearchParams(window.location.search).get("song");
    if (targetSong) {
      const idx = state.allFiles.findIndex(f => f.name === targetSong || f.name.includes(targetSong));
      if (idx >= 0) {
        loadSong(idx);
        return;
      }
    }
    if (state.allFiles.length === 1) loadSong(0);
  } catch (e) {
    if (dom.songSelect) dom.songSelect.innerHTML = `<option value="">加载失败</option>`;
    status("文件列表加载失败: " + e, true);
  }
}

async function loadSong(idx) {
  const file = state.allFiles[idx];
  if (!file) return;

  state.currentFile = file;
  state.selectedLine = -1;
  state.selectedWord = -1;
  state.undoStack = [];
  state.redoStack = [];
  state.dirty = false;
  vocalsReady = false;
  instReady = false;
  trackMuted = { vocals: false, instrumental: false };
  if (dom.songSelect) dom.songSelect.value = idx;
  status(`加载 ${file.name}…`);

  try {
    const r = await fetch("/api/alignment?path=" + encodeURIComponent(file.json_path));
    if (!r.ok) throw new Error(await r.text());
    state.alignment = await r.json();
  } catch (e) {
    status("对齐数据加载失败: " + e, true);
    state.alignment = null;
    return;
  }

  // Load audio tracks
  const tracks = file.audio_tracks || {};
  const vocalsUrl = tracks.vocals ? "/api/audio?path=" + encodeURIComponent(tracks.vocals) : null;
  const instUrl = tracks.instrumental ? "/api/audio?path=" + encodeURIComponent(tracks.instrumental) : null;
  const origUrl = file.audio_path ? "/api/audio?path=" + encodeURIComponent(file.audio_path) : null;

  const primaryUrl = vocalsUrl || origUrl;
  if (primaryUrl && ws) {
    try { await ws.load(primaryUrl); } catch (e) { status("人声轨加载失败: " + e, true); }
  }
  if (instUrl && wsInst) {
    try { await wsInst.load(instUrl); } catch (e) { status("伴奏轨加载失败: " + e, true); }
    if (dom.trackInst) dom.trackInst.classList.remove("hidden");
  } else {
    if (dom.trackInst) dom.trackInst.classList.add("hidden");
  }

  // Track buttons
  if (dom.btnMuteVocals) {
    dom.btnMuteVocals.textContent = vocalsUrl ? "🎤 人声" : "🎵 原始";
    dom.btnMuteVocals.classList.add("active");
    dom.btnMuteVocals.classList.remove("muted");
  }
  if (dom.btnMuteInst) {
    dom.btnMuteInst.classList.add("active");
    dom.btnMuteInst.classList.remove("muted");
  }
  if (dom.trackVocals) dom.trackVocals.classList.remove("muted");
  if (dom.trackInst) dom.trackInst.classList.remove("muted");

  // Hook for page-specific rendering
  if (window.onSongLoaded) window.onSongLoaded();

  const trackInfo = [vocalsUrl ? "人声" : null, instUrl ? "伴奏" : null, (!vocalsUrl && origUrl) ? "原始" : null].filter(Boolean).join("+");
  status(`已加载: ${file.name} (${state.alignment.lines.length} 行, 音轨: ${trackInfo || "无"})`);
  document.title = `${file.name} — M2V`;
}

// ---------------------------------------------------------------------------
// Suno One-Click Import
// ---------------------------------------------------------------------------
async function handleSunoImport() {
  const input = dom.sunoUrlInput || document.getElementById("suno-url-input");
  const btn = dom.btnStartSunoImport || document.getElementById("btn-start-suno-import");
  const prog = dom.sunoProgress || document.getElementById("suno-import-progress");
  const progText = dom.sunoProgressText || document.getElementById("suno-progress-text");
  const url = input ? input.value.trim() : "";

  if (!url) {
    alert("请输入有效的 Suno 歌曲链接（例如 https://suno.com/s/LScMFeOajPYsjwCB）");
    return;
  }
  if (btn) btn.disabled = true;
  if (prog) prog.style.display = "block";
  if (progText) progText.textContent = "正在拉取 Suno 歌词、分离人声伴奏并对齐时间轴，请稍候（约需 20~40 秒）...";

  try {
    const res = await fetch("/api/suno/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "处理失败");

    if (dom.sunoModal) dom.sunoModal.style.display = "none";
    if (input) input.value = "";
    status(`🎉 导入成功: ${data.title}`);
    await loadFileList(data.title);
  } catch (err) {
    alert("Suno 导入失败: " + err.message);
  } finally {
    if (btn) btn.disabled = false;
    if (prog) prog.style.display = "none";
  }
}
window.handleSunoImport = handleSunoImport;

// ---------------------------------------------------------------------------
// Save Alignment (Pydantic v2 Backend)
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
      let msg = "校验错误: ";
      if (j.detail) {
        if (Array.isArray(j.detail)) {
          msg += j.detail.map(d => `${d.loc ? d.loc.join('.') : ''}: ${d.msg}`).join("; ");
        } else if (j.detail.errors) {
          msg += j.detail.errors.join("; ");
        } else {
          msg += JSON.stringify(j.detail);
        }
      } else {
        msg += JSON.stringify(j);
      }
      status(msg, true);
    } else {
      state.dirty = false;
      document.title = (state.currentFile?.name || "M2V") + " — 编辑器";
      status("✅ 已保存");
    }
  } catch (e) {
    status("保存失败: " + e, true);
  }
}

// ---------------------------------------------------------------------------
// Generate Output (ASS / Video)
// ---------------------------------------------------------------------------
async function generateOutput() {
  if (!state.currentFile) return;

  const modeEl = document.querySelector('input[name="gen-mode"]:checked');
  const tagEl = document.querySelector('input[name="gen-tag-type"]:checked');
  const renderEl = document.querySelector('input[name="gen-render-mode"]:checked');

  const mode = modeEl ? modeEl.value : "ass";
  const tagType = tagEl ? tagEl.value : "kf";
  const renderMode = renderEl ? renderEl.value : "apple";

  status(mode === "video" ? "生成视频中，请稍候…" : "生成 ASS 中…");
  try {
    const r = await fetch("/api/regen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        audio_path: state.currentFile.audio_path || "",
        mode: mode,
        tag_type: tagType,
        render_mode: renderMode,
      }),
    });
    const j = await r.json();
    if (!r.ok) {
      status("生成失败: " + (j.detail || JSON.stringify(j)), true);
    } else {
      status(mode === "video" ? "✅ 视频已生成: " + j.video_path : "✅ ASS 已生成: " + j.ass_path);
    }
  } catch (e) {
    status("生成失败: " + e, true);
  }
}

// ---------------------------------------------------------------------------
// Undo / Redo & Dirty Flag
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
  if (window.onAlignmentChanged) window.onAlignmentChanged();
  markDirty();
  status("已撤销");
}

function redo() {
  if (!state.redoStack.length) { status("无可重做操作"); return; }
  state.undoStack.push(JSON.stringify(state.alignment));
  state.alignment = JSON.parse(state.redoStack.pop());
  if (window.onAlignmentChanged) window.onAlignmentChanged();
  markDirty();
  status("已重做");
}

function markDirty() {
  state.dirty = true;
  document.title = "● " + (state.currentFile?.name || "M2V") + " — 编辑器";
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function status(msg, isError = false) {
  if (!dom.statusMsg) return;
  dom.statusMsg.textContent = msg;
  dom.statusMsg.style.color = isError ? "var(--accent)" : "var(--text-dim)";
  if (!isError) setTimeout(() => { if (dom.statusMsg) dom.statusMsg.textContent = ""; }, 4000);
}

function escHtml(s) {
  if (typeof s !== "string") return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function isPunct(ch) {
  return /^[\s，。、！？；：""''（）《》…—·\-,.!?;:'"()\[\]{}]$/.test(ch);
}

function fmtTime(s) {
  const m = Math.floor(s / 60), sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

function fmtTimeShort(s) {
  const m = Math.floor(s / 60), sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

function parseTimeInput(str) {
  if (!str) return null;
  str = str.trim();
  const match = str.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const mins = match[1] ? Number(match[1]) : 0;
  const total = mins * 60 + Number(match[2]);
  return total >= 0 ? Math.round(total * 1000) / 1000 : null;
}

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
});
