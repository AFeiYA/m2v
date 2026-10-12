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
  if (window.M2V_API_BASE && !isLocal) return window.M2V_API_BASE.replace(/\/+$/, "");
  return getDefaultApi().replace(/\/+$/, "");
}

let API = resolveApiBase();
console.log("[M2V] 当前有效 API 服务地址:", API);

// ── State ────────────────────────────────────────────────
let token = localStorage.getItem("m2v_token") || null;
let refreshToken = localStorage.getItem("m2v_refresh") || null;
let authProvider = localStorage.getItem("m2v_auth_provider") || null;
let currentUser = null;
let pollTimer = null;

// ── DOM Helpers ──────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

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
    throw new Error(`后端 API 尚未连通：请求目标 [${url}] 返回了静态页面，请确认后端服务运行状态。`);
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
          throw new Error("Firebase 授权服务初始化中，请稍候");
        }
        const { user, idToken } = await window.m2vAuth.loginWithGoogle();
        token = idToken;
        authProvider = "firebase";
        refreshToken = null;
        localStorage.removeItem("m2v_refresh");
        localStorage.setItem("m2v_auth_provider", authProvider);
        localStorage.setItem("m2v_token", token);
        const ok = await loadUser();
        if (ok) {
          showApp();
        } else {
          logout();
          throw new Error("云端用户身份校验未通过，请重试");
        }
      } catch (err) {
        console.error("Google 登录异常:", err);
        $("#auth-error").textContent = err.message || "Google 登录失败，请重试";
      }
    });
  }

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
      let res;
      if (isLoginMode) {
        res = await fetch(`${API}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
      } else {
        if (!username) {
          $("#auth-error").textContent = "请输入用户名";
          return;
        }
        res = await fetch(`${API}/api/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, username, password }),
        });
      }

      if (res.ok) {
        const data = await res.json();
        // Clear any persisted Google session before switching to a local account.
        if (window.m2vAuth) await window.m2vAuth.logout();
        authProvider = "local";
        localStorage.setItem("m2v_auth_provider", authProvider);
        token = data.access_token;
        refreshToken = data.refresh_token;
        localStorage.setItem("m2v_token", token);
        localStorage.setItem("m2v_refresh", refreshToken);
        await loadUser();
        showApp();
      } else {
        const err = await res.json();
        $("#auth-error").textContent = err.detail || "操作失败";
      }
    } catch (e) {
      $("#auth-error").textContent = "网络错误，请检查服务是否运行";
    }
  });
}

function updateAuthUI() {
  if (isLoginMode) {
    $("#auth-title").textContent = "🎤 M2V 登录";
    $("#auth-submit").textContent = "登录";
    $("#auth-toggle-text").textContent = "没有账号？";
    $("#auth-toggle").textContent = "去注册";
    $("#auth-username").style.display = "none";
    $("#auth-username").required = false;
  } else {
    $("#auth-title").textContent = "🎤 M2V 注册";
    $("#auth-submit").textContent = "注册";
    $("#auth-toggle-text").textContent = "已有账号？";
    $("#auth-toggle").textContent = "去登录";
    $("#auth-username").style.display = "";
    $("#auth-username").required = true;
  }
}

async function logout() {
  token = null;
  refreshToken = null;
  currentUser = null;
  authProvider = null;
  localStorage.removeItem("m2v_token");
  localStorage.removeItem("m2v_refresh");
  localStorage.removeItem("m2v_auth_provider");
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
      window.location.href = redirect;
      return true;
    }
  } catch (e) {
    /* ignore */
  }
  return false;
}

function showApp() {
  if (checkRedirect()) return;
  $("#auth-overlay").style.display = "none";
  $("#app").style.display = "";
  loadTasks();
  startPolling();
}

async function loadUser() {
  try {
    const res = await api("/api/auth/me");
    if (res.ok) {
      currentUser = await res.json();
      $("#user-info").textContent = `👤 ${currentUser.username}`;
      $("#user-credits").textContent = `剩余 ${currentUser.credits} 次`;
      return true;
    }
  } catch (e) {
    console.error("[M2V] 加载用户信息失败:", e);
  }
  currentUser = null;
  return false;
}


// ======================================================================
// Upload
// ======================================================================

function initUpload() {
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
      btn.textContent = "⏳ 解析 Suno 歌曲与音频…";

      try {
        const payload = {
          suno_url: sunoUrl,
          song_title: songTitle || undefined,
          language: $("#suno-opt-lang").value,
          skip_separation: $("#suno-opt-skip-sep").checked,
          ass_only: $("#suno-opt-ass-only").checked,
          beat_effects: $("#suno-opt-beat").checked,
        };

        const res = await api("/api/tasks/from-suno", {
          method: "POST",
          json: payload,
        });

        if (res.ok) {
          const data = await res.json();
          showStatus(data.message || `✅ 任务已创建: ${data.task_id.slice(0, 8)}…`);
          sunoForm.reset();
          loadTasks();
          connectProgressWS(data.task_id);
        } else {
          const err = await res.json();
          showStatus(`❌ ${err.detail || "创建任务失败"}`, true);
        }
      } catch (err) {
        showStatus(`❌ ${err.message || "网络错误"}`, true);
      } finally {
        btn.disabled = false;
        btn.textContent = "✨ 解析 Suno 并生成 MV";
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
      btn.textContent = "⏳ 上传中…";

      const form = new FormData();
      form.append("mp3", mp3File);
      form.append("lyrics", lyricsFile);

      // Query params
      const params = new URLSearchParams();
      params.set("language", $("#opt-lang").value);
      if ($("#opt-skip-sep").checked) params.set("skip_separation", "true");
      if ($("#opt-ass-only").checked) params.set("ass_only", "true");
      if ($("#opt-beat").checked) params.set("beat_effects", "true");

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
          showStatus(`✅ 任务已创建: ${data.task_id.slice(0, 8)}…`);
          uploadForm.reset();
          loadTasks();
          // 连接 WebSocket 监听进度
          connectProgressWS(data.task_id);
        } else {
          const err = await res.json();
          showStatus(`❌ ${err.detail || "上传失败"}`, true);
        }
      } catch (e) {
        showStatus("❌ 网络错误", true);
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 上传并生成";
      }
    });
  }
}


// ======================================================================
// Tasks
// ======================================================================

async function loadTasks() {
  const res = await api("/api/tasks?page=1&page_size=50");
  if (!res.ok) return;

  const data = await res.json();
  const list = $("#tasks-list");
  const empty = $("#tasks-empty");

  if (data.tasks.length === 0) {
    list.innerHTML = "";
    empty.style.display = "";
    return;
  }

  empty.style.display = "none";
  list.innerHTML = data.tasks.map(renderTask).join("");

  // 绑定按钮事件
  list.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", handleTaskAction);
  });
}

function renderTask(task) {
  const statusMap = {
    pending: "⏳ 等待中",
    processing: "🔄 处理中",
    completed: "✅ 已完成",
    failed: "❌ 失败",
  };

  const stepMap = {
    queued: "排队中",
    preprocessing: "歌词预处理",
    separating: "人声分离",
    aligning: "词级对齐",
    subtitle: "字幕生成",
    compositing: "视频合成",
    done: "完成",
    error: "错误",
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
      actions += `<button class="btn btn-sm" data-action="download" data-task="${task.id}" data-type="mp4">📹 下载 MP4</button>`;
    }
    if (task.output_ass_key) {
      actions += `<button class="btn btn-sm" data-action="download" data-task="${task.id}" data-type="ass">📄 下载 ASS</button>`;
    }
    if (task.alignment_json_key) {
      actions += `<button class="btn btn-sm" data-action="download" data-task="${task.id}" data-type="alignment">📊 下载 JSON</button>`;
      actions += `<a class="btn btn-sm" href="/editor/${task.id}" target="_blank">✏️ 编辑时间轴</a>`;
    }
  }
  if (task.status === "failed" && task.error_message) {
    actions += `<span class="error-text" title="${escapeHtml(task.error_message)}">💬 查看错误</span>`;
  }
  actions += `<button class="btn btn-sm btn-danger" data-action="delete" data-task="${task.id}">🗑️</button>`;

  const displayTitle = task.song_title || task.title || "未命名";
  const sunoLink = task.suno_url
    ? `<div class="task-suno-link"><a href="${escapeHtml(task.suno_url)}" target="_blank" rel="noopener noreferrer">🔗 原曲 Suno 页面</a></div>`
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
        <span>创建: ${date}</span>
      </div>
      <div class="task-actions">${actions}</div>
    </div>
  `;
}

async function handleTaskAction(e) {
  const btn = e.currentTarget;
  const action = btn.dataset.action;
  const taskId = btn.dataset.task;

  if (action === "download") {
    const type = btn.dataset.type;
    const originalText = btn.textContent;
    btn.textContent = "下载中...";
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
      alert(`下载失败: ${err.message}`);
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  } else if (action === "delete") {
    if (!confirm("确定删除此任务？")) return;
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
    if (processing.length > 0) {
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

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}


function initApiConfig() {
  const updateLabel = () => {
    const cur = API;
    const el = $("#btn-config-api");
    const elApp = $("#btn-config-api-app");
    let label = "";
    try {
      const u = new URL(cur);
      label = `服务: ${u.host}`;
    } catch (e) {
      label = cur ? `服务: ${cur}` : "未配置 (点击设置)";
    }
    if (el) el.textContent = label;
    if (elApp) elApp.title = `后端 API: ${cur}`;
  };

  const configure = (e) => {
    e?.preventDefault();
    const current = localStorage.getItem("m2v_api_base") || API;
    const input = prompt(
      "请输入 Python 后端 API 服务地址：\n(留空恢复默认: " + getDefaultApi() + ")",
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
  initAuth();
  initUpload();

  // 退出按钮
  $("#btn-logout").addEventListener("click", logout);
  $("#btn-refresh").addEventListener("click", loadTasks);

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
