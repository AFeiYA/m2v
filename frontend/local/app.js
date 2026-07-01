// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
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

let ws = null;  // primary WaveSurfer (vocals or original fallback)
let wsInst = null; // secondary WaveSurfer (instrumental)
let vocalsReady = false, instReady = false;
let trackMuted = { vocals: false, instrumental: false };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  dom.songSelect          = $("#song-select");
  dom.btnSave             = $("#btn-save");
  dom.btnUndo             = $("#btn-undo");
  dom.btnRedo             = $("#btn-redo");
  dom.btnGenerate         = $("#btn-generate");
  dom.generateModal       = $("#generate-modal");
  dom.btnCloseGenerate    = $("#btn-close-generate");
  dom.btnConfirmGenerate  = $("#btn-confirm-generate");
  dom.statusMsg           = $("#status-msg");
  dom.waveformVocals      = $("#waveform-vocals");
  dom.waveformInst        = $("#waveform-instrumental");
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
  dom.btnMuteVocals       = $("#btn-mute-vocals");
  dom.btnMuteInst         = $("#btn-mute-instrumental");
  dom.trackVocals         = $("#track-vocals");
  dom.trackInst           = $("#track-instrumental");

  // Storyboard
  dom.btnBrowseAssets     = $("#btn-browse-assets");
  dom.assetModal          = $("#asset-modal");
  dom.assetGrid           = $("#asset-grid");
  dom.assetPreview        = $("#asset-preview");
  dom.currentAssetName    = $("#current-asset-name");
  dom.assetStart          = $("#asset-start");
  dom.assetEnd            = $("#asset-end");
  dom.btnAssetSync        = $("#btn-asset-sync");
  dom.btnAssetAdd         = $("#btn-asset-add");
  dom.storyboardList      = $("#storyboard-list");
  dom.assetModalClose     = $("#btn-close-asset");
  dom.assetFileInput      = $("#asset-file-input");
  dom.uploadStatus        = $("#upload-status");
  dom.btnSetBg            = $("#btn-set-bg");
  dom.bgName              = $("#bg-name");
  dom.sunoUrl             = $("#suno-url");
  dom.btnSunoImport       = $("#btn-suno-import");
  dom.sunoQuickMode       = $("#suno-quick-mode");

  initWaveSurfer();
  bindEvents();
  loadFileList();
});

// ---------------------------------------------------------------------------
// WaveSurfer (dual-track)
// ---------------------------------------------------------------------------
function initWaveSurfer() {
  ws = WaveSurfer.create({
    container: dom.waveformVocals,
    waveColor: "#4a90d9", progressColor: "#e94560",
    cursorColor: "#fff", height: 72,
    barWidth: 2, barGap: 1, barRadius: 2,
    normalize: true,
  });
  wsInst = WaveSurfer.create({
    container: dom.waveformInst,
    waveColor: "#50c878", progressColor: "#ff9800",
    cursorColor: "#fff", height: 72,
    barWidth: 2, barGap: 1, barRadius: 2,
    normalize: true,
  });

  ws.on("ready", () => { vocalsReady = true; updateTimeDisplay(); status("人声轨已加载"); });
  ws.on("audioprocess", () => { syncInstToVocals(); updateTimeDisplay(); highlightPlayingLine(); });
  ws.on("timeupdate", () => { updateTimeDisplay(); highlightPlayingLine(); });
  ws.on("seeking", () => { syncInstToVocals(); updateTimeDisplay(); });
  ws.on("finish", () => {
    if (wsInst && instReady) wsInst.pause();
    dom.btnPlayPause.textContent = "▶ 播放";
  });

  wsInst.on("ready", () => { instReady = true; status("伴奏轨已加载"); });
  // instrumental follows vocals — no independent events needed
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
  btn.classList.toggle("active", !trackMuted[track]);
  btn.classList.toggle("muted", trackMuted[track]);
  row.classList.toggle("muted", trackMuted[track]);
  status(trackMuted[track] ? `${track} 已静音` : `${track} 已取消静音`);
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
  dom.btnGenerate.addEventListener("click", () => dom.generateModal.style.display = "flex");
  dom.btnCloseGenerate.addEventListener("click", () => dom.generateModal.style.display = "none");
  dom.btnConfirmGenerate.addEventListener("click", () => {
    dom.generateModal.style.display = "none";
    generateOutput();
  });
  dom.btnPlayPause.addEventListener("click", togglePlay);
  dom.btnPlayLine.addEventListener("click", playSelectedLine);
  dom.zoomSlider.addEventListener("input", () => {
    const z = Number(dom.zoomSlider.value);
    if (ws) ws.zoom(z);
    if (wsInst && instReady) wsInst.zoom(z);
  });
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
  dom.btnMuteVocals.addEventListener("click", () => toggleMuteTrack("vocals"));
  dom.btnMuteInst.addEventListener("click", () => toggleMuteTrack("instrumental"));

  const selectSource = $("#select-audio-source");
  if (selectSource) {
    selectSource.addEventListener("change", async (e) => {
      const val = e.target.value;
      if (val === "separate") {
        if (!state.currentFile || !state.currentFile.audio_path) {
          alert("无可用音频文件进行分离");
          selectSource.value = "original";
          return;
        }
        if (confirm("确定要在后台启动人声分离吗？\n（在 Apple Silicon GPU 下耗时约 10-15 秒，分离后将自动刷新音轨）")) {
          try {
            status("⏳ 提交人声分离任务中...", false);
            const r = await fetch("/api/separate", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ audio_path: state.currentFile.audio_path })
            });
            if (!r.ok) throw new Error(await r.text());
            const data = await r.json();
            pollSeparateTask(data.task_id);
          } catch(err) {
            alert("人声分离启动失败: " + err.message);
            selectSource.value = "original";
          }
        } else {
          selectSource.value = "original";
        }
      } else if (val === "vocals") {
        if (state.vocalsUrl) {
          const currentTime = ws.getCurrentTime();
          const isPlaying = ws.isPlaying();
          await ws.load(state.vocalsUrl);
          ws.setTime(currentTime);
          if (isPlaying) ws.play();
          dom.btnMuteVocals.textContent = "🎤 人声";
          status("已切换至人声轨");
        }
      } else if (val === "original") {
        if (state.origUrl) {
          const currentTime = ws.getCurrentTime();
          const isPlaying = ws.isPlaying();
          await ws.load(state.origUrl);
          ws.setTime(currentTime);
          if (isPlaying) ws.play();
          dom.btnMuteVocals.textContent = "🎵 原始";
          status("已切换至原始音轨");
        }
      }
    });
  }

  // Storyboard events
  dom.btnBrowseAssets.addEventListener("click", openAssetModal);
  dom.assetModalClose.addEventListener("click", () => dom.assetModal.style.display = "none");
  dom.btnAssetSync.addEventListener("click", syncAssetToCurrentLine);
  dom.btnAssetAdd.addEventListener("click", addOrUpdateAssetEvent);
  dom.assetFileInput.addEventListener("change", handleAssetUpload);
  dom.btnSetBg.addEventListener("click", openBgPicker);
  dom.btnSunoImport.addEventListener("click", importSuno);
  // 点击模态框背景关闭
  dom.assetModal.addEventListener("click", (e) => { if (e.target === dom.assetModal) dom.assetModal.style.display = "none"; });
  dom.generateModal.addEventListener("click", (e) => { if (e.target === dom.generateModal) dom.generateModal.style.display = "none"; });

  // Autoplay game modal events
  const btnAutoplay = $("#btn-autoplay");
  const gameModal = $("#game-modal");
  const btnCloseGame = $("#btn-close-game");
  const gameAutoplayToggle = $("#game-autoplay-toggle");

  if (btnAutoplay) {
    btnAutoplay.addEventListener("click", () => {
      gameModal.style.display = "flex";
      startGameMode();
    });
  }
  if (btnCloseGame) {
    btnCloseGame.addEventListener("click", () => {
      gameModal.style.display = "none";
      stopGameMode();
    });
  }
  if (gameAutoplayToggle) {
    gameAutoplayToggle.addEventListener("change", (e) => {
      if (window.gameInstance) {
        window.gameInstance.autoplay = e.target.checked;
      }
    });
  }

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
  vocalsReady = false; instReady = false;
  trackMuted = { vocals: false, instrumental: false };
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

  // Load audio tracks
  const tracks = file.audio_tracks || {};
  const vocalsUrl = tracks.vocals ? "/api/audio?path=" + encodeURIComponent(tracks.vocals) : null;
  const instUrl = tracks.instrumental ? "/api/audio?path=" + encodeURIComponent(tracks.instrumental) : null;
  const origUrl = file.audio_path ? "/api/audio?path=" + encodeURIComponent(file.audio_path) : null;

  // Primary track: vocals > original
  const primaryUrl = vocalsUrl || origUrl;
  if (primaryUrl) {
    try { await ws.load(primaryUrl); } catch(e) { status("人声轨加载失败: " + e, true); }
  }
  // Secondary track: instrumental (only if we have separate tracks)
  if (instUrl) {
    try { await wsInst.load(instUrl); } catch(e) { status("伴奏轨加载失败: " + e, true); }
    dom.trackInst.classList.remove("hidden");
  } else {
    dom.trackInst.classList.add("hidden");
  }

  // Update track labels
  state.vocalsUrl = vocalsUrl;
  state.origUrl = origUrl;
  updateAudioSourceDropdown(vocalsUrl, instUrl, origUrl);

  dom.btnMuteVocals.classList.add("active"); dom.btnMuteVocals.classList.remove("muted");
  dom.btnMuteInst.classList.add("active"); dom.btnMuteInst.classList.remove("muted");
  dom.trackVocals.classList.remove("muted"); dom.trackInst.classList.remove("muted");

  renderLyrics();
  clearWordPanel();
  renderStoryboard();
  updateBgDisplay();
  const trackInfo = [vocalsUrl ? "人声" : null, instUrl ? "伴奏" : null, (!vocalsUrl && origUrl) ? "原始" : null].filter(Boolean).join("+");
  status(`已加载: ${file.name} (${state.alignment.lines.length} 行, 音轨: ${trackInfo || "无"})`);
  document.title = `${file.name} — M2V 编辑器`;
}

async function importSuno() {
  const url = dom.sunoUrl.value.trim();
  if (!url) {
    alert("请输入 Suno 歌曲的分享链接");
    return;
  }

  const skipSeparation = dom.sunoQuickMode ? dom.sunoQuickMode.checked : true;

  dom.btnSunoImport.disabled = true;
  dom.btnSunoImport.textContent = "⏳ 提交中...";
  dom.statusMsg.textContent = "⏳ 正在提交任务...";
  dom.statusMsg.style.color = "var(--warning)";

  try {
    const response = await fetch("/api/suno/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url, skip_separation: skipSeparation })
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "任务提交失败");
    }

    const taskId = data.task_id;
    dom.sunoUrl.value = "";
    
    // 开始轮询任务状态
    pollSunoTask(taskId);
  } catch (error) {
    alert("导入失败: " + error.message);
    status("❌ 导入失败: " + error.message, true);
    dom.btnSunoImport.disabled = false;
    dom.btnSunoImport.textContent = "🎵 导入";
  }
}

function pollSunoTask(taskId) {
  const interval = setInterval(async () => {
    try {
      const response = await fetch(`/api/suno/task/${taskId}`);
      if (!response.ok) {
        throw new Error("查询状态失败");
      }
      const task = await response.json();
      
      if (task.status === "processing") {
        dom.statusMsg.textContent = `⏳ ${task.title || "处理中..."}`;
        dom.statusMsg.style.color = "var(--warning)";
        dom.btnSunoImport.textContent = "⏳ 处理中...";
      } else if (task.status === "completed") {
        clearInterval(interval);
        status("✅ Suno 歌曲导入并对齐完成！");
        
        dom.btnSunoImport.disabled = false;
        dom.btnSunoImport.textContent = "🎵 导入";
        
        await loadFileList();
        
        const newSongIndex = state.allFiles.findIndex(f => f.name === task.file.name);
        if (newSongIndex !== -1) {
          loadSong(newSongIndex);
        }
      } else if (task.status === "failed") {
        clearInterval(interval);
        alert("导入失败: " + task.error);
        status("❌ 导入失败: " + task.error, true);
        dom.btnSunoImport.disabled = false;
        dom.btnSunoImport.textContent = "🎵 导入";
      }
    } catch (error) {
      clearInterval(interval);
      alert("导入失败: " + error.message);
      status("❌ 导入失败: " + error.message, true);
      dom.btnSunoImport.disabled = false;
      dom.btnSunoImport.textContent = "🎵 导入";
    }
  }, 2000);
}

function updateAudioSourceDropdown(vocalsUrl, instUrl, origUrl) {
  const select = document.getElementById("select-audio-source");
  if (!select) return;

  select.innerHTML = "";

  if (vocalsUrl) {
    const optVocals = document.createElement("option");
    optVocals.value = "vocals";
    optVocals.textContent = "🎤 人声";
    select.appendChild(optVocals);
  }

  if (origUrl) {
    const optOrig = document.createElement("option");
    optOrig.value = "original";
    optOrig.textContent = "🎵 原始";
    select.appendChild(optOrig);
  }

  if (!vocalsUrl && origUrl) {
    const optSeparate = document.createElement("option");
    optSeparate.value = "separate";
    optSeparate.textContent = "⚡分离人声";
    select.appendChild(optSeparate);
  }

  if (vocalsUrl) {
    select.value = "vocals";
    dom.btnMuteVocals.textContent = "🎤 人声";
  } else {
    select.value = "original";
    dom.btnMuteVocals.textContent = "🎵 原始";
  }
}

function pollSeparateTask(taskId) {
  const interval = setInterval(async () => {
    try {
      const response = await fetch(`/api/suno/task/${taskId}`);
      if (!response.ok) {
        throw new Error("查询状态失败");
      }
      const task = await response.json();
      
      const select = document.getElementById("select-audio-source");
      if (task.status === "processing") {
        status(`⏳ ${task.title || "正在分离人声..."}`, false);
        if (select) select.disabled = true;
      } else if (task.status === "completed") {
        clearInterval(interval);
        status("✅ 人声分离完成！正在重新加载音轨...");
        if (select) select.disabled = false;
        
        const oldIndex = state.currentIndex;
        await loadFileList();
        if (oldIndex !== -1 && oldIndex < state.allFiles.length) {
          await loadSong(oldIndex);
        }
      } else if (task.status === "failed") {
        clearInterval(interval);
        alert("人声分离失败: " + task.error);
        status("❌ 人声分离失败: " + task.error, true);
        if (select) {
          select.disabled = false;
          select.value = "original";
        }
      }
    } catch (error) {
      clearInterval(interval);
      alert("人声分离失败: " + error.message);
      status("❌ 人声分离失败: " + error.message, true);
      const select = document.getElementById("select-audio-source");
      if (select) {
        select.disabled = false;
        select.value = "original";
      }
    }
  }, 2000);
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
      if (ws) {
        ws.setTime(line.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停";
        if (wsInst && instReady) { wsInst.setTime(line.start); wsInst.play(); }
      }
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
        if (wsInst && instReady) { wsInst.setTime(w.start); wsInst.play(); }
        const stopAt = w.end;
        const check = () => {
          if (ws.getCurrentTime() >= stopAt) {
            ws.pause(); if (wsInst && instReady) wsInst.pause();
            dom.btnPlayPause.textContent = "▶ 播放";
          } else if (ws.isPlaying()) requestAnimationFrame(check);
        };
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
  if (ws.isPlaying()) {
    ws.pause();
    if (wsInst && instReady) wsInst.pause();
    dom.btnPlayPause.textContent = "▶ 播放";
  } else {
    if (wsInst && instReady) { wsInst.setTime(ws.getCurrentTime()); wsInst.play(); }
    ws.play();
    dom.btnPlayPause.textContent = "⏸ 暂停";
  }
}

function playSelectedLine() {
  if (state.selectedLine < 0 || !ws) return;
  const line = state.alignment.lines[state.selectedLine];
  if (!line) return;
  ws.setTime(line.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停";
  if (wsInst && instReady) { wsInst.setTime(line.start); wsInst.play(); }
  const stopAt = line.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause(); if (wsInst && instReady) wsInst.pause();
      dom.btnPlayPause.textContent = "▶ 播放";
    } else if (ws.isPlaying()) requestAnimationFrame(check);
  };
  requestAnimationFrame(check);
}

function playSelectedWord() {
  if (state.selectedLine < 0 || state.selectedWord < 0 || !ws) return;
  const w = state.alignment.lines[state.selectedLine]?.words?.[state.selectedWord];
  if (!w) return;
  ws.setTime(w.start); ws.play(); dom.btnPlayPause.textContent = "⏸ 暂停";
  if (wsInst && instReady) { wsInst.setTime(w.start); wsInst.play(); }
  const stopAt = w.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause(); if (wsInst && instReady) wsInst.pause();
      dom.btnPlayPause.textContent = "▶ 播放";
    } else if (ws.isPlaying()) requestAnimationFrame(check);
  };
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

async function generateOutput() {
  if (!state.currentFile) return;

  const mode = document.querySelector('input[name="gen-mode"]:checked').value;
  const tagType = document.querySelector('input[name="gen-tag-type"]:checked').value;
  const renderMode = document.querySelector('input[name="gen-render-mode"]:checked').value;

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
        render_mode: renderMode
      }),
    });
    const j = await r.json();
    if (!r.ok) status("生成失败: " + (j.detail || JSON.stringify(j)), true);
    else status(mode === "video" ? "✅ 视频已生成: " + j.video_path : "✅ ASS 已生成: " + j.ass_path);
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


// ---------------------------------------------------------------------------
// Storyboard / Asset Logic
// ---------------------------------------------------------------------------

let selectedAsset = null;

async function openAssetModal() {
  dom.assetModal.style.display = "flex";
  dom.uploadStatus.textContent = "";
  loadAssetGrid();
}

async function loadAssetGrid() {
  dom.assetGrid.innerHTML = "加载中…";
  try {
    const r = await fetch("/api/assets");
    const assets = await r.json();
    if (assets.length === 0) {
      dom.assetGrid.innerHTML = '<span style="color:var(--text-dim);font-size:13px;">暂无素材，请点击"上传图片"添加</span>';
      return;
    }
    dom.assetGrid.innerHTML = assets.map(a => `
      <div class="asset-card" data-path="${escHtml(a.path)}" data-url="${escHtml(a.url)}" data-name="${escHtml(a.name)}">
        ${isImage(a.name) ? `<img src="${a.url}" alt="">` : `<div style="height:80px; display:flex; align-items:center; justify-content:center; background:#000;">📹</div>`}
        <span>${escHtml(a.name)}</span>
      </div>
    `).join("");
    
    $$(".asset-card").forEach(card => {
      card.addEventListener("click", () => {
        selectAsset({
          name: card.dataset.name,
          path: card.dataset.path,
          url: card.dataset.url
        });
        dom.assetModal.style.display = "none";
      });
    });
  } catch(e) {
    dom.assetGrid.innerHTML = "加载素材失败: " + e;
  }
}

async function handleAssetUpload(e) {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  dom.uploadStatus.textContent = `上传中 (0/${files.length})…`;
  let ok = 0;
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/upload_asset", { method: "POST", body: fd });
      if (r.ok) ok++;
      else { const j = await r.json(); dom.uploadStatus.textContent = "上传失败: " + (j.detail || r.status); }
    } catch(err) {
      dom.uploadStatus.textContent = "上传失败: " + err;
    }
  }
  e.target.value = "";
  dom.uploadStatus.textContent = `✅ 已上传 ${ok}/${files.length}`;
  loadAssetGrid();
}

function selectAsset(asset) {
  selectedAsset = asset;
  dom.currentAssetName.textContent = asset.name;
  if (isImage(asset.name)) {
    dom.assetPreview.innerHTML = `<img src="${asset.url}" alt="">`;
  } else {
    dom.assetPreview.innerHTML = `<span>📹 视频素材</span>`;
  }
}

function syncAssetToCurrentLine() {
  if (state.selectedLine < 0) { status("请先选中一行歌词", true); return; }
  const line = state.alignment.lines[state.selectedLine];
  dom.assetStart.value = fmtTimeShort(line.start);
  dom.assetEnd.value = fmtTimeShort(line.end);
}

function addOrUpdateAssetEvent() {
  if (!selectedAsset) { status("请先选择素材", true); return; }
  const start = parseTimeInput(dom.assetStart.value);
  const end = parseTimeInput(dom.assetEnd.value);
  
  if (start === null || end === null || end <= start) {
    status("时间输入无效", true); return;
  }
  
  pushUndo();
  if (!state.alignment.storyboard) state.alignment.storyboard = [];
  
  // 简单逻辑：如果已经存在相同路径和时间的，就不重复加？
  // 或者直接加。这里我们直接添加。
  state.alignment.storyboard.push({
    type: isImage(selectedAsset.name) ? "image" : "video",
    path: selectedAsset.path,
    start: start,
    end: end
  });
  
  // 按时间排序
  state.alignment.storyboard.sort((a, b) => a.start - b.start);
  
  renderStoryboard();
  markDirty();
  status("✅ 已添加分镜事件");
}

function renderStoryboard() {
  const events = state.alignment?.storyboard || [];
  dom.storyboardList.innerHTML = events.map((e, i) => `
    <tr>
      <td title="${escHtml(e.path)}">${escHtml(e.path.split(/[\\/]/).pop())}</td>
      <td>${fmtTimeShort(e.start)}</td>
      <td>${fmtTimeShort(e.end)}</td>
      <td><button class="btn-delete-asset" data-idx="${i}">删除</button></td>
    </tr>
  `).join("");
  
  dom.storyboardList.querySelectorAll(".btn-delete-asset").forEach(btn => {
    btn.addEventListener("click", () => {
      pushUndo();
      state.alignment.storyboard.splice(Number(btn.dataset.idx), 1);
      renderStoryboard();
      markDirty();
    });
  });
}

function isImage(filename) {
  return /\.(jpg|jpeg|png|webp)$/i.test(filename);
}

// ---------------------------------------------------------------------------
// Background Picker
// ---------------------------------------------------------------------------

let bgPickerMode = false;

function openBgPicker() {
  bgPickerMode = true;
  dom.assetModal.style.display = "flex";
  dom.uploadStatus.textContent = "";
  loadAssetGridForBg();
}

async function loadAssetGridForBg() {
  dom.assetGrid.innerHTML = "加载中…";
  try {
    const r = await fetch("/api/assets");
    const assets = await r.json();
    // 背景只显示图片
    const images = assets.filter(a => isImage(a.name));
    if (images.length === 0) {
      dom.assetGrid.innerHTML = '<span style="color:var(--text-dim);font-size:13px;">暂无图片素材，请点击"上传图片"添加</span>';
      return;
    }

    // 添加"清除背景"选项
    dom.assetGrid.innerHTML = `
      <div class="asset-card" data-path="" data-name="无背景">
        <div style="height:80px; display:flex; align-items:center; justify-content:center; background:#111; color:var(--text-dim); font-size:24px;">✖</div>
        <span>清除背景</span>
      </div>
    ` + images.map(a => `
      <div class="asset-card" data-path="${escHtml(a.path)}" data-url="${escHtml(a.url)}" data-name="${escHtml(a.name)}">
        <img src="${a.url}" alt="">
        <span>${escHtml(a.name)}</span>
      </div>
    `).join("");

    $$(".asset-card").forEach(card => {
      card.addEventListener("click", () => {
        if (bgPickerMode) {
          setBackground(card.dataset.path, card.dataset.name);
          dom.assetModal.style.display = "none";
          bgPickerMode = false;
        } else {
          selectAsset({
            name: card.dataset.name,
            path: card.dataset.path,
            url: card.dataset.url
          });
          dom.assetModal.style.display = "none";
        }
      });
    });
  } catch(e) {
    dom.assetGrid.innerHTML = "加载素材失败: " + e;
  }
}

function setBackground(path, name) {
  if (!state.alignment) return;
  pushUndo();
  state.alignment.background = path || null;
  updateBgDisplay();
  markDirty();
  status(path ? `✅ 背景已设置: ${name}` : "背景已清除");
}

function updateBgDisplay() {
  const bg = state.alignment?.background;
  if (bg) {
    const name = bg.split(/[\\/]/).pop();
    dom.bgName.textContent = name;
    dom.bgName.title = bg;
  } else {
    dom.bgName.textContent = "未设置";
    dom.bgName.title = "";
  }
}

// ---------------------------------------------------------------------------
// Rhythm Game Autoplay Preview
// ---------------------------------------------------------------------------
let gameAudioCtx = null;
window.gameInstance = null;

function handleGameKeyDown(e) {
  if (window.gameInstance) window.gameInstance.handleKeyDown(e);
}
function handleGameKeyUp(e) {
  if (window.gameInstance) window.gameInstance.handleKeyUp(e);
}

function startGameMode() {
  if (!state.currentFile || !state.alignment) {
    alert("请先加载歌曲！");
    $("#game-modal").style.display = "none";
    return;
  }
  
  if (ws) ws.pause();
  
  const notes = [];
  let noteId = 1;
  state.alignment.lines.forEach((line) => {
    line.words.forEach((word, wordIdx) => {
      const lane = wordIdx % 4;
      const type = (word.end - word.start > 0.5) ? 'hold' : 'tap';
      notes.push({
        id: noteId++,
        char: word.word,
        type: type,
        time: word.start,
        end_time: word.end,
        lane: lane,
        hit: false,
        released: false
      });
    });
  });
  
  const chartData = {
    song_name: state.currentFile.name,
    notes: notes
  };
  
  let audioUrl = state.origUrl;
  const selectSource = $("#select-audio-source");
  if (selectSource && selectSource.value === "vocals" && state.vocalsUrl) {
    audioUrl = state.vocalsUrl;
  }
  
  gameAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
  $("#game-status-label").innerText = "加载音频中...";
  $("#game-status-label").style.color = "#ff9800";
  $("#game-score-label").innerText = "0";
  $("#game-combo-label").innerText = "0";
  
  fetch(audioUrl)
    .then(res => {
      if (!res.ok) throw new Error("音频下载失败");
      return res.arrayBuffer();
    })
    .then(buffer => gameAudioCtx.decodeAudioData(buffer))
    .then(audioBuffer => {
      $("#game-status-label").innerText = "正在播放";
      $("#game-status-label").style.color = "#00f6ff";
      
      const canvas = document.getElementById("game-canvas");
      window.gameInstance = new RhythmGame(canvas, chartData, audioBuffer, gameAudioCtx);
      window.gameInstance.autoplay = document.getElementById("game-autoplay-toggle").checked;
      window.gameInstance.start();
      
      window.addEventListener("keydown", handleGameKeyDown);
      window.addEventListener("keyup", handleGameKeyUp);
    })
    .catch(err => {
      alert("音谱初始化失败: " + err.message);
      stopGameMode();
      $("#game-modal").style.display = "none";
    });
}

function stopGameMode() {
  window.removeEventListener("keydown", handleGameKeyDown);
  window.removeEventListener("keyup", handleGameKeyUp);
  
  if (window.gameInstance) {
    window.gameInstance.stop();
    window.gameInstance = null;
  }
  if (gameAudioCtx) {
    if (gameAudioCtx.state !== 'closed') {
      gameAudioCtx.close();
    }
    gameAudioCtx = null;
  }
  $("#game-status-label").innerText = "已停止";
  $("#game-status-label").style.color = "var(--text-dim)";
}

class RhythmGame {
  constructor(canvas, chartData, audioBuffer, audioContext) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.chart = chartData;
    this.buffer = audioBuffer;
    this.ctxAudio = audioContext;
    this.startTime = 0;
    this.isPlaying = false;
    
    this.autoplay = true;   
    this.combo = 0;
    this.maxCombo = 0;
    this.score = 0;
    this.lastHitRating = "";
    this.lastHitChar = "";
    this.hitParticles = []; 
    
    this.laneWidth = 80;
    this.hitPosition = 460;
    this.noteSpeed = 300;   
    
    this.laneActive = [false, false, false, false];
  }

  start() {
    this.audioSource = this.ctxAudio.createBufferSource();
    this.audioSource.buffer = this.buffer;
    this.audioSource.connect(this.ctxAudio.destination);
    
    this.isPlaying = true;
    this.startTime = this.ctxAudio.currentTime;
    this.audioSource.start(0);
    
    this.animate();
  }
  
  stop() {
    this.isPlaying = false;
    if (this.audioSource) {
      try {
        this.audioSource.stop();
      } catch(e) {}
    }
  }

  animate() {
    if (!this.isPlaying) return;
    requestAnimationFrame(() => this.animate());

    const time = this.ctxAudio.currentTime - this.startTime;
    
    if (this.autoplay) {
      this.chart.notes.forEach(note => {
        if (!note.hit && time >= note.time) {
          note.hit = true;
          this.triggerHitFeedback(note, 'Perfect');
        }
        if (note.type === 'hold' && note.hit && !note.released && time >= note.end_time) {
          note.released = true;
          this.triggerReleaseFeedback(note, 'Perfect');
        }
      });
    } else {
      this.chart.notes.forEach(note => {
        if (!note.hit && time > note.time + 0.15) {
          note.hit = true;
          note.missed = true;
          this.triggerMissFeedback();
        }
        if (note.type === 'hold' && note.hit && !note.released && !note.missed && time > note.end_time + 0.15) {
          note.released = true;
          this.triggerMissFeedback();
        }
      });
    }

    this.updateParticles();
    this.draw(time);
  }

  handleKeyDown(e) {
    if (this.autoplay) return;
    const keyToLane = { 'd': 0, 'f': 1, 'j': 2, 'k': 3 };
    const lane = keyToLane[e.key.toLowerCase()];
    if (lane !== undefined) {
      this.laneActive[lane] = true;
      
      const time = this.ctxAudio.currentTime - this.startTime;
      const note = this.chart.notes.find(n => n.lane === lane && !n.hit && Math.abs(n.time - time) < 0.15);
      if (note) {
        note.hit = true;
        const diff = Math.abs(note.time - time);
        let rating = 'Perfect';
        if (diff > 0.04) rating = 'Great';
        if (diff > 0.08) rating = 'Good';
        this.triggerHitFeedback(note, rating);
      }
    }
  }

  handleKeyUp(e) {
    if (this.autoplay) return;
    const keyToLane = { 'd': 0, 'f': 1, 'j': 2, 'k': 3 };
    const lane = keyToLane[e.key.toLowerCase()];
    if (lane !== undefined) {
      this.laneActive[lane] = false;
      
      const time = this.ctxAudio.currentTime - this.startTime;
      const note = this.chart.notes.find(n => n.lane === lane && n.hit && !n.released && !n.missed && n.type === 'hold' && Math.abs(n.end_time - time) < 0.15);
      if (note) {
        note.released = true;
        const diff = Math.abs(note.end_time - time);
        let rating = 'Perfect';
        if (diff > 0.04) rating = 'Great';
        if (diff > 0.08) rating = 'Good';
        this.triggerReleaseFeedback(note, rating);
      }
    }
  }

  triggerHitFeedback(note, rating) {
    this.lastHitRating = rating;
    this.lastHitChar = note.char;
    this.combo++;
    if (this.combo > this.maxCombo) this.maxCombo = this.combo;
    this.score += rating === 'Perfect' ? 100 : rating === 'Great' ? 80 : 50;
    
    document.getElementById("game-score-label").innerText = this.score;
    document.getElementById("game-combo-label").innerText = `${this.combo} (Max: ${this.maxCombo})`;
    
    this.hitParticles.push({
      char: note.char,
      x: note.lane * this.laneWidth + this.laneWidth / 2,
      y: this.hitPosition,
      alpha: 1.0,
      scale: 1.0,
      vx: (Math.random() - 0.5) * 4,
      vy: -Math.random() * 5 - 3
    });
  }

  triggerReleaseFeedback(note, rating) {
    this.lastHitRating = rating;
    this.score += 50;
    document.getElementById("game-score-label").innerText = this.score;
  }

  triggerMissFeedback() {
    this.lastHitRating = "MISS";
    this.combo = 0;
    document.getElementById("game-combo-label").innerText = `0 (Max: ${this.maxCombo})`;
  }

  updateParticles() {
    this.hitParticles.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      p.alpha -= 0.025;
      p.scale += 0.012;
    });
    this.hitParticles = this.hitParticles.filter(p => p.alpha > 0);
  }

  draw(time) {
    this.ctx.fillStyle = '#0f0f1e';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    for (let i = 0; i < 4; i++) {
      if (this.laneActive[i]) {
        this.ctx.fillStyle = 'rgba(0, 246, 255, 0.08)';
        this.ctx.fillRect(i * this.laneWidth, 0, this.laneWidth, this.canvas.height);
      }
      this.ctx.strokeStyle = '#222538';
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(i * this.laneWidth, 0, this.laneWidth, this.canvas.height);
    }

    this.ctx.strokeStyle = '#e94560';
    this.ctx.lineWidth = 4;
    this.ctx.shadowBlur = 15;
    this.ctx.shadowColor = '#e94560';
    this.ctx.beginPath();
    this.ctx.moveTo(0, this.hitPosition);
    this.ctx.lineTo(4 * this.laneWidth, this.hitPosition);
    this.ctx.stroke();
    this.ctx.shadowBlur = 0;

    this.chart.notes.forEach(note => {
      const timeDiff = note.time - time;
      
      if (note.type === 'tap' && note.hit) return;
      if (note.missed) return;
      
      if (timeDiff > -0.2 && timeDiff < 2.0) {
        const x = note.lane * this.laneWidth + 10;
        const y = this.hitPosition - (timeDiff * this.noteSpeed);

        if (note.type === 'tap') {
          this.ctx.fillStyle = '#4a90d9';
          this.ctx.fillRect(x, y - 10, this.laneWidth - 20, 20);
          this.ctx.fillStyle = '#fff';
          this.ctx.font = 'bold 14px Arial';
          this.ctx.fillText(note.char, x + this.laneWidth / 2 - 17, y + 5);
        } else if (note.type === 'hold') {
          const startY = note.hit ? this.hitPosition : y;
          const endDiff = note.end_time - time;
          const endY = this.hitPosition - (endDiff * this.noteSpeed);
          const holdLength = startY - endY;
          
          if (holdLength > 0) {
            this.ctx.fillStyle = note.hit ? 'rgba(255, 152, 0, 0.4)' : '#ff9800';
            this.ctx.fillRect(x, endY, this.laneWidth - 20, holdLength);
            this.ctx.fillStyle = '#fff';
            this.ctx.font = 'bold 14px Arial';
            this.ctx.fillText(note.char, x + this.laneWidth / 2 - 17, startY - 8);
          }
        }
      }
    });

    this.hitParticles.forEach(p => {
      this.ctx.save();
      this.ctx.globalAlpha = p.alpha;
      this.ctx.fillStyle = '#00f6ff';
      this.ctx.font = `bold ${Math.floor(22 * p.scale)}px sans-serif`;
      this.ctx.shadowBlur = 10;
      this.ctx.shadowColor = '#00f6ff';
      this.ctx.fillText(p.char, p.x - 10, p.y);
      this.ctx.restore();
    });

    if (this.autoplay) {
      this.ctx.fillStyle = 'rgba(0, 246, 255, 0.15)';
      this.ctx.fillRect(10, 10, 110, 28);
      this.ctx.fillStyle = '#00f6ff';
      this.ctx.font = 'bold 12px monospace';
      this.ctx.fillText('⚡ AUTOPLAY', 20, 28);
    } else {
      this.ctx.fillStyle = 'rgba(233, 69, 96, 0.15)';
      this.ctx.fillRect(10, 10, 110, 28);
      this.ctx.fillStyle = '#e94560';
      this.ctx.font = 'bold 12px monospace';
      this.ctx.fillText('🎮 MANUAL', 25, 28);
    }

    if (this.combo > 0) {
      this.ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
      this.ctx.font = 'bold 24px Arial';
      this.ctx.fillText(`${this.combo} COMBO`, 20, 100);
      
      this.ctx.fillStyle = this.lastHitRating === 'Perfect' ? '#00f6ff' : this.lastHitRating === 'Great' ? '#ff9800' : '#4a90d9';
      this.ctx.font = 'bold 18px Arial';
      this.ctx.fillText(this.lastHitRating, 20, 130);
    } else if (this.lastHitRating === 'MISS') {
      this.ctx.shadowBlur = 0;
      this.ctx.fillStyle = '#e94560';
      this.ctx.font = 'bold 24px Arial';
      this.ctx.fillText('MISS', 20, 100);
    }
  }
}