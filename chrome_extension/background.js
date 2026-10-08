/**
 * Fovea MV - 后台服务工作线程 (Background Service Worker)
 * 拥有全局跨域权限与下载管理器权限，负责调用后端渲染并自动将 MP4 视频保存至本地。
 */

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
    await onProgress(task);
    if (task.status === "completed") return task.result || {};
    if (["failed", "interrupted"].includes(task.status)) throw new Error(task.error || task.message || "Video creation failed");
    await sleep(2000);
  }
  throw new Error(`Stopped checking after 20 minutes. The job was not cancelled. Click “Resume last video”. Job ID: ${taskId}`);
}

let storageQueue = Promise.resolve();
function changeRecords(key, change) {
  const work = storageQueue.catch(() => {}).then(async () => {
    if (!chrome.storage?.local) return;
    const stored = await chrome.storage.local.get(key);
    const records = change(stored[key] || []);
    await chrome.storage.local.set({ [key]: records });
    return records;
  });
  storageQueue = work;
  return work;
}
function saveJob(job) {
  return changeRecords("videoJobs", jobs => {
    const remaining = jobs.filter(j => j.requestId !== job.requestId && (!job.taskId || j.taskId !== job.taskId) &&
      (Date.now() - (j.updatedAt || Date.now()) < 7 * 86400000 || ["submitting", "pending", "running"].includes(j.status)));
    return [...remaining, { ...job, updatedAt: Date.now() }];
  });
}
function safeServerUrl(value) {
  const url = new URL(value || "https://mv.fovea.si");
  if ((!['localhost', '127.0.0.1'].includes(url.hostname) && url.protocol !== 'https:') ||
      !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error("Use an HTTPS server address, or HTTP for localhost, without a path.");
  }
  return url.origin;
}
async function trackDownload(id, filename, kind, tabId, taskId) {
  await changeRecords("downloads", records => [...records.filter(r => r.id !== id).slice(-49),
    { id, filename, kind, tabId, taskId, state: "in_progress", updatedAt: Date.now() }]);
  if (chrome.downloads.search && chrome.storage?.local) {
    const [item] = await chrome.downloads.search({ id });
    if (item && item.state !== "in_progress") await updateDownload(id, item.state, item.error);
  }
}
async function updateDownload(id, state, error) {
  let record;
  await changeRecords("downloads", records => records.map(r => {
    if (r.id !== id) return r;
    record = { ...r, state, error: error || "", updatedAt: Date.now() };
    return record;
  }));
  if (!record) return;
  if (record.taskId) await changeRecords("videoJobs", jobs => jobs.map(j => j.taskId === record.taskId ?
    { ...j, status: state === "complete" ? "downloaded" : "download_failed", downloadId: id, updatedAt: Date.now() } : j));
  if (record.tabId !== undefined) chrome.tabs.sendMessage(record.tabId,
    { action: "DOWNLOAD_STATUS", download: record }, () => { void chrome.runtime.lastError; });
}
chrome.downloads?.onChanged?.addListener(delta => {
  if (delta.state?.current && delta.state.current !== "in_progress") {
    updateDownload(delta.id, delta.state.current, delta.error?.current).catch(console.error);
  }
});
const activeVideoJobs = new Map();
function finishVideoJob(job, onProgress = () => {}) {
  const key = `${job.targetServer}/${job.taskId}`;
  if (activeVideoJobs.has(key)) return activeVideoJobs.get(key);
  const promise = (async () => {
    if (job.downloadId !== undefined && chrome.downloads.search) {
      const [item] = await chrome.downloads.search({ id: job.downloadId });
      if (item && ["complete", "in_progress"].includes(item.state) && item.exists !== false) return { status: "ok", downloadId: item.id };
      if (item?.state === "interrupted") {
        await chrome.downloads.resume(item.id);
        await saveJob({ ...job, status: "downloading" });
        await trackDownload(item.id, item.filename?.split(/[\\/]/).pop() || `${job.title || 'Video'}.mp4`, "MP4", job.tabId, job.taskId);
        return { status: "ok", downloadId: item.id };
      }
    }
    const result = await pollLyricVideoTask(job.targetServer, job.taskId, async task => {
      if (job.requestId && task.status) {
        Object.assign(job, { status: task.status, progress: task.progress, error: task.error });
        await saveJob(job);
      }
      onProgress(task);
    });
    const rawVideoUrl = result.download_url || result.video_url;
    if (!rawVideoUrl) throw new Error("Server did not return a video download URL");
    const downloadUrl = new URL(rawVideoUrl, job.targetServer).href;
    const suffix = { chorus: "_Chorus", verse1: "_Verse1", intro: "_Intro" }[job.section] || "";
    const filename = `${(job.title || "suno_mv").replace(/[\\/:*?"<>|]/g, "_")}${suffix}_9x16.mp4`;
    const downloadId = await new Promise((resolve, reject) => {
      chrome.downloads.download({ url: downloadUrl, filename, saveAs: false, conflictAction: "uniquify" }, (id) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else if (id === undefined) reject(new Error("Chrome could not start the video download"));
        else resolve(id);
      });
    });
    if (job.requestId) await saveJob({ ...job, downloadId, status: "downloading" });
    await trackDownload(downloadId, filename, "MP4", job.tabId, job.taskId);
    // Do not erase a newer task submitted while this one was rendering.
    const stored = await chrome.storage.local.get("pendingVideoJob");
    if (stored.pendingVideoJob?.taskId === job.taskId) await chrome.storage.local.remove("pendingVideoJob");
    return { status: "ok", result, downloadUrl, filename };
  })().catch(async error => {
    if (job.requestId && /interrupted|Server restarted|not found|Video creation failed/i.test(error.message)) {
      await saveJob({ ...job, status: /interrupted|Server restarted/i.test(error.message) ? "interrupted" : "failed", error: error.message });
    }
    throw error;
  }).finally(() => activeVideoJobs.delete(key));
  activeVideoJobs.set(key, promise);
  return promise;
}

// 调用视频生成并下载 MP4
const activeSubmissions = new Map();
function exportVideoAndDownload(blob, track, serverUrl, section = "", duration = 0, onProgress = () => {}, tabId) {
  const key = JSON.stringify([serverUrl, track.songId, section, duration]);
  if (activeSubmissions.has(key)) return activeSubmissions.get(key);
  const promise = submitVideo(blob, track, serverUrl, section, duration, onProgress, tabId)
    .finally(() => activeSubmissions.delete(key));
  activeSubmissions.set(key, promise);
  return promise;
}
async function submitVideo(blob, track, serverUrl, section, duration, onProgress, tabId) {
  const targetServer = safeServerUrl(serverUrl);
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
  const stored = await chrome.storage.local.get("videoJobs");
  const previous = (stored.videoJobs || []).find(j => j.targetServer === targetServer &&
    j.songId === track.songId && j.section === section && j.duration === duration &&
    ["submitting", "pending", "running", "completed", "downloading", "download_failed"].includes(j.status));
  if (previous?.taskId) return finishVideoJob(previous, onProgress);
  const job = previous || { requestId: crypto.randomUUID(), targetServer, title: track.title,
    songId: track.songId, section, duration, tabId, status: "submitting", track };
  formData.append("request_id", job.requestId);
  await saveJob(job);

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
      body: formData, signal: AbortSignal.timeout(25000),
    });
  } catch (netErr) {
    throw new Error(
      "The server is temporarily unavailable. Resume the saved job to retry safely."
    );
  }

  let data;
  try { data = await readServerResponse(resp); }
  catch (error) {
    if (resp.status >= 400 && resp.status < 500) await saveJob({ ...job, status: "failed", error: error.message });
    throw error;
  }
  const taskId = data.task_id;
  if (!taskId) {
    throw new Error("Server did not return a job ID");
  }

  console.log(`[Fovea MV Background] 任务已提交 (ID: ${taskId})，开始轮询渲染进度...`);

  Object.assign(job, { taskId, status: data.status || "pending" });
  await saveJob(job);
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
  if (track?.is_public === false) throw new Error("Song is not published. Publish it in Suno’s (…) menu before downloading MP3 or MP4.");
  let verified = track?.is_public === true;
  async function verifyPublished() {
    if (!track?.songId || !/^[A-Za-z0-9_-]{1,128}$/.test(track.songId)) throw new Error("Cannot verify publication. Open the song page in Suno and try again.");
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(track.songId);
    const url = new URL(`${safeServerUrl(serverUrl)}/api/suno/publish_status`);
    url.searchParams.set("url", `https://suno.com/${uuid ? "song" : "s"}/${track.songId}`);
    onProgress({ message: "Checking whether the song is published…" });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 35000);
    try {
      const result = await readServerResponse(await fetch(url.href, { signal: controller.signal }));
      if (result.is_public !== true) throw new Error("Song is not published. Use Publish in Suno first.");
      verified = true;
    } finally { clearTimeout(timer); }
  }
  if (!verified) await verifyPublished();
  try {
    return await downloadOriginalMp3(track);
  } catch (error) {
    const recoverable = !track?.audioUrl || /HTTP (403|404|429|5\d\d)|not MP3|Audio check timed out|Failed to fetch|NetworkError/i.test(error.message);
    if (!track?.songId || !recoverable) throw error;
  }
  const targetServer = safeServerUrl(serverUrl);
  // A stale cached public flag must not turn a private-song error into a
  // failed native download whose JSON body the extension cannot inspect.
  await verifyPublished();
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
    chrome.storage.local.get(["videoJobs", "pendingVideoJob"]).then(({ videoJobs, pendingVideoJob }) => {
      const job = (videoJobs || []).find(j => (j.taskId || j.requestId) === request.jobId) ||
        (!request.jobId || pendingVideoJob?.taskId === request.jobId ? pendingVideoJob : null);
      if (!job) throw new Error("No pending video job");
      if (!job.taskId) return exportVideoAndDownload(null, job.track, job.targetServer, job.section, job.duration, onProgress, sender.tab?.id);
      return finishVideoJob(job, onProgress);
    }).then(data => sendResponse({ status: "ok", data }))
      .catch(error => sendResponse({ status: "error", message: error.message }));
    return true;
  }
  if (request.action === "DOWNLOAD_TRACK_MP3") {
    downloadTrackMp3(request.track, request.serverUrl, task => {
      if (sender.tab?.id !== undefined) chrome.tabs.sendMessage(sender.tab.id,
        { action: "MP3_PROGRESS", task }, () => { void chrome.runtime.lastError; });
    })
      .then(async data => {
        await trackDownload(data.downloadId, data.filename, "MP3", sender.tab?.id);
        sendResponse({ status: "ok", data });
      })
      .catch((error) => sendResponse({ status: "error", message: error.message }));
    return true;
  }

  // 1. 直传主世界解密 Blob 并导出 MP4
  if (request.action === "EXPORT_VIDEO_DIRECT_BLOB") {
    try {
      if (!request.track?.songId) throw new Error("Open a song page to create MP4.");
      exportVideoAndDownload(null, request.track, request.serverUrl, request.section, request.duration, onProgress, sender.tab?.id)
        .then((res) => sendResponse({ status: "ok", data: res }))
        .catch((err) => sendResponse({ status: "error", message: err.message }));
    } catch (e) {
      sendResponse({ status: "error", message: `Audio decoding failed: ${e.message}` });
    }
    return true;
  }

  // 2. 代理拉取网络流并导出 MP4
  if (request.action === "EXPORT_VIDEO_FETCH") {
    Promise.resolve().then(() => {
      if (!request.track?.songId) throw new Error("Open a song page to create MP4.");
      return exportVideoAndDownload(null, request.track, request.serverUrl, request.section, request.duration, onProgress, sender.tab?.id);
    })
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }

  // 3. 通过 Song ID 触发一键导出 MP4
  if (request.action === "EXPORT_VIDEO_BY_SONG_ID") {
    exportVideoAndDownload(null, request.track, request.serverUrl, request.section, request.duration, onProgress, sender.tab?.id)
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }
  if (request.action === "RETRY_DOWNLOAD") {
    (async () => {
      const stored = await chrome.storage.local.get("downloads");
      const record = (stored.downloads || []).find(r => r.id === request.downloadId);
      if (!record) throw new Error("Download not found. Download the song again.");
      const [item] = await chrome.downloads.search({ id: record.id });
      if (!item) throw new Error("Download history was removed. Download the song again.");
      try {
        await chrome.downloads.resume(item.id);
        await trackDownload(item.id, record.filename, record.kind, sender.tab?.id, record.taskId);
      } catch (_) {
        const id = await chrome.downloads.download({ url: item.url, filename: record.filename, conflictAction: "uniquify" });
        await trackDownload(id, record.filename, record.kind, sender.tab?.id, record.taskId);
      }
      return { status: "ok" };
    })().then(sendResponse).catch(error => sendResponse({ status: "error", message: error.message }));
    return true;
  }
});

// A sleeping worker can be awakened to reconcile durable jobs. Only completed
// jobs start a download; running jobs are checked once per alarm, not replayed.
async function reconcileJobs() {
  const stored = await chrome.storage.local.get(["videoJobs", "downloads"]);
  for (const record of stored.downloads || []) {
    if (record.state !== "in_progress") continue;
    const [item] = await chrome.downloads.search({ id: record.id });
    if (item && item.state !== "in_progress") await updateDownload(item.id, item.state, item.error);
  }
  for (const job of stored.videoJobs || []) {
    if (!job.taskId || !["pending", "running", "completed"].includes(job.status)) continue;
    try {
      const response = await fetch(`${job.targetServer}/api/lyric_video/task_status?task_id=${encodeURIComponent(job.taskId)}`,
        { signal: AbortSignal.timeout(15000) });
      if (response.status === 404) { await saveJob({ ...job, status: "expired" }); continue; }
      if (!response.ok) continue;
      const task = await readServerResponse(response);
      const latest = (await chrome.storage.local.get("videoJobs")).videoJobs?.find(j => j.taskId === job.taskId);
      if (latest?.downloadId !== undefined) continue;
      const updated = { ...job, status: task.status, progress: task.progress, error: task.error };
      await saveJob(updated);
      if (task.status === "completed") await finishVideoJob(updated);
    } catch (error) { console.warn("Job check deferred:", error.message); }
  }
}
if (chrome.alarms) {
  chrome.alarms.create("fovea-job-check", { periodInMinutes: 1 });
  chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === "fovea-job-check") reconcileJobs().catch(console.error);
  });
  chrome.runtime.onStartup?.addListener(() => reconcileJobs().catch(console.error));
}
