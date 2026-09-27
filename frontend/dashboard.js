/* ==========================================================
   M2V Dashboard — 前端逻辑
   ========================================================== */

const API = "";  // 同源, 无需前缀

// ── State ────────────────────────────────────────────────
let token = localStorage.getItem("m2v_token") || null;
let refreshToken = localStorage.getItem("m2v_refresh") || null;
let currentUser = null;
let pollTimer = null;

// ── DOM Helpers ──────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── API 请求封装 ─────────────────────────────────────────

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.json) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  options.headers = headers;

  const res = await fetch(`${API}${path}`, options);

  if (res.status === 401 && refreshToken) {
    // 尝试刷新 token
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
  return false;
}


// ======================================================================
// Auth
// ======================================================================

let isLoginMode = true;

function initAuth() {
  const form = $("#auth-form");
  const toggle = $("#auth-toggle");

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

function logout() {
  token = null;
  refreshToken = null;
  currentUser = null;
  localStorage.removeItem("m2v_token");
  localStorage.removeItem("m2v_refresh");
  showAuth();
}

function showAuth() {
  $("#auth-overlay").style.display = "flex";
  $("#app").style.display = "none";
  if (pollTimer) clearInterval(pollTimer);
}

function showApp() {
  $("#auth-overlay").style.display = "none";
  $("#app").style.display = "";
  loadTasks();
  startPolling();
}

async function loadUser() {
  const res = await api("/api/auth/me");
  if (res.ok) {
    currentUser = await res.json();
    $("#user-info").textContent = `👤 ${currentUser.username}`;
    $("#user-credits").textContent = `剩余 ${currentUser.credits} 次`;
  }
}


// ======================================================================
// Upload
// ======================================================================

function initUpload() {
  $("#upload-form").addEventListener("submit", async (e) => {
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

    try {
      const res = await api(`/api/upload?${params}`, {
        method: "POST",
        body: form,
      });

      if (res.ok) {
        const data = await res.json();
        showStatus(`✅ 任务已创建: ${data.task_id.slice(0, 8)}…`);
        $("#upload-form").reset();
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

  return `
    <div class="task-card" id="task-${task.id}" data-status="${task.status}">
      <div class="task-header">
        <strong class="task-title">🎵 ${escapeHtml(task.title || "未命名")}</strong>
        <span class="task-status">${statusText}</span>
      </div>
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
    window.open(`${API}/api/tasks/${taskId}/download/${type}`, "_blank");
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
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws/tasks/${taskId}/progress`);

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


// ======================================================================
// Init
// ======================================================================

document.addEventListener("DOMContentLoaded", async () => {
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
