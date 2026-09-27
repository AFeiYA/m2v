/**
 * Fovea MV - Suno 歌词视频制作助手 (Content Script - Isolated World)
 * 负责注入优雅的 UI 交互，与 MAIN World 及 Background Service Worker 协同工作。
 */

(function () {
  let activeServerUrl = "http://127.0.0.1:8000";

  // 读取配置的服务器地址
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
        <span class="fovea-toast-badge">免扣 25 首额度</span>
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

  // 2. 注入悬浮胶囊按钮
  function injectFloatingButton() {
    if (document.getElementById("fovea-suno-floating-btn")) return;

    const btn = document.createElement("div");
    btn.id = "fovea-suno-floating-btn";
    btn.innerHTML = `
      <span class="fovea-pulse-dot"></span>
      <span>✨ 制作动效短视频</span>
    `;

    btn.title = "无需消耗 Suno 25 首下载额度，一键将当前试听歌曲导入 Fovea MV";

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
        label.textContent = `✨ 制作《${title.slice(0, 10)}》动效 MV`;
      }
    }, 2000);
  }

  // 3. 触发捕获流程: 向 MAIN World 的 inject.js 发送请求
  function triggerCapture() {
    const btn = document.getElementById("fovea-suno-floating-btn");
    if (btn) btn.classList.add("fovea-loading");

    showToast("🎵 正在截获音频...", "正在从浏览器播放内存中提取纯净音轨 (零扣 Suno 额度)...");
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
        sec += 3;
        if (sec >= 4 && sec < 15) {
          showToast("⚡ [步骤 2/3] 音频已传输", "正在执行 Demucs 神经网络人声伴奏分离 (Metal GPU 加速中)...");
        } else if (sec >= 15 && sec < 35) {
          showToast("🚀 [步骤 2/3] 深度分轨中", `正在提取高品质纯人声音轨 (${sec}s / 歌曲长达 4 分 15 秒，请耐心稍候)...`);
        } else if (sec >= 35) {
          showToast("✨ [步骤 3/3] 生成动效视频", "正在精准对齐字级时间轴并构建 9:16 短视频工程...");
        }
      }, 3000);
    }

    function stopProgressStages() {
      if (progressTimer) {
        clearInterval(progressTimer);
        progressTimer = null;
      }
    }

    if (event.data.type === "FOVEA_CAPTURE_SUCCESS") {
      showToast("⚡ [步骤 1/3] 音频已读取", "正在传输至编辑器后台，即将开始人声分离与对齐...");
      startProgressStages();

      chrome.runtime.sendMessage(
        {
          action: "UPLOAD_DIRECT_BLOB",
          dataUrl: event.data.dataUrl,
          track: event.data.track,
          serverUrl: activeServerUrl,
        },
        (response) => {
          stopProgressStages();
          if (btn) btn.classList.remove("fovea-loading");
          if (!response || response.status !== "ok") {
            alert(`[Fovea MV] 制作失败: ${response ? response.message : "未知错误"}`);
            hideToast();
            return;
          }
          showToast("🎉 对齐完成！", "已自动在新标签页打开 9:16 动效短视频界面！", false);
          hideToast(2500);
        }
      );
    } else if (event.data.type === "FOVEA_CAPTURE_NEED_BG_FETCH") {
      showToast("⚡ [步骤 1/3] 正在后台解析流媒体", "正在读取 CloudFront 媒体流...");
      startProgressStages();

      chrome.runtime.sendMessage(
        {
          action: "FETCH_AND_UPLOAD",
          url: event.data.url,
          track: event.data.track,
          serverUrl: activeServerUrl,
        },
        (response) => {
          stopProgressStages();
          if (btn) btn.classList.remove("fovea-loading");
          if (!response || response.status !== "ok") {
            alert(`[Fovea MV] 制作失败: ${response ? response.message : "未知错误"}`);
            hideToast();
            return;
          }
          showToast("🎉 对齐完成！", "已自动在新标签页打开 9:16 动效短视频界面！", false);
          hideToast(2500);
        }
      );
    } else if (event.data.type === "FOVEA_CAPTURE_BY_SONG_ID") {
      showToast("⚡ [步骤 1/3] 正在通过歌曲 ID 解析", "正在连接后台进行智能对齐与处理...");
      startProgressStages();

      chrome.runtime.sendMessage(
        {
          action: "IMPORT_BY_SONG_ID",
          songId: event.data.songId,
          track: event.data.track,
          serverUrl: activeServerUrl,
        },
        (response) => {
          stopProgressStages();
          if (btn) btn.classList.remove("fovea-loading");
          if (!response || response.status !== "ok") {
            alert(`[Fovea MV] 制作失败: ${response ? response.message : "未知错误"}`);
            hideToast();
            return;
          }
          showToast("🎉 对齐完成！", "已自动在新标签页打开 9:16 动效短视频界面！", false);
          hideToast(2500);
        }
      );
    }
 else if (event.data.type === "FOVEA_CAPTURE_ERROR") {
      if (btn) btn.classList.remove("fovea-loading");
      alert(`[Fovea MV] 提示: ${event.data.error}\n💡 请先在 Suno 页面点击【播放】试听该歌曲，确保本地编辑器 (127.0.0.1:8000) 正在运行。`);
      hideToast();
    }

  });

  // 接收来自 popup.js 的消息
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === "TRIGGER_EXPORT") {
        triggerCapture();
        sendResponse({ status: "triggered" });
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
