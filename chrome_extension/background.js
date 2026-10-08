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
    throw new Error(`服务器返回非 JSON 响应 (HTTP ${response.status})${summary ? `：${summary}` : ""}`);
  }
  if (!response.ok) {
    const detail = data?.detail || data?.message || data?.error;
    throw new Error(`后台请求失败 (HTTP ${response.status})${detail ? `：${typeof detail === "string" ? detail : JSON.stringify(detail)}` : ""}`);
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`服务器响应格式异常 (HTTP ${response.status})`);
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
        onProgress({ message: "网络暂时中断，正在重新查询；后台任务继续运行。", task_id: taskId });
        await sleep(3000);
        continue;
      }
      if (!resp.ok) {
        const detail = resp.status === 404 ? "任务不存在，后台可能已经重启" : `查询失败 (HTTP ${resp.status})`;
        throw Object.assign(new Error(`${detail}；任务编号：${taskId}`), { terminal: true });
      }
      task = await readServerResponse(resp);
    } catch (error) {
      if (error.terminal) throw error;
      onProgress({ message: "暂时无法查询进度，正在重连；后台任务可能仍在运行。", task_id: taskId });
      await sleep(3000);
      continue;
    }
    onProgress(task);
    if (task.status === "completed") return task.result || {};
    if (task.status === "failed") throw new Error(task.error || task.message || "视频生成失败");
    await sleep(2000);
  }
  throw new Error(`等待进度已超过 20 分钟，后台任务未被取消。请在插件中点击“继续查询上次任务”。任务编号：${taskId}`);
}

const activeVideoJobs = new Map();
function finishVideoJob(job, onProgress = () => {}) {
  const key = `${job.targetServer}/${job.taskId}`;
  if (activeVideoJobs.has(key)) return activeVideoJobs.get(key);
  const promise = (async () => {
    const result = await pollLyricVideoTask(job.targetServer, job.taskId, onProgress);
    const rawVideoUrl = result.download_url || result.video_url;
    if (!rawVideoUrl) throw new Error("后台未返回视频下载地址");
    const downloadUrl = new URL(rawVideoUrl, job.targetServer).href;
    const suffix = { chorus: "_副歌", verse1: "_主歌1", intro: "_前奏" }[job.section] || "";
    const filename = `${(job.title || "suno_mv").replace(/[\\/:*?"<>|]/g, "_")}${suffix}_9x16.mp4`;
    await new Promise((resolve, reject) => {
      chrome.downloads.download({ url: downloadUrl, filename, saveAs: false, conflictAction: "uniquify" }, (id) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else if (id === undefined) reject(new Error("浏览器未能启动视频下载"));
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
      `曲目《${track.title || "当前歌曲"}》尚未公开 (Publish)，无法生成视频！\n💡 请先在 Suno 歌曲右侧菜单（...）中点击【Publish】公开发布后再试。`
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
      `无法连接本地后台服务 (${targetServer})。\n原因: ${netErr.message}。\n请确保终端已运行: .venv/bin/python -m src.local_editor --port 8000`
    );
  }

  const data = await readServerResponse(resp);
  const taskId = data.task_id;
  if (!taskId) {
    throw new Error("后台未返回任务 ID");
  }

  console.log(`[Fovea MV Background] 任务已提交 (ID: ${taskId})，开始轮询渲染进度...`);

  const job = { taskId, targetServer, title: track.title, section };
  await chrome.storage.local.set({ pendingVideoJob: job });
  return finishVideoJob(job, onProgress);
}

// Download original MP3 independently of the alignment/rendering server.
async function downloadOriginalMp3(track) {
  if (!track || !track.audioUrl) {
    throw new Error("未检测到歌曲的 MP3 地址，请刷新 Suno 页面并播放目标歌曲后再试。");
  }
  let url;
  try { url = new URL(track.audioUrl); } catch (_) {
    throw new Error("歌曲音频地址无效，请刷新页面后重试。");
  }
  const allowedHost = ["suno.ai", "suno.com", "cloudfront.net", "amazonaws.com"]
    .some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`));
  if (url.protocol !== "https:" || !allowedHost || url.username || url.password) {
    throw new Error("未检测到可信的 Suno 音频地址。");
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url.href, {
      headers: { Range: "bytes=0-1023" }, signal: controller.signal,
    });
    if (!response.ok) throw new Error(`音频无法下载 (HTTP ${response.status})，请刷新歌曲后重试。`);
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
      throw new Error("当前音频源不是 MP3，无法直接保存为 MP3。请使用 Suno 的原音频下载入口。");
    }
  } catch (error) {
    if (error.name === "AbortError") throw new Error("检查音频超时，请稍后重试。");
    throw error;
  } finally { clearTimeout(timer); }

  const title = String(track.title || "Suno_Track")
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").replace(/^\.+|[. ]+$/g, "").slice(0, 120) || "Suno_Track";
  const filename = `${title}.mp3`;
  const downloadId = await new Promise((resolve, reject) => {
    chrome.downloads.download({ url: url.href, filename, saveAs: false, conflictAction: "uniquify" }, (id) => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(`无法启动下载：${error.message}`));
      else if (id === undefined) reject(new Error("浏览器未能启动音频下载。"));
      else resolve(id);
    });
  });
  return { downloadId, filename };
}

// Original MP3 first; if absent/denied or actually MP4, use the backend's
// existing Suno MP4 audio extraction without running separation/alignment.
async function downloadTrackMp3(track, serverUrl, onProgress = () => {}) {
  try {
    return await downloadOriginalMp3(track);
  } catch (error) {
    const recoverable = !track?.audioUrl || /HTTP (403|404)|不是 MP3/.test(error.message);
    if (!track?.songId || !recoverable) throw error;
  }
  const targetServer = (serverUrl || "https://mv.fovea.si").replace(/\/+$/, "");
  onProgress({ message: "正在通过后台提取 MP4 音轨并转换 MP3，无需歌词对齐…" });
  const form = new FormData();
  form.append("song_id", track.songId);
  form.append("title", track.title || "Suno_Track");
  const data = await readServerResponse(await fetch(`${targetServer}/api/plugin/export_audio`, { method: "POST", body: form }));
  if (!data.task_id) throw new Error("后台未返回音频任务编号");
  const result = await pollLyricVideoTask(targetServer, data.task_id, onProgress);
  if (!result.download_url) throw new Error("后台未返回 MP3 下载地址");
  const downloadId = await new Promise((resolve, reject) => {
    chrome.downloads.download({ url: new URL(result.download_url, targetServer).href,
      filename: result.filename, saveAs: false, conflictAction: "uniquify" }, id => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (id === undefined) reject(new Error("浏览器未能启动 MP3 下载"));
      else resolve(id);
    });
  });
  return { downloadId, filename: result.filename, converted: true };
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const onProgress = (task) => {
    if (sender.tab?.id !== undefined) chrome.tabs.sendMessage(sender.tab.id,
      { action: "EXPORT_PROGRESS", task }, () => { void chrome.runtime.lastError; });
  };
  if (request.action === "RESUME_VIDEO_JOB") {
    chrome.storage.local.get("pendingVideoJob").then(({ pendingVideoJob }) => {
      if (!pendingVideoJob) throw new Error("没有待查询的任务");
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
      sendResponse({ status: "error", message: `音频流解码异常: ${e.message}` });
    }
    return true;
  }

  // 2. 代理拉取网络流并导出 MP4
  if (request.action === "EXPORT_VIDEO_FETCH") {
    fetch(request.url)
      .then((r) => {
        if (!r.ok) throw new Error(`CDN 音频流下载失败 (HTTP ${r.status})`);
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
