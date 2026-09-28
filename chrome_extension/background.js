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

// 轮询短视频生成任务进度
async function pollLyricVideoTask(targetServer, taskId) {
  const maxAttempts = 120; // 最长等待 180 秒
  let attempts = 0;

  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(timer);
        reject(new Error("视频合成超时，请检查后端运行状态"));
        return;
      }

      try {
        const resp = await fetch(`${targetServer}/api/lyric_video/task_status?task_id=${taskId}`);
        if (!resp.ok) return;
        const task = await resp.json();

        if (task.status === "completed") {
          clearInterval(timer);
          resolve(task.result || {});
        } else if (task.status === "failed") {
          clearInterval(timer);
          reject(new Error(task.error || task.message || "短视频合成失败"));
        }
      } catch (e) {
        console.warn("[Fovea MV] 轮询任务进度异常:", e);
      }
    }, 1500);
  });
}

// 调用视频生成并下载 MP4
async function exportVideoAndDownload(blob, track, serverUrl) {
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

  if (!resp.ok) {
    let errDetail = "";
    try {
      const errJson = await resp.json();
      errDetail = errJson.detail || errJson.message || "";
    } catch (_) {
      errDetail = await resp.text();
    }
    throw new Error(errDetail || `后台处理失败 (HTTP ${resp.status})`);
  }

  const data = await resp.json();
  const taskId = data.task_id;
  if (!taskId) {
    throw new Error("后台未返回任务 ID");
  }

  console.log(`[Fovea MV Background] 任务已提交 (ID: ${taskId})，开始轮询渲染进度...`);

  // 轮询直至完成
  const result = await pollLyricVideoTask(targetServer, taskId);
  const rawVideoUrl = result.download_url || result.video_url;
  if (!rawVideoUrl) {
    throw new Error("后台未返回视频下载地址");
  }

  const fullDownloadUrl = rawVideoUrl.startsWith("http")
    ? rawVideoUrl
    : `${targetServer}${rawVideoUrl}`;

  const safeFilename = `${(track.title || "suno_mv").replace(/[\\/:*?"<>|]/g, "_")}_9x16.mp4`;

  console.log("[Fovea MV Background] 视频渲染成功，正在下载:", fullDownloadUrl);

  // 通过 Chrome Downloads API 自动静默下载到本地
  if (chrome.downloads && chrome.downloads.download) {
    chrome.downloads.download({
      url: fullDownloadUrl,
      filename: safeFilename,
      saveAs: false,
    });
  } else {
    // 回退方案: 打开新标签页触发下载
    chrome.tabs.create({ url: fullDownloadUrl });
  }

  return { status: "ok", result, downloadUrl: fullDownloadUrl, filename: safeFilename };
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  // 1. 直传主世界解密 Blob 并导出 MP4
  if (request.action === "EXPORT_VIDEO_DIRECT_BLOB") {
    try {
      const blob = dataUrlToBlob(request.dataUrl);
      exportVideoAndDownload(blob, request.track, request.serverUrl)
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
      .then((blob) => exportVideoAndDownload(blob, request.track, request.serverUrl))
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }

  // 3. 通过 Song ID 触发一键导出 MP4
  if (request.action === "EXPORT_VIDEO_BY_SONG_ID") {
    exportVideoAndDownload(null, request.track, request.serverUrl)
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }
});
