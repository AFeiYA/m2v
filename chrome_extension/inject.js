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

  const UI_BLACKLIST = new Set([
    "liked songs", "liked so", "liked", "create", "library", "explore",
    "studio", "trash", "trending", "home", "playlists", "search",
    "similar", "simple", "advanced", "sounds", "lyrics", "history",
    "dislikes", "suno", "untitled", "my library", "feed", "tracks",
    "playlist", "add a caption"
  ]);

  function isValidSongTitle(t) {
    if (!t || typeof t !== "string") return false;
    const clean = t.trim().toLowerCase();
    if (clean.length < 1 || clean.length > 100) return false;
    if (UI_BLACKLIST.has(clean)) return false;
    if (clean.startsWith("liked song") || clean.startsWith("liked so")) return false;
    if (clean === "create" || clean.startsWith("create ")) return false;
    return true;
  }

  // 监听音频播放事件，捕获当前活跃曲目的 UUID 并通知 content.js
  document.addEventListener("play", (e) => {
    try {
      const audio = e.target;
      if (audio && (audio.src || audio.currentSrc)) {
        const src = audio.currentSrc || audio.src;
        const m = src.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
        if (m) {
          window.__FOVEA_CURRENT_PLAYING_CLIP_ID__ = m[1];
        }
      }
      setTimeout(() => {
        const track = getTrackInfo();
        window.postMessage({ type: "FOVEA_REPORT_TRACK_INFO", track }, "*");
      }, 300);
    } catch (_) {}
  }, true);

  // 3. 提取歌曲元数据与 Publish (公开) 状态
  function getTrackInfo() {
    let title = "";
    let artist = "Suno Creator";
    let prompt = "";
    let songId = window.__FOVEA_CURRENT_PLAYING_CLIP_ID__ || "";
    let is_public = true;
    let coverUrl = "";

    // 1. 从 URL 提取 songId (若位于 /song/xxx 或 /s/xxx)
    const m = window.location.pathname.match(/(?:song|s)\/([0-9a-zA-Z_-]+)/);
    if (m) songId = m[1];

    // 2. 从页面活跃 <audio> 提取 UUID
    const audios = Array.from(document.querySelectorAll("audio"));
    const activeAudio =
      audios.find((a) => !a.paused) || audios.find((a) => a.currentTime > 0) || audios[0];
    if (activeAudio) {
      const src = activeAudio.currentSrc || activeAudio.src || "";
      const uuidMatch = src.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
      if (uuidMatch && !songId) {
        songId = uuidMatch[1];
      }
    }

    // 3. 优先级 A: 系统级 MediaSession (Suno 播放时由其 Web 音频播放引擎写入，100% 精准对应当前曲目)
    if (navigator.mediaSession && navigator.mediaSession.metadata) {
      const msMeta = navigator.mediaSession.metadata;
      if (isValidSongTitle(msMeta.title)) {
        title = msMeta.title.trim();
      }
      if (msMeta.artist && msMeta.artist.trim()) {
        artist = msMeta.artist.trim();
      }
      if (msMeta.artwork && msMeta.artwork.length > 0) {
        const lastArt = msMeta.artwork[msMeta.artwork.length - 1];
        if (lastArt && lastArt.src) coverUrl = lastArt.src;
      }
    }

    // 4. 优先级 B: 扫描底部常驻播放器 (Bottom Player Bar)
    // 包含当前播放中的封面缩略图与指向 /song/{id} 的歌名链接
    const playerBar = document.querySelector(
      "footer, [data-testid*='player'], [class*='player-bar'], [class*='bottom-0']"
    );
    if (playerBar) {
      const playerSongLink = playerBar.querySelector("a[href*='/song/'], a[href*='/s/']");
      if (playerSongLink) {
        const linkTxt = playerSongLink.innerText.trim();
        if (isValidSongTitle(linkTxt) && !title) {
          title = linkTxt;
        }
        const mSong = playerSongLink.getAttribute("href")?.match(/(?:song|s)\/([0-9a-zA-Z_-]+)/);
        if (mSong && !songId) {
          songId = mSong[1];
        }
      }
      const playerCover = playerBar.querySelector("img[src*='suno.ai'], img[src*='image_']");
      if (playerCover && playerCover.src && !coverUrl) {
        coverUrl = playerCover.src;
      }
    }

    // 5. 优先级 C: 详情页 / 主内容展示区 (排除侧边栏与导航)
    if (!title) {
      const mainHeadings = document.querySelectorAll(
        "main h1, main h2, main [role='heading'], [data-testid*='song-detail'] h1, [data-testid*='song-detail'] h2, [class*='songDetail'] h1"
      );
      for (const h of mainHeadings) {
        const txt = (h.innerText || "").trim();
        if (isValidSongTitle(txt)) {
          title = txt;
          break;
        }
      }
    }

    if (!title) {
      const allHeadings = document.querySelectorAll("h1, h2, h3, [role='heading']");
      for (const h of allHeadings) {
        if (h.closest("nav, aside, [role='navigation'], [class*='sidebar'], [class*='left-pane']")) {
          continue;
        }
        const txt = (h.innerText || "").trim();
        if (isValidSongTitle(txt)) {
          title = txt;
          break;
        }
      }
    }

    if (!title) {
      const rawTitle = (document.title || "")
        .replace(/\|.*$/g, "")
        .replace(/- Suno.*$/i, "")
        .trim();
      if (isValidSongTitle(rawTitle)) {
        title = rawTitle;
      }
    }

    // 6. 优先级 D: 从全局拦截的 API 数据缓存中检查公开状态并补全
    if (songId && window.__FOVEA_CLIPS__[songId]) {
      const clip = window.__FOVEA_CLIPS__[songId];
      if (clip.is_public === false) {
        is_public = false;
      }
      if (clip.title && isValidSongTitle(clip.title)) title = clip.title;
      if (clip.display_name || clip.handle) artist = clip.display_name || clip.handle;
      if (clip.metadata && clip.metadata.prompt) prompt = clip.metadata.prompt;
      if (!coverUrl) coverUrl = clip.image_large_url || clip.image_url || "";
    } else if (title) {
      // 通过标题在已拦截的 clips 中反向匹配对应 clip
      const matched = Object.values(window.__FOVEA_CLIPS__).find(
        (c) => c.title && c.title.trim().toLowerCase() === title.toLowerCase()
      );
      if (matched) {
        songId = matched.id;
        if (matched.is_public === false) is_public = false;
        if (matched.display_name || matched.handle) artist = matched.display_name || matched.handle;
        if (matched.metadata && matched.metadata.prompt) prompt = matched.metadata.prompt;
        if (!coverUrl) coverUrl = matched.image_large_url || matched.image_url || "";
      }
    }

    // 7. 提取作者
    if (artist === "Suno Creator") {
      const authorEl = document.querySelector("a[href*='/@']");
      if (authorEl && authorEl.innerText.trim()) {
        artist = authorEl.innerText.trim().replace(/^@/, "");
      }
    }

    // 8. 提取歌词/Prompt
    if (!prompt) {
      const candidates = document.querySelectorAll("pre, [data-testid*='prompt'], [class*='lyrics']");
      for (const el of candidates) {
        const text = el.innerText || "";
        if (text.includes("[Verse") || text.includes("[Chorus") || text.length > 50) {
          prompt = text.trim();
          break;
        }
      }
    }

    // 9. 提取封面图片
    if (!coverUrl) {
      const coverImg = document.querySelector(
        "img[src*='cdn2.suno.ai/image_'], img[src*='suno.ai/image_'], img[alt*='Cover']"
      );
      if (coverImg && coverImg.src) {
        coverUrl = coverImg.src;
      }
    }

    // 10. 检查页面 DOM 中是否存在未发布 (Publish) 按钮
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
  function returnBlobResult(blob, track, source = "blob", section = "chorus", duration = 30) {
    const reader = new FileReader();
    reader.onloadend = () => {
      window.postMessage(
        {
          type: "FOVEA_CAPTURE_SUCCESS",
          dataUrl: reader.result,
          track,
          source,
          section,
          duration,
        },
        "*"
      );
    };
    reader.readAsDataURL(blob);
  }

  // 5. 执行捕获与导出主流程
  async function handleCapture(section = "chorus", duration = 30) {
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
      returnBlobResult(window.__FOVEA_LAST_BLOB__, track, "hooked_blob", section, duration);
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
            returnBlobResult(blob, track, "audio_blob_src", section, duration);
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
            section,
            duration,
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
          section,
          duration,
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
      const sec = event.data.section || "chorus";
      const dur = event.data.duration !== undefined ? event.data.duration : 30;
      handleCapture(sec, dur).catch((err) => {
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
