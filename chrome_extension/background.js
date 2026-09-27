/**
 * Fovea MV - 后台服务工作线程 (Background Service Worker)
 * 拥有全局权限，负责跨域音轨下载与与本地/云端编辑器的稳定通信。
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

async function uploadToFoveaServer(blob, track, serverUrl) {
  const targetServer = (serverUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const endpoint = `${targetServer}/api/plugin/import`;

  console.log("[Fovea MV Background] 正在上传至:", endpoint, `大小: ${(blob.size / 1024 / 1024).toFixed(2)}MB`);

  const formData = new FormData();
  formData.append("audio_file", blob, `${track.title || "suno_track"}.mp3`);
  formData.append("title", track.title || "Suno_Track");
  formData.append("prompt", track.prompt || "");
  formData.append("artist", track.artist || "unknown");
  formData.append("song_id", track.songId || "");

  let resp;
  try {
    resp = await fetch(endpoint, {
      method: "POST",
      body: formData,
    });
  } catch (netErr) {
    throw new Error(
      `无法连接本地后台服务 (${targetServer})。\n详细原因: ${netErr.message}。\n请确保终端已运行: .venv/bin/python -m src.local_editor --port 8000`
    );
  }

  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`后台处理失败 (HTTP ${resp.status}): ${txt}`);
  }

  const data = await resp.json();
  const targetUrl = data.full_editor_url || `${targetServer}${data.editor_url}`;

  // 自动在新标签页打开编辑器
  chrome.tabs.create({ url: targetUrl });
  return data;
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  // 1. 直传主世界截获的解密 Blob
  if (request.action === "UPLOAD_DIRECT_BLOB") {
    try {
      const blob = dataUrlToBlob(request.dataUrl);
      uploadToFoveaServer(blob, request.track, request.serverUrl)
        .then((res) => sendResponse({ status: "ok", data: res }))
        .catch((err) => sendResponse({ status: "error", message: err.message }));
    } catch (e) {
      sendResponse({ status: "error", message: `音频流解码异常: ${e.message}` });
    }
    return true;
  }

  // 2. 代理下载网络媒体流 (CDN / CloudFront)
  if (request.action === "FETCH_AND_UPLOAD") {
    console.log("[Fovea MV Background] 代理下载音轨:", request.url);
    fetch(request.url)
      .then((r) => {
        if (!r.ok) throw new Error(`CDN 音频流下载失败 (HTTP ${r.status})`);
        return r.blob();
      })
      .then((blob) => uploadToFoveaServer(blob, request.track, request.serverUrl))
      .then((res) => sendResponse({ status: "ok", data: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }

  // 3. 回退方案: 通过 Song ID 导入
  if (request.action === "IMPORT_BY_SONG_ID") {
    const targetServer = (request.serverUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
    const songUrl = `https://suno.com/song/${request.songId}`;
    fetch(`${targetServer}/api/suno/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: songUrl }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const t = await r.text();
          throw new Error(t);
        }
        return r.json();
      })
      .then((data) => {
        const url = `${targetServer}/?song=${encodeURIComponent(data.title || request.track.title)}`;
        chrome.tabs.create({ url });
        sendResponse({ status: "ok", data });
      })
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true;
  }
});
