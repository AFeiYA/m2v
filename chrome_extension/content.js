/**
 * Fovea MV - Suno 歌词短视频生成助手 (Content Script - Isolated World)
 * 注入悬浮胶囊，与 MAIN World (inject.js) 及 Background Service Worker 协同工作。
 */

(function () {
  let activeServerUrl = "https://mv.fovea.si";
  let collapsed = false;
  let floatingHidden = false;
  let capturePending = false;
  let captureStarting = false;
  let captureTimer;
  function applyBarPreferences() {
    const bar = document.getElementById("fovea-suno-floating-btn");
    if (!bar) return;
    bar.classList.toggle("fovea-collapsed", collapsed);
    bar.style.display = floatingHidden ? "none" : "flex";
    const toggle = bar.querySelector(".fovea-collapse");
    toggle.textContent = collapsed ? "Fovea MV" : "−";
    toggle.title = collapsed ? "Expand controls" : "Minimize controls";
    toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  // 读取配置的服务器地址 (默认云端服务 https://mv.fovea.si，亦可在扩展弹窗切换为本地服务)
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["serverUrl", "barCollapsed", "barHidden"], (res) => {
      if (res && res.serverUrl) {
        activeServerUrl = res.serverUrl.replace(/\/+$/, "");
      }
      collapsed = Boolean(res.barCollapsed);
      floatingHidden = Boolean(res.barHidden);
      applyBarPreferences();
    });
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== "local") return;
      if (changes.serverUrl) activeServerUrl = changes.serverUrl.newValue || "https://mv.fovea.si";
      if (changes.barCollapsed) collapsed = Boolean(changes.barCollapsed.newValue);
      if (changes.barHidden) floatingHidden = Boolean(changes.barHidden.newValue);
      applyBarPreferences();
    });
  }

  // 1. Toast 状态弹窗
  function showToast(title, desc, indeterminate = true, badge = "9:16 Lyric MP4") {
    let overlay = document.getElementById("fovea-toast-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "fovea-toast-overlay";
      document.body.appendChild(overlay);
    }

    overlay.innerHTML = `
      <div class="fovea-toast-title">
        <span class="fovea-toast-heading"></span>
        <span class="fovea-toast-badge"></span>
      </div>
      <div class="fovea-toast-desc"></div>
      <div class="fovea-toast-progress">
        <div class="fovea-toast-bar ${indeterminate ? "fovea-indeterminate" : ""}"></div>
      </div>
    `;
    overlay.querySelector(".fovea-toast-heading").textContent = title;
    overlay.querySelector(".fovea-toast-badge").textContent = badge;
    overlay.querySelector(".fovea-toast-desc").textContent = desc;
    overlay.style.display = "block";
  }

  function hideToast(delayMs = 0) {
    setTimeout(() => {
      const overlay = document.getElementById("fovea-toast-overlay");
      if (overlay) overlay.style.display = "none";
    }, delayMs);
  }

  let currentTrackTitle = "";
  function progressLabel(task, fallback) {
    if (task.message && !/[\u3400-\u9fff]/.test(task.message)) return task.message;
    return {
      queued: "Waiting in queue…", fetching: "Reading song info…",
      audio: "Preparing audio…", separation: "Separating vocals…",
      separating: "Separating vocals…", alignment: "Aligning lyrics…",
      aligning: "Aligning lyrics…", rendering: "Rendering video…",
      completed: "Video ready!", failed: "Video creation failed",
    }[task.phase || task.status] || fallback;
  }
  let currentSection = "chorus";
  let currentDuration = 30;

  const SECTION_LABELS = {
    chorus: "Chorus · 30s",
    verse1: "Verse 1 · 30s",
    intro: "Intro · 30s",
    full: "Full song",
  };

  // 读取已保存的乐段偏好
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["preferredSection", "preferredDuration"], (res) => {
      if (res && res.preferredSection) currentSection = res.preferredSection;
      if (res && res.preferredDuration !== undefined) currentDuration = Number(res.preferredDuration);
      updateSectionTriggerLabel();
    });
  }

  function updateSectionTriggerLabel() {
    const triggerLabel = document.querySelector(".fovea-section-label");
    if (triggerLabel) {
      triggerLabel.textContent = SECTION_LABELS[currentSection] || "Chorus · 30s";
    }
    const items = document.querySelectorAll(".fovea-dropdown-item");
    items.forEach((it) => {
      it.classList.toggle("active", it.dataset.section === currentSection);
    });
  }

  function updateButtonLabel(title) {
    const btn = document.getElementById("fovea-suno-floating-btn");
    if (!btn) return;
    const label = btn.querySelector(".fovea-btn-text");
    if (!label) return;
    if (title && title !== "Suno_Track" && title !== "Unknown track") {
      currentTrackTitle = title;
      label.textContent = title;
      label.title = title;
    } else if (!currentTrackTitle) {
      label.textContent = "Current song";
    }
  }

  // 2. 注入悬浮分段胶囊按钮与乐段切换下拉菜单 (方案 A)
  function injectFloatingButton() {
    if (document.getElementById("fovea-suno-floating-btn")) return;

    const btn = document.createElement("div");
    btn.id = "fovea-suno-floating-btn";
    btn.innerHTML = `
      <div class="fovea-song-title">
        <span class="fovea-pulse-dot"></span>
        <span class="fovea-btn-text">Current song</span>
      </div>
      <div class="fovea-btn-divider"></div>
      <button type="button" class="fovea-btn-mp3" title="Download the full song as MP3">🎵 Download MP3</button>
      <div class="fovea-btn-divider"></div>
      <div class="fovea-video-controls">
        <button type="button" class="fovea-btn-main" title="Create a vertical lyric video">🎬 Create MP4</button>
        <button type="button" class="fovea-btn-section-trigger" title="Choose the MP4 clip" aria-expanded="false" aria-controls="fovea-section-dropdown">
          <span class="fovea-section-label">${SECTION_LABELS[currentSection] || "Chorus · 30s"}</span>
          <span class="fovea-dropdown-arrow">▾</span>
        </button>
        <button type="button" class="fovea-collapse" title="Minimize controls" aria-label="Toggle floating controls" aria-expanded="true">−</button>
      </div>
    `;

    document.body.appendChild(btn);
    applyBarPreferences();
    btn.querySelector(".fovea-collapse").addEventListener("click", event => {
      event.stopPropagation();
      collapsed = !collapsed;
      applyBarPreferences();
      chrome.storage.local.set({ barCollapsed: collapsed });
    });

    // 下拉菜单
    let dropdown = document.getElementById("fovea-section-dropdown");
    if (!dropdown) {
      dropdown = document.createElement("div");
      dropdown.id = "fovea-section-dropdown";
      dropdown.innerHTML = `
        <div class="fovea-dropdown-item ${currentSection === "chorus" ? "active" : ""}" data-section="chorus" data-duration="30">
          <span class="fovea-item-icon">🔥</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">Chorus</div>
            <div class="fovea-item-desc">30 seconds from the chorus</div>
          </div>
        </div>
        <div class="fovea-dropdown-item ${currentSection === "verse1" ? "active" : ""}" data-section="verse1" data-duration="30">
          <span class="fovea-item-icon">🎧</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">Verse 1</div>
            <div class="fovea-item-desc">30 seconds from the first verse</div>
          </div>
        </div>
        <div class="fovea-dropdown-item ${currentSection === "intro" ? "active" : ""}" data-section="intro" data-duration="30">
          <span class="fovea-item-icon">⚡</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">Intro</div>
            <div class="fovea-item-desc">First 30 seconds of the song</div>
          </div>
        </div>
        <div class="fovea-dropdown-item ${currentSection === "full" ? "active" : ""}" data-section="full" data-duration="0">
          <span class="fovea-item-icon">🎬</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">Full song</div>
            <div class="fovea-item-desc">Create a video for the entire song</div>
          </div>
        </div>
      `;
      document.body.appendChild(dropdown);

      // 下拉项点击切换
      dropdown.querySelectorAll(".fovea-dropdown-item").forEach((it) => {
        it.addEventListener("click", (e) => {
          e.stopPropagation();
          currentSection = it.dataset.section || "chorus";
          currentDuration = Number(it.dataset.duration || 30);
          updateSectionTriggerLabel();
          dropdown.style.display = "none";
          btn.querySelector(".fovea-btn-section-trigger").setAttribute("aria-expanded", "false");

          if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            chrome.storage.local.set({
              preferredSection: currentSection,
              preferredDuration: currentDuration,
            });
          }
        });
      });

      // 点击外部关闭下拉
      document.addEventListener("click", (e) => {
        if (!e.target.closest("#fovea-suno-floating-btn") && !e.target.closest("#fovea-section-dropdown")) {
          dropdown.style.display = "none";
          btn.querySelector(".fovea-btn-section-trigger").setAttribute("aria-expanded", "false");
        }
      });
    }

    // 绑定分段按钮触发
    const mainBtn = btn.querySelector(".fovea-btn-main");
    if (mainBtn) {
      mainBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        triggerCapture();
      });
    }

    const mp3Button = btn.querySelector(".fovea-btn-mp3");
    mp3Button.addEventListener("click", async (event) => {
      event.stopPropagation();
      mp3Button.disabled = true;
      mp3Button.textContent = "Checking…";
      try {
        // Read the selected track at click time, rather than cached song state.
        const track = await requestCurrentTrack();
        if (track.is_public === false) throw new Error("Song is not published. Publish it in Suno first.");
        if (!await FoveaUI.consent(activeServerUrl, "audio")) return;
        await FoveaUI.allowAudio(track);
        const response = await new Promise((resolve, reject) => {
          chrome.runtime.sendMessage({ action: "DOWNLOAD_TRACK_MP3", track, serverUrl: activeServerUrl }, result => {
            if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
            else if (result?.status !== "ok") reject(new Error(result?.message || "Could not start MP3 download"));
            else resolve(result);
          });
        });
        showToast("MP3 download started", response.data.filename + ". Check Chrome’s downloads for progress.", false, "Song MP3");
        hideToast(5000);
      } catch (error) {
        showToast("MP3 download failed", FoveaUI.error(error), false, "MP3");
        console.warn("MP3 download details:", error.message);
      } finally {
        mp3Button.disabled = false;
        mp3Button.textContent = "🎵 Download MP3";
      }
    });

    const secTrigger = btn.querySelector(".fovea-btn-section-trigger");
    if (secTrigger) {
      secTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.style.display = dropdown.style.display === "block" ? "none" : "block";
        secTrigger.setAttribute("aria-expanded", String(dropdown.style.display === "block"));
      });
    }

    // 定期向 MAIN world 的 inject.js 请求精准的当前歌曲信息 (避开页面 h1 干扰)
    setInterval(() => {
      window.postMessage({ type: "FOVEA_QUERY_TRACK_INFO" }, "*");
    }, 1500);
    window.postMessage({ type: "FOVEA_QUERY_TRACK_INFO" }, "*");
  }

  function requestCurrentTrack() {
    return new Promise((resolve, reject) => {
      const handler = event => {
        if (event.source !== window || event.data?.type !== "FOVEA_REPORT_TRACK_INFO") return;
        clearTimeout(timer);
        window.removeEventListener("message", handler);
        if (event.data.track) resolve(event.data.track);
        else reject(new Error("No song detected. Play the song and try again."));
      };
      const timer = setTimeout(() => {
        window.removeEventListener("message", handler);
        reject(new Error("Cannot read song info. Refresh Suno and try again."));
      }, 5000);
      window.addEventListener("message", handler);
      window.postMessage({ type: "FOVEA_QUERY_TRACK_INFO" }, "*");
    });
  }

  // 3. 触发捕获流程: 向 MAIN World 的 inject.js 发送请求
  async function triggerCapture() {
    const btn = document.getElementById("fovea-suno-floating-btn");
    if (captureStarting || btn?.classList.contains("fovea-loading")) return;
    captureStarting = true;
    try {
      if (!await FoveaUI.consent(activeServerUrl, "video")) return;
    } finally { captureStarting = false; }
    if (btn) btn.classList.add("fovea-loading");
    capturePending = true;
    captureTimer = setTimeout(() => {
      capturePending = false;
      btn?.classList.remove("fovea-loading");
      showToast("Cannot read song", "Refresh Suno and try again.", false);
    }, 10000);

    const secBadge = SECTION_LABELS[currentSection] || "Chorus";
    showToast("🎵 Reading song info...", `Preparing ${currentTrackTitle || "current song"} · ${secBadge}...`);
    window.postMessage(
      {
        type: "FOVEA_CAPTURE_REQUEST",
        section: currentSection,
        duration: currentDuration,
      },
      "*"
    );
  }

  // 4. 监听来自 inject.js (MAIN World) 的响应
  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data) return;

    // 实时同步当前检测到的曲目名称
    if (event.data.type === "FOVEA_REPORT_TRACK_INFO" && event.data.track) {
      if (event.data.track.title) {
        updateButtonLabel(event.data.track.title);
      }
      return;
    }

    const btn = document.getElementById("fovea-suno-floating-btn");
    if (!["FOVEA_CAPTURE_BY_SONG_ID", "FOVEA_CAPTURE_NOT_PUBLISHED", "FOVEA_CAPTURE_ERROR"].includes(event.data.type)) return;
    if (!capturePending) return;
    capturePending = false;
    clearTimeout(captureTimer);

    // 拦截到未公开 (Publish) 的曲目
    if (event.data.type === "FOVEA_CAPTURE_NOT_PUBLISHED") {
      if (btn) btn.classList.remove("fovea-loading");
      hideToast();
      alert(
        `⚠️ Cannot create MP4\n\n` +
        `${event.data.track?.title || "This song"} is not published.\n\n` +
        `💡 How to publish:\n` +
        `Choose Publish in the song’s (…) menu in Suno, then create your MP4.`
      );
      return;
    }

    if (event.data.type === "FOVEA_CAPTURE_BY_SONG_ID") {
      showToast("Submitting video job", "Processing progress will appear after submission.");
      chrome.runtime.sendMessage({
        action: "EXPORT_VIDEO_BY_SONG_ID", track: event.data.track,
        serverUrl: activeServerUrl, section: event.data.section || currentSection,
        duration: event.data.duration !== undefined ? event.data.duration : currentDuration,
      }, response => {
        const runtimeError = chrome.runtime.lastError?.message;
        if (btn) btn.classList.remove("fovea-loading");
        if (runtimeError || response?.status !== "ok") {
          showToast("Video creation failed", FoveaUI.error(runtimeError || response?.message), false);
          return;
        }
        showToast("Video ready!", "Download started. Check the extension popup for completion.", false);
        hideToast(3500);
      });
    } else if (event.data.type === "FOVEA_CAPTURE_ERROR") {
      if (btn) btn.classList.remove("fovea-loading");
      showToast("Cannot create MP4", FoveaUI.error(event.data.error), false);
    }
  });

  // 接收来自 popup.js 的消息
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === "DOWNLOAD_STATUS") {
        const completed = request.download.state === "complete";
        showToast(completed ? "Download complete" : "Download failed",
          completed ? request.download.filename : "Open the extension popup and choose Retry download.", false, request.download.kind);
        hideToast(completed ? 5000 : 10000);
        sendResponse({ status: "ok" });
      } else if (request.action === "MP3_PROGRESS") {
        showToast("Preparing MP3", progressLabel(request.task, "Preparing audio…"), true, "MP3 audio");
        sendResponse({ status: "ok" });
      } else if (request.action === "EXPORT_PROGRESS") {
        showToast(progressLabel(request.task, "Processing video…"),
          `Job: ${request.task.task_id}${Number.isFinite(request.task.progress) ? ` · ${Math.round(request.task.progress)}%` : ""}`);
        sendResponse({ status: "ok" });
      } else if (request.action === "TRIGGER_EXPORT") {
        triggerCapture();
        sendResponse({ status: "triggered" });
      } else if (request.action === "GET_TRACK_INFO") {
        // 请求 MAIN world 当前歌曲
        const timer = setTimeout(() => {
          window.removeEventListener("message", handler);
          sendResponse(null);
        }, 5000);
        const handler = (ev) => {
          if (ev.source === window && ev.data && ev.data.type === "FOVEA_REPORT_TRACK_INFO") {
            clearTimeout(timer);
            window.removeEventListener("message", handler);
            sendResponse(ev.data.track);
          }
        };
        window.addEventListener("message", handler);
        window.postMessage({ type: "FOVEA_QUERY_TRACK_INFO" }, "*");
        return true; // 异步响应
      }
    });
  }

  // 页面加载完成后注入
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectFloatingButton);
  } else {
    injectFloatingButton();
  }

  // SPA 路由变化检测
  let lastUrl = location.href;
  new MutationObserver(() => {
    const url = location.href;
    if (url !== lastUrl) {
      lastUrl = url;
      injectFloatingButton();
    }
  }).observe(document, { subtree: true, childList: true });
})();
