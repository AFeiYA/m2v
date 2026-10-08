document.addEventListener("DOMContentLoaded", async () => {
  const songNameEl = document.getElementById("songName");
  const publishStatusEl = document.getElementById("publishStatus");
  const btnExport = document.getElementById("btnExport");
  const btnDownloadMp3 = document.getElementById("btnDownloadMp3");
  const downloadStatus = document.getElementById("downloadStatus");
  const serverInput = document.getElementById("serverInput");

  const btnCloud = document.getElementById("btnCloudNode");
  const btnLocal = document.getElementById("btnLocalNode");

  function updateNodeButtons(url) {
    if (!btnCloud || !btnLocal) return;
    if (url.includes("127.0.0.1") || url.includes("localhost")) {
      btnLocal.classList.add("active");
      btnCloud.classList.remove("active");
    } else {
      btnCloud.classList.add("active");
      btnLocal.classList.remove("active");
    }
  }

  // 加载保存的服务器地址 (默认云端生产节点 https://mv.fovea.si)
  chrome.storage.local.get(["serverUrl"], (res) => {
    const defaultUrl = (res && res.serverUrl) ? res.serverUrl : "https://mv.fovea.si";
    serverInput.value = defaultUrl;
    updateNodeButtons(defaultUrl);
  });

  serverInput.addEventListener("change", () => {
    const val = serverInput.value.trim().replace(/\/+$/, "");
    chrome.storage.local.set({ serverUrl: val });
    updateNodeButtons(val);
  });

  if (btnCloud) {
    btnCloud.addEventListener("click", () => {
      serverInput.value = "https://mv.fovea.si";
      chrome.storage.local.set({ serverUrl: "https://mv.fovea.si" });
      updateNodeButtons("https://mv.fovea.si");
    });
  }

  if (btnLocal) {
    btnLocal.addEventListener("click", () => {
      serverInput.value = "http://127.0.0.1:8000";
      chrome.storage.local.set({ serverUrl: "http://127.0.0.1:8000" });
      updateNodeButtons("http://127.0.0.1:8000");
    });
  }

  // 获取当前活跃标签页
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (!tab || !tab.url || !tab.url.includes("suno.com")) {
    songNameEl.textContent = "请先打开 Suno 页面 (suno.com)";
    publishStatusEl.innerHTML = '<span style="color: #94a3b8;">⚠️ 请切换至 Suno 听歌标签页</span>';
    btnExport.disabled = true;
    return;
  }

  // 向当前 Suno 标签页请求歌曲信息
  chrome.tabs.sendMessage(tab.id, { action: "GET_TRACK_INFO" }, (response) => {
    if (chrome.runtime.lastError || !response) {
      songNameEl.textContent = "未检测到歌曲信息";
      publishStatusEl.innerHTML = '<span style="color: #94a3b8;">💡 请在页面上点击【播放】试听歌曲</span>';
      return;
    }

    songNameEl.textContent = response.title || "未知曲目";
    btnDownloadMp3.disabled = !response.audioUrl;
    btnDownloadMp3.title = response.audioUrl ? "下载当前曲目的原始 MP3" : "请刷新页面并播放目标歌曲，让插件识别音频地址";
    if (!response.audioUrl) downloadStatus.textContent = "尚未检测到 MP3 地址，请刷新页面并播放目标歌曲。";

    if (response.is_public === false) {
      publishStatusEl.innerHTML = '<span style="color: #f59e0b;">⚠️ 未公开 (需在 Suno 点击 Publish)</span>';
      btnExport.disabled = true;
      btnExport.title = "该曲目尚未公开，请在 Suno 歌曲右侧菜单（...）中点击【Publish】公开发布";
    } else {
      publishStatusEl.innerHTML = '<span style="color: #10b981;">● 已公开 (可一键生成 9:16 动效视频)</span>';
      btnExport.disabled = false;
      btnExport.title = "点击开始纯 CTC 字级对齐并渲染 9:16 动效 MP4 短视频";
    }
  });

  btnDownloadMp3.addEventListener("click", () => {
    btnDownloadMp3.disabled = true;
    downloadStatus.textContent = "正在检查当前歌曲音频…";
    // Re-query on click so switching tracks after opening the popup cannot
    // accidentally download the previously displayed song.
    chrome.tabs.sendMessage(tab.id, { action: "GET_TRACK_INFO" }, (track) => {
      if (chrome.runtime.lastError || !track) {
        downloadStatus.textContent = "无法读取歌曲，请刷新 Suno 页面后重试。";
        btnDownloadMp3.disabled = false;
        return;
      }
      songNameEl.textContent = track.title || "未知曲目";
      chrome.runtime.sendMessage({ action: "DOWNLOAD_TRACK_MP3", track }, (response) => {
        const error = chrome.runtime.lastError;
        downloadStatus.textContent = error ? `下载失败：${error.message}` :
          response?.status === "ok" ? `已开始下载 ${response.data.filename}，进度请查看 Chrome 下载列表。` :
          response?.message || "下载失败，请重试。";
        btnDownloadMp3.disabled = false;
      });
    });
  });

  // 触发生成短视频
  btnExport.addEventListener("click", () => {
    btnExport.disabled = true;
    btnExport.textContent = "⏳ 正在提交渲染并下载...";
    chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_EXPORT" }, (response) => {
      window.close();
    });
  });
});
