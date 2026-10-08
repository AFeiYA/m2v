document.addEventListener("DOMContentLoaded", async () => {
  const songNameEl = document.getElementById("songName");
  const publishStatusEl = document.getElementById("publishStatus");
  const btnExport = document.getElementById("btnExport");
  const btnDownloadMp3 = document.getElementById("btnDownloadMp3");
  const downloadStatus = document.getElementById("downloadStatus");
  const serverInput = document.getElementById("serverInput");
  let configuredServer = "https://mv.fovea.si";
  const hideBar = document.getElementById("hideBar");
  chrome.storage.local.get("barHidden", data => { hideBar.checked = Boolean(data.barHidden); });
  hideBar.addEventListener("change", () => chrome.storage.local.set({ barHidden: hideBar.checked }));

  const btnResumeVideo = document.getElementById("btnResumeVideo");
  const videoTaskStatus = document.getElementById("videoTaskStatus");
  const jobSelect = document.getElementById("jobSelect");
  const errorDetails = document.getElementById("errorDetails");
  function showError(element, detail) {
    element.textContent = FoveaUI.error(detail);
    errorDetails.hidden = false;
    document.getElementById("errorText").textContent = String(detail?.message || detail || "Unknown error");
  }
  async function refreshHistory() {
    const { videoJobs = [], pendingVideoJob, downloads = [] } = await chrome.storage.local.get(["videoJobs", "pendingVideoJob", "downloads"]);
    const jobs = videoJobs.length ? videoJobs : pendingVideoJob ? [pendingVideoJob] : [];
    const selection = jobSelect.value;
    jobSelect.replaceChildren();
    jobs.slice().reverse().forEach(job => {
      const option = document.createElement("option");
      option.value = job.taskId || job.requestId;
      option.textContent = `${job.title || "Video"} · ${job.section || "full"} · ${job.status || "pending"}`;
      jobSelect.appendChild(option);
    });
    if (jobs.some(j => (j.taskId || j.requestId) === selection)) jobSelect.value = selection;
    btnResumeVideo.hidden = jobSelect.hidden = !jobs.length;
    btnResumeVideo.textContent = "Resume selected video";
    const last = downloads.at(-1);
    document.getElementById("recentDownload").textContent = last ? `${last.filename} · ${last.state === "complete" ? "Downloaded" : last.state === "interrupted" ? "Download failed" : "Downloading…"}` : "";
    const retry = document.getElementById("btnRetryDownload");
    retry.hidden = last?.state !== "interrupted";
    retry.dataset.id = last?.id;
  }
  refreshHistory();
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && (changes.videoJobs || changes.downloads)) refreshHistory();
  });
  document.getElementById("btnRetryDownload").addEventListener("click", event => {
    chrome.runtime.sendMessage({ action: "RETRY_DOWNLOAD", downloadId: Number(event.currentTarget.dataset.id) }, response => {
      if (chrome.runtime.lastError || response?.status !== "ok") showError(downloadStatus, chrome.runtime.lastError?.message || response?.message);
    });
  });
  document.getElementById("btnClearHistory").addEventListener("click", async () => {
    const { videoJobs = [], downloads = [], pendingVideoJob } = await chrome.storage.local.get(["videoJobs", "downloads", "pendingVideoJob"]);
    const remaining = videoJobs.filter(j => ["submitting", "pending", "running", "completed", "downloading"].includes(j.status));
    await chrome.storage.local.set({ videoJobs: remaining, downloads: downloads.filter(d => d.state === "in_progress") });
    if (pendingVideoJob && videoJobs.some(j => j.taskId === pendingVideoJob.taskId) && !remaining.some(j => j.taskId === pendingVideoJob.taskId)) {
      await chrome.storage.local.remove("pendingVideoJob");
    }
    videoTaskStatus.textContent = "Finished history cleared. Active jobs and server files were kept.";
    refreshHistory();
  });
  btnResumeVideo.addEventListener("click", () => {
    btnResumeVideo.disabled = true;
    videoTaskStatus.textContent = "Checking the existing job. Download starts when ready.";
    chrome.runtime.sendMessage({ action: "RESUME_VIDEO_JOB", jobId: jobSelect.value }, response => {
      if (chrome.runtime.lastError || response?.status !== "ok") showError(videoTaskStatus, chrome.runtime.lastError?.message || response?.message);
      else videoTaskStatus.textContent = "Download is ready. Check the download status below.";
      btnResumeVideo.disabled = false;
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
    try { configuredServer = FoveaUI.serverUrl(defaultUrl); } catch (_) {}
    serverInput.value = configuredServer;
    updateNodeButtons(configuredServer);
  });

  async function saveServer(value) {
    const status = document.getElementById("serverStatus");
    try {
      const val = await FoveaUI.allowServer(value.trim());
      await chrome.storage.local.set({ serverUrl: val });
      configuredServer = val;
      serverInput.value = val;
      updateNodeButtons(val);
      status.textContent = "Server saved.";
    } catch (error) { showError(status, error); }
  }
  document.getElementById("btnSaveServer").addEventListener("click", () => saveServer(serverInput.value));

  if (btnCloud) {
    btnCloud.addEventListener("click", () => {
      serverInput.value = "https://mv.fovea.si";
      saveServer("https://mv.fovea.si");
    });
  }

  if (btnLocal) {
    btnLocal.addEventListener("click", () => {
      serverInput.value = "http://127.0.0.1:8000";
      saveServer("http://127.0.0.1:8000");
    });
  }

  // 获取当前活跃标签页
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (!tab || !tab.url || !/^https:\/\/(?:[^/]+\.)?suno\.com\//i.test(tab.url)) {
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
      downloadStatus.textContent = "MP3 and MP4 require a published song. Use Publish in Suno’s (…) menu first.";
    } else {
      publishStatusEl.textContent = response.is_public === true ? "● Published — ready for MP3 / MP4" : "Publication status unknown — the server will check";
      btnExport.disabled = false;
      btnExport.title = "Align lyrics and create a vertical MP4";
    }
  });

  btnDownloadMp3.addEventListener("click", async () => {
    btnDownloadMp3.disabled = true;
    downloadStatus.textContent = "Checking song audio…";
    // Re-query on click so switching tracks after opening the popup cannot
    // accidentally download the previously displayed song.
    chrome.tabs.sendMessage(tab.id, { action: "GET_TRACK_INFO" }, async (track) => {
      if (chrome.runtime.lastError || !track) {
        downloadStatus.textContent = "Cannot read the song. Refresh Suno and try again.";
        btnDownloadMp3.disabled = false;
        return;
      }
      songNameEl.textContent = track.title || "Unknown track";
      try {
        if (track.is_public === false) throw new Error("Song is not published. Publish it in Suno first.");
        if (!await FoveaUI.consent(configuredServer, "audio")) { btnDownloadMp3.disabled = false; return; }
        await FoveaUI.allowAudio(track);
      }
      catch (error) { showError(downloadStatus, error); btnDownloadMp3.disabled = false; return; }
      chrome.runtime.sendMessage({ action: "DOWNLOAD_TRACK_MP3", track, serverUrl: configuredServer }, (response) => {
        const error = chrome.runtime.lastError;
        if (error || response?.status !== "ok") showError(downloadStatus, error?.message || response?.message);
        else downloadStatus.textContent = `Downloading ${response.data.filename}. Check the download status below.`;
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
