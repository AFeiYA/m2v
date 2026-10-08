document.addEventListener("DOMContentLoaded", async () => {
  const songNameEl = document.getElementById("songName");
  const publishStatusEl = document.getElementById("publishStatus");
  const btnExport = document.getElementById("btnExport");
  const btnDownloadMp3 = document.getElementById("btnDownloadMp3");
  const downloadStatus = document.getElementById("downloadStatus");
  const serverInput = document.getElementById("serverInput");

  const btnResumeVideo = document.getElementById("btnResumeVideo");
  const videoTaskStatus = document.getElementById("videoTaskStatus");
  chrome.storage.local.get("pendingVideoJob", ({ pendingVideoJob }) => {
    if (!pendingVideoJob) return;
    btnResumeVideo.hidden = false;
    videoTaskStatus.textContent = `${pendingVideoJob.title || "Video"} · ${pendingVideoJob.taskId}`;
  });
  btnResumeVideo.addEventListener("click", () => {
    btnResumeVideo.disabled = true;
    videoTaskStatus.textContent = "Checking the existing job. Download starts when ready.";
    chrome.runtime.sendMessage({ action: "RESUME_VIDEO_JOB" }, response => {
      videoTaskStatus.textContent = chrome.runtime.lastError?.message ||
        (response?.status === "ok" ? "Video download started." : response?.message || "Connection interrupted. Resume to try again.");
      btnResumeVideo.disabled = false;
      if (response?.status === "ok") btnResumeVideo.hidden = true;
    });
  });

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
    songNameEl.textContent = "Open a song on suno.com";
    publishStatusEl.innerHTML = '<span style="color: #94a3b8;">⚠️ Switch to a Suno tab</span>';
    btnExport.disabled = true;
    return;
  }

  // 向当前 Suno 标签页请求歌曲信息
  chrome.tabs.sendMessage(tab.id, { action: "GET_TRACK_INFO" }, (response) => {
    if (chrome.runtime.lastError || !response) {
      songNameEl.textContent = "No song detected";
      publishStatusEl.innerHTML = '<span style="color: #94a3b8;">💡 Play the song to detect it</span>';
      return;
    }

    songNameEl.textContent = response.title || "Unknown track";
    btnDownloadMp3.disabled = !response.audioUrl && !response.songId;
    btnDownloadMp3.title = response.audioUrl ? "Download this song as MP3" : "Extract MP3 audio using the selected server";
    if (!response.audioUrl) downloadStatus.textContent = "If no MP3 URL is available, the server extracts the audio. No lyric alignment is needed.";

    if (response.is_public === false) {
      publishStatusEl.innerHTML = '<span style="color: #f59e0b;">⚠️ Not published — use Publish in Suno</span>';
      btnExport.disabled = true;
      btnExport.title = "Publish this song in Suno’s (…) menu first";
    } else {
      publishStatusEl.innerHTML = '<span style="color: #10b981;">● Published — ready for MP4</span>';
      btnExport.disabled = false;
      btnExport.title = "Align lyrics and create a vertical MP4";
    }
  });

  btnDownloadMp3.addEventListener("click", () => {
    btnDownloadMp3.disabled = true;
    downloadStatus.textContent = "Checking song audio…";
    // Re-query on click so switching tracks after opening the popup cannot
    // accidentally download the previously displayed song.
    chrome.tabs.sendMessage(tab.id, { action: "GET_TRACK_INFO" }, (track) => {
      if (chrome.runtime.lastError || !track) {
        downloadStatus.textContent = "Cannot read the song. Refresh Suno and try again.";
        btnDownloadMp3.disabled = false;
        return;
      }
      songNameEl.textContent = track.title || "Unknown track";
      chrome.runtime.sendMessage({ action: "DOWNLOAD_TRACK_MP3", track, serverUrl: serverInput.value }, (response) => {
        const error = chrome.runtime.lastError;
        downloadStatus.textContent = error ? `Download failed: ${error.message}` :
          response?.status === "ok" ? `Downloading ${response.data.filename}. Check Chrome’s downloads.` :
          response?.message || "Download failed. Please try again.";
        btnDownloadMp3.disabled = false;
      });
    });
  });

  // 触发生成短视频
  btnExport.addEventListener("click", () => {
    btnExport.disabled = true;
    btnExport.textContent = "⏳ Submitting video...";
    chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_EXPORT" }, (response) => {
      window.close();
    });
  });
});
