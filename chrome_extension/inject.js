/**
 * Fovea MV - Suno 页面主世界脚本 (MAIN World)
 * 在页面加载最早期 (document_start) 注入，全局监听媒体解码与 Blob 创建。
 */

(function () {
  window.__FOVEA_MEDIA_BLOBS__ = [];

  // 1. 深度拦截 URL.createObjectURL，精准捕获 Suno Wasm 解密生成的音频 Blob
  try {
    const origCreate = URL.createObjectURL;
    URL.createObjectURL = function (obj) {
      if (obj && (obj instanceof Blob || obj instanceof File)) {
        // 捕获音频流或大于 100KB 的媒体 Blob
        if (
          (obj.type && (obj.type.includes("audio") || obj.type.includes("video") || obj.type.includes("octet-stream"))) ||
          obj.size > 200000
        ) {
          console.log("[Fovea MV] 🎯 捕获到播放流 Blob:", obj.type, `${(obj.size / 1024 / 1024).toFixed(2)}MB`);
          window.__FOVEA_MEDIA_BLOBS__.push(obj);
          window.__FOVEA_LAST_BLOB__ = obj;
        }
      }
      return origCreate.apply(this, arguments);
    };
  } catch (e) {
    console.warn("[Fovea MV] 拦截 createObjectURL 异常:", e);
  }

  // 2. 提取歌曲元数据
  function getTrackInfo() {
    let title = "";
    let artist = "Suno Creator";
    let prompt = "";
    let songId = "";

    // 从 URL 提取 songId
    const m = window.location.pathname.match(/(?:song|s)\/([0-9a-zA-Z_-]+)/);
    if (m) songId = m[1];

    // 从页面 H1 或 Title 提取标题
    const h1 = document.querySelector("h1");
    if (h1 && h1.innerText.trim()) {
      title = h1.innerText.trim();
    } else {
      title = (document.title || "")
        .replace(/\|.*$/g, "")
        .replace(/- Suno.*$/i, "")
        .trim();
    }

    // 提取作者
    const authorEl = document.querySelector("a[href*='/@']");
    if (authorEl && authorEl.innerText.trim()) {
      artist = authorEl.innerText.trim().replace(/^@/, "");
    }

    // 提取歌词/Prompt
    const candidates = document.querySelectorAll("pre, [data-testid*='prompt'], [class*='lyrics']");
    for (const el of candidates) {
      const text = el.innerText || "";
      if (text.includes("[Verse") || text.includes("[Chorus") || text.length > 50) {
        prompt = text.trim();
        break;
      }
    }

    return { title: title || "Suno_Track", artist, prompt, songId };
  }

  // 3. 将 Blob 转换为 DataURL 并回传给 content.js
  function returnBlobResult(blob, track, source = "blob") {
    const reader = new FileReader();
    reader.onloadend = () => {
      window.postMessage(
        {
          type: "FOVEA_CAPTURE_SUCCESS",
          dataUrl: reader.result,
          track,
          source,
        },
        "*"
      );
    };
    reader.readAsDataURL(blob);
  }

  // 4. 执行捕获主流程
  async function handleCapture() {
    const track = getTrackInfo();

    // 优先策略 A: 使用内存拦截捕获到的完整解密 Blob
    if (window.__FOVEA_LAST_BLOB__) {
      console.log("[Fovea MV] 使用拦截到的媒体 Blob 读取音频...");
      returnBlobResult(window.__FOVEA_LAST_BLOB__, track, "hooked_blob");
      return;
    }

    // 优先策略 B: 扫描页面上的 <audio> 标签
    const audios = Array.from(document.querySelectorAll("audio"));
    if (audios.length > 0) {
      const activeAudio =
        audios.find((a) => !a.paused) || audios.find((a) => a.currentTime > 0) || audios[0];
      const src = activeAudio.currentSrc || activeAudio.src;

      console.log("[Fovea MV] 发现播放器 audio.src:", src);

      if (src && src.startsWith("blob:")) {
        try {
          const resp = await window.fetch(src);
          if (resp.ok) {
            const blob = await resp.blob();
            returnBlobResult(blob, track, "audio_blob_src");
            return;
          }
        } catch (err) {
          console.warn("[Fovea MV] 主世界 fetch blob 失败:", err);
        }
      }

      if (src && src.startsWith("http")) {
        // 网络直链转由拥有跨域 host_permissions 的 background service worker 下载
        window.postMessage(
          {
            type: "FOVEA_CAPTURE_NEED_BG_FETCH",
            url: src,
            track,
          },
          "*"
        );
        return;
      }
    }

    // 优先策略 C: 若在 song 详情页且未点播放，检查页面上的 Next.js 初始数据
    if (track.songId) {
      window.postMessage(
        {
          type: "FOVEA_CAPTURE_BY_SONG_ID",
          songId: track.songId,
          track,
        },
        "*"
      );
      return;
    }

    throw new Error(
      `未找到播放流（检测到 ${audios.length} 个播放器）。请先在 Suno 页面点击【播放】试听这首歌曲！`
    );
  }

  // 监听来自 content.js 的指令
  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data) return;
    if (event.data.type === "FOVEA_CAPTURE_REQUEST") {
      handleCapture().catch((err) => {
        window.postMessage(
          {
            type: "FOVEA_CAPTURE_ERROR",
            error: err.message || "截取音频失败",
          },
          "*"
        );
      });
    }
  });
})();
