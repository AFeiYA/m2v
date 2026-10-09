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

function setTrackLoadingState(trackType, isLoading, trackName, errorMsg) {
  const isVocals = trackType === "vocals";
  const btn = isVocals ? (dom.btnMuteVocals || document.getElementById("btn-mute-vocals")) : (dom.btnMuteInst || document.getElementById("btn-mute-instrumental"));
  const skeleton = document.getElementById(isVocals ? "skeleton-vocals" : "skeleton-instrumental");
  const skeletonText = document.getElementById(isVocals ? "skeleton-text-vocals" : "skeleton-text-inst");

  if (btn) {
    if (isLoading) {
      btn.classList.add("buffering");
      btn.classList.add("active");
      btn.classList.remove("muted");
      btn.innerHTML = `<span class="track-btn-title">${trackName}</span><span class="track-btn-badge"><i class="wave-dot"></i>缓冲中</span>`;
    } else {
      btn.classList.remove("buffering");
      if (errorMsg) {
        btn.innerHTML = `<span class="track-btn-title">${trackName}</span><span class="track-btn-badge error">${errorMsg}</span>`;
      } else {
        btn.innerHTML = `<span class="track-btn-title">${trackName}</span>`;
      }
    }
  }

  if (skeleton) {
    if (isLoading) {
      skeleton.classList.remove("loaded");
      skeleton.style.display = "flex";
      if (skeletonText) skeletonText.textContent = `${trackName}缓冲加载中...`;
    } else {
      skeleton.classList.add("loaded");
      setTimeout(() => {
        if (skeleton.classList.contains("loaded")) {
          skeleton.style.display = "none";
        }
      }, 350);
    }
  }
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
    updateAudioAnalysisSummary();
  } catch (e) {
    status("对齐数据加载失败: " + e, true);
    state.alignment = null;
    return;
  }

  // 1. 立即优先渲染歌词与分镜面板 (零等待秒级呈现)
  if (window.onSongLoaded) window.onSongLoaded();
  status(`📝 歌词已就绪 (${state.alignment.lines.length} 行)，正在加载音轨波形...`);

  // 2. 并行异步下载人声与伴奏音轨 (耗时缩减 50%)
  const tracks = file.audio_tracks || {};
  const vocalsUrl = tracks.vocals ? "/api/audio?path=" + encodeURIComponent(tracks.vocals) : null;
  const instUrl = tracks.instrumental ? "/api/audio?path=" + encodeURIComponent(tracks.instrumental) : null;
  const origUrl = file.audio_path ? "/api/audio?path=" + encodeURIComponent(file.audio_path) : null;

  const primaryUrl = vocalsUrl || origUrl;
  const primaryTitle = vocalsUrl ? "🎤 人声" : "🎵 原声";
  const instTitle = "🎸 伴奏";

  if (dom.trackVocals) dom.trackVocals.classList.remove("muted");
  if (dom.trackInst) dom.trackInst.classList.remove("muted");

  const loadTasks = [];
  if (primaryUrl && ws) {
    setTrackLoadingState("vocals", true, primaryTitle);
    loadTasks.push(
      ws.load(primaryUrl)
        .then(() => {
          vocalsReady = true;
          setTrackLoadingState("vocals", false, primaryTitle);
        })
        .catch((e) => {
          status("人声轨加载失败: " + e, true);
          setTrackLoadingState("vocals", false, primaryTitle, "加载失败");
        })
    );
  }
  if (instUrl && wsInst) {
    if (dom.trackInst) dom.trackInst.classList.remove("hidden");
    setTrackLoadingState("instrumental", true, instTitle);
    loadTasks.push(
      wsInst.load(instUrl)
        .then(() => {
          instReady = true;
          setTrackLoadingState("instrumental", false, instTitle);
        })
        .catch((e) => {
          status("伴奏轨加载失败: " + e, true);
          setTrackLoadingState("instrumental", false, instTitle, "加载失败");
        })
    );
  } else {
    if (dom.trackInst) dom.trackInst.classList.add("hidden");
    setTrackLoadingState("instrumental", false, instTitle);
  }

  Promise.allSettled(loadTasks).then(() => {
    const trackInfo = [vocalsUrl ? "人声" : null, instUrl ? "伴奏" : null, (!vocalsUrl && origUrl) ? "原声" : null].filter(Boolean).join("+");
    status(`✅ 全部就绪: ${file.name} (${state.alignment.lines.length} 行, 音轨: ${trackInfo || "无"})`);
    document.title = `${file.name} — M2V`;
  });
}

// ---------------------------------------------------------------------------
// Suno URL 10-Item Local History
// ---------------------------------------------------------------------------
const DEFAULT_URL_HISTORY = [
  "https://suno.com/s/toVdvY4vNA3pRYbG", // Tailwind
  "https://suno.com/s/3PeLT56j07K4vjk8", // Circus in my head
  "https://suno.com/s/eNqSlezWB2i53tD3", // Road Closed, Door Open
  "https://suno.com/s/gLAkLu9fiymSb0eV", // Look Up·抬头看
];

function getSunoUrlHistory() {
  try {
    const raw = localStorage.getItem("suno_url_history_v1");
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr) && arr.length > 0) return arr.slice(0, 10);
    }
  } catch (e) {}
  return [...DEFAULT_URL_HISTORY];
}

function saveSunoUrlHistory(url) {
  if (!url || typeof url !== "string") return;
  const clean = url.trim();
  if (!clean || clean.length < 5) return;
  try {
    const history = getSunoUrlHistory().filter((u) => u !== clean);
    history.unshift(clean);
    const top10 = history.slice(0, 10);
    localStorage.setItem("suno_url_history_v1", JSON.stringify(top10));
    renderSunoUrlHistory(top10);
  } catch (e) {}
}

function renderSunoUrlHistory(list) {
  const history = list || getSunoUrlHistory();
  const datalist = document.getElementById("suno-url-history");
  if (datalist) {
    datalist.innerHTML = history.map((u) => `<option value="${u}"></option>`).join("");
  }
  const select = document.getElementById("suno-url-history-select");
  if (select) {
    const options = [
      '<option value="">🕒 最近历史 (10条)</option>',
      ...history.map((u, i) => {
        let label = u;
        if (u.includes("toVdvY4vNA3pRYbG")) label = "Tailwind (双语/吉他Solo)";
        else if (u.includes("3PeLT56j07K4vjk8")) label = "Circus (快歌/气口)";
        else if (u.includes("eNqSlezWB2i53tD3")) label = "Road Closed (尾奏复唱)";
        else if (u.includes("gLAkLu9fiymSb0eV")) label = "Look Up (口哨间奏)";
        else {
          label = u.replace(/^https?:\/\/(www\.)?/, "");
          if (label.length > 30) label = label.slice(0, 27) + "...";
        }
        return `<option value="${u}">#${i + 1} ${label}</option>`;
      }),
    ];
    select.innerHTML = options.join("");
  }
}
window.getSunoUrlHistory = getSunoUrlHistory;
window.saveSunoUrlHistory = saveSunoUrlHistory;
window.renderSunoUrlHistory = renderSunoUrlHistory;

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
    alert("请输入有效的 Suno / 网易云歌曲链接、iframe 代码或歌曲 ID");
    return;
  }
  saveSunoUrlHistory(url);
  if (btn) btn.disabled = true;
  if (prog) prog.style.display = "block";

  const chkSep = document.getElementById("chk-separate-vocals");
  const chkGpu = document.getElementById("chk-use-gpu");
  const selLang = document.getElementById("select-import-lang");
  const separateVocals = chkSep ? chkSep.checked : true;
  const useGpu = chkGpu ? chkGpu.checked : true;
  const importLang = selLang ? selLang.value : "auto";

  try {
    localStorage.setItem("suno_chk_sep", separateVocals ? "1" : "0");
    localStorage.setItem("suno_chk_gpu", useGpu ? "1" : "0");
    if (selLang) localStorage.setItem("suno_import_lang", importLang);
  } catch (e) {}

  const isNetEase = url.includes("163.com") || url.includes("163cn.tv") || url.includes("<iframe") || /^\d{5,}$/.test(url);
  let importSec = 0;
  const updateProgressMessage = () => {
    let stage = isNetEase ? "正在从网易云音乐提取歌曲、LRC 歌词与音频..." : "正在从 Suno 提取歌曲信息与歌词...";
    if (importSec > 5) {
      stage = separateVocals ? "正在进行人声与伴奏分离及时间轴对齐..." : "正在进行原曲词级时间轴对齐 (CTC / WhisperX)...";
    }
    if (progText) {
      progText.textContent = `${stage} (已耗时 ${importSec}s)`;
    }
  };
  updateProgressMessage();
  const importTimer = setInterval(() => {
    importSec++;
    updateProgressMessage();
  }, 1000);

  try {
    const res = await fetch("/api/suno/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        async_mode: true,
        skip_separation: !separateVocals,
        use_gpu: useGpu,
        language: importLang,
      }),
    });

    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      if (text.includes("<!DOCTYPE") || res.status === 504 || res.status === 502) {
        throw new Error("云端网关超时，但后端正在后台继续处理中，请稍后刷新页面查看！");
      }
      throw new Error("服务器返回了非标准响应: " + text.slice(0, 100));
    }

    if (!res.ok) throw new Error(data.detail || "处理失败");

    // 异步轮询任务进度 (每个轮询请求仅需几十毫秒，彻底规避 Vercel 120s 超时截断)
    if (data.task_id) {
      const taskId = data.task_id;
      let finalResult = null;
      let previewLyricsShown = false;
      while (true) {
        await new Promise((r) => setTimeout(r, 1200));
        let task;
        try {
          const pollRes = await fetch(`/api/suno/task_status?task_id=${encodeURIComponent(taskId)}`);
          if (pollRes.status === 404) {
            throw Object.assign(new Error("导入任务不存在或服务已重启，请重新导入"), {terminal: true});
          }
          if (!pollRes.ok) continue;
          task = await pollRes.json();
        } catch (pollErr) {
          if (pollErr.terminal) throw pollErr;
          console.warn("轮询状态重试中...", pollErr);
          continue;
        }
        if (progText && task.message) {
          progText.textContent = `${task.message} (已耗时 ${importSec}s)`;
        }

        // 步骤 1 拿到歌词后，提前在左侧列表渲染歌词预览，避免用户干等
        if (task.title && task.lyrics && !previewLyricsShown) {
          previewLyricsShown = true;
          status(`📝 已提前获取《${task.title}》歌词，后台正在进行时间轴对齐...`);
          const listEl = document.getElementById("lyrics-list");
          if (listEl) {
            const rawLines = task.lyrics.split("\n").filter(Boolean);
            listEl.innerHTML = `<div style="padding: 10px 14px; font-size: 11px; color: #10b981; background: rgba(16,185,129,0.08); border-bottom: 1px solid var(--border); border-radius: 4px 4px 0 0;">✨ 已提前解析《${escHtml(task.title)}》(${rawLines.length} 行歌词)，后台正在进行字级时间轴对齐：</div>` +
              rawLines.map((l, i) => `<div class="lyric-line-item" style="opacity: 0.85;"><span class="line-index">${i+1}</span><span class="line-text">${escHtml(l)}</span></div>`).join("");
          }
        }

        if (task.status === "done") {
          finalResult = task.result;
          break;
        } else if (task.status === "error") {
          throw new Error(task.error || "处理失败");
        }
      }
      data = finalResult || data;
    }

    if (dom.sunoModal) dom.sunoModal.style.display = "none";
    if (input) input.value = "";
    status(`🎉 导入成功: ${data.title}`);
    await loadFileList(data.title);
  } catch (err) {
    alert("Suno 导入失败: " + err.message);
  } finally {
    clearInterval(importTimer);
    if (btn) btn.disabled = false;
    if (prog) prog.style.display = "none";
  }
}
window.handleSunoImport = handleSunoImport;

// ---------------------------------------------------------------------------
// Download Original Audio (Dual Mode: URL Input -> Step 1 | Loaded Song -> Existing)
// ---------------------------------------------------------------------------
async function downloadOriginalAudio() {
  const sunoInput = document.getElementById("suno-url-input");
  const rawUrl = sunoInput ? sunoInput.value.trim() : "";

  // 模式 1: 用户在输入框贴入了 Suno / 网易云链接、iframe 或 ID -> 提取并下载原曲 MP3
  const isImportUrl = rawUrl && (
    rawUrl.startsWith("http://") ||
    rawUrl.startsWith("https://") ||
    rawUrl.includes("suno.com") ||
    rawUrl.includes("163.com") ||
    rawUrl.includes("163cn.tv") ||
    rawUrl.includes("<iframe") ||
    /^\d{5,}$/.test(rawUrl)
  );

  if (isImportUrl) {
    saveSunoUrlHistory(rawUrl);
    const isNetEase = rawUrl.includes("163.com") || rawUrl.includes("163cn.tv") || rawUrl.includes("<iframe") || /^\d{5,}$/.test(rawUrl);
    status(isNetEase ? "⏳ [1/2] 正在连接网易云音乐解析歌曲音频..." : "⏳ [1/2] 正在连接 Suno 解析歌曲信息与歌词...");
    const dlUrl = `/api/suno/download_mp3?url=${encodeURIComponent(rawUrl)}`;
    const a = document.createElement("a");
    a.href = dlUrl;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => {
      status("🎵 [2/2] 正在从音频/视频流提取高品质 MP3，提取完成后浏览器将自动保存...");
    }, 1500);
    return;
  }

  // 模式 2: 当前工程已导入/加载 -> 直接秒级下载第一步已生成好的原曲 MP3
  if (state.currentFile) {
    const songName = state.currentFile.name;
    const jsonPath = state.currentFile.json_path || "";
    status(`正在下载《${songName}》原曲 MP3...`);

    const url = `/api/download/original_mp3?song=${encodeURIComponent(songName)}&json_path=${encodeURIComponent(jsonPath)}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${songName}.mp3`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => status(`已触发下载: ${songName}.mp3`), 800);
    return;
  }

  alert("请在左上方输入框粘贴 Suno 歌曲链接，或者在下拉列表中选择已导入的项目！");
}
window.downloadOriginalAudio = downloadOriginalAudio;


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
  return /^[\s，。、！？；：""''（）《》…—·\-,.!?;:'"()\[\]{}]+$/.test(ch);
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

// 全局兼容性函数 (解决 formatTime / parseTime / escapeHtml 未定义异常)
function formatTime(s) {
  return fmtTime(s);
}

function parseTime(str) {
  return parseTimeInput(str);
}

function escapeHtml(s) {
  return escHtml(s);
}

window.fmtTime = fmtTime;
window.formatTime = formatTime;
window.fmtTimeShort = fmtTimeShort;
window.parseTimeInput = parseTimeInput;
window.parseTime = parseTime;
window.escHtml = escHtml;
window.escapeHtml = escapeHtml;

window.addEventListener("DOMContentLoaded", () => {
  renderSunoUrlHistory();
  const chkSep = document.getElementById("chk-separate-vocals");
  const chkGpu = document.getElementById("chk-use-gpu");
  const devOpt = document.getElementById("suno-dev-options");

  // 默认启用分离与 GPU 加速 (保证最高准确率与防跳句)
  if (chkSep) chkSep.checked = true;
  if (chkGpu) chkGpu.checked = true;

  try {
    if (chkSep && localStorage.getItem("suno_chk_sep") !== null) {
      chkSep.checked = localStorage.getItem("suno_chk_sep") === "1";
    }
    if (chkGpu && localStorage.getItem("suno_chk_gpu") !== null) {
      chkGpu.checked = localStorage.getItem("suno_chk_gpu") === "1";
    }
    const selLang = document.getElementById("select-import-lang");
    if (selLang && localStorage.getItem("suno_import_lang") !== null) {
      selLang.value = localStorage.getItem("suno_import_lang");
    }
  } catch (e) {}

  // 开发者调试模式显隐控制:
  // 1. URL 含有 ?dev=1 或 ?debug=1 时自动显现
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("dev") === "1" || urlParams.get("debug") === "1") {
    if (devOpt) devOpt.style.display = "inline-flex";
  }

  // 2. 连续点击 3 次左上角标题，或者按下快捷键 Ctrl+Shift+D / Cmd+Shift+D 切换显隐
  let clickCount = 0;
  let clickTimer = null;
  const titleEl = document.querySelector("header h1");
  if (titleEl && devOpt) {
    titleEl.style.cursor = "pointer";
    titleEl.title = "三击标题可显示/隐藏开发者调试选项";
    titleEl.addEventListener("click", () => {
      clickCount++;
      clearTimeout(clickTimer);
      if (clickCount >= 3) {
        devOpt.style.display = devOpt.style.display === "none" ? "inline-flex" : "none";
        clickCount = 0;
        status(devOpt.style.display === "inline-flex" ? "🛠 已开启开发者调试选项" : "🛠 已隐藏开发者调试选项");
      } else {
        clickTimer = setTimeout(() => { clickCount = 0; }, 500);
      }
    });
  }

  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "D" || e.key === "d")) {
      e.preventDefault();
      if (devOpt) {
        devOpt.style.display = devOpt.style.display === "none" ? "inline-flex" : "none";
        status(devOpt.style.display === "inline-flex" ? "🛠 已开启开发者调试选项" : "🛠 已隐藏开发者调试选项");
      }
    }
  });
});

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
});

window.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("btn-analyze-audio");
  if (!button) return;
  button.addEventListener("click", async () => {
    if (!state.currentFile || !state.alignment) return status("请先选择歌曲", true);
    const song = state.currentFile;
    button.disabled = true;
    try {
      status("正在分析原曲节拍、能量和频段变化…");
      const response = await fetch("/api/audio/analyze", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({json_path: song.json_path})});
      if (!response.ok) throw new Error(await response.text());
      const task = await response.json();
      let result;
      do {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const poll = await fetch("/api/audio/analyze/" + task.task_id);
        if (!poll.ok) throw new Error(await poll.text());
        result = await poll.json();
      } while (result.status === "running");
      if (result.status !== "done") throw new Error(result.error || "分析失败");
      if (state.currentFile === song) {
        const updated = await fetch("/api/alignment?path=" + encodeURIComponent(song.json_path));
        if (!updated.ok) throw new Error(await updated.text());
        const project = await updated.json();
        // Retain unsaved lyric edits in the open editor.
        state.alignment.analysis = project.analysis;
        state.alignment.audio_path = project.audio_path;
        state.alignment.duration = project.duration;
        updateAudioAnalysisSummary();
      }
      status(`音频分析完成：${result.bpm ? result.bpm + " BPM" : "未检测到稳定节拍"}，${result.beats} 个拍点，100Hz 特征${result.cache_hit ? "（缓存）" : ""}；重拍和鼓点类别为估计值`);
    } catch (error) {
      status("音频分析失败：" + error.message, true);
    } finally { button.disabled = false; }
  });
});

function updateAudioAnalysisSummary() {
  const panel = document.getElementById("audio-analysis-summary");
  if (!panel) return;
  const analysis = state.alignment?.analysis;
  if (!analysis?.envelopes?.length) {
    panel.textContent = "音频特征尚未分析 · 点击“分析音频”即可补做，无需重新对齐歌词";
    return;
  }
  panel.textContent = `音频特征已就绪 · ${analysis.duration.toFixed(1)} 秒 · ${analysis.bpm ? "估算 " + analysis.bpm + " BPM" : "未检测到稳定节拍"} · ${analysis.beats.length} 个拍点 · ${analysis.feature_rate_hz}Hz / ${analysis.envelopes.length} 个采样点 · 重拍和鼓点类别为估计值`;
}
