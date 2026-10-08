/**
 * Fovea MV - 后台服务工作线程 (Background Service Worker)
 * 拥有全局跨域权限与下载管理器权限，负责调用后端渲染并自动将 MP4 视频保存至本地。
 */

function dataUrlToBlob(dataUrl) {
  const arr = dataUrl.split(",");
  const mime = arr[0].match(/:(.*?);/)[1];
  const bstr = atob(arr[1]);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n);
  }
  return new Blob([u8arr], { type: mime });
}

// Response bodies are single-use: read text once, then parse that string.
async function readServerResponse(response) {
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch (_) {
    const summary = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 240);
    throw new Error(`Server returned a non-JSON response (HTTP ${response.status})${summary ? `：${summary}` : ""}`);
  }
  if (!response.ok) {
    const detail = data?.detail || data?.message || data?.error;
    throw new Error(`Server request failed (HTTP ${response.status})${detail ? `：${typeof detail === "string" ? detail : JSON.stringify(detail)}` : ""}`);
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`Unexpected server response (HTTP ${response.status})`);
  }
  return data;
}

// Each query is bounded and sequential; transient gateway failures do not
// cancel the backend job. A saved ID allows resuming without resubmitting.
async function pollLyricVideoTask(targetServer, taskId, onProgress = () => {}, options = {}) {
  const deadline = Date.now() + (options.timeoutMs ?? 20 * 60 * 1000);
  const sleep = options.sleep || ((ms) => new Promise(resolve => setTimeout(resolve, ms)));
  while (Date.now() < deadline) {
    let task;
    try {
      const resp = await fetch(`${targetServer}/api/lyric_video/task_status?task_id=${encodeURIComponent(taskId)}`,
        { signal: AbortSignal.timeout(15000) });
      if ([429, 502, 503, 504].includes(resp.status)) {
        onProgress({ message: "Connection interrupted. Reconnecting; the job continues on the server.", task_id: taskId });
        await sleep(3000);
        continue;
      }
      if (!resp.ok) {
        const detail = resp.status === 404 ? "Job not found; the server may have restarted" : `Status request failed (HTTP ${resp.status})`;
        throw Object.assign(new Error(`${detail}; job ID: ${taskId}`), { terminal: true });
      }
      task = await readServerResponse(resp);
    } catch (error) {
      if (error.terminal) throw error;
      onProgress({ message: "Unable to fetch progress. Reconnecting; the job may still be running.", task_id: taskId });
      await sleep(3000);
      continue;
    }
    onProgress(task);
    if (task.status === "completed") return task.result || {};
    if (task.status === "failed") throw new Error(task.error || task.message || "Video creation failed");
    await sleep(2000);
  }
  throw new Error(`Stopped checking after 20 minutes. The job was not cancelled. Click “Resume last video”. Job ID: ${taskId}`);
}

const activeVideoJobs = new Map();
function finishVideoJob(job, onProgress = () => {}) {
  const key = `${job.targetServer}/${job.taskId}`;
  if (activeVideoJobs.has(key)) return activeVideoJobs.get(key);
  const promise = (async () => {
    const result = await pollLyricVideoTask(job.targetServer, job.taskId, onProgress);
    const rawVideoUrl = result.download_url || result.video_url;
    if (!rawVideoUrl) throw new Error("Server did not return a video download URL");
    const downloadUrl = new URL(rawVideoUrl, job.targetServer).href;
    const suffix = { chorus: "_Chorus", verse1: "_Verse1", intro: "_Intro" }[job.section] || "";
    const filename = `${(job.title || "suno_mv").replace(/[\\/:*?"<>|]/g, "_")}${suffix}_9x16.mp4`;
    await new Promise((resolve, reject) => {
      chrome.downloads.download({ url: downloadUrl, filename, saveAs: false, conflictAction: "uniquify" }, (id) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else if (id === undefined) reject(new Error("Chrome could not start the video download"));
        else resolve(id);
      });
    });
    // Do not erase a newer task submitted while this one was rendering.
    const stored = await chrome.storage.local.get("pendingVideoJob");
    if (stored.pendingVideoJob?.taskId === job.taskId) await chrome.storage.local.remove("pendingVideoJob");
    return { status: "ok", result, downloadUrl, filename };
  })().finally(() => activeVideoJobs.delete(key));
  activeVideoJobs.set(key, promise);
  return promise;
}

// 调用视频生成并下载 MP4
async function exportVideoAndDownload(blob, track, serverUrl, section = "", duration = 0, onProgress = () => {}) {
  const targetServer = (serverUrl || "https://mv.fovea.si").replace(/\/+$/, "");
  const endpoint = `${targetServer}/api/plugin/export_video`;

  // 严格检查公开状态 (Publish)
  if (track && track.is_public === false) {
    throw new Error(
      `${track.title || "This song"} is not published. Cannot create a video.\n💡 Choose Publish in Suno’s (…) menu and try again.`
    );
  }

  const formData = new FormData();
  if (blob) {
    formData.append("audio_file", blob, `${track.title || "suno_track"}.mp3`);
  }
  formData.append("title", track.title || "Suno_Track");
  formData.append("prompt", track.prompt || "");
  formData.append("artist", track.artist || "unknown");
  formData.append("song_id", track.songId || "");
  formData.append("cover_url", track.coverUrl || "");
  formData.append("is_public", track.is_public !== false ? "true" : "false");
  formData.append("aspect_ratio", "9:16");
  formData.append("template", "apple");
  formData.append("theme", "apple_white");
  formData.append("background_mode", "full_bleed");

  if (section) {
    formData.append("section_name", section);
  }
  if (duration !== undefined && duration !== null) {
    formData.append("duration_limit", String(duration));
  }

  let resp;
  try {
    resp = await fetch(endpoint, {
      method: "POST",
      body: formData,
    });
  } catch (netErr) {
    throw new Error(
      `Cannot connect to the server (${targetServer})。\nReason: ${netErr.message}。\nFor a local server, run: .venv/bin/python -m src.local_editor --port 8000`
    );
  }

  const data = await readServerResponse(resp);
  const taskId = data.task_id;
  if (!taskId) {
    throw new Error("Server did not return a job ID");
  }

  console.log(`[Fovea MV Background] 任务已提交 (ID: ${taskId})，开始轮询渲染进度...`);

  const job = { taskId, targetServer, title: track.title, section };
  await chrome.storage.local.set({ pendingVideoJob: job });
  return finishVideoJob(job, onProgress);
}

// Download original MP3 independently of the alignment/rendering server.
async function downloadOriginalMp3(track) {
  if (!track || !track.audioUrl) {
    throw new Error("No MP3 URL detected. Refresh Suno and play the song.");
  }
  let url;
  try { url = new URL(track.audioUrl); } catch (_) {
    throw new Error("Invalid audio URL. Refresh Suno and try again.");
  }
  const allowedHost = ["suno.ai", "suno.com", "cloudfront.net", "amazonaws.com"]
    .some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`));
  if (url.protocol !== "https:" || !allowedHost || url.username || url.password) {
    throw new Error("No trusted Suno audio URL detected.");
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url.href, {
      headers: { Range: "bytes=0-1023" }, signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Audio download failed (HTTP ${response.status}). Refresh the song and try again.`);
    // Verify the header instead of renaming an MP4/HTML response to .mp3.
    const reader = response.body.getReader();
    const header = [];
    try {
      while (header.length < 10) {
        const { done, value } = await reader.read();
        if (done) break;
        header.push(...value.subarray(0, 1024 - header.length));
      }
    } finally { await reader.cancel(); }
    const id3 = header[0] === 0x49 && header[1] === 0x44 && header[2] === 0x33;
    const mp3Frame = header.length >= 4 && header[0] === 0xff &&
      (header[1] & 0xe0) === 0xe0 && (header[1] & 0x06) === 0x02 &&
      (header[1] & 0x18) !== 0x08 && (header[2] & 0xf0) !== 0 &&
      (header[2] & 0xf0) !== 0xf0 && (header[2] & 0x0c) !== 0x0c;
    if (!id3 && !mp3Frame) {
      throw new Error("The audio source is not MP3 and cannot be downloaded directly.");
    }
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Audio check timed out. Please try again.");
    throw error;
  } finally { clearTimeout(timer); }

  const title = String(track.title || "Suno_Track")
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").replace(/^\.+|[. ]+$/g, "").slice(0, 120) || "Suno_Track";
  const filename = `${title}.mp3`;
  const downloadId = await new Promise((resolve, reject) => {
    chrome.downloads.download({ url: url.href, filename, saveAs: false, conflictAction: "uniquify" }, (id) => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(`Could not start download: ${error.message}`));
      else if (id === undefined) reject(new Error("Chrome could not start the audio download."));
      else resolve(id);
    });
  });
  return { downloadId, filename };
}

// Original MP3 first; otherwise use the editor's existing download-only route.
// Chrome owns the download, including waiting for MP4 audio extraction, so it
// continues even if the popup closes or the service worker goes idle.
async function downloadTrackMp3(track, serverUrl, onProgress = () => {}) {
  try {
    return await downloadOriginalMp3(track);
  } catch (error) {
    const recoverable = !track?.audioUrl || /HTTP (403|404)|not MP3/.test(error.message);
    if (!track?.songId || !recoverable) throw error;
  }
  const targetServer = (serverUrl || "https://mv.fovea.si").replace(/\/+$/, "");
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(track.songId)) throw new Error("Invalid song ID. Refresh Suno and try again.");
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(track.songId);
  const songUrl = `https://suno.com/${uuid ? "song" : "s"}/${track.songId}`;
  const downloadUrl = new URL(`${targetServer}/api/suno/download_mp3`);
  downloadUrl.searchParams.set("url", songUrl);
  const title = String(track.title || "Suno_Track")
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").replace(/^\.+|[. ]+$/g, "").slice(0, 120) || "Suno_Track";
  const filename = `${title}.mp3`;
  onProgress({ message: "Audio download requested. Check Chrome’s downloads for progress." });
  const downloadId = await new Promise((resolve, reject) => {
    chrome.downloads.download({ url: downloadUrl.href,
      filename, saveAs: false, conflictAction: "uniquify" }, id => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (id === undefined) reject(new Error("Chrome could not start the MP3 download"));
      else resolve(id);
    });
  });
  return { downloadId, filename, serverDownload: true };
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const onProgress = (task) => {
    if (sender.tab?.id !== undefined) chrome.tabs.sendMessage(sender.tab.id,
      { action: "EXPORT_PROGRESS", task }, () => { void chrome.runtime.lastError; });
  };
  if (request.action === "RESUME_VIDEO_JOB") {
    chrome.storage.local.get("pendingVideoJob").then(({ pendingVideoJob }) => {
      if (!pendingVideoJob) throw new Error("No pending video job");
      return finishVideoJob(pendingVideoJob, onProgress);
    }).then(data => sendResponse({ status: "ok", data }))
      .catch(error => sendResponse({ status: "error", message: error.message }));
    return true;
  }
  if (request.action === "DOWNLOAD_TRACK_MP3") {
    downloadTrackMp3(request.track, request.serverUrl, task => {
      if (sender.tab?.id !== undefined) chrome.tabs.sendMessage(sender.tab.id,
        { action: "MP3_PROGRESS", task }, () => { void chrome.runtime.lastError; });
    })
      .then((data) => sendResponse({ status: "ok", data }))
      .catch((error) => sendResponse({ status: "error", message: error.message }));
    return true;
  }

  // 1. 直传主世界解密 Blob 并导出 MP4
  if (request.action === "EXPORT_VIDEO_DIRECT_BLOB") {
    try {
      const blob = dataUrlToBlob(request.dataUrl);
      exportVideoAndDownload(blob, request.track, request.serverUrl, request.section, request.duration, onProgress)
        .then((res) => sendResponse({ status: "ok", data: res }))
        .catch((err) => sendResponse({ status: "error", message: err.message }));
    } catch (e) {
      sendResponse({ status: "error", message: `Audio decoding failed: ${e.message}` });
    }
    return true;
  }

  // 2. 代理拉取网络流并导出 MP4
  if (request.action === "EXPORT_VIDEO_FETCH") {
    fetch(request.url)
      .then((r) => {
        if (!r.ok) throw new Error(`CDN audio download failed (HTTP ${r.status})`);
        return r.blob();
      })
      .then((blob) => exportVideoAndDownload(blob, request.track, request.serverUrl, request.section, request.duration, onProgress))
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }

  // 3. 通过 Song ID 触发一键导出 MP4
  if (request.action === "EXPORT_VIDEO_BY_SONG_ID") {
    exportVideoAndDownload(null, request.track, request.serverUrl, request.section, request.duration, onProgress)
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }
});
