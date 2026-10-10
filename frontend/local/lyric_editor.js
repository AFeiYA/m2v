// ===========================================================================
// M2V Local Editor — Lyric & Subtitle Editor Module (for index.html)
// ===========================================================================

document.addEventListener("DOMContentLoaded", () => {
  // DOM element cache
  dom.songSelect          = $("#song-select");
  dom.btnSave             = $("#btn-save");
  dom.btnUndo             = $("#btn-undo");
  dom.btnRedo             = $("#btn-redo");
  dom.btnRegenAss         = $("#btn-regen-ass");
  dom.sunoUrlInput        = $("#suno-url-input");
  dom.btnStartSunoImport  = $("#btn-start-suno-import");
  dom.sunoProgress        = $("#suno-import-progress");
  dom.sunoProgressText    = $("#suno-progress-text");
  dom.statusMsg           = $("#status-msg");
  dom.waveformVocals      = $("#waveform-vocals");
  dom.waveformInst        = $("#waveform-instrumental");
  dom.btnPlayPause        = $("#btn-play-pause");
  dom.btnPlayLine         = $("#btn-play-line");
  dom.timeDisplay         = $("#time-display");
  dom.zoomSlider          = $("#zoom-slider");
  dom.lyricsList          = $("#lyrics-list");
  dom.wordTitle           = $("#word-panel-title");
  dom.wordTimeline        = $("#word-timeline");
  dom.btnShiftLeft        = $("#btn-shift-left");
  dom.btnNudgeLeft        = $("#btn-nudge-left");
  dom.btnNudgeRight       = $("#btn-nudge-right");
  dom.btnShiftRight       = $("#btn-shift-right");
  dom.btnEvenSplit        = $("#btn-even-split");
  dom.btnPlayWord         = $("#btn-play-word");
  dom.lineEditControls    = $("#line-edit-controls");
  dom.btnLineNudgeLeftBig  = $("#btn-line-nudge-left-big");
  dom.btnLineNudgeLeft     = $("#btn-line-nudge-left");
  dom.btnLineNudgeRight    = $("#btn-line-nudge-right");
  dom.btnLineNudgeRightBig = $("#btn-line-nudge-right-big");
  dom.btnLineExpand       = $("#btn-line-expand");
  dom.btnLineShrink       = $("#btn-line-shrink");
  dom.btnMuteVocals       = $("#btn-mute-vocals");
  dom.btnMuteInst         = $("#btn-mute-instrumental");
  dom.trackVocals         = $("#track-vocals");
  dom.trackInst           = $("#track-instrumental");

  try {
    initWaveSurfer();
  } catch (err) {
    console.warn("WaveSurfer 初始化异常:", err);
  }

  bindLyricEvents();
  loadFileList();
});

// ---------------------------------------------------------------------------
// Lifecycle Hooks
// ---------------------------------------------------------------------------
window.onSongLoaded = () => {
  renderLyrics();
  clearWordPanel();
};

window.onAlignmentChanged = () => {
  renderLyrics();
  if (state.selectedLine >= 0) {
    renderWords(state.selectedLine);
    selectLine(state.selectedLine, { seek: false });
  }
};

window.onPlaybackTick = () => {
  highlightPlayingLine();
};

// ---------------------------------------------------------------------------
// Event Listeners
// ---------------------------------------------------------------------------
function bindLyricEvents() {
  if (dom.songSelect) {
    dom.songSelect.addEventListener("change", () => {
      const idx = dom.songSelect.value;
      if (idx !== "") loadSong(parseInt(idx));
    });
  }
  if (dom.btnSave) dom.btnSave.addEventListener("click", saveAlignment);
  if (dom.btnUndo) dom.btnUndo.addEventListener("click", undo);
  if (dom.btnRedo) dom.btnRedo.addEventListener("click", redo);

  if (dom.btnRegenAss) {
    dom.btnRegenAss.addEventListener("click", async () => {
      if (!state.currentFile) {
        alert("请先选择或加载一首歌曲");
        return;
      }
      status("正在重新生成 ASS 字幕...");
      try {
        const res = await fetch("/api/regen", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            json_path: state.currentFile.json_path,
            mode: "ass",
            render_mode: "apple",
            tag_type: "kf",
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "生成失败");
        status(`🎉 ASS 字幕已生成: ${data.ass_path}`);
        alert(`ASS 字幕生成成功！\n保存路径: ${data.ass_path}`);
      } catch (err) {
        status("生成 ASS 失败: " + err.message, true);
        alert("生成 ASS 失败: " + err.message);
      }
    });
  }

  if (dom.btnPlayPause) dom.btnPlayPause.addEventListener("click", togglePlay);
  if (dom.btnPlayLine) dom.btnPlayLine.addEventListener("click", playSelectedLine);
  if (dom.zoomSlider) {
    dom.zoomSlider.addEventListener("input", () => {
      const z = Number(dom.zoomSlider.value);
      if (ws) ws.zoom(z);
      if (wsInst && instReady) wsInst.zoom(z);
    });
  }

  if (dom.btnShiftLeft) dom.btnShiftLeft.addEventListener("click", () => nudgeWord(-0.05));
  if (dom.btnNudgeLeft) dom.btnNudgeLeft.addEventListener("click", () => nudgeWord(-0.01));
  if (dom.btnNudgeRight) dom.btnNudgeRight.addEventListener("click", () => nudgeWord(0.01));
  if (dom.btnShiftRight) dom.btnShiftRight.addEventListener("click", () => nudgeWord(0.05));
  if (dom.btnEvenSplit) dom.btnEvenSplit.addEventListener("click", evenSplitLine);
  if (dom.btnPlayWord) dom.btnPlayWord.addEventListener("click", playSelectedWord);

  if (dom.btnLineNudgeLeftBig) dom.btnLineNudgeLeftBig.addEventListener("click", () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.2); });
  if (dom.btnLineNudgeLeft) dom.btnLineNudgeLeft.addEventListener("click", () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.05); });
  if (dom.btnLineNudgeRight) dom.btnLineNudgeRight.addEventListener("click", () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.05); });
  if (dom.btnLineNudgeRightBig) dom.btnLineNudgeRightBig.addEventListener("click", () => { if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.2); });
  if (dom.btnLineExpand) dom.btnLineExpand.addEventListener("click", () => { if (state.selectedLine >= 0) resizeLine(state.selectedLine, -0.05, 0.05); });
  if (dom.btnLineShrink) dom.btnLineShrink.addEventListener("click", () => { if (state.selectedLine >= 0) resizeLine(state.selectedLine, 0.05, -0.05); });
  const btnSnapStart = $("#btn-snap-start-playhead");
  if (btnSnapStart) btnSnapStart.addEventListener("click", () => {
    if (state.selectedLine >= 0) snapFirstWordStartToPlayhead(state.selectedLine);
  });
  const btnSnapEnd = $("#btn-snap-end-playhead");
  if (btnSnapEnd) btnSnapEnd.addEventListener("click", () => {
    if (state.selectedLine >= 0) {
      const line = state.alignment?.lines?.[state.selectedLine];
      if (line && line.words?.length) snapSplitToPlayhead(state.selectedLine, line.words.length - 1);
    }
  });

  if (dom.btnMuteVocals) dom.btnMuteVocals.addEventListener("click", () => toggleMuteTrack("vocals"));
  if (dom.btnMuteInst) dom.btnMuteInst.addEventListener("click", () => toggleMuteTrack("instrumental"));

  initLyricExportModal();

  document.addEventListener("keydown", handleLyricKey);
}

// ---------------------------------------------------------------------------
// 动效短视频导出弹窗逻辑
// ---------------------------------------------------------------------------
function initLyricExportModal() {
  const btnOpen = $("#btn-export-lyric-video");
  const modal = $("#lyric-export-modal");
  const btnClose = $("#btn-close-lyric-modal");
  const btnCancel = $("#btn-cancel-lyric-modal");
  const btnStart = $("#btn-start-lyric-export");
  const btnReRender = $("#btn-re-render");
  const progressBox = $("#lyric-render-progress-box");
  const progressBar = $("#lyric-progress-bar");
  const progressText = $("#lyric-progress-text");
  const progressPct = $("#lyric-progress-pct");
  const resultBox = $("#lyric-result-box");
  const resultMeta = $("#lyric-result-meta");
  const resultVideo = $("#lyric-modal-video");
  const btnDownload = $("#btn-download-lyric-mp4");

  if (!btnOpen || !modal) return;

  let currentDurationLimit = 0; // 0 = 全曲, 20 = 20s

  const closeModal = () => {
    modal.style.display = "none";
    if (resultVideo) resultVideo.pause();
  };

  const openModal = () => {
    if (!state.currentFile) {
      alert("请先选择或加载一首歌曲");
      return;
    }
    modal.style.display = "flex";
  };

  btnOpen.addEventListener("click", openModal);
  if (btnClose) btnClose.addEventListener("click", closeModal);
  if (btnCancel) btnCancel.addEventListener("click", closeModal);

  // 点击背景遮罩关闭
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  // 单选比例交互
  $$(".ratio-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      $$(".ratio-option").forEach((o) => {
        o.classList.remove("active");
        o.style.borderColor = "#2d3342";
      });
      opt.classList.add("active");
      opt.style.borderColor = "#10b981";
      const radio = opt.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // 视觉背景交互
  $$(".bg-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      $$(".bg-option").forEach((o) => {
        o.classList.remove("active");
        o.style.borderColor = "#2d3342";
      });
      opt.classList.add("active");
      opt.style.borderColor = "#10b981";
      const radio = opt.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  function parseTimeString(str) {
    if (!str || typeof str !== "string") return null;
    str = str.trim();
    if (!str) return null;
    if (str.includes(":")) {
      const parts = str.split(":");
      if (parts.length === 2) {
        const m = parseFloat(parts[0]) || 0;
        const s = parseFloat(parts[1]) || 0;
        return m * 60 + s;
      } else if (parts.length === 3) {
        const h = parseFloat(parts[0]) || 0;
        const m = parseFloat(parts[1]) || 0;
        const s = parseFloat(parts[2]) || 0;
        return h * 3600 + m * 60 + s;
      }
    }
    const val = parseFloat(str);
    return isNaN(val) ? null : val;
  }

  function formatTimeSec(sec) {
    if (sec == null || isNaN(sec)) return "00:00";
    const m = Math.floor(sec / 60);
    const s = (sec % 60).toFixed(1);
    return `${String(m).padStart(2, "0")}:${parseFloat(s) < 10 ? "0" : ""}${s}`;
  }

  function updateTimeRangeBadge() {
    const badge = $("#export-segment-dur-badge");
    if (!badge) return;
    const st = parseTimeString($("#export-start-time")?.value) || 0.0;
    const et = parseTimeString($("#export-end-time")?.value);
    if (et && et > st) {
      const dur = (et - st).toFixed(1);
      badge.textContent = `片段截取: ${dur}秒 (${formatTimeSec(st)} - ${formatTimeSec(et)})`;
      badge.style.background = "rgba(59, 130, 246, 0.2)";
      badge.style.color = "#60a5fa";
    } else if (st > 0) {
      badge.textContent = `从 ${formatTimeSec(st)} 起直至全曲结束`;
      badge.style.background = "rgba(59, 130, 246, 0.2)";
      badge.style.color = "#60a5fa";
    } else {
      badge.textContent = "全曲完整导出";
      badge.style.background = "rgba(16, 185, 129, 0.15)";
      badge.style.color = "#10b981";
    }
  }

  // 乐段预设按钮绑定
  $$(".btn-sec-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".btn-sec-preset").forEach((b) => {
        b.classList.remove("active");
        b.style.borderColor = "#2d3342";
        b.style.background = "transparent";
        b.style.color = "#8b949e";
      });
      btn.classList.add("active");
      btn.style.borderColor = "#10b981";
      btn.style.background = "rgba(16, 185, 129, 0.2)";
      btn.style.color = "#10b981";

      const preset = btn.dataset.preset;
      const startInp = $("#export-start-time");
      const endInp = $("#export-end-time");

      // 优先从已加载的对齐数据 state.alignment 中读取 sections 与 lines
      const sections = (state.alignment?.sections && state.alignment.sections.length > 0)
        ? state.alignment.sections
        : (state.currentFile?.sections || []);
      const lines = state.alignment?.lines || [];

      if (preset === "full") {
        if (startInp) startInp.value = "00:00";
        if (endInp) endInp.value = "";
      } else if (preset === "chorus") {
        let chStart = null;
        const ch = sections.find((s) => (s.name && s.name.toLowerCase().includes("chorus")) || (s.label && s.label.includes("副歌")));
        if (ch && typeof ch.start === "number") {
          chStart = ch.start;
        } else {
          const lCh = lines.find((l) => (l.section || "").toLowerCase().includes("chorus") || (l.section || "").includes("副歌"));
          if (lCh && typeof lCh.start === "number") {
            chStart = lCh.start;
          }
        }

        if (chStart !== null) {
          const st = chStart;
          const et = chStart + 30.0;
          if (startInp) startInp.value = formatTimeSec(st);
          if (endInp) endInp.value = formatTimeSec(et);
        } else {
          const totalD = state.alignment?.duration || state.duration || 60;
          const st = totalD * 0.35;
          if (startInp) startInp.value = formatTimeSec(st);
          if (endInp) endInp.value = formatTimeSec(st + 30.0);
        }
      } else if (preset === "verse1") {
        let v1Start = null;
        const v1 = sections.find((s) => (s.name && (s.name.toLowerCase().includes("verse") || s.name.toLowerCase().includes("v1"))) || (s.label && s.label.includes("主歌")));
        if (v1 && typeof v1.start === "number") {
          v1Start = v1.start;
        } else {
          const lV1 = lines.find((l) => (l.section || "").toLowerCase().includes("verse") || (l.section || "").includes("主歌"));
          if (lV1 && typeof lV1.start === "number") {
            v1Start = lV1.start;
          }
        }

        if (v1Start !== null) {
          const st = v1Start;
          const et = v1Start + 30.0;
          if (startInp) startInp.value = formatTimeSec(st);
          if (endInp) endInp.value = formatTimeSec(et);
        } else {
          if (startInp) startInp.value = "00:00";
          if (endInp) endInp.value = "00:30";
        }
      }
      updateTimeRangeBadge();
    });
  });

  $("#export-start-time")?.addEventListener("input", updateTimeRangeBadge);
  $("#export-end-time")?.addEventListener("input", updateTimeRangeBadge);

  $("#btn-set-start-curr")?.addEventListener("click", () => {
    const audio = $("#audio-player") || $("#karaoke-audio");
    if (audio) {
      const cur = audio.currentTime || 0;
      const startInp = $("#export-start-time");
      if (startInp) startInp.value = formatTimeSec(cur);
      updateTimeRangeBadge();
    }
  });

  $("#btn-set-end-curr")?.addEventListener("click", () => {
    const audio = $("#audio-player") || $("#karaoke-audio");
    if (audio) {
      const cur = audio.currentTime || 0;
      const endInp = $("#export-end-time");
      if (endInp) endInp.value = formatTimeSec(cur);
      updateTimeRangeBadge();
    }
  });

  $("#btn-reset-time-range")?.addEventListener("click", () => {
    const startInp = $("#export-start-time");
    const endInp = $("#export-end-time");
    if (startInp) startInp.value = "00:00";
    if (endInp) endInp.value = "";
    $$(".btn-sec-preset").forEach((b) => {
      b.classList.toggle("active", b.dataset.preset === "full");
      b.style.borderColor = b.dataset.preset === "full" ? "#10b981" : "#2d3342";
      b.style.background = b.dataset.preset === "full" ? "rgba(16, 185, 129, 0.2)" : "transparent";
      b.style.color = b.dataset.preset === "full" ? "#10b981" : "#8b949e";
    });
    updateTimeRangeBadge();
  });

  if (btnReRender) {
    btnReRender.addEventListener("click", () => {
      resultBox.style.display = "none";
      if (resultVideo) resultVideo.pause();
    });
  }

  // 开始合成
  if (btnStart) {
    btnStart.addEventListener("click", async () => {
      if (!state.currentFile) return;

      const ratio = document.querySelector('input[name="export-ratio"]:checked')?.value || "9:16";
      const bg = document.querySelector('input[name="export-bg"]:checked')?.value || "full_bleed";
      const template = $("#export-template-select")?.value || "apple";
      const theme = $("#export-theme-select")?.value || "apple_white";

      const st = parseTimeString($("#export-start-time")?.value) || 0.0;
      const et = parseTimeString($("#export-end-time")?.value);
      const durLimit = (et && et > st) ? (et - st) : null;

      btnStart.disabled = true;
      btnStart.textContent = "⏳ 合成中，请稍候...";
      btnStart.style.opacity = "0.6";

      progressBox.style.display = "block";
      resultBox.style.display = "none";
      progressBar.style.width = "5%";
      progressText.textContent = "正在提交短视频任务...";
      progressPct.textContent = "5%";

      try {
        const res = await fetch("/api/lyric_video/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            json_path: state.currentFile.json_path,
            aspect_ratio: ratio,
            template: template,
            theme: theme,
            background_mode: bg,
            duration_limit: durLimit,
            start_time: st,
            end_time: et,
          }),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "任务提交失败");

        const taskId = data.task_id;

        // 轮询任务进度
        const pollInterval = setInterval(async () => {
          try {
            const sRes = await fetch(`/api/lyric_video/task_status?task_id=${taskId}`);
            if (!sRes.ok) return;
            const task = await sRes.json();

            const prog = Math.round(task.progress || 0);
            progressBar.style.width = `${prog}%`;
            progressPct.textContent = `${prog}%`;
            progressText.textContent = task.message || "视频渲染中...";

            if (task.status === "completed") {
              clearInterval(pollInterval);
              btnStart.disabled = false;
              btnStart.textContent = "🚀 立即开始合成短视频";
              btnStart.style.opacity = "1";
              progressBox.style.display = "none";

              // 展示结果
              const result = task.result || {};
              resultBox.style.display = "flex";
              resultMeta.textContent = `${result.resolution ? result.resolution.join('x') : ''} · ${result.size_mb || 0}MB · 耗时 ${result.elapsed_seconds || 0}s`;

              if (resultVideo && result.video_url) {
                resultVideo.src = result.video_url;
                resultVideo.load();
                resultVideo.play().catch(() => {});
              }
              if (btnDownload && result.video_url) {
                btnDownload.href = result.video_url;
                btnDownload.download = result.video_url.split("/").pop() || "lyric_video.mp4";
              }
              status("🎉 动效短视频已生成完成！");
            } else if (task.status === "failed") {
              clearInterval(pollInterval);
              btnStart.disabled = false;
              btnStart.textContent = "🚀 立即开始合成短视频";
              btnStart.style.opacity = "1";
              progressBox.style.display = "none";
              alert("短视频合成失败: " + (task.error || task.message));
              status("短视频合成失败", true);
            }
          } catch (e) {
            console.error("轮询异常:", e);
          }
        }, 800);

      } catch (err) {
        btnStart.disabled = false;
        btnStart.textContent = "🚀 立即开始合成短视频";
        btnStart.style.opacity = "1";
        progressBox.style.display = "none";
        alert("短视频任务异常: " + err.message);
        status("导出短视频失败: " + err.message, true);
      }
    });
  }
}

function handleLyricKey(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const ctrl = e.ctrlKey || e.metaKey;
  switch (true) {
    case e.code === "Space": e.preventDefault(); togglePlay(); break;
    case ctrl && e.code === "KeyS": e.preventDefault(); saveAlignment(); break;
    case ctrl && e.code === "KeyZ" && !e.shiftKey: e.preventDefault(); undo(); break;
    case ctrl && (e.code === "KeyY" || (e.code === "KeyZ" && e.shiftKey)): e.preventDefault(); redo(); break;
    case e.code === "ArrowLeft" && !ctrl: e.preventDefault(); nudgeWord(-0.01); break;
    case e.code === "ArrowRight" && !ctrl: e.preventDefault(); nudgeWord(0.01); break;
    case e.code === "KeyA" && !ctrl: e.preventDefault(); nudgeWord(-0.05); break;
    case e.code === "KeyD" && !ctrl: e.preventDefault(); nudgeWord(0.05); break;
    case e.code === "ArrowUp": e.preventDefault(); selectAdjacentLine(-1); break;
    case e.code === "ArrowDown": e.preventDefault(); selectAdjacentLine(1); break;
    case e.code === "Enter": e.preventDefault(); playSelectedLine(); break;
    case e.code === "Tab" && !ctrl: e.preventDefault(); selectAdjacentWord(e.shiftKey ? -1 : 1); break;
    case e.code === "BracketLeft" && !ctrl && !e.shiftKey: e.preventDefault(); if (state.selectedLine >= 0) nudgeLine(state.selectedLine, -0.05); break;
    case e.code === "BracketRight" && !ctrl && !e.shiftKey: e.preventDefault(); if (state.selectedLine >= 0) nudgeLine(state.selectedLine, 0.05); break;
    case e.code === "BracketLeft" && !ctrl && e.shiftKey: e.preventDefault(); if (state.selectedLine >= 0) resizeLine(state.selectedLine, -0.05, 0.05); break;
    case e.code === "BracketRight" && !ctrl && e.shiftKey: e.preventDefault(); if (state.selectedLine >= 0) resizeLine(state.selectedLine, 0.05, -0.05); break;
  }
}

// ---------------------------------------------------------------------------
// Lyrics Panel
// ---------------------------------------------------------------------------
function renderLyrics() {
  if (!dom.lyricsList) return;
  const lines = state.alignment?.lines || [];
  const sections = state.alignment?.sections || [];
  dom.lyricsList.innerHTML = "";

  // 1. 如果有前奏 (Intro) 且不包含歌词行，先在顶部渲染前奏卡片
  const introSec = sections.find(s => s.name && s.name.toLowerCase().includes("intro") && (!s.line_indices || s.line_indices.length === 0));
  if (introSec) {
    const introDiv = document.createElement("div");
    introDiv.className = "section-header section-intro";
    introDiv.title = "双击从前奏开始播放";
    introDiv.innerHTML = `
      <div class="sec-left">
        <span class="sec-badge">🎵 ${escHtml(introSec.label || introSec.name)}</span>
        ${introSec.style ? `<span class="sec-style" title="${escHtml(introSec.style)}">${escHtml(introSec.style)}</span>` : ""}
      </div>
      <span class="sec-time">${fmtTimeShort(introSec.start)} → ${fmtTimeShort(introSec.end)}</span>
    `;
    introDiv.addEventListener("dblclick", () => {
      if (ws) {
        ws.setTime(introSec.start); ws.play(); if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
        if (wsInst && instReady) { wsInst.setTime(introSec.start); wsInst.play(); }
      }
    });
    dom.lyricsList.appendChild(introDiv);
  }

  let lastSectionName = "";

  lines.forEach((line, i) => {
    // 检查是否有新乐段开始
    const matchedSec = sections.find(s => s.line_indices && s.line_indices[0] === i);
    const lineSecName = line.section || (matchedSec ? matchedSec.name : "");

    if (matchedSec || (lineSecName && lineSecName !== lastSectionName)) {
      lastSectionName = lineSecName;
      const secLabel = matchedSec?.label || lineSecName;
      const secStyle = matchedSec?.style || "";
      const secStart = matchedSec ? matchedSec.start : line.start;
      const secEnd = matchedSec ? matchedSec.end : line.end;
      const isOutro = lineSecName.toLowerCase().includes("outro");

      const secDiv = document.createElement("div");
      secDiv.className = `section-header ${isOutro ? "section-outro" : ""}`;
      secDiv.title = "双击从本乐段开始播放";
      secDiv.innerHTML = `
        <div class="sec-left">
          <span class="sec-badge">🔖 ${escHtml(secLabel)}</span>
          ${secStyle ? `<span class="sec-style" title="${escHtml(secStyle)}">${escHtml(secStyle)}</span>` : ""}
        </div>
        <span class="sec-time">${fmtTimeShort(secStart)} → ${fmtTimeShort(secEnd)}</span>
      `;
      secDiv.addEventListener("dblclick", () => {
        if (ws) {
          ws.setTime(secStart); ws.play(); if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
          if (wsInst && instReady) { wsInst.setTime(secStart); wsInst.play(); }
        }
      });
      dom.lyricsList.appendChild(secDiv);
    }

    const row = document.createElement("div");
    row.className = "lyric-row";
    row.dataset.idx = i;
    const charSpans = renderLineCharSpans(line, i);
    const dur = (line.end - line.start).toFixed(1);
    row.innerHTML = `
      <span class="lyric-num">${i + 1}</span>
      <span class="lyric-text">${charSpans}</span>
      <span class="lyric-time-edit">
        <input type="text" class="time-input line-start-input" value="${fmtTimeShort(line.start)}" data-field="start" data-idx="${i}" title="行起始时间">
        <span class="time-arrow">→</span>
        <input type="text" class="time-input line-end-input" value="${fmtTimeShort(line.end)}" data-field="end" data-idx="${i}" title="行结束时间">
        <span class="line-dur">${dur}s</span>
        <button class="line-nudge-btn" data-idx="${i}" data-delta="-0.1" title="整行前移100ms">◁</button>
        <button class="line-nudge-btn" data-idx="${i}" data-delta="0.1" title="整行后移100ms">▷</button>
      </span>`;
    row.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      selectLine(i);
    });
    row.addEventListener("dblclick", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      if (ws) {
        ws.setTime(line.start); ws.play(); if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
        if (wsInst && instReady) { wsInst.setTime(line.start); wsInst.play(); }
      }
    });
    dom.lyricsList.appendChild(row);
  });

  dom.lyricsList.querySelectorAll(".time-input").forEach(input => {
    input.addEventListener("change", handleLineTimeInput);
    input.addEventListener("keydown", (e) => { if (e.code === "Enter") e.target.blur(); e.stopPropagation(); });
    input.addEventListener("focus", (e) => e.target.select());
  });

  dom.lyricsList.querySelectorAll(".line-nudge-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      nudgeLine(Number(btn.dataset.idx), Number(btn.dataset.delta));
    });
  });
}

function selectLine(idx, options = {}) {
  const { seek = true, scroll = false } = options;
  state.selectedLine = idx;
  state.selectedWord = -1;
  $$(".lyric-row").forEach((row, i) => row.classList.toggle("selected", i === idx));
  const line = state.alignment?.lines?.[idx];
  if (seek && ws && line) ws.setTime(line.start);
  if (scroll) {
    const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${idx}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  if (dom.lineEditControls) dom.lineEditControls.style.display = idx >= 0 ? "flex" : "none";
  renderWords(idx);
}

function selectAdjacentLine(delta) {
  const lines = state.alignment?.lines || [];
  if (!lines.length) return;
  let next = Math.max(0, Math.min(state.selectedLine + delta, lines.length - 1));
  selectLine(next, { scroll: true });
}

function highlightPlayingLine() {
  if (!ws || !state.alignment) return;
  const t = ws.getCurrentTime();
  const lines = state.alignment.lines;
  let activeLineIdx = -1;

  $$(".lyric-row").forEach((row, i) => {
    const line = lines[i];
    const playing = line && t >= line.start && t <= line.end;
    row.classList.toggle("playing", playing);
    if (playing) activeLineIdx = i;
  });

  $$(".lyric-char").forEach((span) => {
    const li = Number(span.dataset.line), wi = Number(span.dataset.word);
    const line = lines[li]; if (!line) { span.classList.remove("sung","singing"); return; }
    const w = line.words[wi]; if (!w) { span.classList.remove("sung","singing"); return; }
    if (t >= w.end) { span.classList.add("sung"); span.classList.remove("singing"); }
    else if (t >= w.start) { span.classList.add("singing"); span.classList.remove("sung"); }
    else { span.classList.remove("sung","singing"); }
  });

  if (activeLineIdx >= 0 && activeLineIdx !== state.selectedLine) {
    selectLine(activeLineIdx, { seek: false, scroll: true });
  }

  if (activeLineIdx >= 0 && activeLineIdx === state.selectedLine) {
    const line = lines[activeLineIdx];
    $$(".word-bar").forEach((bar) => {
      const wi = Number(bar.dataset.idx), w = line.words[wi];
      if (!w) { bar.classList.remove("bar-singing"); return; }
      bar.classList.toggle("bar-singing", t >= w.start && t < w.end);
    });
  }

  if (activeLineIdx >= 0) {
    const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${activeLineIdx}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

// ---------------------------------------------------------------------------
// Word Panel
// ---------------------------------------------------------------------------
function renderWords(lineIdx) {
  const line = state.alignment?.lines?.[lineIdx];
  if (!line) { clearWordPanel(); return; }

  const lineDurMs = ((line.end - line.start) * 1000).toFixed(0);
  dom.wordTitle.textContent = `第 ${lineIdx + 1} 行 [${fmtTimeShort(line.start)} → ${fmtTimeShort(line.end)}, ${lineDurMs}ms]: ${line.text}`;
  const words = line.words || [];
  if (!words.length) { clearWordPanel(); return; }

  const lines = state.alignment?.lines || [];
  const prevLine = lineIdx > 0 ? lines[lineIdx - 1] : null;
  const nextLine = lineIdx < lines.length - 1 ? lines[lineIdx + 1] : null;
  const audioDur = (ws && ws.getDuration && ws.getDuration() > 0) ? ws.getDuration() : (line.end + 30);

  const preGapSec = Math.max(0, prevLine ? (line.start - prevLine.end) : line.start);
  const postGapSec = Math.max(0, nextLine ? (nextLine.start - line.end) : (audioDur - line.end));
  const lineDur = Math.max(0.1, line.end - line.start);

  dom.wordTimeline.innerHTML = "";
  const container = document.createElement("div");
  container.className = "word-bar-container";

  // 1. 前置紧凑标签 (只显示时间，不抢占歌词空间)
  const prePill = document.createElement("div");
  prePill.className = "gap-pill gap-pre";
  const preLabel = preGapSec > 3.0 ? `间奏 ${preGapSec.toFixed(1)}s` : (preGapSec > 0.05 ? `空隙 ${preGapSec.toFixed(2)}s` : `紧接上句`);
  prePill.title = `前置间奏/静音 (${preGapSec.toFixed(2)}s) | 双击或拖拽尾部手柄调节首字起唱时间`;
  prePill.innerHTML = `
    <span class="gap-text">◀ ${preLabel}</span>
    <div class="edge-handle handle-line-start" title="拖拽调节首字起唱 | 双击获取当前播放头时间"></div>
  `;
  // 双击占位块本身直接获取播放头时间轴
  prePill.addEventListener("dblclick", (e) => {
    e.preventDefault(); e.stopPropagation();
    snapFirstWordStartToPlayhead(lineIdx);
  });
  container.appendChild(prePill);

  // 2. 歌词主体容器 (占满剩余所有开阔宽度，单词舒展开阔不挤压)
  const wordsTrack = document.createElement("div");
  wordsTrack.className = "words-track";

  const totalWordsDur = words.reduce((acc, w) => acc + Math.max(0.05, w.end - w.start), 0) || 1.0;

  words.forEach((w, i) => {
    const dur = Math.max(0.02, w.end - w.start);
    const flexGrow = (dur / totalWordsDur) * 100;
    const isNeedsReview = Boolean(w.needs_review || w.unresolved_compound);
    const bar = document.createElement("div");
    bar.className = "word-bar" + (isPunct(w.word) ? " punct" : "") + (i === 0 ? " first-word" : "") + (isNeedsReview ? " needs-review" : "");
    bar.style.flex = `${flexGrow.toFixed(2)} 1 ${isPunct(w.word) ? "18px" : "36px"}`;
    bar.dataset.idx = i;
    bar.title = `${w.word}  ${fmtTime(w.start)} → ${fmtTime(w.end)}  (${(dur * 1000).toFixed(0)}ms)${isNeedsReview ? " [声学边界较弱/连音，建议人工复核]" : ""}`;
    const isInternal = (i < words.length - 1);
    bar.innerHTML = `
      <span>${escHtml(w.word.trim() || w.word)}</span>
      <span class="word-dur">${(dur * 1000).toFixed(0)}</span>
      ${isInternal ? '<div class="drag-handle" title="拖拽分割点 | 双击=对齐至当前播放头"></div>' : ''}
    `;

    bar.addEventListener("click", (e) => {
      if (e.target.classList.contains("drag-handle")) return;
      selectWord(i);
    });
    bar.addEventListener("dblclick", () => {
      if (ws) {
        ws.setTime(w.start); ws.play(); if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
        if (wsInst && instReady) { wsInst.setTime(w.start); wsInst.play(); }
        const stopAt = w.end;
        const check = () => {
          if (ws.getCurrentTime() >= stopAt) {
            ws.pause(); if (wsInst && instReady) wsInst.pause();
            if (dom.btnPlayPause) dom.btnPlayPause.textContent = "▶ 播放";
          } else if (ws.isPlaying()) requestAnimationFrame(check);
        };
        requestAnimationFrame(check);
      }
    });

    if (isInternal) {
      setupDragHandle(bar, i, lineIdx, wordsTrack);
      const handle = bar.querySelector(".drag-handle");
      if (handle) {
        handle.addEventListener("dblclick", (e) => {
          e.preventDefault(); e.stopPropagation();
          snapSplitToPlayhead(lineIdx, i);
        });
      }
    }

    wordsTrack.appendChild(bar);
  });
  container.appendChild(wordsTrack);

  // 3. 后置紧凑标签 (只显示时间)
  const postPill = document.createElement("div");
  postPill.className = "gap-pill gap-post";
  const postLabel = postGapSec > 3.0 ? `间奏 ${postGapSec.toFixed(1)}s` : (postGapSec > 0.05 ? `空隙 ${postGapSec.toFixed(2)}s` : `紧接下句`);
  postPill.title = `后置间歇 (${postGapSec.toFixed(2)}s) | 尾字收唱: ${fmtTimeShort(line.end)} | 双击或拖拽橙色手柄调节收唱点`;
  postPill.innerHTML = `
    <div class="edge-handle handle-line-end" title="拖拽调节尾字收唱 (${fmtTimeShort(line.end)}) | 双击对齐至播放头"></div>
    <span class="gap-text" title="后置间歇时长: ${postGapSec.toFixed(2)}s">${postLabel} ▶</span>
  `;
  postPill.addEventListener("dblclick", (e) => {
    e.preventDefault(); e.stopPropagation();
    const l = state.alignment?.lines?.[lineIdx];
    if (l && l.words?.length) snapSplitToPlayhead(lineIdx, l.words.length - 1);
  });
  container.appendChild(postPill);

  dom.wordTimeline.appendChild(container);

  // 绑定首尾边缘拖拽事件
  setupLineEdgeDragHandle(prePill, postPill, lineIdx, wordsTrack);

  if (words.length > 0 && state.selectedWord < 0) selectWord(0);
}

function clearWordPanel() {
  if (dom.wordTitle) dom.wordTitle.textContent = "点击左侧歌词行查看字级时间";
  if (dom.wordTimeline) dom.wordTimeline.innerHTML = "";
}

function selectWord(idx) {
  state.selectedWord = idx;
  $$(".word-bar").forEach((bar, i) => bar.classList.toggle("selected", i === idx));
}

function selectAdjacentWord(delta) {
  if (state.selectedLine < 0) return;
  const words = state.alignment?.lines?.[state.selectedLine]?.words || [];
  if (!words.length) return;
  selectWord(Math.max(0, Math.min(state.selectedWord + delta, words.length - 1)));
}

// ---------------------------------------------------------------------------
// Word Dragging & Nudging
// ---------------------------------------------------------------------------
function snapFirstWordStartToPlayhead(lineIdx) {
  if (!ws) return;
  const line = state.alignment?.lines?.[lineIdx];
  if (!line || !line.words?.length) return;
  const words = line.words;
  const t = ws.getCurrentTime();
  const lines = state.alignment.lines;
  const prevLine = lineIdx > 0 ? lines[lineIdx - 1] : null;
  const minStart = prevLine ? (prevLine.end + 0.01) : 0.0;
  // 首字起唱点允许在上一句结束与第 2 个字开始之间任意自由调节
  const maxStart = words.length > 1 ? (words[1].start - 0.05) : (line.end - 0.05);

  let targetT = t;
  if (targetT < minStart) {
    status(`⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 早于上一句结束 (${fmtTimeShort(minStart)})，已自动约束在上一句后`, true);
    targetT = minStart;
  } else if (targetT > maxStart) {
    status(`⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 晚于第 2 个字起唱 (${fmtTimeShort(maxStart)})，已自动约束在第 2 字前`, true);
    targetT = maxStart;
  }
  const clamped = Math.round(targetT * 1000) / 1000;

  pushUndo();
  words[0].start = clamped;
  line.start = clamped;

  if (words.length > 1) {
    if (words[0].end <= clamped || words[0].end > words[1].start) {
      words[0].end = words[1].start;
    }
  } else {
    if (words[0].end <= clamped) {
      words[0].end = clamped + 0.5;
      line.end = words[0].end;
    }
  }

  syncLineFromWords(lineIdx);
  renderLyrics();
  renderWords(lineIdx);
  selectLine(lineIdx);
  selectWord(0);
  markDirty();

  const preGap = prevLine ? (line.start - prevLine.end) : line.start;
  status(`🎯 首字起唱点已吸附至播放头: ${fmtTimeShort(clamped)}（前置间奏: ${preGap.toFixed(1)}s）`);
}

function snapSplitToPlayhead(lineIdx, wordIdx) {
  if (!ws) return;
  const line = state.alignment?.lines?.[lineIdx];
  if (!line || !line.words?.length) return;
  const words = line.words;
  const isLast = (wordIdx === words.length - 1);
  const t = ws.getCurrentTime();

  if (isLast) {
    const lines = state.alignment.lines;
    const nextLine = lineIdx < lines.length - 1 ? lines[lineIdx + 1] : null;
    const audioDur = (ws && ws.getDuration ? ws.getDuration() : 9999);
    const maxEnd = nextLine ? (nextLine.start - 0.01) : audioDur;
    const minEnd = words[wordIdx].start + 0.05;

    let targetT = t;
    if (targetT < minEnd) {
      status(`⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 早于尾字起唱 (${fmtTimeShort(minEnd)})`, true);
      targetT = minEnd;
    } else if (targetT > maxEnd) {
      status(`⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 晚于下一句起唱 (${fmtTimeShort(maxEnd)})，已约束在下一句前`, true);
      targetT = maxEnd;
    }
    const clamped = Math.round(targetT * 1000) / 1000;

    pushUndo();
    words[wordIdx].end = clamped;
    line.end = clamped;
    syncLineFromWords(lineIdx);
    renderLyrics();
    renderWords(lineIdx);
    selectLine(lineIdx);
    selectWord(wordIdx);
    markDirty();

    const postGap = nextLine ? (nextLine.start - line.end) : (audioDur - line.end);
    status(`🎯 尾字收唱点已吸附至播放头: ${fmtTimeShort(clamped)}（后置间歇: ${postGap.toFixed(1)}s）`);
  } else {
    const minVal = words[wordIdx].start + 0.01;
    const maxVal = words[wordIdx + 1].end - 0.01;
    const clamped = Math.round(Math.max(minVal, Math.min(maxVal, t)) * 1000) / 1000;
    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;
    pushUndo();
    words[wordIdx].end = clamped;
    delete words[wordIdx].needs_review;
    delete words[wordIdx].unresolved_compound;
    words[wordIdx + 1].start = clamped;
    delete words[wordIdx + 1].needs_review;
    delete words[wordIdx + 1].unresolved_compound;
    syncLineFromWords(lineIdx);
    renderWords(lineIdx);
    selectWord(wordIdx);
    markDirty();
    status(`✂ 分割点 ${wordIdx + 1}|${wordIdx + 2} → ${fmtTimeShort(clamped)}`);
  }
}

function setupLineEdgeDragHandle(prePill, postPill, lineIdx, wordsTrack) {
  const handleStart = prePill.querySelector(".handle-line-start");
  const handleEnd = postPill.querySelector(".handle-line-end");

  if (handleStart) {
    handleStart.addEventListener("dblclick", (e) => {
      e.preventDefault(); e.stopPropagation();
      snapFirstWordStartToPlayhead(lineIdx);
    });

    handleStart.addEventListener("mousedown", (e) => {
      e.preventDefault(); e.stopPropagation();
      const line = state.alignment?.lines?.[lineIdx];
      if (!line || !line.words?.length) return;
      pushUndo();
      const startX = e.clientX;
      const startStart = line.words[0].start;
      const trackWidth = wordsTrack.getBoundingClientRect().width || 400;
      const activeSpan = Math.max(0.1, line.words[line.words.length - 1].end - line.words[0].start);
      const pxPerSec = trackWidth / activeSpan;
      const lines = state.alignment.lines;
      const prevLine = lineIdx > 0 ? lines[lineIdx - 1] : null;
      const minStart = prevLine ? (prevLine.end + 0.01) : 0.0;
      const maxStart = line.words.length > 1 ? (line.words[1].start - 0.05) : (line.end - 0.05);

      document.body.style.cursor = "col-resize";
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        const dt = dx / pxPerSec;
        const newStart = Math.round((startStart + dt) * 1000) / 1000;
        const clamped = Math.max(minStart, Math.min(maxStart, newStart));
        line.words[0].start = clamped;
        line.start = clamped;
        if (line.words.length > 1 && line.words[0].end <= clamped) {
          line.words[0].end = line.words[1].start;
        }
        renderWords(lineIdx);
        selectWord(0);
        markDirty();
      };
      const onUp = () => {
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        syncLineFromWords(lineIdx);
        renderLyrics();
        selectLine(lineIdx);
        selectWord(0);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  if (handleEnd) {
    handleEnd.addEventListener("dblclick", (e) => {
      e.preventDefault(); e.stopPropagation();
      const line = state.alignment?.lines?.[lineIdx];
      if (line && line.words?.length) snapSplitToPlayhead(lineIdx, line.words.length - 1);
    });

    handleEnd.addEventListener("mousedown", (e) => {
      e.preventDefault(); e.stopPropagation();
      const line = state.alignment?.lines?.[lineIdx];
      if (!line || !line.words?.length) return;
      const lastIdx = line.words.length - 1;
      pushUndo();
      const startX = e.clientX;
      const startEnd = line.words[lastIdx].end;
      const trackWidth = wordsTrack.getBoundingClientRect().width || 400;
      const activeSpan = Math.max(0.1, line.words[lastIdx].end - line.words[0].start);
      const pxPerSec = trackWidth / activeSpan;
      const lines = state.alignment.lines;
      const nextLine = lineIdx < lines.length - 1 ? lines[lineIdx + 1] : null;
      const audioDur = (ws && ws.getDuration && ws.getDuration() > 0) ? ws.getDuration() : 9999;
      const maxEnd = nextLine ? (nextLine.start - 0.01) : audioDur;
      const minEnd = line.words[lastIdx].start + 0.05;

      document.body.style.cursor = "col-resize";
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        const dt = dx / pxPerSec;
        const newEnd = Math.round((startEnd + dt) * 1000) / 1000;
        const clamped = Math.max(minEnd, Math.min(maxEnd, newEnd));
        line.words[lastIdx].end = clamped;
        line.end = clamped;
        renderWords(lineIdx);
        selectWord(lastIdx);
        markDirty();
      };
      const onUp = () => {
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        syncLineFromWords(lineIdx);
        renderLyrics();
        selectLine(lineIdx);
        selectWord(lastIdx);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
}

function setupDragHandle(bar, wordIdx, lineIdx, wordsTrack) {
  const handle = bar.querySelector(".drag-handle");
  if (!handle) return;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault(); e.stopPropagation();
    const line = state.alignment?.lines?.[lineIdx];
    if (!line || !line.words?.length) return;
    const words = line.words;
    if (wordIdx >= words.length - 1) return;
    pushUndo();
    const startX = e.clientX;
    const startEnd = words[wordIdx].end;
    const trackWidth = wordsTrack.getBoundingClientRect().width || 400;
    const activeSpan = Math.max(0.1, words[words.length - 1].end - words[0].start);
    const pxPerSec = trackWidth / activeSpan;

    const minEnd = words[wordIdx].start + 0.01;
    const maxEnd = words[wordIdx + 1].end - 0.01;

    document.body.style.cursor = "col-resize";
    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      const dt = dx / pxPerSec;
      const newEnd = Math.round((startEnd + dt) * 1000) / 1000;
      const clamped = Math.max(minEnd, Math.min(maxEnd, newEnd));
      words[wordIdx].end = clamped;
      words[wordIdx + 1].start = clamped;
      renderWords(lineIdx);
      selectWord(wordIdx);
      markDirty();
    };
    const onUp = () => {
      document.body.style.cursor = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      delete words[wordIdx].needs_review;
      delete words[wordIdx].unresolved_compound;
      if (words[wordIdx + 1]) {
        delete words[wordIdx + 1].needs_review;
        delete words[wordIdx + 1].unresolved_compound;
      }
      syncLineFromWords(lineIdx);
      renderWords(lineIdx);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

function nudgeWord(delta) {
  if (state.selectedLine < 0 || state.selectedWord < 0) return;
  const line = state.alignment.lines[state.selectedLine];
  const words = line.words, idx = state.selectedWord;
  if (!words[idx]) return;
  const lines = state.alignment.lines;
  const prevLine = state.selectedLine > 0 ? lines[state.selectedLine - 1] : null;
  const nextLine = state.selectedLine < lines.length - 1 ? lines[state.selectedLine + 1] : null;
  const newStart = Math.round((words[idx].start + delta) * 1000) / 1000;
  const newEnd   = Math.round((words[idx].end + delta) * 1000) / 1000;
  if (newStart < 0 || newEnd < 0) return;
  if (idx === 0 && prevLine && newStart < prevLine.end + 0.01) return;
  if (idx > 0 && newStart < words[idx - 1].start + 0.01) return;
  if (idx < words.length - 1 && newEnd > words[idx + 1].end - 0.01) return;
  if (idx === words.length - 1 && nextLine && newEnd > nextLine.start - 0.01) return;
  pushUndo();
  if (idx > 0) words[idx - 1].end = newStart;
  if (idx < words.length - 1) words[idx + 1].start = newEnd;
  words[idx].start = newStart; words[idx].end = newEnd;
  syncLineFromWords(state.selectedLine);
  renderWords(state.selectedLine); selectWord(idx); markDirty();
}

function evenSplitLine() {
  if (state.selectedLine < 0) return;
  const line = state.alignment.lines[state.selectedLine];
  const words = line.words;
  if (!words.length) return;
  pushUndo();
  const totalDur = line.end - line.start;
  const charCount = words.reduce((sum, w) => sum + w.word.length, 0);
  let t = line.start;
  words.forEach((w) => {
    const dur = (w.word.length / charCount) * totalDur;
    w.start = Math.round(t * 1000) / 1000; t += dur;
    w.end = Math.round(t * 1000) / 1000;
  });
  words[words.length - 1].end = line.end;
  renderWords(state.selectedLine); markDirty();
}

function playSelectedWord() {
  if (state.selectedLine < 0 || state.selectedWord < 0 || !ws) return;
  const w = state.alignment.lines[state.selectedLine]?.words?.[state.selectedWord];
  if (!w) return;
  ws.setTime(w.start); ws.play(); if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
  if (wsInst && instReady) { wsInst.setTime(w.start); wsInst.play(); }
  const stopAt = w.end;
  const check = () => {
    if (ws.getCurrentTime() >= stopAt) {
      ws.pause(); if (wsInst && instReady) wsInst.pause();
      if (dom.btnPlayPause) dom.btnPlayPause.textContent = "▶ 播放";
    } else if (ws.isPlaying()) requestAnimationFrame(check);
  };
  requestAnimationFrame(check);
}

function syncLineFromWords(lineIdx) {
  const line = state.alignment.lines[lineIdx];
  const words = line.words;
  if (!words.length) return;
  line.start = words[0].start; line.end = words[words.length - 1].end;
  const row = dom.lyricsList.querySelector(`.lyric-row[data-idx="${lineIdx}"]`);
  if (row) {
    const si = row.querySelector(`.line-start-input`);
    const ei = row.querySelector(`.line-end-input`);
    if (si) si.value = fmtTimeShort(line.start);
    if (ei) ei.value = fmtTimeShort(line.end);
    const dur = row.querySelector(".line-dur");
    if (dur) dur.textContent = (line.end - line.start).toFixed(1) + "s";
  }
}

// ---------------------------------------------------------------------------
// Line Editing
// ---------------------------------------------------------------------------
function nudgeLine(lineIdx, delta) {
  const line = state.alignment.lines[lineIdx];
  if (!line) return;
  pushUndo();
  const newStart = Math.round((line.start + delta) * 1000) / 1000;
  if (newStart < 0) return;
  line.words.forEach(w => {
    w.start = Math.round((w.start + delta) * 1000) / 1000;
    w.end   = Math.round((w.end + delta) * 1000) / 1000;
  });
  line.start = newStart;
  line.end = Math.round((line.end + delta) * 1000) / 1000;
  renderLyrics(); selectLine(lineIdx); markDirty();
}

function resizeLine(lineIdx, startDelta, endDelta) {
  const line = state.alignment.lines[lineIdx];
  if (!line || !line.words.length) return;
  const oldStart = line.start, oldEnd = line.end, oldDur = oldEnd - oldStart;
  if (oldDur <= 0) return;
  let newStart = Math.round((oldStart + startDelta) * 1000) / 1000;
  let newEnd   = Math.round((oldEnd + endDelta) * 1000) / 1000;
  if (newStart < 0) newStart = 0;
  if (newEnd - newStart < 0.1) return;
  pushUndo();
  const newDur = newEnd - newStart;
  line.words.forEach(w => {
    const relStart = (w.start - oldStart) / oldDur;
    const relEnd   = (w.end - oldStart) / oldDur;
    w.start = Math.round((newStart + relStart * newDur) * 1000) / 1000;
    w.end   = Math.round((newStart + relEnd * newDur) * 1000) / 1000;
  });
  line.start = newStart; line.end = newEnd;
  line.words[0].start = newStart;
  line.words[line.words.length - 1].end = newEnd;
  renderLyrics(); selectLine(lineIdx); markDirty();
}

function handleLineTimeInput(e) {
  const input = e.target;
  const idx = Number(input.dataset.idx), field = input.dataset.field;
  const line = state.alignment?.lines?.[idx];
  if (!line || !line.words?.length) return;
  const parsed = parseTimeInput(input.value);
  if (parsed === null) {
    input.value = fmtTimeShort(line[field]);
    status("时间格式错误，请输入 m:ss.xxx 或 秒数", true); return;
  }
  const lines = state.alignment.lines;
  if (field === "start") {
    const prevLine = idx > 0 ? lines[idx - 1] : null;
    const minStart = prevLine ? (prevLine.end + 0.01) : 0.0;
    const maxStart = line.words.length > 1 ? (line.words[1].start - 0.05) : (line.end - 0.05);
    if (parsed >= minStart && parsed <= maxStart) {
      pushUndo();
      line.words[0].start = Math.round(parsed * 1000) / 1000;
      line.start = line.words[0].start;
      if (line.words.length > 1 && line.words[0].end <= line.words[0].start) {
        line.words[0].end = line.words[1].start;
      }
      syncLineFromWords(idx); renderLyrics(); renderWords(idx); selectLine(idx); markDirty();
      const preGap = prevLine ? (line.start - prevLine.end) : line.start;
      status(`🎯 首字起唱点已调整为 ${fmtTimeShort(line.start)}（前置间奏: ${preGap.toFixed(1)}s）`);
    } else {
      resizeLine(idx, parsed - line.start, 0);
    }
  } else {
    const nextLine = idx < lines.length - 1 ? lines[idx + 1] : null;
    const maxEnd = nextLine ? (nextLine.start - 0.01) : 9999;
    const lastWord = line.words[line.words.length - 1];
    const minEnd = lastWord.start + 0.05;
    if (parsed >= minEnd && parsed <= maxEnd) {
      pushUndo();
      lastWord.end = Math.round(parsed * 1000) / 1000;
      line.end = lastWord.end;
      syncLineFromWords(idx); renderLyrics(); renderWords(idx); selectLine(idx); markDirty();
      const postGap = nextLine ? (nextLine.start - line.end) : 0;
      status(`🎯 尾字收唱点已调整为 ${fmtTimeShort(line.end)}（后置间歇: ${postGap.toFixed(1)}s）`);
    } else {
      resizeLine(idx, 0, parsed - line.end);
    }
  }
}
