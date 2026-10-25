/* ==========================================================
   M2V Dashboard — 前端逻辑
   ========================================================== */

const DEFAULT_CLOUD_API = "https://lucazhou-suno2mv-api.hf.space";
const DEFAULT_LOCAL_API = "http://localhost:8000";

function getDefaultApi() {
  const isLocal = location.hostname === "localhost" || location.hostname === "127.0.0.1";
  return isLocal ? DEFAULT_LOCAL_API : DEFAULT_CLOUD_API;
}

function resolveApiBase() {
  // A backend-served workbench must never reuse another deployment’s API.
  if (window.M2V_API_BASE) return window.M2V_API_BASE.replace(/\/+$/, "");
  const isLocal = location.hostname === "localhost" || location.hostname === "127.0.0.1";
  let saved = (localStorage.getItem("m2v_api_base") || "").trim();

  const isStaticCloud =
    location.hostname === "mv.fovea.si" ||
    location.hostname.endsWith(".pages.dev") ||
    location.hostname.includes("fovea.si");

  // 若在非本地环境（线上生产），但 saved 包含 localhost/127.0.0.1，必须清除
  if (!isLocal && (saved.includes("localhost") || saved.includes("127.0.0.1"))) {
    console.warn("[M2V] 清除残留的本地 API 地址:", saved);
    localStorage.removeItem("m2v_api_base");
    saved = "";
  }

  // 若 saved 错误指向了静态站域名 (mv.fovea.si / pages.dev / 相对根路径)，静态站无法提供 API，必须清除
  if (
    saved &&
    ((isStaticCloud && (saved === location.origin || saved.includes(location.host))) ||
      saved === "/" ||
      saved === "" ||
      saved.includes("fovea.si") ||
      saved.includes("pages.dev"))
  ) {
    console.warn("[M2V] 清除错误的静态站 API 地址:", saved);
    localStorage.removeItem("m2v_api_base");
    saved = "";
  }

  if (saved) return saved.replace(/\/+$/, "");
  return getDefaultApi().replace(/\/+$/, "");
}

let API = resolveApiBase();
window.m2vWorkspaceApi = () => API;
console.log("[M2V] 当前有效 API 服务地址:", API);

// ── State ────────────────────────────────────────────────
let token = localStorage.getItem("m2v_token") || null;
let refreshToken = localStorage.getItem("m2v_refresh") || null;
let authProvider = localStorage.getItem("m2v_auth_provider") || null;
let currentUser = null;
let userLoadError = "";
let pollTimer = null;

function syncAuthCookie(activeToken) {
  if (activeToken) {
    const secureFlag = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `m2v_token=${encodeURIComponent(activeToken)}; path=/; max-age=2592000; SameSite=Lax${secureFlag}`;
  } else {
    document.cookie = "m2v_token=; path=/; max-age=0; SameSite=Lax";
  }
}

if (token) {
  syncAuthCookie(token);
}

// ── DOM Helpers ──────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── API 请求封装 ─────────────────────────────────────────

async function api(path, options = {}) {
  // 确保 API 始终有效且不指向静态站
  if (!API || API === location.origin || API.includes("fovea.si") || API.includes("pages.dev")) {
    API = resolveApiBase();
  }

  const headers = options.headers || {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.json) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  options.headers = headers;

  const url = `${API}${path}`;
  const res = await fetch(url, options);

  // 防护：如果返回的是 HTML 页面（例如纯静态前端未配置后端反向代理），避免 JSON 解析崩溃
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("text/html")) {
    console.error("[M2V] API 返回了 HTML 静态页面而非 JSON:", url, res.status);
    throw new Error(`Cannot connect to the backend: [${url}] returned an HTML page. Check the backend service.`);
  }

  if (res.status === 401) {
    // 尝试刷新 token (Firebase ID Token 优先，随后本地 refresh_token)
    const refreshed = await tryRefresh();
    if (refreshed) {
      headers["Authorization"] = `Bearer ${token}`;
      return fetch(`${API}${path}`, options);
    }
    logout();
    return res;
  }

  return res;
}

async function tryRefresh() {
  // 1. 若当前存在 Firebase 用户，使用 Firebase Web SDK 强制获取最新 ID Token
  const fbUser = typeof firebase !== "undefined" && firebase.auth ? firebase.auth().currentUser : null;
  if (authProvider === "firebase" || fbUser) {
    try {
      const newToken = fbUser ? await fbUser.getIdToken(true) : await window.m2vAuth?.getIdToken();
      if (newToken && (fbUser || newToken !== token)) {
        token = newToken;
        localStorage.setItem("m2v_token", token);
        syncAuthCookie(token);
        return true;
      }
    } catch (fbErr) {
      console.warn("[M2V] Firebase 令牌刷新失败:", fbErr);
    }
    // A Firebase session must never fall back to another account's local token.
    return false;
  }

  // 2. 本地开发账号使用 refresh_token 刷新
  if (refreshToken) {
    try {
      const res = await fetch(`${API}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (res.ok) {
        const data = await res.json();
        token = data.access_token;
        refreshToken = data.refresh_token;
        localStorage.setItem("m2v_token", token);
        localStorage.setItem("m2v_refresh", refreshToken);
        syncAuthCookie(token);
        return true;
      }
    } catch (e) { /* ignore */ }
  }
  return false;
}


// ======================================================================
// Auth
// ======================================================================

let isLoginMode = true;

function initAuth() {
  const form = $("#auth-form");
  const toggle = $("#auth-toggle");
  const googleBtn = $("#btn-google-login");

  if (googleBtn) {
    googleBtn.addEventListener("click", async () => {
      $("#auth-error").textContent = "";
      try {
        if (!window.m2vAuth) {
          throw new Error("Authentication is starting. Please try again shortly.");
        }
        const { user, idToken } = await window.m2vAuth.loginWithGoogle();
        token = idToken;
        authProvider = "firebase";
        refreshToken = null;
        localStorage.removeItem("m2v_refresh");
        localStorage.setItem("m2v_auth_provider", authProvider);
        localStorage.setItem("m2v_token", token);
        syncAuthCookie(token);
        const ok = await loadUser();
        if (ok) {
          showApp();
        } else {
          logout();
          throw new Error(userLoadError || "Account verification failed. Please try again.");
        }
      } catch (err) {
        console.error("Google 登录异常:", err);
        $("#auth-error").textContent = err.message || "Google sign-in failed. Please try again.";
      }
    });
  }

  $("#auth-reset-password")?.addEventListener("click", async () => {
    const email = $("#auth-email").value.trim();
    if (!email) { $("#auth-error").textContent = "Enter your email address first."; return; }
    try {
      await window.m2vAuth.resetPassword(email);
      $("#auth-error").textContent = "If an account exists for this email, you will receive a password reset email.";
    } catch (error) {
      $("#auth-error").textContent = window.m2vAuth?.errorMessage(error) || error.message;
    }
  });

  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    isLoginMode = !isLoginMode;
    updateAuthUI();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#auth-error").textContent = "";

    const email = $("#auth-email").value.trim();
    const password = $("#auth-password").value;
    const username = $("#auth-username").value.trim();

    try {
      if (!window.m2vAuth) throw new Error("Sign-in is unavailable. Please refresh and try again.");
      const result = isLoginMode
        ? await window.m2vAuth.loginWithEmail(email, password)
        : await window.m2vAuth.registerWithEmail(email, password, username);
      token = result.idToken;
      authProvider = "firebase";
      refreshToken = null;
      localStorage.removeItem("m2v_refresh");
      localStorage.setItem("m2v_auth_provider", authProvider);
      localStorage.setItem("m2v_token", token);
      syncAuthCookie(token);
      if (await loadUser()) showApp();
      else throw new Error(userLoadError || "Unable to load your account. Please try again.");
    } catch (error) {
      $("#auth-error").textContent = window.m2vAuth?.errorMessage(error) || error.message;
    }
  });
}

function updateAuthUI() {
  if (isLoginMode) {
    $("#auth-title").textContent = "Sign in to Sonicflow Studio";
    $("#auth-submit").textContent = "Sign in";
    $("#auth-toggle-text").textContent = "New to Sonicflow Studio?";
    $("#auth-toggle").textContent = "Create an account";
    $("#auth-username").style.display = "none";
    $("#auth-username").required = false;
    $("#auth-password").autocomplete = "current-password";
  } else {
    $("#auth-title").textContent = "Create your Sonicflow account";
    $("#auth-submit").textContent = "Create account";
    $("#auth-toggle-text").textContent = "Already have an account?";
    $("#auth-toggle").textContent = "Sign in";
    $("#auth-username").style.display = "";
    $("#auth-username").required = true;
    $("#auth-password").autocomplete = "new-password";
  }
}

async function logout() {
  if (window.m2vCache && currentUser?.id) {
    try {
      await window.m2vCache.clearUserCache(currentUser.id);
    } catch (_) {}
  }
  token = null;
  refreshToken = null;
  currentUser = null;
  window.m2vBilling?.reset();
  exportSequence++;
  songSequence++; songPage=1; librarySongs.clear(); songPresentations.clear(); loadTasks.hasActive=false;
  if ($("#tasks-list")) $("#tasks-list").innerHTML="";
  for(const [id,value] of [["#song-search",""],["#song-view","active"],["#song-sort","recent"]])if($(id))$(id).value=value;
  if ($("#songs-status")) $("#songs-status").textContent="";
  if ($("#songs-page")) $("#songs-page").textContent="";
  if($("#version-trash-list"))$("#version-trash-list").innerHTML='';
  if($("#version-trash"))$("#version-trash").open=false;
  exportSongFilter=null;
  creditSequence++;
  if (creditExpiryTimer) clearTimeout(creditExpiryTimer);
  creditExpiryTimer = null;
  if ($("#credit-history")) $("#credit-history").innerHTML = "";
  if ($("#credit-summary")) $("#credit-summary").textContent = "";
  renderCreditOverview(null);
  renderJobsSequence++;
  if (renderJobsTimer) clearTimeout(renderJobsTimer);
  loadRenderJobs.hadActive = false;
  if ($("#render-jobs-list")) $("#render-jobs-list").innerHTML = "";
  closeExportPreview();
  if ($("#exports-list")) $("#exports-list").innerHTML = "";
  authProvider = null;
  localStorage.removeItem("m2v_token");
  localStorage.removeItem("m2v_user");
  localStorage.removeItem("m2v_refresh");
  localStorage.removeItem("m2v_auth_provider");
  syncAuthCookie(null);
  const lyricIframe = $("#iframe-lyric-editor");
  if (lyricIframe) {
    lyricIframe.src = "about:blank";
    if (lyricIframe.dataset) delete lyricIframe.dataset.loadedSongId;
  }
  const motionIframe = $("#iframe-motion-studio");
  if (motionIframe) {
    motionIframe.src = "about:blank";
    if (motionIframe.dataset) delete motionIframe.dataset.loadedSongId;
  }
  if (window.m2vStudios) {
    try {
      window.m2vStudios.lyric?.destroy();
      window.m2vStudios.motion?.destroy();
    } catch (_) {}
  }
  if (window.m2vMediaArbiter) {
    try {
      window.m2vMediaArbiter.clearAll();
    } catch (_) {}
  }
  window.m2vActiveSong = null;
  if (window.m2vStore) window.m2vStore.clearUser();
  try {
    if (typeof sessionStorage !== "undefined") {
      sessionStorage.removeItem("m2v_active_song");
    }
  } catch (_) {}
  if (window.m2vAuth && typeof window.m2vAuth.logout === "function") {
    try {
      await window.m2vAuth.logout();
    } catch (e) {
      console.warn("Firebase logout error:", e);
    }
  }
  showAuth();
}

function showAuth() {
  $("#auth-overlay").style.display = "flex";
  $("#app").style.display = "none";
  if (pollTimer) clearInterval(pollTimer);
}

window.openLyricStudio = function(songId, songTitle) {
  if(window.m2vCanOpenStudio&&!window.m2vCanOpenStudio("lyric",songId||window.m2vActiveSong?.id))return false;
  if (songId) {
    const title = songTitle || (window.librarySongs?.get(songId)?.title) || songId;
    window.m2vActiveSong = { id: songId, title: title };
    if (window.m2vStore) window.m2vStore.setActiveSong(window.m2vActiveSong);
    try {
      if (typeof sessionStorage !== "undefined") {
        sessionStorage.setItem("m2v_active_song", JSON.stringify(window.m2vActiveSong));
      }
    } catch (_) {}
  }
  const activeSong = window.m2vActiveSong || JSON.parse(sessionStorage.getItem("m2v_active_song") || "null");
  const titleEl = $("#lyric-bar-song-title");
  if (titleEl && activeSong?.title) titleEl.textContent = activeSong.title;
  const bcSong = $("#bc-song-name");
  const bcSep = $("#bc-sep-song");
  if (bcSong && activeSong?.title) {
    bcSong.textContent = "🎵 " + activeSong.title;
    if (bcSong.style) bcSong.style.display = "inline";
    if (bcSep && bcSep.style) bcSep.style.display = "inline";
  }
  if(window.m2vNavigateWorkspace)window.m2vNavigateWorkspace("lyric-editor-section");
  else location.hash = "lyric-editor-section";
};

window.openMotionStudio = function(songId, songTitle) {
  if(window.m2vCanOpenStudio&&!window.m2vCanOpenStudio("motion",songId||window.m2vActiveSong?.id))return false;
  if (songId) {
    const title = songTitle || (window.librarySongs?.get(songId)?.title) || songId;
    window.m2vActiveSong = { id: songId, title: title };
    if (window.m2vStore) window.m2vStore.setActiveSong(window.m2vActiveSong);
    try {
      if (typeof sessionStorage !== "undefined") {
        sessionStorage.setItem("m2v_active_song", JSON.stringify(window.m2vActiveSong));
      }
    } catch (_) {}
  }
  const activeSong = window.m2vActiveSong || JSON.parse(sessionStorage.getItem("m2v_active_song") || "null");
  const titleEl = $("#motion-bar-song-title");
  if (titleEl && activeSong?.title) titleEl.textContent = activeSong.title;
  const bcSong = $("#bc-song-name");
  const bcSep = $("#bc-sep-song");
  if (bcSong && activeSong?.title) {
    bcSong.textContent = "🎵 " + activeSong.title;
    if (bcSong.style) bcSong.style.display = "inline";
    if (bcSep && bcSep.style) bcSep.style.display = "inline";
  }
  if(window.m2vNavigateWorkspace)window.m2vNavigateWorkspace("motion-studio-section");
  else location.hash = "motion-studio-section";
};

function checkRedirect() {
  try {
    const params = new URLSearchParams(window.location.search);
    const redirect = params.get("redirect");
    if (
      redirect &&
      redirect.startsWith("/") &&
      !redirect.startsWith("//") &&
      redirect !== "/" &&
      redirect !== "/index.html"
    ) {
      if (redirect.startsWith("/lyric-editor")) {
        const songId = redirect.replace(/^\/lyric-editor\/?/, "");
        if (window.openLyricStudio) {
          window.openLyricStudio(songId);
          const cleanUrl = window.location.pathname + window.location.hash;
          window.history.replaceState({}, "", cleanUrl);
          return true;
        }
      } else if (redirect.startsWith("/motion-studio")) {
        const u = new URL(redirect, window.location.origin);
        const songId = u.searchParams.get("project") || u.searchParams.get("song") || "";
        if (window.openMotionStudio) {
          window.openMotionStudio(songId);
          const cleanUrl = window.location.pathname + window.location.hash;
          window.history.replaceState({}, "", cleanUrl);
          return true;
        }
      }
      window.location.href = redirect;
      return true;
    }
  } catch (e) {
    /* ignore */
  }
  return false;
}

function showApp() {
  $("#auth-overlay").style.display = "none";
  $("#app").style.display = "";
  loadTasks();
  loadExports();
  loadRenderJobs();
  loadCredits();
  window.m2vBilling?.refresh();
  startPolling();
  checkRedirect();
}

async function loadUser() {
  userLoadError = "";
  try {
    const res = await api("/api/auth/me");
    if (res.ok) {
      currentUser = await res.json();
      const displayName = currentUser.display_name || currentUser.username || "Account";
      if ($("#user-info")) $("#user-info").textContent = displayName;
      if ($("#user-email-label")) $("#user-email-label").textContent = currentUser.email || "Signed in";
      $("#user-credits").textContent = `${currentUser.credits} available`;
      if ($("#header-username-label")) $("#header-username-label").textContent = displayName;
      document.querySelectorAll?.(".avatar-circle")?.forEach?.(el => el.textContent = (displayName || "U").charAt(0).toUpperCase());
      if ($("#sidebar-credits-num")) $("#sidebar-credits-num").textContent = Number(currentUser.credits || 0).toLocaleString();
      if ($("#stat-val-available")) $("#stat-val-available").textContent = Number(currentUser.credits || 0).toLocaleString();
      if ($("#stat-val-monthly")) $("#stat-val-monthly").textContent = Number(currentUser.credits || 0).toLocaleString();
      localStorage.setItem("m2v_user", JSON.stringify({
        id: currentUser.id,
        displayName: displayName,
        email: currentUser.email,
      }));
      if (window.m2vStore) window.m2vStore.setUser(currentUser, authProvider);
      return true;
    }
    userLoadError = res.status >= 500
      ? `Unable to load account (HTTP ${res.status}). Check the backend database and service logs.`
      : `Account verification failed (HTTP ${res.status}). Please sign in again.`;
  } catch (e) {
    userLoadError = `Unable to load account: ${e.message}`;
    console.error("[M2V] 加载用户信息失败:", e);
  }
  currentUser = null;
  return false;
}


// ======================================================================
// Upload
// ======================================================================

function isDevMode() {
  const params = new URLSearchParams(location.search);
  let enabled = (params.get("dev") === "1" ||
                params.get("debug") === "1" ||
                params.get("mode") === "dev" ||
                (params.has("debug") && params.get("debug") !== "0" && params.get("debug") !== "false") ||
                (params.has("dev") && params.get("dev") !== "0" && params.get("dev") !== "false"));
  try {
    enabled ||= localStorage.getItem("suno2mv_dev_mode") === "true" ||
                localStorage.getItem("suno2mv_debug_mode") === "true";
  } catch (_) {}
  if (params.get("dev") === "0" || params.get("debug") === "0") {
    enabled = false;
  }
  return Boolean(enabled);
}

function applyDevMode(isDev) {
  const tabSuno = $("#tab-suno");
  const tabLocal = $("#tab-local");
  const sunoForm = $("#suno-form");
  const uploadForm = $("#upload-form");
  const modeTabs = $("#import-mode-tabs");
  const wrapLocalSunoUrl = $("#wrap-local-suno-url");

  if (isDev) {
    if (tabSuno) tabSuno.style.display = "";
    if (modeTabs) modeTabs.style.display = "";
    if (wrapLocalSunoUrl) wrapLocalSunoUrl.style.display = "";
  } else {
    if (tabSuno) tabSuno.style.display = "none";
    if (modeTabs) modeTabs.style.display = "none";
    if (wrapLocalSunoUrl) wrapLocalSunoUrl.style.display = "none";
    if (sunoForm) sunoForm.style.display = "none";
    if (uploadForm) uploadForm.style.display = "";
    if (tabLocal) tabLocal.classList.add("active");
    if (tabSuno) tabSuno.classList.remove("active");
  }

  if (typeof initApiConfig === "function") initApiConfig();

  document.querySelectorAll(".task-suno-link").forEach((el) => {
    el.style.display = isDev ? "" : "none";
  });
}

window.toggleDevMode = function(forceState) {
  const current = isDevMode();
  const next = typeof forceState === "boolean" ? forceState : !current;
  try {
    localStorage.setItem("suno2mv_dev_mode", next ? "true" : "false");
    localStorage.setItem("suno2mv_debug_mode", next ? "true" : "false");
  } catch (_) {}
  applyDevMode(next);
  if (typeof showStatus === "function") {
    showStatus(next
      ? "🛠 Debug mode enabled: link import & dev tools unlocked"
      : "🛠 Debug mode disabled: link import hidden");
  }
  try {
    document.querySelectorAll("iframe").forEach((frame) => {
      frame.contentWindow?.postMessage?.({ type: "toggle_dev_mode", enabled: next }, "*");
    });
  } catch (_) {}
  return next;
};
window.toggleDebugMode = window.toggleDevMode;

function setupTripleClickDebug(el) {
  if (!el) return;
  let count = 0;
  let timer = null;
  el.style.cursor = "pointer";
  el.title = "Triple-click to toggle debug mode (Ctrl+Shift+D)";
  el.addEventListener("click", () => {
    count++;
    clearTimeout(timer);
    if (count >= 3) {
      count = 0;
      window.toggleDevMode();
    } else {
      timer = setTimeout(() => { count = 0; }, 500);
    }
  });
}

// 快捷键 Ctrl+Shift+D / Cmd+Shift+D (Mac) 切换调试模式
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "D" || e.key === "d")) {
      e.preventDefault();
      window.toggleDevMode();
    }
  });

  // 监听跨页面/iframe 同步
  window.addEventListener("storage", (e) => {
    if (e.key === "suno2mv_dev_mode" || e.key === "suno2mv_debug_mode") {
      applyDevMode(isDevMode());
    }
  });
}

function initUpload() {
  applyDevMode(isDevMode());
  setupTripleClickDebug($(".workspace-brand"));
  setupTripleClickDebug($(".hero-title"));
  setupTripleClickDebug($("#auth-title"));

  const tabSuno = $("#tab-suno");
  const tabLocal = $("#tab-local");
  const sunoForm = $("#suno-form");
  const uploadForm = $("#upload-form");

  if (tabSuno && tabLocal && sunoForm && uploadForm) {
    tabSuno.addEventListener("click", () => {
      tabSuno.classList.add("active");
      tabLocal.classList.remove("active");
      sunoForm.style.display = "";
      uploadForm.style.display = "none";
    });
    tabLocal.addEventListener("click", () => {
      tabLocal.classList.add("active");
      tabSuno.classList.remove("active");
      uploadForm.style.display = "";
      sunoForm.style.display = "none";
    });
  }

  // 1. Suno 链接直接生成
  if (sunoForm) {
    sunoForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const sunoUrl = $("#input-suno-url").value.trim();
      const songTitle = $("#input-suno-title").value.trim();
      if (!sunoUrl) return;

      const btn = $("#btn-suno-submit");
      btn.disabled = true;
      btn.textContent = "⏳ Importing Suno song and audio…";

      try {
        const payload = {
          suno_url: sunoUrl,
          song_title: songTitle || undefined,
          language: $("#suno-opt-lang").value,
          skip_separation: $("#suno-opt-skip-sep").checked,
          ass_only: true,
          beat_effects: $("#suno-opt-beat") ? $("#suno-opt-beat").checked : true,
        };

        const res = await api("/api/tasks/from-suno", {
          method: "POST",
          json: payload,
        });

        if (res.ok) {
          const data = await res.json();
          showStatus(data.message || `✅ Project created: ${data.task_id.slice(0, 8)}…`);
          sunoForm.reset();
          loadTasks();
          connectProgressWS(data.task_id);
          loadCredits();
        } else {
          const err = await res.json();
          showStatus(`❌ ${err.detail || "Unable to create project"}`, true);
        }
      } catch (err) {
        showStatus(`❌ ${err.message || "Network error"}`, true);
      } finally {
        btn.disabled = false;
        btn.textContent = "⚡ Import & align lyrics";
      }
    });
  }

  // 2. 本地文件上传
  if (uploadForm) {
    uploadForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const mp3File = $("#file-mp3").files[0];
      const lyricsFile = $("#file-lyrics").files[0];
      if (!mp3File || !lyricsFile) return;

      const btn = $("#btn-upload");
      btn.disabled = true;
      btn.textContent = "⏳ Uploading…";

      const form = new FormData();
      form.append("mp3", mp3File);
      form.append("lyrics", lyricsFile);

      // Query params
      const params = new URLSearchParams();
      params.set("language", $("#opt-lang").value);
      params.set("ass_only", "true");
      if ($("#opt-skip-sep").checked) params.set("skip_separation", "true");
      if ($("#opt-beat") ? $("#opt-beat").checked : true) params.set("beat_effects", "true");

      const localSongTitle = $("#local-song-title")?.value.trim();
      const localSunoUrl = $("#local-suno-url")?.value.trim();
      if (localSongTitle) params.set("song_title", localSongTitle);
      if (localSunoUrl) params.set("suno_url", localSunoUrl);

      try {
        const res = await api(`/api/upload?${params}`, {
          method: "POST",
          body: form,
        });

        if (res.ok) {
          const data = await res.json();
          showStatus(`✅ Project created: ${data.task_id.slice(0, 8)}…`);
          uploadForm.reset();
          loadTasks();
          loadCredits();
          // 连接 WebSocket 监听进度
          connectProgressWS(data.task_id);
        } else {
          const err = await res.json();
          showStatus(`❌ ${err.detail || "Upload failed"}`, true);
        }
      } catch (e) {
        showStatus("❌ Network error", true);
      } finally {
        btn.disabled = false;
        btn.textContent = "⚡ Upload & align lyrics";
      }
    });
  }
}


// ======================================================================
// Tasks
// ======================================================================

let songPage = 1, songSequence = 0, songSearchTimer;
let librarySongs = new Map();
const songPresentations = new Map();

async function loadTasks(page = songPage) {
  if (!Number.isInteger(page)) page = songPage;
  const uid = currentUser?.id, sequence = ++songSequence;
  if (!uid) return;
  const query = new URLSearchParams({page:String(page),page_size:"12",
    q:$("#song-search")?.value || "",view:$("#song-view")?.value || "active",
    sort:$("#song-sort")?.value || "recent"});
  $("#songs-status").textContent = "Loading your songs…";
  try {
    const res = await api(`/api/songs?${query}`);
    if (!res.ok) throw Error(`Unable to load songs (HTTP ${res.status}). Please retry.`);
    const data = await res.json();
    if (sequence !== songSequence || currentUser?.id !== uid) return;
    if (!data.songs.length && data.total && page > 1) return loadTasks(page-1);
    songPage = page;
    librarySongs = new Map(data.songs.map(song => [song.id,song]));
    loadTasks.hasActive = data.active_count > 0;
    const list = $("#tasks-list");
    const expanded = new Set(Array.from(list.querySelectorAll('.song-card')).filter(card=>card.querySelector('details')?.open).map(card=>card.id));
    list.innerHTML = data.songs.map(renderSong).join("");
    void loadSongPresentations(data.songs,uid,sequence);
    list.querySelectorAll('.song-card').forEach(card=>{if(expanded.has(card.id))card.querySelector('details').open=true;});
    $("#tasks-empty").style.display = data.songs.length ? "none" : "";
    $("#songs-status").textContent = `${data.total} ${data.total===1?"song":"songs"} in this view · ${data.total_songs} in your library`;
    $("#songs-page").textContent = `Page ${page} of ${Math.max(1,Math.ceil(data.total/12))}`;
    $("#songs-prev").disabled = page <= 1;
    $("#songs-next").disabled = page*12 >= data.total;
    list.querySelectorAll("[data-action]").forEach(btn=>btn.addEventListener("click",handleTaskAction));
    list.querySelectorAll("[data-song-action]").forEach(btn=>btn.addEventListener("click",()=>handleSongAction(btn)));
  } catch (error) {
    if (sequence === songSequence && currentUser?.id === uid) $("#songs-status").textContent = error.message;
  }
}

function renderSong(song) {
  const id=escapeHtml(song.id), current=song.current_task_id;
  const labels={pending:"Import queued",processing:"Aligning lyrics",completed:"Ready to edit",failed:song.current_task_id?"Latest import failed · saved version available":"Import failed"};
  const versions=song.versions.map(v=>{
    const ready=v.editable;
    return `<div class="song-version"><div><strong>${escapeHtml(v.title)}</strong> <span class="badge">${escapeHtml(v.status)}</span>${v.id===current?' <span class="badge">Current</span>':''}</div>
      <p>${escapeHtml(new Date(v.updated_at).toLocaleString())} · ${v.export_count} videos</p>
      ${v.error?`<p class="error-text">${escapeHtml(v.error)}</p>`:''}
      <div class="task-actions">${ready?`<a class="btn btn-sm" href="/lyric-editor/${encodeURIComponent(v.id)}" data-action="open-studio" data-studio="lyric" data-task-id="${encodeURIComponent(v.id)}" data-song-id="${id}">Open lyrics</a><button class="btn btn-sm btn-outline" data-song-action="current" data-song="${id}" data-version="${escapeHtml(v.id)}">Use this version</button>`:''}
      ${ready?`<button class="btn btn-sm btn-outline" data-action="download" data-task="${escapeHtml(v.id)}" data-type="alignment">Download JSON</button>`:''}
      ${v.has_ass?`<button class="btn btn-sm btn-outline" data-action="download" data-task="${escapeHtml(v.id)}" data-type="ass">Download ASS</button>`:''}
      ${v.has_video?`<button class="btn btn-sm btn-outline" data-action="download" data-task="${escapeHtml(v.id)}" data-type="mp4">Download video</button>`:''}
      <button class="btn btn-sm btn-outline" data-song-action="trash" data-song="${id}" data-version="${escapeHtml(v.id)}">Move to Trash</button></div></div>`;
  }).join('');
  return `<article class="song-card" id="song-${id}" data-status="${escapeHtml(song.status)}">
    <div class="song-heading"><span class="song-initial" aria-hidden="true">${escapeHtml((song.title||'♫').slice(0,1))}</span><div><h3>${escapeHtml(song.title)}</h3><span class="song-artist">${escapeHtml(song.artist||'')}</span><p>${song.version_count} ${song.version_count===1?"version":"versions"} · ${song.export_count} ${song.export_count===1?"video":"videos"}${song.archived?' · Archived':''}</p></div>
    <button class="song-star" data-song-action="star" data-song="${id}" aria-label="${song.starred?'Unfavorite':'Favorite'} song" aria-pressed="${song.starred}">${song.starred?'★':'☆'}</button></div>
    <p class="song-state">${escapeHtml(song.status==='completed'&&!current?'Import finished':labels[song.status]||song.status)}${song.status==='processing'?` · ${Math.max(0,Math.min(100,Number(song.progress)||0))}%`:''}</p>
    <p class="song-updated">Updated ${escapeHtml(new Date(song.updated_at).toLocaleDateString())}</p>
    <div class="task-actions">${current?`<a class="btn btn-primary btn-sm" href="/lyric-editor/${encodeURIComponent(current)}" data-action="open-studio" data-studio="lyric" data-task-id="${encodeURIComponent(current)}" data-song-id="${id}">Edit lyrics</a><a class="btn btn-sm btn-outline" href="/motion-studio?project=${encodeURIComponent(current)}" data-action="open-studio" data-studio="motion" data-task-id="${encodeURIComponent(current)}" data-song-id="${id}">Design video</a>`:''}
    ${song.export_count?`<button class="btn btn-sm btn-outline" data-song-action="exports" data-song="${id}">View videos</button>`:''}
    <button class="btn btn-sm btn-outline" data-song-action="archive" data-song="${id}">${song.archived?'Restore':'Archive'}</button></div>
    <details class="song-versions"><summary>Versions &amp; history (${song.version_count})</summary>${versions}</details></article>`;
}

async function handleSongAction(button) {
  const song=librarySongs.get(button.dataset.song), action=button.dataset.songAction, uid=currentUser?.id;
  if (!song || !uid) return;
  if (action === "exports") {
    closeExportPreview();
    exportSongFilter = song.export_task_ids || song.versions.map(v=>v.id);
    await loadExports(1);
    window.location.hash = "exports-section";
    $("#exports-section").scrollIntoView?.({behavior:"smooth"});
    return;
  }
  if(action==='trash'){
    if(!confirm('Move this lyric version to Trash? Finished videos will be kept. You can restore the version later.'))return;
    button.disabled=true;
    try{const res=await api(`/api/songs/versions/${encodeURIComponent(button.dataset.version)}/trash`,{method:'POST'});
      if(!res.ok)throw Error('Unable to move this version to Trash. Please retry.');
      if(currentUser?.id===uid){await loadTasks();await loadVersionTrash();await loadRenderJobs();await loadCredits();}
    }catch(error){if(currentUser?.id===uid)$("#songs-status").textContent=error.message;}
    finally{button.disabled=false;}
    return;
  }
  const changes=action==='star'?{starred:!song.starred}:action==='archive'?{archived:!song.archived}:{preferred_task_id:button.dataset.version};
  button.disabled=true;
  try {
    const res=await api(`/api/songs/${song.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(changes)});
    if(!res.ok)throw Error('Unable to update your song. Please retry.');
    if(currentUser?.id===uid)await loadTasks();
  }catch(error){if(currentUser?.id===uid)$("#songs-status").textContent=error.message;}
  finally{button.disabled=false;}
}

async function loadSongPresentations(songs,uid,sequence) {
  await Promise.allSettled(songs.map(async song=>{
    const task=song.current_task_id||song.latest_task_id;
    const key=uid+':'+task+':'+song.updated_at;
    try{
      let data=songPresentations.get(key);
      if(!data||data.until<Date.now()){
        const response=await api(`/api/songs/versions/${encodeURIComponent(task)}/presentation`);
        if(!response.ok)return;
        data={...await response.json(),until:Date.now()+12*60*1000};
        if(currentUser?.id!==uid)return;
        songPresentations.set(key,data);
      }
      if(currentUser?.id!==uid||sequence!==songSequence)return;
      const card=document.getElementById('song-'+song.id);if(!card)return;
      card.querySelector('.song-artist').textContent=data.artist||'';
      if(data.cover_url){
        const source=new URL(data.cover_url,API||location.origin);
        if(!/^https?:$/.test(source.protocol))return;
        const image=document.createElement('img');image.alt='';image.loading='lazy';image.referrerPolicy='no-referrer';image.src=source.href;
        image.onerror=()=>image.remove();card.querySelector('.song-initial').append(image);
      }
    }catch{/* Artwork is optional; never block the song library. */}
  }));
}

let trashSequence=0;
async function loadVersionTrash(){
 const uid=currentUser?.id, sequence=++trashSequence;if(!uid)return;
 try {
 const response=await api('/api/songs/trash/versions');if(!response.ok||currentUser?.id!==uid)return;
 const data=await response.json();if(currentUser?.id!==uid||sequence!==trashSequence)return;
 const list=$("#version-trash-list");list.innerHTML=data.versions.length?data.versions.map(v=>`<div class="song-version"><strong>${escapeHtml(v.title)}</strong><p>${escapeHtml(new Date(v.updated_at).toLocaleString())}</p><button class="btn btn-sm" data-restore-version="${escapeHtml(v.id)}">Restore version</button></div>`).join(''):'Trash is empty.';
 list.querySelectorAll('[data-restore-version]').forEach(button=>button.onclick=async()=>{
  button.disabled=true;
  try{const res=await api(`/api/songs/versions/${encodeURIComponent(button.dataset.restoreVersion)}/restore`,{method:'POST'});if(!res.ok)throw Error('Unable to restore version.');if(currentUser?.id===uid){await loadTasks();await loadVersionTrash();}}
  catch(error){if(currentUser?.id===uid)$("#songs-status").textContent=error.message;}finally{button.disabled=false;}
 });
 } catch {if(currentUser?.id===uid&&sequence===trashSequence)$("#version-trash-list").textContent='Unable to load Trash. Close and reopen to retry.';}
}

function initSongLibrary() {
  $("#version-trash")?.addEventListener('toggle',()=>{if($("#version-trash").open)void loadVersionTrash();});
  $("#song-search")?.addEventListener("input",()=>{clearTimeout(songSearchTimer);songSearchTimer=setTimeout(()=>loadTasks(1),250);});
  for(const id of ["#song-view","#song-sort"])$(id)?.addEventListener("change",()=>loadTasks(1));
  $("#songs-prev")?.addEventListener("click",()=>loadTasks(songPage-1));
  $("#songs-next")?.addEventListener("click",()=>loadTasks(songPage+1));
}

function renderTask(task) {
  const statusMap = {
    pending: "⏳ Queued",
    processing: "🔄 Processing",
    completed: "✅ Completed",
    failed: "❌ Failed",
  };

  const stepMap = {
    queued: "Queued",
    preprocessing: "Preparing lyrics",
    separating: "Separating vocals",
    aligning: "Aligning words",
    subtitle: "Generating subtitles",
    compositing: "Rendering video",
    done: "Done",
    error: "Error",
  };

  const statusText = statusMap[task.status] || task.status;
  const stepText = stepMap[task.current_step] || task.current_step;
  const date = new Date(task.created_at).toLocaleString("zh-CN");

  let progressBar = "";
  if (task.status === "processing") {
    progressBar = `
      <div class="progress-bar">
        <div class="progress-fill" style="width:${task.progress}%">${task.progress}%</div>
      </div>
      <span class="step-text">${stepText}</span>
    `;
  }

  let actions = "";
  if (task.status === "completed") {
    if (task.output_mp4_key) {
      actions += `<button class="btn btn-sm" data-action="download" data-task="${task.id}" data-type="mp4">📹 Download MP4</button>`;
    }
    if (task.output_ass_key || task.alignment_json_key) {
      actions += `<button class="btn btn-sm" data-action="download" data-task="${task.id}" data-type="ass">📄 Download ASS</button>`;
    }
    if (task.alignment_json_key) {
      actions += `<button class="btn btn-sm" data-action="download" data-task="${task.id}" data-type="alignment">📊 Download JSON</button>`;
      actions += `<a class="btn btn-sm" href="/lyric-editor/${encodeURIComponent(task.id)}" data-action="open-studio" data-studio="lyric" data-task-id="${encodeURIComponent(task.id)}" data-song-id="${encodeURIComponent(task.id)}">✏️ Edit lyrics</a>`;
    }
  }
  if (task.status === "failed" && task.error_message) {
    actions += `<span class="error-text" title="${escapeHtml(task.error_message)}">💬 View error</span>`;
  }
  actions += `<button class="btn btn-sm btn-danger" data-action="delete" data-task="${task.id}">🗑️</button>`;

  const displayTitle = task.song_title || task.title || "Untitled";
  const sunoLink = (task.suno_url && isDevMode())
    ? `<div class="task-suno-link"><a href="${escapeHtml(task.suno_url)}" target="_blank" rel="noopener noreferrer">🔗 Original song link</a></div>`
    : "";

  return `
    <div class="task-card" id="task-${task.id}" data-status="${task.status}">
      <div class="task-header">
        <strong class="task-title">🎵 ${escapeHtml(displayTitle)}</strong>
        <span class="task-status">${statusText}</span>
      </div>
      ${sunoLink}
      ${progressBar}
      <div class="task-meta">
        <span>Created: ${date}</span>
      </div>
      <div class="task-actions">${actions}</div>
    </div>
  `;
}

async function handleTaskAction(e) {
  const btn = e.currentTarget;
  const action = btn.dataset.action;
  const taskId = btn.dataset.task;

  if (action === "open-studio") {
    e.preventDefault();
    const studio = btn.dataset.studio;
    const songId = btn.dataset.songId || taskId;
    const task = decodeURIComponent(btn.dataset.taskId || taskId || "");
    const song = librarySongs?.get(songId);
    const title = song?.title || btn.dataset.songTitle || task;
    if (studio === "lyric" && window.openLyricStudio) {
      window.openLyricStudio(task, title);
    } else if (studio === "motion" && window.openMotionStudio) {
      window.openMotionStudio(task, title);
    }
    return;
  }

  if (action === "download") {
    const type = btn.dataset.type;
    const originalText = btn.textContent;
    btn.textContent = "Downloading...";
    btn.disabled = true;
    try {
      const res = await api(`/api/tasks/${taskId}/download/${type}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      const disposition = res.headers.get("content-disposition");
      let filename = `task_${taskId.slice(0, 8)}.${type === "alignment" ? "json" : type}`;
      if (disposition && disposition.includes("filename=")) {
        const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if (match && match[1]) {
          filename = match[1].replace(/['"]/g, "");
        }
      }
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      alert(`Download failed: ${err.message}`);
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  } else if (action === "delete") {
    if (!confirm("Delete this lyric version and its exported videos? Other versions of the song will be kept.")) return;
    const res = await api(`/api/tasks/${taskId}`, { method: "DELETE" });
    if (res.ok) loadTasks();
  }
}


// ======================================================================
// WebSocket Progress
// ======================================================================

function connectProgressWS(taskId) {
  const currentToken = token || localStorage.getItem("m2v_token") || "";
  let wsUrl = "";
  if (API) {
    try {
      const u = new URL(API, location.href);
      const wsProto = u.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${wsProto}//${u.host}/ws/tasks/${taskId}/progress`;
    } catch (e) {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${protocol}//${location.host}/ws/tasks/${taskId}/progress`;
    }
  } else {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    wsUrl = `${protocol}//${location.host}/ws/tasks/${taskId}/progress`;
  }
  if (currentToken) {
    wsUrl += `?token=${encodeURIComponent(currentToken)}`;
  }
  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      updateTaskProgress(data);
    } catch (e) { /* ignore */ }
  };

  ws.onclose = () => {
    // 任务完成后刷新列表
    setTimeout(loadTasks, 500);
    loadUser();  // 刷新配额
    loadCredits();
  };
}

function updateTaskProgress(data) {
  const card = $(`#task-${data.task_id}`);
  if (!card) {
    loadTasks();
    return;
  }

  const progressFill = card.querySelector(".progress-fill");
  if (progressFill) {
    progressFill.style.width = `${data.progress}%`;
    progressFill.textContent = `${data.progress}%`;
  }

  const stepText = card.querySelector(".step-text");
  if (stepText) {
    stepText.textContent = data.message || data.current_step;
  }

  if (data.current_step === "done" || data.current_step === "error") {
    setTimeout(loadTasks, 500);
    loadCredits();
  }
}


// ======================================================================
// Polling (fallback when WebSocket unavailable)
// ======================================================================

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    // 检查是否有进行中的任务
    const processing = document.querySelectorAll('[data-status="processing"], [data-status="pending"]');
    if (processing.length > 0 || loadTasks.hasActive) {
      await loadTasks();
    }
  }, 5000);
}


// ======================================================================
// Utils
// ======================================================================

function showStatus(msg, isError = false) {
  // 简单 toast
  const toast = document.createElement("div");
  toast.className = `toast ${isError ? "toast-error" : "toast-success"}`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}
window.showStatus = showStatus;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}


function initApiConfig() {
  const enabled = isDevMode();
  for (const selector of ["#api-config-login", "#btn-config-api-app"]) {
    const element = $(selector);
    if (element) element.style.display = enabled ? "" : "none";
  }
  if (!enabled) return;

  const updateLabel = () => {
    const cur = API;
    const el = $("#btn-config-api");
    const elApp = $("#btn-config-api-app");
    let label = "";
    try {
      const u = new URL(cur);
      label = `Service: ${u.host}`;
    } catch (e) {
      label = cur ? `Service: ${cur}` : "Not configured (click to set up)";
    }
    if (el) el.textContent = label;
    if (elApp) elApp.title = `Backend API: ${cur}`;
  };

  const configure = (e) => {
    e?.preventDefault();
    const current = localStorage.getItem("m2v_api_base") || API;
    const input = prompt(
      "Enter the Python backend API address:\n(Leave blank for the default: " + getDefaultApi() + ")",
      current
    );
    if (input !== null) {
      const trimmed = input.trim().replace(/\/+$/, "");
      if (trimmed) {
        localStorage.setItem("m2v_api_base", trimmed);
      } else {
        localStorage.removeItem("m2v_api_base");
      }
      location.reload();
    }
  };

  $("#btn-config-api")?.addEventListener("click", configure);
  $("#btn-config-api-app")?.addEventListener("click", configure);
  updateLabel();
}

// ======================================================================
// Init
// ======================================================================

document.addEventListener("DOMContentLoaded", async () => {
  initApiConfig();
  initSongLibrary();
  initExportLibrary();
  initCredits();
  initAuth();
  initUpload();

  // 退出与刷新按钮
  $("#btn-logout").addEventListener("click", logout);
  $("#btn-refresh").addEventListener("click", loadTasks);

  // 修改显示昵称
  const btnEditNickname = $("#btn-edit-nickname");
  if (btnEditNickname) {
    btnEditNickname.addEventListener("click", async () => {
      if (!currentUser) return;
      const currentName = currentUser.display_name || currentUser.username || "";
      const newName = prompt("Enter your display name (up to 64 characters):", currentName);
      if (newName === null) return;
      const trimmed = newName.trim();
      try {
        const res = await api("/api/auth/me", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display_name: trimmed }),
        });
        if (res.ok) {
          currentUser = await res.json();
          const displayName = currentUser.display_name || currentUser.username || "Account";
          if ($("#user-info")) $("#user-info").textContent = displayName;
          if ($("#header-username-label")) $("#header-username-label").textContent = displayName;
          document.querySelectorAll?.(".avatar-circle")?.forEach?.(el => el.textContent = (displayName || "U").charAt(0).toUpperCase());
          localStorage.setItem("m2v_user", JSON.stringify({
            id: currentUser.id,
            displayName: displayName,
            email: currentUser.email,
          }));
          alert("Display name updated.");
        } else {
          const err = await res.json().catch(() => ({}));
          alert("Unable to update display name: " + (err.detail || "Request failed"));
        }
      } catch (err) {
        alert("Unable to update display name: " + err.message);
      }
    });
  }

  // 复制插件登录凭据 Token
  const btnCopyToken = $("#btn-copy-plugin-token");
  if (btnCopyToken) {
    btnCopyToken.addEventListener("click", async () => {
      const activeToken = token || localStorage.getItem("m2v_token");
      if (!activeToken) {
        alert("Sign in before copying your extension token.");
        return;
      }
      try {
        await navigator.clipboard.writeText(activeToken);
        const originalText = btnCopyToken.textContent;
        btnCopyToken.textContent = "✅ Token copied";
        setTimeout(() => {
          btnCopyToken.textContent = originalText;
        }, 2000);
      } catch (err) {
        prompt("Copy your token:", activeToken);
      }
    });
  }

  // If we already have a cached token, reveal app immediately and verify in background
  if (token) {
    $("#app").style.display = "";
    $("#auth-overlay").style.display = "none";
  }

  // Firebase restores its session asynchronously; never trust an old cached ID token.
  if (window.m2vAuth?.ready) {
    await window.m2vAuth.ready;
    if (authProvider === "firebase") {
      token = await window.m2vAuth.getIdToken();
      if (token) localStorage.setItem("m2v_token", token);
      else localStorage.removeItem("m2v_token");
      syncAuthCookie(token);
    }
  }

  // 已登录？
  if (token) {
    try {
      await loadUser();
      if (currentUser) {
        showApp();
        return;
      }
    } catch (e) { /* token 失效 */ }
  }

  showAuth();
});


// Durable video library. Request media only after a user clicks Preview/Download.
let exportPage = 1;
let exportSongFilter = null;
let exportSequence = 0;
let exportPreviewSequence = 0;
let renderJobsSequence = 0;
let renderJobsTimer;
async function loadRenderJobs() {
  const uid = currentUser?.id, sequence = ++renderJobsSequence;
  if (renderJobsTimer) clearTimeout(renderJobsTimer);
  if (!uid) return;
  try {
    const response = await api("/api/editor/render-jobs");
    if (currentUser?.id !== uid || sequence !== renderJobsSequence) return;
    if (!response.ok) throw Error("Unable to load render progress. Refresh to retry.");
    const data = await response.json();
    if (currentUser?.id !== uid || sequence !== renderJobsSequence) return;
    const rows = data.jobs || [];
    const active = rows.some(row => ["queued", "running", "uploading"].includes(row.status));
    const labels = {queued:"Queued",running:"Rendering",uploading:"Uploading",failed:"Failed",interrupted:"Interrupted"};
    $("#render-jobs-list").innerHTML = rows.map(row => {
      const retryable = ["failed", "interrupted"].includes(row.status);
      const percent = Math.max(0, Math.min(100, Number(row.progress) || 0));
      const cost = Math.max(0, Number(row.credit_cost) || 0);
      return `<article class="task-card"><strong>${escapeHtml(row.title || "Untitled")}</strong><p>${escapeHtml(labels[row.status] || row.status)} · ${percent}% · Attempt ${Number(row.attempt) || 1}</p><progress max="100" value="${percent}" aria-label="Render progress"></progress><p>${escapeHtml(row.error || row.message || "")}</p>${retryable ? `<div class="export-actions"><button class="btn btn-sm" data-render-job="${escapeHtml(row.id)}" data-render-cost="${cost}" data-render-action="retry">Retry rendering${cost ? ` · ${cost} credits` : " · Free"}</button><button class="btn btn-sm btn-outline" data-render-job="${escapeHtml(row.id)}" data-render-action="dismiss">Dismiss</button></div>` : ""}</article>`;
    }).join("");
    // Refresh the completed library too: a job may finish in another browser.
    if (loadRenderJobs.hadActive) { await loadExports(); await loadCredits(); }
    if (currentUser?.id !== uid || sequence !== renderJobsSequence) return;
    loadRenderJobs.hadActive = active;
    if (active) renderJobsTimer = setTimeout(() => { if (currentUser?.id === uid) loadRenderJobs(); }, 5000);
  } catch (error) {
    if (currentUser?.id === uid && sequence === renderJobsSequence) $("#render-jobs-list").textContent = error.message;
  }
}
async function handleRenderAction(button) {
  const uid = currentUser?.id, id = button.dataset.renderJob, retry = button.dataset.renderAction === "retry";
  button.disabled = true;
  try {
    const response = await api(`/api/editor/jobs/${encodeURIComponent(id)}${retry ? "/retry" : ""}`, {method:retry ? "POST" : "DELETE", ...(retry ? {json:{accepted_cost:Math.max(0, Number(button.dataset.renderCost) || 0)}} : {})});
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || "Unable to update export job.");
    if (currentUser?.id !== uid) return;
    await loadRenderJobs();
    if (retry) await loadExports();
    if (retry) await loadCredits();
  } catch (error) {
    if (currentUser?.id === uid) $("#exports-status").textContent = error.message;
  } finally { button.disabled = false; }
}
async function trackImportedVideo(jobId) {
  const uid = currentUser?.id;
  if (!uid) return;
  try {
    const response = await api(`/api/editor/jobs/${encodeURIComponent(jobId)}`);
    if (currentUser?.id !== uid) return;
    if (!response.ok) throw Error(`Unable to check video export (HTTP ${response.status}).`);
    const job = await response.json();
    if (currentUser?.id !== uid) return;
    if (job.status === "completed") {
      showStatus("Video ready. Download it from My Exports.");
      await loadExports(1);
      return;
    }
    if (job.status === "failed") throw Error(job.error || "Video rendering failed. Your saved alignment is unchanged.");
    setTimeout(() => { if (currentUser?.id === uid) trackImportedVideo(jobId); }, 3000);
  } catch (error) {
    if (currentUser?.id === uid) showStatus(error.message, true);
  }
}
let currentPreviewExportId = null;
let lastLoadedExports = new Map();

function formatDuration(sec) {
  if (!sec || isNaN(sec)) return "";
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? '0' : ''}${rem}`;
}

function closeExportPreview() {
  exportPreviewSequence++;
  currentPreviewExportId = null;
  const video = $("#export-preview-video");
  video?.pause?.(); video?.removeAttribute?.("src"); video?.load?.();
  if ($("#exports-preview")) $("#exports-preview").hidden = true;
}
async function loadExports(page = exportPage) {
  const sequence = ++exportSequence, uid = currentUser?.id;
  if (!uid || !$("#exports-list")) return;
  $("#exports-status").textContent = "Loading exports…";
  try {
    const filter = exportSongFilter?.length ? '&task_ids='+encodeURIComponent(exportSongFilter.join(',')) : '';
    const response = await api(`/api/exports?page=${page}&page_size=20${filter}`);
    if (!response.ok) throw Error(`Unable to load exports (HTTP ${response.status}).`);
    const data = await response.json();
    if (sequence !== exportSequence || currentUser?.id !== uid) return;
    exportPage = page;
    const rows = data.exports || [];
    lastLoadedExports = new Map(rows.map(r => [r.id, r]));
    $("#exports-list").innerHTML = rows.map(item => {
      const detail = item.details || {}, size = detail.size_bytes ? (detail.size_bytes < 1048576 ? Math.max(1, Math.round(detail.size_bytes / 1024)) + " KB" : (detail.size_bytes / 1048576).toFixed(1) + " MB") : "";
      const resolution = detail.resolution?.every(Boolean) ? detail.resolution.join(" × ") : "";
      const resPill = detail.resolution ? (detail.resolution[1] >= 1080 || detail.resolution[0] >= 1080 ? "1080p HD" : "720p") : "HD";
      const durationSec = Number(detail.duration) || 0;
      const durationFormatted = durationSec ? formatDuration(durationSec) : "";
      const kindLabel = ({lyric:"Lyric Video",poster:"Motion Studio",rhythm:"Rhythm Studio"})[item.kind] || "Video";
      const meta = [detail.recovered ? "Recovered" : "", kindLabel, resolution, durationSec ? durationSec.toFixed(1) + "s" : "", size, new Date(item.created_at).toLocaleString()].filter(Boolean).join(" · ");
      const safeTitle = escapeHtml(item.title || "Untitled");
      const gradientClass = item.kind === 'poster' ? 'gradient-poster' : item.kind === 'rhythm' ? 'gradient-rhythm' : 'gradient-lyric';

      return `<article class="task-card yt-video-card" data-export-id="${escapeHtml(item.id)}">
        <div class="yt-thumb-box" data-export="${escapeHtml(item.id)}" data-export-action="preview" role="button" tabindex="0" title="Click to preview video">
          <div class="yt-thumb-gradient ${gradientClass}">
            <div class="yt-thumb-art">
              <svg viewBox="0 0 48 48" class="yt-vinyl-svg" fill="none" stroke="currentColor">
                <circle cx="24" cy="24" r="21" stroke="rgba(255,255,255,0.25)" stroke-width="2"/>
                <circle cx="24" cy="24" r="14" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/>
                <circle cx="24" cy="24" r="7" stroke="rgba(255,255,255,0.4)" fill="rgba(255,255,255,0.1)"/>
                <circle cx="24" cy="24" r="2.5" fill="currentColor"/>
              </svg>
            </div>
            <div class="yt-play-hover-btn" aria-hidden="true">▶</div>
          </div>
          <span class="yt-badge-res">${resPill}</span>
          <span class="yt-badge-kind">${kindLabel}</span>
          ${durationFormatted ? `<span class="yt-badge-duration">${durationFormatted}</span>` : ""}
        </div>
        <div class="yt-card-info">
          <strong class="yt-card-title" title="${safeTitle}">${safeTitle}</strong>
          <p class="yt-card-meta">${escapeHtml(meta)}</p>
          <div class="export-actions yt-card-actions">
            <button class="btn btn-sm btn-yt-preview" data-export="${escapeHtml(item.id)}" data-export-action="preview">Preview</button>
            <button class="btn btn-sm btn-yt-download" data-export="${escapeHtml(item.id)}" data-export-action="download">Download MP4</button>
            <button class="btn btn-sm btn-outline btn-yt-delete" data-export="${escapeHtml(item.id)}" data-export-action="delete" title="Delete video">Delete video</button>
          </div>
        </div>
      </article>`;
    }).join("");
    if ($("#exports-clear-filter")) $("#exports-clear-filter").hidden = !exportSongFilter;
    $("#exports-status").textContent = data.total ? `${data.total} exports · Preview loads only when requested.` : "No exports yet. Export from Lyric Editor or Motion Studio, or find earlier exports.";
    $("#exports-page").textContent = `Page ${page}`;
    $("#exports-prev").disabled = page <= 1;
    $("#exports-next").disabled = page * 20 >= data.total;
  } catch (error) {
    if (sequence === exportSequence && currentUser?.id === uid) $("#exports-status").textContent = error.message;
  }
}
async function handleExportAction(button) {
  const id = button.dataset.export, action = button.dataset.exportAction, uid = currentUser?.id;
  const previewSequence = action === "preview" ? ++exportPreviewSequence : null;
  button.disabled = true;
  try {
    if (action === "delete") {
      if (!confirm("Delete this exported video? Your song and lyric alignment will be kept.")) return;
      const response = await api(`/api/exports/${id}`, {method:"DELETE"});
      if (!response.ok) throw Error("Unable to delete video. Please retry.");
      if (currentUser?.id !== uid) return;
      closeExportPreview();
      await loadExports(1);
      return;
    }
    const response = await api(`/api/exports/${id}/access?preview=${action === "preview"}`);
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || "Unable to access video.");
    if (currentUser?.id !== uid) return;
    const url = data.url.startsWith("/") ? API + data.url : data.url;
    if (action === "preview") {
      if (previewSequence !== exportPreviewSequence) return;
      currentPreviewExportId = id;
      const item = lastLoadedExports.get(id);
      if ($("#export-preview-title")) $("#export-preview-title").textContent = item?.title || "Video Preview";
      if ($("#export-preview-meta") && item) {
        const detail = item.details || {};
        const size = detail.size_bytes ? (detail.size_bytes < 1048576 ? Math.max(1, Math.round(detail.size_bytes / 1024)) + " KB" : (detail.size_bytes / 1048576).toFixed(1) + " MB") : "";
        const resolution = detail.resolution?.every(Boolean) ? detail.resolution.join(" × ") : "";
        const duration = detail.duration ? Number(detail.duration).toFixed(1) + "s" : "";
        $("#export-preview-meta").textContent = [({lyric:"Lyric Video",poster:"Motion Studio",rhythm:"Rhythm Studio"})[item.kind] || "Video", resolution, duration, size].filter(Boolean).join(" · ");
      }
      const dlBtn = $("#btn-preview-download");
      if (dlBtn) {
        if (!dlBtn.dataset) dlBtn.dataset = {};
        dlBtn.dataset.export = id;
        dlBtn.setAttribute?.("data-export", id);
      }
      if ($("#exports-preview")) $("#exports-preview").hidden = false;
      const video = $("#export-preview-video");
      if (video) video.src = url;
      video?.play?.()?.catch?.(() => {});
    } else {
      const link = document.createElement("a"); link.href = url; link.download = data.filename;
      document.body.appendChild(link); link.click(); link.remove();
    }
  } catch (error) {
    if (currentUser?.id === uid && (previewSequence === null || previewSequence === exportPreviewSequence)) $("#exports-status").textContent = error.message;
  } finally { button.disabled = false; }
}
function initExportLibrary() {
  $("#exports-clear-filter")?.addEventListener("click",()=>{exportSongFilter=null;loadExports(1);});
  $("#btn-refresh-exports")?.addEventListener("click", () => { loadExports(); loadRenderJobs(); });
  $("#render-jobs-list")?.addEventListener("click", event => {
    const button = event.target.closest("button[data-render-action]");
    if (button) void handleRenderAction(button);
  });
  $("#exports-prev")?.addEventListener("click", () => loadExports(exportPage - 1));
  $("#exports-next")?.addEventListener("click", () => loadExports(exportPage + 1));
  $("#btn-close-export-preview")?.addEventListener("click", closeExportPreview);
  $("#exports-preview")?.addEventListener("click", event => {
    if (event.target === $("#exports-preview")) closeExportPreview();
  });
  window.addEventListener?.("keydown", event => {
    if (event.key === "Escape" && !$("#exports-preview")?.hidden) closeExportPreview();
  });
  $("#btn-preview-download")?.addEventListener("click", () => {
    const id = $("#btn-preview-download")?.dataset.export || currentPreviewExportId;
    if (id) void handleExportAction({dataset: {export: id, exportAction: "download"}});
  });
  $("#exports-list")?.addEventListener("click", event => {
    const button = event.target.closest("button[data-export-action]") || event.target.closest(".yt-thumb-box[data-export-action]");
    if (button) void handleExportAction(button);
  });
  $("#btn-discover-exports")?.addEventListener("click", async event => {
    const button = event.currentTarget, uid = currentUser?.id;
    button.disabled = true; $("#exports-status").textContent = "Looking for earlier exports…";
    try {
      const response = await api("/api/exports/discover", {method:"POST"});
      if (!response.ok) throw Error("Recovery scan failed. Please retry.");
      const data = await response.json();
      if (currentUser?.id !== uid) return;
      await loadExports(1);
      $("#exports-status").textContent = `${data.added} earlier exports found. ${data.message}`;
    } catch(error) { if(currentUser?.id === uid) $("#exports-status").textContent = error.message; }
    finally {button.disabled = false;}
  });
}

let creditPage = 1;
let creditSequence = 0;
let creditExpiryTimer = null;
function creditRate(value) {
  return Number.isSafeInteger(value) && value >= 0 ? `${value} ${value === 1 ? 'credit' : 'credits'}` : 'Unavailable';
}
function renderCreditOverview(data) {
  const amount = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : '—';
  for (const [id, value] of [
    ['#stat-val-available', data?.available],
    ['#stat-val-monthly', data?.wallet?.subscription_available],
    ['#stat-val-permanent', data?.wallet?.permanent_available]
  ]) if ($(id)) $(id).textContent = amount(value);
  const pricing = data?.pricing;
  const motionRates = [pricing?.motion_export, pricing?.motion_webcodecs];
  let motion = 'Unavailable';
  if (motionRates.every(value => Number.isSafeInteger(value) && value >= 0)) {
    motion = motionRates[0] === motionRates[1] ? creditRate(motionRates[0]) : `${Math.min(...motionRates)}–${Math.max(...motionRates)} credits`;
  }
  for (const [id, text] of [
    ['#stat-val-alignment-cost', creditRate(pricing?.alignment)],
    ['#stat-val-motion-cost', motion]
  ]) if ($(id)) $(id).textContent = text;
  if ($('#credit-pricing')) $('#credit-pricing').textContent = pricing
    ? `Lyrics alignment: ${creditRate(pricing.alignment)} per import. Motion video export: ${motion} per video. Each selected video is charged separately. Review the exact cost before starting. Reusing an unchanged alignment and downloading an existing video are free.`
    : 'Usage costs are unavailable. Refresh before starting a new task.';
}

async function loadCredits(page = creditPage) {
  const uid = currentUser?.id, sequence = ++creditSequence;
  if (!uid) return;
  try {
    const response = await api(`/api/credits?page=${page}&page_size=20`);
    if (!response.ok) throw Error(`Unable to load credit history (HTTP ${response.status}).`);
    const data = await response.json();
    if (currentUser?.id !== uid || sequence !== creditSequence) return;
    creditPage = page;
    renderCreditOverview(data);
    const available = Number(data.available) || 0, reserved = Number(data.reserved) || 0;
    $("#credit-summary").textContent = `${available} available · ${reserved} reserved. Failed tasks return unused, unexpired credits.`;
    $("#user-credits").textContent = `${available} available`;
    if ($("#sidebar-credits-num")) $("#sidebar-credits-num").textContent = available.toLocaleString();
    if ($("#stat-val-available")) $("#stat-val-available").textContent = available.toLocaleString();
    if ($("#sidebar-credits-fill")) {
      const pct = Math.min(100, Math.max(0, Math.round((available / 3000) * 100)));
      $("#sidebar-credits-fill").style.width = pct + "%";
    }
    if (creditExpiryTimer) clearTimeout(creditExpiryTimer);
    creditExpiryTimer = null;
    if (data.monthly_quota?.eligible && !data.monthly_quota?.claimed) {
      try {
        const claimRes = await api('/api/credits/claim-monthly-quota', {method: 'POST'});
        if (claimRes.ok) {
          const claimed = await claimRes.json();
          if (claimed.granted) return loadCredits(page);
        }
      } catch (e) { console.debug("Monthly quota auto-claim skipped", e); }
    }
    if (data.wallet) {
      if (data.wallet.next_expiry) {
        const delay = Math.min(86400000, Math.max(500, new Date(data.wallet.next_expiry).getTime() - Date.now() + 250));
        creditExpiryTimer = setTimeout(() => { if (currentUser?.id === uid) void loadCredits(); }, delay);
      }
      const expiry = data.wallet.next_expiry ? ` · Next expiry: ${new Date(data.wallet.next_expiry).toLocaleString()}` : "";
      $("#credit-summary").textContent += ` Monthly: ${data.wallet.subscription_available} · Permanent: ${data.wallet.permanent_available}${expiry}. Monthly credits are used first; permanent credits never expire.`;
      if ($("#stat-val-monthly")) $("#stat-val-monthly").textContent = Number(data.wallet.subscription_available || 0).toLocaleString();
      if ($("#stat-val-permanent")) $("#stat-val-permanent").textContent = Number(data.wallet.permanent_available || 0).toLocaleString();
    }
    const labels = {opening:"Starting balance",reserve:"Reserved",settle:"Completed",release:"Returned",grant:"Added"};
    const entries = data.entries || [];
    $("#credit-history").innerHTML = entries.length ? `<div class="credit-table-wrap"><table class="credit-table"><thead><tr><th>Date</th><th>Activity</th><th>Credits</th><th>Available after</th></tr></thead><tbody>${entries.map(row => `<tr><td>${escapeHtml(new Date(row.created_at).toLocaleString())}</td><td><span class="credit-badge badge-${escapeHtml(row.event || 'default')}">${escapeHtml(row.description || labels[row.event] || row.event)}</span></td><td><span class="${Number(row.amount) > 0 ? 'delta-pos' : Number(row.amount) < 0 ? 'delta-neg' : 'delta-zero'}">${row.event === "settle" ? "—" : (Number(row.amount)>0 ? "+" : "")+(Number(row.amount)||0)}</span></td><td><strong>${Number(row.balance_after)||0}</strong></td></tr>`).join("")}</tbody></table></div>` : "No credit activity yet.";
    $("#credits-page").textContent = `Page ${page}`;
    $("#credits-prev").disabled = page <= 1;
    $("#credits-next").disabled = page * 20 >= (data.total || 0);
  } catch (error) {
    if (currentUser?.id === uid && sequence === creditSequence) { renderCreditOverview(null); $("#credit-summary").textContent = error.message; }
  }
}
// Called only after StudioAdapter validates the sending frame and navigation.
window.m2vRefreshExportState = async () => {
  if (!currentUser?.id) return;
  await Promise.allSettled([loadCredits(1), loadExports()]);
};
function initCredits() {
  $("#btn-refresh-credits")?.addEventListener("click", () => loadCredits());
  $("#credits-prev")?.addEventListener("click", () => loadCredits(creditPage-1));
  $("#credits-next")?.addEventListener("click", () => loadCredits(creditPage+1));
}
