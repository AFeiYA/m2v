/**
 * Fovea MV - Suno 歌词短视频生成助手 (Content Script - Isolated World)
 * 注入悬浮胶囊，与 MAIN World (inject.js) 及 Background Service Worker 协同工作。
 */

(function () {
  let activeServerUrl = "https://mv.fovea.si";

  // 读取配置的服务器地址 (默认云端服务 https://mv.fovea.si，亦可在扩展弹窗切换为本地服务)
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["serverUrl"], (res) => {
      if (res && res.serverUrl) {
        activeServerUrl = res.serverUrl.replace(/\/+$/, "");
      }
    });
  }

  // 1. Toast 状态弹窗
  function showToast(title, desc, indeterminate = true, badge = "9:16 动效 MP4") {
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
  let currentSection = "chorus";
  let currentDuration = 30;

  const SECTION_LABELS = {
    chorus: "🔥 副歌 (30s)",
    verse1: "🎧 主歌1 (30s)",
    intro: "⚡ 前奏 (30s)",
    full: "🎬 完整全曲",
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
      triggerLabel.textContent = SECTION_LABELS[currentSection] || "🔥 副歌 (30s)";
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
    if (title && title !== "Suno_Track" && title !== "未知曲目") {
      currentTrackTitle = title;
      const displayTitle = title.length > 12 ? title.slice(0, 11) + "…" : title;
      label.textContent = `🎬 生成《${displayTitle}》`;
    } else if (!currentTrackTitle) {
      label.textContent = "🎬 一键生成 9:16 MP4";
    }
  }

  // 2. 注入悬浮分段胶囊按钮与乐段切换下拉菜单 (方案 A)
  function injectFloatingButton() {
    if (document.getElementById("fovea-suno-floating-btn")) return;

    const btn = document.createElement("div");
    btn.id = "fovea-suno-floating-btn";
    btn.innerHTML = `
      <div class="fovea-btn-main" title="点击开始一键对齐并渲染 9:16 动效短视频">
        <span class="fovea-pulse-dot"></span>
        <span class="fovea-btn-text">🎬 一键生成 9:16 MP4</span>
      </div>
      <div class="fovea-btn-divider"></div>
      <div class="fovea-btn-section-trigger" title="点击切换短视频截取乐段 (默认副歌 30s)">
        <span class="fovea-section-label">${SECTION_LABELS[currentSection] || "🔥 副歌 (30s)"}</span>
        <span class="fovea-dropdown-arrow">▾</span>
      </div>
      <div class="fovea-btn-divider"></div>
      <button type="button" class="fovea-btn-mp3" title="仅下载当前歌曲原始 MP3，无需后台生成视频">🎵 仅下载 MP3</button>
    `;

    document.body.appendChild(btn);

    // 下拉菜单
    let dropdown = document.getElementById("fovea-section-dropdown");
    if (!dropdown) {
      dropdown = document.createElement("div");
      dropdown.id = "fovea-section-dropdown";
      dropdown.innerHTML = `
        <div class="fovea-dropdown-item ${currentSection === "chorus" ? "active" : ""}" data-section="chorus" data-duration="30">
          <span class="fovea-item-icon">🔥</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">爆款副歌 (Chorus)</div>
            <div class="fovea-item-desc">从副歌高潮起截取 30 秒 (短视频首选)</div>
          </div>
        </div>
        <div class="fovea-dropdown-item ${currentSection === "verse1" ? "active" : ""}" data-section="verse1" data-duration="30">
          <span class="fovea-item-icon">🎧</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">主歌第 1 段 (Verse 1)</div>
            <div class="fovea-item-desc">从主歌开头向后截取 30 秒 (叙事氛围)</div>
          </div>
        </div>
        <div class="fovea-dropdown-item ${currentSection === "intro" ? "active" : ""}" data-section="intro" data-duration="30">
          <span class="fovea-item-icon">⚡</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">黄金前奏 (Intro Hook)</div>
            <div class="fovea-item-desc">从音频开头向后截取 30 秒</div>
          </div>
        </div>
        <div class="fovea-dropdown-item ${currentSection === "full" ? "active" : ""}" data-section="full" data-duration="0">
          <span class="fovea-item-icon">🎬</span>
          <div class="fovea-item-info">
            <div class="fovea-item-title">完整全曲 (Full Track)</div>
            <div class="fovea-item-desc">导出整首歌完整长视频</div>
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
      mp3Button.textContent = "正在检查…";
      try {
        // Read the selected track at click time, rather than cached song state.
        const track = await requestCurrentTrack();
        const response = await new Promise((resolve, reject) => {
          chrome.runtime.sendMessage({ action: "DOWNLOAD_TRACK_MP3", track, serverUrl: activeServerUrl }, result => {
            if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
            else if (result?.status !== "ok") reject(new Error(result?.message || "无法启动 MP3 下载"));
            else resolve(result);
          });
        });
        showToast("MP3 已开始下载", response.data.filename + "，进度请查看 Chrome 下载列表。", false, "原曲 MP3");
        hideToast(5000);
      } catch (error) {
        alert(`[Fovea MV] MP3 下载失败：${error.message}`);
      } finally {
        mp3Button.disabled = false;
        mp3Button.textContent = "🎵 仅下载 MP3";
      }
    });

    const secTrigger = btn.querySelector(".fovea-btn-section-trigger");
    if (secTrigger) {
      secTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.style.display = dropdown.style.display === "block" ? "none" : "block";
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
        else reject(new Error("未检测到歌曲，请播放目标歌曲后再试。"));
      };
      const timer = setTimeout(() => {
        window.removeEventListener("message", handler);
        reject(new Error("无法读取歌曲信息，请刷新 Suno 页面后再试。"));
      }, 5000);
      window.addEventListener("message", handler);
      window.postMessage({ type: "FOVEA_QUERY_TRACK_INFO" }, "*");
    });
  }

  // 3. 触发捕获流程: 向 MAIN World 的 inject.js 发送请求
  function triggerCapture() {
    const btn = document.getElementById("fovea-suno-floating-btn");
    if (btn) btn.classList.add("fovea-loading");

    const secBadge = SECTION_LABELS[currentSection] || "副歌";
    showToast("🎵 正在分析歌曲信息...", `正在准备《${currentTrackTitle || "当前曲目"}》[${secBadge}]...`);
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

    function startProgressStages() {
      showToast("正在提交视频任务", "提交成功后将显示后台实际处理阶段，请耐心等待。");
    }
    function stopProgressStages() {}

    // 拦截到未公开 (Publish) 的曲目
    if (event.data.type === "FOVEA_CAPTURE_NOT_PUBLISHED") {
      if (btn) btn.classList.remove("fovea-loading");
      hideToast();
      alert(
        `⚠️ 【无法生成短视频】\n\n` +
        `曲目《${event.data.track?.title || "当前歌曲"}》尚未公开 (Publish)！\n\n` +
        `💡 操作指引：\n` +
        `请在 Suno 歌曲右侧的菜单按钮（...）中，点击【Publish】公开发布，发布后即可一键导出 9:16 动效 MP4 视频！`
      );
      return;
    }

    if (event.data.type === "FOVEA_CAPTURE_SUCCESS") {
      showToast("⚡ [步骤 1/3] 音频已就绪", "正在传输至后台，即将开始纯 CTC 字级对齐与视频合成...");
      startProgressStages();

      chrome.runtime.sendMessage(
        {
          action: "EXPORT_VIDEO_DIRECT_BLOB",
          dataUrl: event.data.dataUrl,
          track: event.data.track,
          serverUrl: activeServerUrl,
          section: event.data.section || currentSection,
          duration: event.data.duration !== undefined ? event.data.duration : currentDuration,
        },
        (response) => {
          stopProgressStages();
          if (btn) btn.classList.remove("fovea-loading");
          if (!response || response.status !== "ok") {
            alert(`[Fovea MV] 视频生成失败:\n${response ? response.message : "未知错误"}`);
            hideToast();
            return;
          }
          showToast("🎉 渲染完成！", `已自动将《${event.data.track.title || "suno"}》动效 MP4 保存至下载目录！`, false);
          hideToast(3500);
        }
      );
    } else if (event.data.type === "FOVEA_CAPTURE_NEED_BG_FETCH") {
      showToast("⚡ [步骤 1/3] 正在拉取音轨流", "正在后台下载媒体流并提交短视频渲染...");
      startProgressStages();

      chrome.runtime.sendMessage(
        {
          action: "EXPORT_VIDEO_FETCH",
          url: event.data.url,
          track: event.data.track,
          serverUrl: activeServerUrl,
          section: event.data.section || currentSection,
          duration: event.data.duration !== undefined ? event.data.duration : currentDuration,
        },
        (response) => {
          stopProgressStages();
          if (btn) btn.classList.remove("fovea-loading");
          if (!response || response.status !== "ok") {
            alert(`[Fovea MV] 视频生成失败:\n${response ? response.message : "未知错误"}`);
            hideToast();
            return;
          }
          showToast("🎉 渲染完成！", `已自动将《${event.data.track.title || "suno"}》动效 MP4 保存至下载目录！`, false);
          hideToast(3500);
        }
      );
    } else if (event.data.type === "FOVEA_CAPTURE_BY_SONG_ID") {
      showToast("⚡ [步骤 1/3] 正在通过歌曲 ID 生成", "正在连接后台进行智能对齐与视频渲染...");
      startProgressStages();

      chrome.runtime.sendMessage(
        {
          action: "EXPORT_VIDEO_BY_SONG_ID",
          track: event.data.track,
          serverUrl: activeServerUrl,
          section: event.data.section || currentSection,
          duration: event.data.duration !== undefined ? event.data.duration : currentDuration,
        },
        (response) => {
          stopProgressStages();
          if (btn) btn.classList.remove("fovea-loading");
          if (!response || response.status !== "ok") {
            alert(`[Fovea MV] 视频生成失败:\n${response ? response.message : "未知错误"}`);
            hideToast();
            return;
          }
          showToast("🎉 渲染完成！", `已自动将《${event.data.track.title || "suno"}》动效 MP4 保存至下载目录！`, false);
          hideToast(3500);
        }
      );
    } else if (event.data.type === "FOVEA_CAPTURE_ERROR") {
      if (btn) btn.classList.remove("fovea-loading");
      alert(`[Fovea MV] 提示: ${event.data.error}\n💡 请先在 Suno 页面点击【播放】试听该歌曲，确保本地后台服务 (127.0.0.1:8000) 正在运行。`);
      hideToast();
    }
  });

  // 接收来自 popup.js 的消息
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === "MP3_PROGRESS") {
        showToast("正在准备 MP3", request.task.message || "正在转换音轨…", true, "MP3 音轨");
        sendResponse({ status: "ok" });
      } else if (request.action === "EXPORT_PROGRESS") {
        showToast(request.task.message || "正在处理视频…",
          `任务：${request.task.task_id}${Number.isFinite(request.task.progress) ? ` · ${Math.round(request.task.progress)}%` : ""}`);
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
