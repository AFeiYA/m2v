// ===========================================================================
// M2V Local Editor — Common Module (Player, Song Selector, Status, Utilities)
// ===========================================================================

function getApiUrl(path) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const base = (window.M2V_API_BASE || "").replace(/\/+$/, "");
  return path.startsWith("/api") && base ? `${base}${path}` : path;
}

function isCloudMode() {
  if (window.M2V_FORCE_CLOUD !== undefined) return Boolean(window.M2V_FORCE_CLOUD);
  if (window.M2V_FORCE_LOCAL !== undefined) return !window.M2V_FORCE_LOCAL;
  if (window.M2V_DETECTED_CLOUD) return true;
  if (window.M2V_API_BASE && window.M2V_API_BASE.trim().length > 0) return true;
  const h = (window.location && window.location.hostname) || "";
  if (h && (h.includes("fovea.si") || h.includes("pages.dev") || h.includes("hf.space") || h.includes("huggingface.co"))) {
    return true;
  }
  return false;
}
window.isCloudMode = isCloudMode;

// Synchronize authentication with parent Studio Shell if embedded
(function initParentAuthSync() {
  if (typeof window === "undefined") return;
  if (window.parent && window.parent !== window) {
    try {
      const pToken = window.parent.localStorage?.getItem("m2v_token");
      const pUser = window.parent.localStorage?.getItem("m2v_user");
      const pProvider = window.parent.localStorage?.getItem("m2v_auth_provider");
      if (pToken) {
        localStorage.setItem("m2v_token", pToken);
        if (pUser) localStorage.setItem("m2v_user", pUser);
        if (pProvider) localStorage.setItem("m2v_auth_provider", pProvider);
      }
      if (window.parent.m2vAuth) {
        window.m2vAuth = window.parent.m2vAuth;
      }
    } catch (_) {}
  }
})();

if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    if (window.parent && window.parent !== window && event.source !== window.parent) return;
    if (!event.data || typeof event.data !== "object") return;
    if (event.data.type === "M2V_SYNC_AUTH") {
      if (event.data.token) localStorage.setItem("m2v_token", event.data.token);
      if (event.data.user) localStorage.setItem("m2v_user", JSON.stringify(event.data.user));
      if (window.updateAuthUi) window.updateAuthUi();
    } else if (event.data.type === "M2V_LOAD_SONG") {
      const songId = event.data.songId;
      if (songId && typeof window.loadSongFile === "function") {
        window.loadSongFile(songId);
      }
    } else if (event.data.type === "M2V_STUDIO_PAUSE") {
      try {
        if (ws) ws.pause();
        if (wsInst) wsInst.pause();
      } catch (_) {}
    } else if (event.data.type === "M2V_STUDIO_DESTROY") {
      try {
        if (ws) { ws.pause(); ws.empty(); }
        if (wsInst) { wsInst.pause(); wsInst.empty(); }
        state.currentFile = null;
        state.alignment = null;
      } catch (_) {}
    }
  });
}

// Intercept clicks on links that point to parent dashboard sections or sibling studios
if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("click", (e) => {
    const link = e.target.closest("a");
    if (!link) return;
    const href = link.getAttribute("href");
    if (!href) return;
    if (window.parent && window.parent !== window) {
      const targetOrigin = window.location.origin;
      if (href === "/#exports-section" || href.includes("#exports-section") || href === "/#exports") {
        e.preventDefault();
        window.parent.postMessage({ type: "M2V_NAVIGATE", hash: "exports-section" }, targetOrigin);
      } else if (href === "/" || href === "/index.html" || href.startsWith("/#")) {
        e.preventDefault();
        const targetHash = href.includes("#") ? href.slice(href.indexOf("#") + 1) : "tasks-section";
        window.parent.postMessage({ type: "M2V_NAVIGATE", hash: targetHash }, targetOrigin);
      } else if (href === "/motion-studio" || href.startsWith("/motion-studio")) {
        e.preventDefault();
        const currentFile = (typeof state !== "undefined" && state.currentFile) ? state.currentFile : null;
        const currentId = currentFile?.task_id || currentFile?.id || (typeof window.getCurrentSongId === "function" ? window.getCurrentSongId() : "");
        window.parent.postMessage({ type: "M2V_SWITCH_STUDIO", target: "motion-studio", songId: currentId }, targetOrigin);
      }
    }
  });
}

function updateAuthUi() {
  const pill = document.getElementById("auth-pill");
  const info = document.getElementById("auth-user-info");
  const btn = document.getElementById("btn-auth-action");
  if (!pill || !btn) return;

  if (!isCloudMode()) {
    pill.style.display = "none";
    return;
  }

  pill.style.display = "inline-flex";
  const token = localStorage.getItem("m2v_token");
  let user = null;
  try {
    user = JSON.parse(localStorage.getItem("m2v_user") || "null");
  } catch (_) {}

  if (token) {
    if (info) info.textContent = user?.displayName || user?.email || "👤 Signed in";
    if (!user || !user.displayName) {
      apiFetch("/api/auth/me")
        .then(r => r.ok ? r.json() : null)
        .then(u => {
          if (u) {
            const userData = {
              id: u.id,
              displayName: u.display_name || u.username,
              email: u.email,
            };
            localStorage.setItem("m2v_user", JSON.stringify(userData));
            if (info) info.textContent = userData.displayName || "👤 Signed in";
          }
        })
        .catch(() => {});
    }
    btn.textContent = window.currentLocale === "en" ? "Sign Out" : "登出";
    btn.onclick = async () => {
      if (window.m2vCache) {
        try {
          const uid = window.m2vCache.getCurrentUid();
          await window.m2vCache.clearUserCache(uid);
        } catch (_) {}
      }
      if (window.m2vAuth?.logout) await window.m2vAuth.logout();
      localStorage.removeItem("m2v_token");
      localStorage.removeItem("m2v_user");
      localStorage.removeItem("m2v_refresh");
      localStorage.removeItem("m2v_auth_provider");
      updateAuthUi();
      await loadFileList();
    };
  } else {
    if (info) info.textContent = "";
    btn.textContent = window.currentLocale === "en" ? "Sign In" : "🔑 登录";
    btn.onclick = async () => {
      if (window.m2vAuth?.loginWithGoogle) {
        try {
          await editorLogin();
          updateAuthUi();
          await loadFileList();
        } catch (e) {
          alert("Sign-in failed: " + e.message);
        }
      } else {
        window.location.href = "/";
      }
    };
  }
}
window.updateAuthUi = updateAuthUi;

let editorRefreshPromise = null;
async function refreshEditorToken() {
  if (editorRefreshPromise) return editorRefreshPromise;
  editorRefreshPromise = (async () => {
    const provider = localStorage.getItem("m2v_auth_provider");
    const fbUser = typeof firebase !== "undefined" && firebase.auth ? firebase.auth().currentUser : null;
    if (provider === "firebase" || fbUser) {
      if (window.parent && window.parent !== window && window.parent.m2vAuth?.getIdToken) {
        try {
          const pToken = await window.parent.m2vAuth.getIdToken(true);
          if (pToken) {
            localStorage.setItem("m2v_token", pToken);
            return pToken;
          }
        } catch (_) {}
      }
      if (window.m2vAuth?.getIdToken) {
        try {
          const lToken = await window.m2vAuth.getIdToken(true);
          if (lToken) {
            localStorage.setItem("m2v_token", lToken);
            return lToken;
          }
        } catch (_) {}
      }
      // Never switch a Google session to a retained local-account refresh token.
      if (!fbUser) return null;
      const token = await fbUser.getIdToken(true);
      localStorage.setItem("m2v_token", token);
      return token;
    }
    const refresh = localStorage.getItem("m2v_refresh");
    if (!refresh) return null;
    const response = await fetch(getApiUrl("/api/auth/refresh"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({refresh_token: refresh}),
    });
    if (!response.ok) return null;
    const data = await response.json();
    localStorage.setItem("m2v_token", data.access_token);
    localStorage.setItem("m2v_refresh", data.refresh_token);
    return data.access_token;
  })().catch(() => null).finally(() => { editorRefreshPromise = null; });
  return editorRefreshPromise;
}

async function apiFetch(url, options = {}) {
  const fullUrl = getApiUrl(url);
  const token = localStorage.getItem("m2v_token");
  const opts = { ...options };
  const headers = new Headers(opts.headers || {});
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  opts.headers = headers;
  const response = await fetch(fullUrl, opts);
  if (response.status !== 401 || !isCloudMode()) return response;
  const refreshed = await refreshEditorToken();
  if (!refreshed) return response;
  headers.set("Authorization", `Bearer ${refreshed}`);
  return fetch(fullUrl, opts);
}
window.apiFetch = apiFetch;
window.getApiUrl = getApiUrl;

async function editorLogin() {
  const result = await window.m2vAuth.loginWithGoogle();
  localStorage.setItem("m2v_auth_provider", "firebase");
  localStorage.removeItem("m2v_refresh");
  return result;
}

function setupEditorAuth() {
  if (typeof firebase === "undefined" || !firebase.auth || window.editorAuthBound) return;
  window.editorAuthBound = true;
  firebase.auth().onAuthStateChanged(async user => {
    if (localStorage.getItem("m2v_auth_provider") === "local") return;
    if (user) {
      localStorage.setItem("m2v_auth_provider", "firebase");
      localStorage.removeItem("m2v_refresh");
      localStorage.setItem("m2v_token", await user.getIdToken());
      updateAuthUi();
      // Auth restoration may arrive after the initial anonymous list request.
      if (!state.currentFile) await loadFileList();
    } else if (localStorage.getItem("m2v_auth_provider") === "firebase") {
      localStorage.removeItem("m2v_token");
      updateAuthUi();
    }
  });
}
window.setupEditorAuth = setupEditorAuth;

let trackBlobUrls = [];
async function loadEditorAudio(player, path, taskId, trackType, version) {
  if (!isCloudMode() && !taskId) return player.load(formatAudioEndpoint(path));

  // 0. 优先从父级 MediaArbiter 共享内存缓存获取
  try {
    const sharedMedia = window.parent?.m2vMediaArbiter?.getCachedMedia(taskId, trackType);
    if (sharedMedia?.url) {
      console.log(`[m2vMediaArbiter] 共享内存缓存命中音轨: ${trackType} (task=${taskId})`);
      trackBlobUrls.push(sharedMedia.url);
      return player.load(sharedMedia.url);
    }
  } catch (_) {}

  const uid = window.m2vCache ? window.m2vCache.getCurrentUid() : null;

  // 1. 优先尝试从本地 IndexedDB 缓存加载 (秒开，0 流量)
  if (window.m2vCache && taskId && trackType) {
    try {
      const cachedBlob = await window.m2vCache.getMedia(uid, taskId, trackType, version);
      if (cachedBlob) {
        console.log(`[m2vCache] 本地缓存命中音轨: ${trackType} (task=${taskId})`);
        const url = URL.createObjectURL(cachedBlob);
        trackBlobUrls.push(url);
        try {
          window.parent?.m2vMediaArbiter?.cacheMedia(taskId, trackType, { url, blob: cachedBlob });
        } catch (_) {}
        return player.load(url);
      }
    } catch (e) {
      console.warn("[m2vCache] 读取媒体失败:", e);
    }
  }

  // 2. 缓存未命中或版本变更，从服务器下载 (走 Authorization Bearer 请求头，不将 token 暴露在 URL 中)
  const response = await apiFetch(path);
  if (!response.ok) throw new Error(`音轨读取失败 (HTTP ${response.status})`);
  const blob = await response.blob();

  // 3. 异步写入本地持久化缓存
  if (window.m2vCache && taskId && trackType) {
    window.m2vCache.saveMedia(uid, taskId, trackType, blob, version).catch(e => {
      console.warn("[m2vCache] 写入媒体缓存失败:", e);
    });
  }

  const url = URL.createObjectURL(blob);
  trackBlobUrls.push(url);
  try {
    window.parent?.m2vMediaArbiter?.cacheMedia(taskId, trackType, { url, blob });
  } catch (_) {}
  return player.load(url);
}

function formatAudioEndpoint(relPath) {
  if (!relPath) return null;
  const token = localStorage.getItem("m2v_token");
  let url = relPath;
  if (!relPath.startsWith("/api/")) {
    url = "/api/audio?path=" + encodeURIComponent(relPath);
  }
  if (token && !url.includes("token=")) {
    url += (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
  }
  return getApiUrl(url);
}
window.formatAudioEndpoint = formatAudioEndpoint;


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
if (typeof window !== "undefined") {
  window.state = state;
  window.getCurrentSongId = () => state.currentFile?.task_id || state.currentFile?.id || state.currentFile?.name || "";
}

let ws = null;        // primary WaveSurfer (vocals or original fallback)
let wsInst = null;    // secondary WaveSurfer (instrumental)
let vocalsReady = false, instReady = false;
let trackMuted = { vocals: false, instrumental: false };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const dom = {};

// ---------------------------------------------------------------------------
// WaveSurfer (dual-track)
// ---------------------------------------------------------------------------
function initWaveSurfer() {
  if (!dom.waveformVocals) return;

  ws = WaveSurfer.create({
    container: dom.waveformVocals,
    waveColor: "#38bdf8", progressColor: "#b7f34a",
    cursorColor: "#b7f34a", height: 72,
    barWidth: 2, barGap: 1, barRadius: 2,
    normalize: true,
  });

  if (dom.waveformInst) {
    wsInst = WaveSurfer.create({
      container: dom.waveformInst,
      waveColor: "#334155", progressColor: "#64748b",
      cursorColor: "#b7f34a", height: 72,
      barWidth: 2, barGap: 1, barRadius: 2,
      normalize: true,
    });
  }

  ws.on("ready", () => {
    vocalsReady = true;
    updateTimeDisplay();
    status(window.t ? t("msg_vocals_loaded") : "人声轨已加载");
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

  ws.on("play", () => {
    try {
      const origin = (typeof window !== "undefined" && window.location?.origin) ? window.location.origin : "*";
      window.parent?.postMessage({ type: "M2V_MEDIA_PLAY", source: "lyric" }, origin);
    } catch (_) {}
  });

  ws.on("pause", () => {
    try {
      const origin = (typeof window !== "undefined" && window.location?.origin) ? window.location.origin : "*";
      window.parent?.postMessage({ type: "M2V_MEDIA_PAUSE", source: "lyric" }, origin);
    } catch (_) {}
  });

  ws.on("finish", () => {
    if (wsInst && instReady) wsInst.pause();
    updatePlayPauseBtn(false);
  });

  if (wsInst) {
    wsInst.on("ready", () => {
      instReady = true;
      status(window.t ? t("msg_inst_loaded") : "伴奏轨已加载");
    });
  }
}

function syncInstToVocals() {
  if (!wsInst || !instReady || !vocalsReady) return;
  const tTime = ws.getCurrentTime();
  const instT = wsInst.getCurrentTime();
  if (Math.abs(tTime - instT) > 0.15) wsInst.setTime(tTime);
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
  const trackName = track === "vocals"
    ? (window.t ? t("track_vocals") : "人声")
    : (window.t ? t("track_inst") : "伴奏");
  const msgKey = trackMuted[track] ? "msg_muted" : "msg_unmuted";
  status(window.t ? t(msgKey, null, { track: trackName }) : (trackMuted[track] ? `${track} 已静音` : `${track} 已取消静音`));
}

function updatePlayPauseBtn(playing) {
  if (!dom.btnPlayPause) return;
  dom.btnPlayPause.textContent = playing
    ? (window.t ? t("btn_pause", "⏸ 暂停") : "⏸ 暂停")
    : (window.t ? t("btn_play", "▶ 播放") : "▶ 播放");
}

const trackLoadingStates = new Map();
function setTrackLoadingState(trackType, isLoading, trackName, errorMsg, titleKey) {
  titleKey ||= trackType === "vocals" ? "track_vocals" : "track_inst";
  trackLoadingStates.set(trackType, {isLoading, trackName, errorMsg, titleKey});
  if (window.t) trackName = t(titleKey, trackName);
  const buffering = window.t ? t("track_buffering") : "Buffering";
  const failed = window.t ? t("track_load_failed") : "Load failed";
  const isVocals = trackType === "vocals";
  const btn = isVocals ? (dom.btnMuteVocals || document.getElementById("btn-mute-vocals")) : (dom.btnMuteInst || document.getElementById("btn-mute-instrumental"));
  const skeleton = document.getElementById(isVocals ? "skeleton-vocals" : "skeleton-instrumental");
  const skeletonText = document.getElementById(isVocals ? "skeleton-text-vocals" : "skeleton-text-inst");

  if (btn) {
    if (isLoading) {
      btn.classList.add("buffering");
      btn.classList.add("active");
      btn.classList.remove("muted");
      btn.innerHTML = `<span class="track-btn-title">${trackName}</span><span class="track-btn-badge"><i class="wave-dot"></i>${buffering}</span>`;
    } else {
      btn.classList.remove("buffering");
      if (errorMsg) {
        btn.innerHTML = `<span class="track-btn-title">${trackName}</span><span class="track-btn-badge error">${failed}</span>`;
      } else {
        btn.innerHTML = `<span class="track-btn-title">${trackName}</span>`;
      }
    }
  }

  if (skeleton) {
    if (isLoading) {
      skeleton.classList.remove("loaded");
      skeleton.style.display = "flex";
      if (skeletonText) skeletonText.textContent = window.t ? t("track_loading", null, {track: trackName}) : `Loading ${trackName}…`;
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
    updatePlayPauseBtn(false);
  } else {
    if (wsInst && instReady) { wsInst.setTime(ws.getCurrentTime()); wsInst.play(); }
    ws.play();
    updatePlayPauseBtn(true);
  }
}

function playSelectedLine() {
  if (state.selectedLine < 0 || !ws) return;
  const line = state.alignment?.lines?.[state.selectedLine];
  if (!line) return;
  ws.setTime(line.start);
  ws.play();
  updatePlayPauseBtn(true);
  if (wsInst && instReady) { wsInst.setTime(line.start); wsInst.play(); }
  const stopAt = line.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause();
      if (wsInst && instReady) wsInst.pause();
      updatePlayPauseBtn(false);
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
  updateAuthUi();
  try {
    let files = [];
    if (isCloudMode()) {
      const r = await apiFetch('/api/songs?view=all&page_size=50'+(preferredTitle?'&q='+encodeURIComponent(preferredTitle):''));
      if (!r.ok) throw new Error('Unable to load your songs. Please sign in and retry.');
      const data=await r.json();
      files=data.songs.filter(s=>s.current_task_id).map(s=>cloudSongFile({task_id:s.current_task_id,name:s.title}));
      const params=new URLSearchParams(window.location.search);
      const target=params.get('task_id')||(window.location.pathname.match(/\/lyric-editor\/([0-9a-fA-F-]+)/)||[])[1];
      if(target&&!files.some(f=>f.task_id===target)){
        const response=await apiFetch('/api/editor/tasks/'+encodeURIComponent(target)+'/info');
        if(response.ok)files.push(cloudSongFile(await response.json()));
      }
      if(window.m2vSongPicker)window.m2vSongPicker.mount(dom.songSelect,async path=>{
        const response=await apiFetch(path);if(!response.ok)throw Error('Unable to load songs. Please retry.');return response.json();
      },async id=>{
        if(state.dirty&&!confirm('Switch versions and discard unsaved lyric changes?'))return false;
        let index=state.allFiles.findIndex(f=>f.task_id===id);
        if(index<0){state.allFiles.push(cloudSongFile({task_id:id,name:'Song'}));index=state.allFiles.length-1;}
        await loadSong(index);return state.currentFile?.task_id===id;
      });
    } else {
      const r = await apiFetch("/api/files");
      if (r.status === 403) {
        // 本地单机目录在云端被拦截，自愈切换为云端模式
        window.M2V_DETECTED_CLOUD = true;
        return loadFileList(preferredTitle);
      }
      if (!r.ok) throw new Error(await r.text());
      files = await r.json();
    }

    state.allFiles = files;
    if (dom.songSelect) {
      dom.songSelect.innerHTML = state.allFiles.length === 0
        ? `<option value="">${window.t ? t("song_select_empty") : "No song projects found"}</option>`
        : `<option value="">${window.t ? t("song_select_prompt") : "— Select a song —"}</option>` +
          state.allFiles.map((f, i) =>
            `<option value="${i}">${escHtml(f.name)}${f.audio_path ? " 🎵" : ""}</option>`
          ).join("");
    }

    const urlParams = new URLSearchParams(window.location.search);
    const targetTaskId = urlParams.get("task_id") || (window.location.pathname.match(/\/lyric-editor\/([0-9a-fA-F-]+)/) || [])[1];
    const targetSong = preferredTitle || urlParams.get("song");

    if (targetTaskId) {
      const idx = state.allFiles.findIndex(f => f.task_id === targetTaskId);
      if (idx >= 0) {
        loadSong(idx);
        return;
      }
    }
    if (targetSong) {
      const idx = state.allFiles.findIndex(f => f.name === targetSong || f.name.includes(targetSong));
      if (idx >= 0) {
        loadSong(idx);
        return;
      }
    }
    if (state.allFiles.length === 1) loadSong(0);
  } catch (e) {
    if (dom.songSelect) dom.songSelect.innerHTML = `<option value="">${window.t ? t("song_select_failed") : "Unable to load songs"}</option>`;
    status((window.t ? t("msg_load_file_failed") : "Failed to load song list: ") + e, true);
  }
}

function cloudSongFile(s) {
 return {name:s.name||s.task_id,task_id:s.task_id,is_saas:true,json_path:s.task_id,version:s.version||null,
   audio_path:`/api/editor/tasks/${s.task_id}/audio`,details_loaded:Boolean(s.version),
   audio_tracks:{vocals:s.has_vocals?`/api/editor/tasks/${s.task_id}/vocals`:null,instrumental:s.has_instrumental?`/api/editor/tasks/${s.task_id}/inst`:null}};
}

let songLoadSequence = 0;
async function loadSong(idx) {
  const loadSequence = ++songLoadSequence;
  const loadOwner = window.m2vCache?.getCurrentUid();
  const isCurrentLoad = () => loadSequence === songLoadSequence && loadOwner === window.m2vCache?.getCurrentUid();
  const file = state.allFiles[idx];
  if (!file) return;
  if(file.is_saas&&!file.details_loaded){
    const response=await apiFetch(`/api/editor/tasks/${file.task_id}/info`);
    if(!response.ok){status('Unable to open this version. Restore it from Trash if needed.',true);return;}
    const info = await response.json();
    if (!isCurrentLoad()) return;
    Object.assign(file,cloudSongFile(info));
  }

  if (ws) { ws.pause(); ws.empty(); }
  if (wsInst) { wsInst.pause(); wsInst.empty(); }
  trackBlobUrls.forEach(url => URL.revokeObjectURL(url));
  trackBlobUrls = [];
  trackLoadingStates.clear();

  state.currentFile = file;
  if (window.parent && window.parent !== window) {
    try {
      window.parent.postMessage({
        type: "M2V_SONG_CHANGED",
        songId: file.task_id || file.id || file.name,
        title: file.name
      }, window.location.origin);
    } catch (_) {}
  }
  state.selectedLine = -1;
  state.selectedWord = -1;
  state.undoStack = [];
  state.redoStack = [];
  state.dirty = false;
  vocalsReady = false;
  instReady = false;
  trackMuted = { vocals: false, instrumental: false };
  if (dom.songSelect) dom.songSelect.value = idx;
  status(window.t ? t("msg_loading_song", null, {name: file.name}) : `Loading ${file.name}…`);

  const taskId = file.task_id || file.id;
  const version = file.version || null;
  const uid = window.m2vCache ? window.m2vCache.getCurrentUid() : null;

  try {
    let loadedFromCache = false;
    if (window.m2vCache && taskId && version) {
      const cachedAlign = await window.m2vCache.getProject(uid, taskId, "alignment", version);
      if (!isCurrentLoad()) return;
      if (cachedAlign) {
        state.alignment = cachedAlign;
        loadedFromCache = true;
        console.log(`[m2vCache] 本地缓存命中工程: task=${taskId}, version=${version}`);
      }
    }

    if (!loadedFromCache) {
      let r;
      if (file.is_saas || file.task_id) {
        r = await apiFetch(`/api/editor/tasks/${file.task_id}/align`);
      } else {
        r = await apiFetch("/api/alignment?path=" + encodeURIComponent(file.json_path));
      }
      if (!r.ok) throw new Error(await r.text());
      const serverVersion = r.headers.get("X-Resource-Version") || version;
      const alignment = await r.json();
      if (!isCurrentLoad()) return;
      state.alignment = alignment;
      if (window.m2vCache && taskId) {
        window.m2vCache.saveProject(uid, taskId, "alignment", state.alignment, serverVersion);
      }
    }

    // 检查是否有未保存的本地草稿
    if (window.m2vCache && taskId) {
      const draft = await window.m2vCache.getDraft(uid, taskId, "alignment");
      if (!isCurrentLoad()) return;
      if (draft && draft.data) {
        const draftTime = new Date(draft.savedAt).toLocaleTimeString();
        const restore = confirm(`检测到您在此设备上有未保存的本地草稿 (保存于 ${draftTime})。\n是否恢复该草稿？`);
        if (restore) {
          state.alignment = draft.data;
          markDirty();
          status(`已恢复本地草稿 (${draftTime})`);
        } else {
          await window.m2vCache.clearDraft(uid, taskId, "alignment");
        }
      }
    }

    updateAudioAnalysisSummary();
  } catch (e) {
    if (!isCurrentLoad()) return;
    status((window.t ? t("msg_align_load_failed") : "Failed to load alignment data: ") + e, true);
    state.alignment = null;
    return;
  }

  // 1. 立即优先渲染歌词与分镜面板 (零等待秒级呈现)
  if (window.onSongLoaded) window.onSongLoaded();
  status(window.t ? t("msg_lyrics_ready", null, {count: state.alignment.lines.length}) : `Lyrics ready (${state.alignment.lines.length} lines), loading audio waveforms…`);

  // 2. 并行异步下载人声与伴奏音轨 (耗时缩减 50%)
  const tracks = file.audio_tracks || {};
  const vocalsUrl = formatAudioEndpoint(tracks.vocals);
  const instUrl = formatAudioEndpoint(tracks.instrumental);
  const origUrl = formatAudioEndpoint(file.audio_path);

  const primaryUrl = vocalsUrl || origUrl;
  const primaryTrackKey = tracks.vocals || file.audio_path;
  const primaryTrackType = tracks.vocals ? "vocals" : "original";
  const primaryTitleKey = tracks.vocals ? "track_vocals" : "track_orig";
  const primaryTitle = vocalsUrl ? (window.t ? t("track_vocals") : "🎤 Vocals") : (window.t ? t("track_orig") : "🎵 Original");
  const instTitle = window.t ? t("track_inst") : "🎸 Instrumental";

  if (dom.trackVocals) dom.trackVocals.classList.remove("muted");
  if (dom.trackInst) dom.trackInst.classList.remove("muted");

  const loadTasks = [];
  if (primaryUrl && ws) {
    setTrackLoadingState("vocals", true, primaryTitle, null, primaryTitleKey);
    loadTasks.push(
      loadEditorAudio(ws, primaryTrackKey, taskId, primaryTrackType, version)
        .then(() => {
          vocalsReady = true;
          setTrackLoadingState("vocals", false, primaryTitle, null, primaryTitleKey);
        })
        .catch((e) => {
          status((window.t ? t("msg_vocals_load_failed") : "Failed to load vocals track: ") + e, true);
          setTrackLoadingState("vocals", false, primaryTitle, true, primaryTitleKey);
        })
    );
  }
  if (instUrl && wsInst) {
    if (dom.trackInst) dom.trackInst.classList.remove("hidden");
    setTrackLoadingState("instrumental", true, instTitle);
    loadTasks.push(
      loadEditorAudio(wsInst, tracks.instrumental, taskId, "instrumental", version)
        .then(() => {
          instReady = true;
          setTrackLoadingState("instrumental", false, instTitle);
        })
        .catch((e) => {
          status((window.t ? t("msg_inst_load_failed") : "Failed to load instrumental track: ") + e, true);
          setTrackLoadingState("instrumental", false, instTitle, true);
        })
    );
  } else {
    if (dom.trackInst) dom.trackInst.classList.add("hidden");
    setTrackLoadingState("instrumental", false, instTitle);
  }

  Promise.allSettled(loadTasks).then(() => {
    if (state.currentFile !== file) return;
    if ((primaryUrl && !vocalsReady) || (instUrl && !instReady)) {
      status(window.t ? t("msg_tracks_partial_failure") : "Lyrics loaded, but some audio tracks could not load. Please retry.", true);
      return;
    }
    const trackInfo = [
      vocalsUrl ? (window.t ? t("msg_track_vocals") : "人声") : null,
      instUrl ? (window.t ? t("msg_track_inst") : "伴奏") : null,
      (!vocalsUrl && origUrl) ? (window.t ? t("msg_track_orig") : "原声") : null
    ].filter(Boolean).join("+");
    const msg = window.t
      ? t("msg_all_ready", null, { name: file.name, count: state.alignment.lines.length, tracks: trackInfo || t("msg_track_none") })
      : `✅ 全部就绪: ${file.name} (${state.alignment.lines.length} 行, 音轨: ${trackInfo || "无"})`;
    status(msg);
    document.title = `${file.name} — ${window.t ? t("app_title") : "M2V"}`;
  });
}

window.loadSongFile = async function(songId) {
  if (!songId) return;
  if (!state.allFiles || state.allFiles.length === 0) {
    await loadFileList();
  }
  const idx = state.allFiles.findIndex(f => (f.task_id === songId || f.id === songId || f.name === songId));
  if (idx >= 0 && idx !== (dom.songSelect ? Number(dom.songSelect.value) : -1)) {
    await loadSong(idx);
  }
};

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
    alert(window.t ? t("msg_enter_valid_url") : "请输入有效的 Suno / 网易云歌曲链接、iframe 代码或歌曲 ID");
    return;
  }

  // 云端模式下的登录凭据前置检查
  if (isCloudMode()) {
    const token = localStorage.getItem("m2v_token");
    if (!token) {
      if (window.m2vAuth?.loginWithGoogle) {
        const proceed = confirm("Sign in with Google to keep your projects private and align this song?");
        if (proceed) {
          try {
            await editorLogin();
            updateAuthUi();
          } catch (authErr) {
            alert("Sign-in cancelled or failed: " + authErr.message);
            return;
          }
        } else {
          return;
        }
      } else {
        alert("Sign in on the home page before importing a song.");
        return;
      }
    }
  }

  if (btn) btn.disabled = true;
  if (prog) prog.style.display = "block";

  const separateVocals = true;
  const useGpu = true;
  const importLang = "auto";

  const isNetEase = url.includes("163.com") || url.includes("163cn.tv") || url.includes("<iframe") || /^\d{5,}$/.test(url);
  let importSec = 0;
  const updateProgressMessage = (customMsg) => {
    let stage = customMsg || (isNetEase
      ? (window.t ? t("msg_netease_extracting") : "正在从网易云音乐提取歌曲、LRC 歌词与音频...")
      : (window.t ? t("msg_suno_extracting") : "正在从 Suno 提取歌曲信息与歌词..."));
    if (!customMsg && importSec > 5) {
      stage = separateVocals
        ? (window.t ? t("msg_aligning_vocals") : "正在进行人声与伴奏分离及时间轴对齐...")
        : (window.t ? t("msg_aligning_direct") : "正在进行原曲词级时间轴对齐 (WhisperX)...");
    }
    if (progText) {
      const elapsedText = window.currentLocale === "en" ? `(elapsed ${importSec}s)` : `(已耗时 ${importSec}s)`;
      progText.textContent = `${stage} ${elapsedText}`;
    }
  };
  updateProgressMessage();
  const importTimer = setInterval(() => {
    importSec++;
    updateProgressMessage();
  }, 1000);

  try {
    if (isCloudMode()) {
      // ─────────────────────────────────────────────
      // 云端 SaaS 模式：调用 /api/tasks/from-suno
      // 默认 ass_only: true (首步只导入对齐，不生成视频)
      // ─────────────────────────────────────────────
      const res = await apiFetch("/api/tasks/from-suno", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          suno_url: url,
          ass_only: true,
          skip_separation: !separateVocals,
          language: importLang,
        }),
      });

      const resText = await res.text();
      let initData;
      try {
        initData = JSON.parse(resText);
      } catch (_) {
        throw new Error("云端网关响应异常: " + resText.slice(0, 100));
      }
      if (!res.ok) {
        throw new Error(initData.detail || "创建任务失败");
      }

      const taskId = initData.task_id;
      status(initData.message || `⏳ 正在读取任务 (${taskId.slice(0, 8)}…)`);

      // 轮询任务完成
      let pollTask = null;
      while (true) {
        await new Promise((r) => setTimeout(r, 1500));
        let pollRes;
        try {
          pollRes = await apiFetch(`/api/tasks/${taskId}`);
        } catch (e) {
          continue;
        }
        if (!pollRes.ok) {
          if (pollRes.status === 401) throw new Error("Your session expired. Please sign in again.");
          continue;
        }
        pollTask = await pollRes.json();
        const step = pollTask.current_step || "processing";
        const progress = pollTask.progress || 0;
        let stepText = "正在处理";
        if (step === "separating") stepText = "正在进行人声与伴奏高保真分离 (ZeroGPU)";
        else if (step === "aligning") stepText = "正在进行词级时间轴对齐 (WhisperX)";
        else if (step === "subtitle") stepText = "正在生成 ASS 动效字幕";
        else if (step === "analyzing") stepText = "正在分析原曲节拍与音频特征";

        updateProgressMessage(`${stepText} [${progress}%]`);

        if (pollTask.status === "completed" || pollTask.alignment_json_key) {
          break;
        }
        if (pollTask.status === "failed") {
          throw new Error(pollTask.error_message || "云端任务执行失败");
        }
      }

      if (dom.sunoModal) dom.sunoModal.style.display = "none";
      if (input) input.value = "";
      const songTitle = pollTask.song_title || pollTask.title || "歌曲";
      status(window.t ? t("msg_import_success", null, { title: songTitle }) : `🎉 导入成功: ${songTitle}`);

      // 刷新列表并自动定位加载该歌曲
      await loadFileList(songTitle);
      const songIdx = state.allFiles.findIndex((f) => f.task_id === taskId);
      if (songIdx >= 0) {
        await loadSong(songIdx);
      }
      return;
    }

    // ─────────────────────────────────────────────
    // 单机本地模式：调用 /api/suno/import
    // ─────────────────────────────────────────────
    const res = await apiFetch("/api/suno/import", {
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
          const pollRes = await apiFetch(`/api/suno/task_status?task_id=${encodeURIComponent(taskId)}`);
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
          const rawLines = task.lyrics.split("\n").filter(Boolean);
          status(window.t ? t("msg_lyrics_ready", null, { count: rawLines.length }) : `📝 已提前获取《${task.title}》歌词，后台正在进行时间轴对齐...`);
          const listEl = document.getElementById("lyrics-list");
          if (listEl) {
            const previewHeader = window.currentLocale === "en"
              ? `✨ Lyrics parsed for "${escHtml(task.title)}" (${rawLines.length} lines), aligning in background:`
              : `✨ 已提前解析《${escHtml(task.title)}》(${rawLines.length} 行歌词)，后台正在进行字级时间轴对齐：`;
            listEl.innerHTML = `<div style="padding: 10px 14px; font-size: 11px; color: #10b981; background: rgba(16,185,129,0.08); border-bottom: 1px solid var(--border); border-radius: 4px 4px 0 0;">${previewHeader}</div>` +
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
    status(window.t ? t("msg_import_success", null, { title: data.title }) : `🎉 导入成功: ${data.title}`);
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
    const isNetEase = rawUrl.includes("163.com") || rawUrl.includes("163cn.tv") || rawUrl.includes("<iframe") || /^\d{5,}$/.test(rawUrl);
    status(isNetEase ? "⏳ [1/2] 正在连接网易云音乐解析歌曲音频..." : "⏳ [1/2] 正在连接 Suno 解析歌曲信息与歌词...");
    let dlUrl = `/api/suno/download_mp3?url=${encodeURIComponent(rawUrl)}`;
    const token = localStorage.getItem("m2v_token");
    if (token) dlUrl += `&token=${encodeURIComponent(token)}`;
    dlUrl = getApiUrl(dlUrl);
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
    status(window.t ? t("msg_downloading_mp3", null, { song: songName }) : `正在下载《${songName}》原曲 MP3...`);

    let url;
    if (state.currentFile.is_saas || state.currentFile.task_id) {
      url = `/api/tasks/${state.currentFile.task_id}/download/mp3`;
    } else {
      url = `/api/download/original_mp3?song=${encodeURIComponent(songName)}&json_path=${encodeURIComponent(jsonPath)}`;
    }
    const token = localStorage.getItem("m2v_token");
    if (token) url += (url.includes("?") ? "&" : "?") + `token=${encodeURIComponent(token)}`;
    url = getApiUrl(url);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${songName}.mp3`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => status(window.t ? t("msg_download_triggered", null, { song: songName }) : `已触发下载: ${songName}.mp3`), 800);
    return;
  }

  alert(window.t ? t("msg_enter_valid_url") : "请在左上方输入框粘贴 Suno 歌曲链接，或者在下拉列表中选择已导入的项目！");
}
window.downloadOriginalAudio = downloadOriginalAudio;


// ---------------------------------------------------------------------------
// Save Alignment (Pydantic v2 Backend)
// ---------------------------------------------------------------------------
async function saveAlignment() {
  if (!state.currentFile || !state.alignment) return false;
  status(window.t ? t("msg_saving") : "保存中…");
  try {
    let r;
    if (state.currentFile.is_saas || state.currentFile.task_id) {
      r = await apiFetch(`/api/editor/tasks/${state.currentFile.task_id}/align`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.alignment),
      });
    } else {
      r = await apiFetch("/api/alignment?path=" + encodeURIComponent(state.currentFile.json_path), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.alignment),
      });
    }
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
      return false;
    } else {
      state.dirty = false;
      const newVersion = j.version || String(Date.now());
      if (state.currentFile) {
        state.currentFile.version = newVersion;
      }
      const uid = window.m2vCache ? window.m2vCache.getCurrentUid() : null;
      const taskId = state.currentFile?.task_id || state.currentFile?.id;
      if (window.m2vCache && taskId) {
        window.m2vCache.saveProject(uid, taskId, "alignment", state.alignment, newVersion);
        window.m2vCache.clearDraft(uid, taskId, "alignment");
      }
      document.title = (state.currentFile?.name || "M2V") + " — " + (window.t ? t("app_title") : "编辑器");
      status(window.t ? t("msg_saved") : "✅ 已保存");
      return true;
    }
  } catch (e) {
    status((window.t ? t("msg_save_failed") : "保存失败: ") + e, true);
    return false;
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
    let r;
    if (state.currentFile.is_saas || state.currentFile.task_id) {
      r = await apiFetch(`/api/editor/tasks/${state.currentFile.task_id}/regen`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: mode }),
      });
    } else {
      r = await apiFetch("/api/regen", {
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
    }
    const j = await r.json();
    if (!r.ok) {
      status("生成失败: " + (j.detail || JSON.stringify(j)), true);
    } else {
      status(mode === "video" ? "✅ 视频已生成: " + (j.video_path || "已保存至任务") : "✅ ASS 已生成: " + (j.ass_path || "已保存至任务"));
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
  if (!state.undoStack.length) { status(window.t ? t("msg_no_undo") : "无可撤销操作"); return; }
  state.redoStack.push(JSON.stringify(state.alignment));
  state.alignment = JSON.parse(state.undoStack.pop());
  if (window.onAlignmentChanged) window.onAlignmentChanged();
  markDirty();
  status(window.t ? t("msg_undone") : "已撤销");
}

function redo() {
  if (!state.redoStack.length) { status(window.t ? t("msg_no_redo") : "无可重做操作"); return; }
  state.undoStack.push(JSON.stringify(state.alignment));
  state.alignment = JSON.parse(state.redoStack.pop());
  if (window.onAlignmentChanged) window.onAlignmentChanged();
  markDirty();
  status(window.t ? t("msg_redone") : "已重做");
}

let draftDebounceTimer = null;
function scheduleDraftSave() {
  if (!window.m2vCache || !state.currentFile || !state.alignment) return;
  const taskId = state.currentFile.task_id || state.currentFile.id;
  if (!taskId) return;
  if (draftDebounceTimer) clearTimeout(draftDebounceTimer);
  draftDebounceTimer = setTimeout(() => {
    const uid = window.m2vCache.getCurrentUid();
    window.m2vCache.saveDraft(uid, taskId, "alignment", state.alignment);
    console.log(`[m2vCache] 草稿自动保存已同步 (task=${taskId})`);
  }, 1200);
}

function markDirty() {
  state.dirty = true;
  document.title = "● " + (state.currentFile?.name || "M2V") + " — 编辑器";
  scheduleDraftSave();
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

function renderLineCharSpans(line, lineIdx) {
  if (!line || !line.words || line.words.length === 0) {
    return escHtml(line ? line.text : "");
  }

  const text = line.text || "";
  let searchIdx = 0;
  const spans = [];

  for (let wi = 0; wi < line.words.length; wi++) {
    const w = line.words[wi];
    const wordStr = w.word || "";
    if (!wordStr) continue;

    let foundIdx = text.indexOf(wordStr, searchIdx);
    if (foundIdx === -1) {
      foundIdx = text.toLowerCase().indexOf(wordStr.toLowerCase(), searchIdx);
    }

    const formatWordWithSyllables = (matchedStr) => {
      if (w.syllables && w.syllables.length > 1) {
        let sylSearch = 0;
        const sylSpans = [];
        for (let si = 0; si < w.syllables.length; si++) {
          const syl = w.syllables[si];
          const sText = syl.text || "";
          const sFound = matchedStr.toLowerCase().indexOf(sText.toLowerCase(), sylSearch);
          if (sFound !== -1) {
            if (sFound > sylSearch) sylSpans.push(escHtml(matchedStr.slice(sylSearch, sFound)));
            sylSpans.push(`<span class="lyric-syl" data-line="${lineIdx}" data-word="${wi}" data-syl="${si}" data-start="${syl.start}" data-end="${syl.end}">${escHtml(matchedStr.slice(sFound, sFound + sText.length))}</span>`);
            sylSearch = sFound + sText.length;
          } else {
            sylSpans.push(`<span class="lyric-syl" data-line="${lineIdx}" data-word="${wi}" data-syl="${si}" data-start="${syl.start}" data-end="${syl.end}">${escHtml(sText)}</span>`);
          }
        }
        if (sylSearch < matchedStr.length) sylSpans.push(escHtml(matchedStr.slice(sylSearch)));
        return `<span class="lyric-char has-syl" data-line="${lineIdx}" data-word="${wi}">${sylSpans.join("")}</span>`;
      }
      return `<span class="lyric-char" data-line="${lineIdx}" data-word="${wi}">${escHtml(matchedStr)}</span>`;
    };

    if (foundIdx !== -1) {
      if (foundIdx > searchIdx) {
        spans.push(escHtml(text.slice(searchIdx, foundIdx)));
      }
      const matchedText = text.slice(foundIdx, foundIdx + wordStr.length);
      spans.push(formatWordWithSyllables(matchedText));
      searchIdx = foundIdx + wordStr.length;
    } else {
      if (wi > 0) {
        const prevW = line.words[wi - 1].word || "";
        const needSpace = /[a-zA-Z0-9]/.test(prevW.slice(-1)) || /[a-zA-Z0-9]/.test(wordStr.slice(0, 1));
        if (needSpace) spans.push(" ");
      }
      spans.push(formatWordWithSyllables(wordStr));
    }
  }

  if (searchIdx < text.length) {
    spans.push(escHtml(text.slice(searchIdx)));
  }

  return spans.join("");
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
window.renderLineCharSpans = renderLineCharSpans;

window.addEventListener("DOMContentLoaded", () => {
  // Remove obsolete URL history; saved projects are the source of song history.
  try { localStorage.removeItem("suno_url_history_v1"); } catch (_) {}
  updateAuthUi();
  setupEditorAuth();

  // 开发者调试模式初始化
  checkAndApplyDevMode();

  // 连续点击 3 次左上角标题切换显隐
  let clickCount = 0;
  let clickTimer = null;
  const titleEl = document.querySelector("header h1");
  if (titleEl) {
    titleEl.style.cursor = "pointer";
    titleEl.title = window.t ? t("header_title_title") : "三击标题可显示/隐藏开发者调试选项（音频分析、分镜制作）";
    titleEl.addEventListener("click", () => {
      clickCount++;
      clearTimeout(clickTimer);
      if (clickCount >= 3) {
        window.toggleDevMode();
        clickCount = 0;
      } else {
        clickTimer = setTimeout(() => { clickCount = 0; }, 500);
      }
    });
  }
});

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
});

window.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("btn-analyze-audio");
  if (!button) return;
  button.addEventListener("click", async () => {
    if (!state.currentFile || !state.alignment) return status(window.t ? t("msg_select_song_first") : "请先选择歌曲", true);
    const song = state.currentFile;
    button.disabled = true;
    try {
      status(window.t ? t("msg_analyzing_audio") : "正在分析原曲节拍、能量和频段变化…");
      const cloud = Boolean(song.is_saas || song.task_id);
      const response = await apiFetch(cloud ? `/api/editor/tasks/${song.task_id}/analyze` : "/api/audio/analyze", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(cloud ? {} : {json_path: song.json_path})});
      if (!response.ok) throw new Error(await response.text());
      const task = await response.json();
      let result;
      do {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const poll = await apiFetch(cloud ? `/api/editor/jobs/${task.task_id}` : "/api/audio/analyze/" + task.task_id);
        if (!poll.ok) throw new Error(await poll.text());
        result = await poll.json();
      } while (["running", "pending"].includes(result.status));
      if (!["done", "completed"].includes(result.status)) throw new Error(result.error || "分析失败");
      if (cloud) result = result.result;
      if (state.currentFile === song) {
        const updated = await apiFetch(cloud ? `/api/editor/tasks/${song.task_id}/align` : "/api/alignment?path=" + encodeURIComponent(song.json_path));
        if (!updated.ok) throw new Error(await updated.text());
        const project = await updated.json();
        // Retain unsaved lyric edits in the open editor.
        state.alignment.analysis = project.analysis;
        state.alignment.audio_path = project.audio_path;
        state.alignment.duration = project.duration;
        updateAudioAnalysisSummary();
      }
      const cacheNote = result.cache_hit ? (window.currentLocale === "en" ? " (cache)" : "（缓存）") : "";
      const bpmStr = result.bpm ? (result.bpm + " BPM") : (window.currentLocale === "en" ? "No stable BPM" : "未检测到稳定节拍");
      status(window.t ? t("msg_audio_analysis_done", null, { bpm: bpmStr, beats: result.beats, cache: cacheNote }) : `音频分析完成：${bpmStr}，${result.beats} 个拍点，100Hz 特征${cacheNote}；重拍和鼓点类别为估计值`);
    } catch (error) {
      status((window.t ? t("msg_audio_analysis_failed") : "音频分析失败：") + error.message, true);
    } finally { button.disabled = false; }
  });
});

function updateAudioAnalysisSummary() {
  const panel = document.getElementById("audio-analysis-summary");
  if (!panel) return;
  const analysis = state.alignment?.analysis;
  if (!analysis?.envelopes?.length) {
    panel.textContent = window.t ? t("audio_feat_not_analyzed_hint") : "音频特征尚未分析 · 点击“分析音频”即可补做，无需重新对齐歌词";
    return;
  }
  const bpmText = analysis.bpm ? (window.currentLocale === "en" ? `Est. ${analysis.bpm} BPM` : `估算 ${analysis.bpm} BPM`) : (window.currentLocale === "en" ? "No stable BPM" : "未检测到稳定节拍");
  panel.textContent = window.currentLocale === "en"
    ? `Audio features ready · ${analysis.duration.toFixed(1)}s · ${bpmText} · ${analysis.beats.length} beats · ${analysis.feature_rate_hz}Hz / ${analysis.envelopes.length} samples · Downbeats & drum types are estimates`
    : `音频特征已就绪 · ${analysis.duration.toFixed(1)} 秒 · ${bpmText} · ${analysis.beats.length} 个拍点 · ${analysis.feature_rate_hz}Hz / ${analysis.envelopes.length} 个采样点 · 重拍和鼓点类别为估计值`;
}

window.addEventListener("languagechange", () => {
  for (const [track, value] of trackLoadingStates) {
    setTrackLoadingState(track, value.isLoading, value.trackName, value.errorMsg, value.titleKey);
  }
  updateAudioAnalysisSummary();
  if (ws) updatePlayPauseBtn(ws.isPlaying());
  const titleEl = document.querySelector("header h1");
  if (titleEl && window.t) titleEl.title = t("header_title_title");
});

// ---------------------------------------------------------------------------
// 开发者模式控制器 (Dev / Debug Mode Controller)
// 默认不可见；可通过 URL 参数 (?debug=1 / ?dev=1 / ?mode=dev)、三击标题、快捷键 (Ctrl+Shift+D / Cmd+Shift+D) 切换
// ---------------------------------------------------------------------------
function checkAndApplyDevMode() {
  const params = new URLSearchParams(window.location.search);
  const isDev = params.has("dev") ||
                params.has("debug") ||
                params.get("dev") === "1" ||
                params.get("debug") === "1" ||
                params.get("mode") === "dev" ||
                localStorage.getItem("suno2mv_dev_mode") === "true";

  // 分析音频与分镜制作（Debug 模式，默认隐藏，三击标题显示）
  const analyzeBtn = document.getElementById("btn-analyze-audio");
  if (analyzeBtn) {
    analyzeBtn.style.display = isDev ? "inline-block" : "none";
  }
  const storyboardNav = document.getElementById("nav-storyboard");
  if (storyboardNav) {
    storyboardNav.style.display = isDev ? "inline-flex" : "none";
  }
  const audioSummary = document.getElementById("audio-analysis-summary");
  if (audioSummary) {
    audioSummary.style.display = isDev ? "block" : "none";
  }

  // 导入对齐与仅下 MP3 均为默认常驻可见操作按钮
  const quickMp3Btn = document.getElementById("btn-quick-download-mp3");
  if (quickMp3Btn) {
    quickMp3Btn.style.display = "inline-block";
  }
  const importBtn = document.getElementById("btn-start-suno-import");
  if (importBtn) {
    importBtn.style.display = "inline-block";
  }
  return isDev;
}

window.toggleDevMode = function(forceState) {
  const current = localStorage.getItem("suno2mv_dev_mode") === "true";
  const next = typeof forceState === "boolean" ? forceState : !current;
  localStorage.setItem("suno2mv_dev_mode", next ? "true" : "false");
  checkAndApplyDevMode();
  console.log(`[Suno2MV] 开发者调试模式已${next ? "开启" : "关闭"}`);
  if (typeof status === "function") {
    status(next
      ? (window.t ? t("msg_dev_enabled") : "🛠 已开启开发者调试模式（已显示音频分析、分镜制作）")
      : (window.t ? t("msg_dev_disabled") : "🛠 已隐藏开发者调试选项"));
  }
  return next;
};

// 快捷键 Ctrl+Shift+D / Cmd+Shift+D (Mac) 切换开发模式
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "D" || e.key === "d")) {
    e.preventDefault();
    window.toggleDevMode();
  }
});

// 页面加载完成后应用 Dev 状态
if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", checkAndApplyDevMode);
} else {
  checkAndApplyDevMode();
}

// 离开页面前确保脏数据已同步到本地草稿
window.addEventListener("beforeunload", () => {
  if (state.dirty && window.m2vCache && state.currentFile && state.alignment) {
    const taskId = state.currentFile.task_id || state.currentFile.id;
    const uid = window.m2vCache.getCurrentUid();
    window.m2vCache.saveDraft(uid, taskId, "alignment", state.alignment);
  }
});

