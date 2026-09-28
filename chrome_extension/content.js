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
  function showToast(title, desc, indeterminate = true) {
    let overlay = document.getElementById("fovea-toast-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "fovea-toast-overlay";
      document.body.appendChild(overlay);
    }

    overlay.innerHTML = `
      <div class="fovea-toast-title">
        <span>${title}</span>
        <span class="fovea-toast-badge">9:16 动效 MP4</span>
      </div>
      <div class="fovea-toast-desc">${desc}</div>
      <div class="fovea-toast-progress">
        <div class="fovea-toast-bar ${indeterminate ? "fovea-indeterminate" : ""}"></div>
      </div>
    `;
    overlay.style.display = "block";
  }

  function hideToast(delayMs = 0) {
    setTimeout(() => {
      const overlay = document.getElementById("fovea-toast-overlay");
      if (overlay) overlay.style.display = "none";
    }, delayMs);
  }

  // 2. 注入悬浮胶囊按钮 (仅提供生成动效 MP4)
  function injectFloatingButton() {
    if (document.getElementById("fovea-suno-floating-btn")) return;

    const btn = document.createElement("div");
    btn.id = "fovea-suno-floating-btn";
    btn.innerHTML = `
      <span class="fovea-pulse-dot"></span>
      <span>🎬 一键生成 9:16 动效 MP4</span>
    `;

    btn.title = "仅支持已公开发布 (Publish) 的曲目，纯 CTC 字级时间轴对齐并一键生成下载 9:16 动效短视频";

    btn.addEventListener("click", () => {
      triggerCapture();
    });

    document.body.appendChild(btn);

    // 动态提取页面歌曲名
    setInterval(() => {
      const h1 = document.querySelector("h1");
      const label = btn.querySelector("span:last-child");
      if (label && h1 && h1.innerText.trim()) {
        const title = h1.innerText.trim();
        label.textContent = `🎬 生成《${title.slice(0, 8)}》动效 MP4`;
      }
    }, 2000);
  }

  // 3. 触发捕获流程: 向 MAIN World 的 inject.js 发送请求
  function triggerCapture() {
    const btn = document.getElementById("fovea-suno-floating-btn");
    if (btn) btn.classList.add("fovea-loading");

    showToast("🎵 正在分析歌曲信息...", "正在从浏览器播放内存中提取纯净音轨并校验公开状态...");
    window.postMessage({ type: "FOVEA_CAPTURE_REQUEST" }, "*");
  }

  // 4. 监听来自 inject.js (MAIN World) 的响应
  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data) return;

    const btn = document.getElementById("fovea-suno-floating-btn");

    let progressTimer = null;
    function startProgressStages() {
      if (progressTimer) clearInterval(progressTimer);
      let sec = 0;
      progressTimer = setInterval(() => {
        sec += 2;
        if (sec >= 3 && sec < 8) {
          showToast("⚡ [步骤 2/3] 纯 CTC 歌词对齐中", "正在执行毫秒级字级时间轴智能对齐 (纯 CTC 极速方案)...");
        } else if (sec >= 8 && sec < 35) {
          showToast("🚀 [步骤 3/3] 动效短视频渲染中", `FFmpeg 正在渲染 9:16 灵动渐变短视频 (${sec}s / 预计约 15~20 秒)...`);
        } else if (sec >= 35) {
          showToast("✨ [步骤 3/3] 即将完成", "视频合成已接近尾声，准备调用浏览器下载...");
        }
      }, 2000);
    }

    function stopProgressStages() {
      if (progressTimer) {
        clearInterval(progressTimer);
        progressTimer = null;
      }
    }

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
      if (request.action === "TRIGGER_EXPORT") {
        triggerCapture();
        sendResponse({ status: "triggered" });
      } else if (request.action === "GET_TRACK_INFO") {
        // 请求 MAIN world 当前歌曲
        const handler = (ev) => {
          if (ev.source === window && ev.data && ev.data.type === "FOVEA_REPORT_TRACK_INFO") {
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
