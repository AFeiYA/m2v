/**
 * Fovea MV - Suno 页面主世界脚本 (MAIN World)
 * 在页面加载最早期 (document_start) 注入，全局监听媒体解码与 API 数据包。
 */

(function () {
  window.__FOVEA_MEDIA_BLOBS__ = [];
  window.__FOVEA_CLIPS__ = window.__FOVEA_CLIPS__ || {};

  // 1. 深度拦截 URL.createObjectURL，捕获播放流 Blob
  try {
    const origCreate = URL.createObjectURL;
    URL.createObjectURL = function (obj) {
      if (obj && (obj instanceof Blob || obj instanceof File)) {
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

  // 2. 深度拦截 window.fetch，自动捕获 Suno 的 Clip 数据对象并精准判断 is_public
  try {
    const origFetch = window.fetch;
    window.fetch = async function (...args) {
      const res = await origFetch.apply(this, args);
      try {
        const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url ? args[0].url : "");
        if (url.includes("suno.com") || url.includes("studio-api")) {
          const clone = res.clone();
          clone.json().then((data) => {
            function recordClip(c) {
              if (c && c.id) {
                window.__FOVEA_CLIPS__[c.id] = c;
              }
            }
            if (Array.isArray(data)) {
              data.forEach(recordClip);
            } else if (data && data.clips && Array.isArray(data.clips)) {
              data.clips.forEach(recordClip);
            } else if (data && data.id) {
              recordClip(data);
            }
          }).catch(() => {});
        }
      } catch (e) {}
      return res;
    };
  } catch (e) {
    console.warn("[Fovea MV] 拦截 fetch 异常:", e);
  }

  // 3. 提取歌曲元数据与 Publish (公开) 状态
  function getTrackInfo() {
    let title = "";
    let artist = "Suno Creator";
    let prompt = "";
    let songId = "";
    let is_public = true;
    let coverUrl = "";

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

    // 提取封面图片
    const coverImg = document.querySelector("img[src*='cdn2.suno.ai/image_'], img[src*='suno.ai/image_'], img[alt*='Cover']");
    if (coverImg && coverImg.src) {
      coverUrl = coverImg.src;
    }

    // 从全局拦截的 API 数据缓存中检查公开状态
    if (songId && window.__FOVEA_CLIPS__[songId]) {
      const clip = window.__FOVEA_CLIPS__[songId];
      if (clip.is_public === false) {
        is_public = false;
      }
      if (clip.title) title = clip.title;
      if (clip.display_name || clip.handle) artist = clip.display_name || clip.handle;
      if (clip.metadata && clip.metadata.prompt) prompt = clip.metadata.prompt;
      if (!coverUrl) coverUrl = clip.image_large_url || clip.image_url || "";
    }

    // 检查页面 DOM 中是否存在未发布 (Publish) 按钮
    const allButtons = document.querySelectorAll("button");
    for (const b of allButtons) {
      const t = (b.innerText || "").trim().toLowerCase();
      if (t === "publish" || t === "publish to profile" || t === "发布") {
        is_public = false;
        break;
      }
    }

    return { title: title || "Suno_Track", artist, prompt, songId, coverUrl, is_public };
  }

  // 4. 将 Blob 转换为 DataURL 并回传给 content.js
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

  // 5. 执行捕获与导出主流程
  async function handleCapture() {
    const track = getTrackInfo();

    // 强制校验: 未公开曲目直接拒绝，引导用户先 Publish
    if (track.is_public === false) {
      console.warn("[Fovea MV] 检测到该曲目未公开 (is_public: false)");
      window.postMessage(
        {
          type: "FOVEA_CAPTURE_NOT_PUBLISHED",
          track,
          message: `曲目《${track.title}》尚未公开 (Publish)，无法生成视频！\n💡 请先在 Suno 歌曲右侧菜单（...）中点击【Publish】公开发布后再试。`,
        },
        "*"
      );
      return;
    }

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
    } else if (event.data.type === "FOVEA_QUERY_TRACK_INFO") {
      const track = getTrackInfo();
      window.postMessage(
        {
          type: "FOVEA_REPORT_TRACK_INFO",
          track,
        },
        "*"
      );
    }
  });
})();
