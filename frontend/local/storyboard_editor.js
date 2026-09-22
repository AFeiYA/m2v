// ===========================================================================
// Suno2MV Local Editor — AI Director & Animatic Studio Module
// ===========================================================================

let selectedAsset = null;
let bgPickerMode = false;
let currentShotIndex = -1;
let activeShot = null;

document.addEventListener("DOMContentLoaded", () => {
  // 基础 DOM
  dom.songSelect          = $("#song-select");
  dom.btnSave             = $("#btn-save");
  dom.btnSetBg            = $("#btn-set-bg");
  dom.bgName              = $("#bg-name");
  dom.btnGenerate         = $("#btn-generate");
  dom.generateModal       = $("#generate-modal");
  dom.btnCloseGenerate    = $("#btn-close-generate");
  dom.btnConfirmGenerate  = $("#btn-confirm-generate");
  dom.statusMsg           = $("#status-msg");

  // 音频播放控制
  dom.waveformVocals      = $("#waveform-vocals");
  dom.waveformInst        = $("#waveform-instrumental");
  dom.btnPlayPause        = $("#btn-play-pause");
  dom.btnPlayLine         = $("#btn-play-line");
  dom.timeDisplay         = $("#time-display");
  dom.zoomSlider          = $("#zoom-slider");
  dom.btnMuteVocals       = $("#btn-mute-vocals");
  dom.btnMuteInst         = $("#btn-mute-instrumental");
  dom.trackVocals         = $("#track-vocals");
  dom.trackInst           = $("#track-instrumental");

  // 歌词列表与传统分镜表格
  dom.lyricsList          = $("#lyrics-list");
  dom.storyboardList      = $("#storyboard-list");
  dom.btnBrowseAssets     = $("#btn-browse-assets");
  dom.assetModal          = $("#asset-modal");
  dom.assetGrid           = $("#asset-grid");
  dom.assetPreview        = $("#asset-preview");
  dom.currentAssetName    = $("#current-asset-name");
  dom.assetStart          = $("#asset-start");
  dom.assetEnd            = $("#asset-end");
  dom.btnAssetSync        = $("#btn-asset-sync");
  dom.btnAssetAdd         = $("#btn-asset-add");
  dom.assetModalClose     = $("#btn-close-asset");
  dom.assetFileInput      = $("#asset-file-input");
  dom.uploadStatus        = $("#upload-status");

  // Animatic Studio 专属 DOM
  dom.btnAutoDirect       = $("#btn-auto-direct");
  dom.btnModeAnimatic     = $("#btn-mode-animatic");
  dom.btnModeTable        = $("#btn-mode-table");
  dom.viewAnimatic        = $("#view-animatic");
  dom.viewTable           = $("#view-table");

  dom.animaticViewport    = $("#animatic-viewport");
  dom.animaticImg         = $("#animatic-img");
  dom.animaticPlaceholder = $("#animatic-empty-placeholder");
  dom.hudShotBadge        = $("#hud-shot-badge");
  dom.hudSpecsBadge       = $("#hud-specs-badge");
  dom.hudLyricBar         = $("#hud-lyric-bar");
  dom.shotsTimelineTrack  = $("#shots-timeline-track");
  dom.timelineShotStats   = $("#timeline-shot-stats");
  dom.animaticStatusSummary = $("#animatic-status-summary");

  // Inspector DOM
  dom.inspectorTitle      = $("#inspector-title");
  dom.inspectorDuration   = $("#inspector-duration-badge");
  dom.inspectorStart      = $("#inspector-start");
  dom.inspectorEnd        = $("#inspector-end");
  dom.inspectorScale      = $("#inspector-scale");
  dom.inspectorMotion     = $("#inspector-motion");
  dom.inspectorAction     = $("#inspector-action");
  dom.inspectorLyric      = $("#inspector-lyric");
  dom.inspectorPrompt     = $("#inspector-prompt");
  dom.inspectorTakesList  = $("#inspector-takes-list");
  dom.btnRenderFrame      = $("#btn-render-current-frame");

  try {
    initWaveSurfer();
  } catch (err) {
    console.warn("WaveSurfer 初始化异常:", err);
  }

  bindStoryboardEvents();
  bindAnimaticEvents();
  loadFileList();
});

// ---------------------------------------------------------------------------
// Lifecycle Hooks
// ---------------------------------------------------------------------------
window.onSongLoaded = () => {
  renderReferenceLyrics();
  renderStoryboard();
  renderAnimaticTimeline();
  updateBgDisplay();
  checkAndInitFirstShot();
};

window.onAlignmentChanged = () => {
  renderReferenceLyrics();
  renderStoryboard();
  renderAnimaticTimeline();
  updateBgDisplay();
};

window.onPlaybackTick = () => {
  highlightReferenceLine();
  syncAnimaticPlayback();
};

// ---------------------------------------------------------------------------
// Event Listeners (Animatic Studio)
// ---------------------------------------------------------------------------
function bindAnimaticEvents() {
  // 视图模式切换
  if (dom.btnModeAnimatic && dom.btnModeTable) {
    dom.btnModeAnimatic.addEventListener("click", () => switchViewMode("animatic"));
    dom.btnModeTable.addEventListener("click", () => switchViewMode("table"));
  }

  // AI 导演一键分镜
  if (dom.btnAutoDirect) {
    dom.btnAutoDirect.addEventListener("click", handleAutoDirect);
  }

  // 检视面板属性变动即时同步
  if (dom.inspectorScale) {
    dom.inspectorScale.addEventListener("change", () => {
      if (!activeShot) return;
      activeShot.shot_size = dom.inspectorScale.value;
      activeShot.scale = dom.inspectorScale.value;
      markDirty();
      updateShotHUD(activeShot);
    });
  }

  if (dom.inspectorMotion) {
    dom.inspectorMotion.addEventListener("change", () => {
      if (!activeShot) return;
      activeShot.camera_motion = dom.inspectorMotion.value;
      activeShot.camera_movement = dom.inspectorMotion.value;
      markDirty();
      applyKenBurnsMotion(dom.inspectorMotion.value);
      updateShotHUD(activeShot);
    });
  }

  if (dom.inspectorAction) {
    dom.inspectorAction.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.action = dom.inspectorAction.value;
      activeShot.prompt_zh = dom.inspectorAction.value;
      markDirty();
    });
  }

  if (dom.inspectorPrompt) {
    dom.inspectorPrompt.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.prompt_en = dom.inspectorPrompt.value;
      markDirty();
    });
  }

  if (dom.btnRenderFrame) {
    dom.btnRenderFrame.addEventListener("click", handleRenderCurrentFrame);
  }
}

function switchViewMode(mode) {
  if (mode === "animatic") {
    dom.viewAnimatic.style.display = "flex";
    dom.viewTable.style.display = "none";
    dom.btnModeAnimatic.classList.add("active");
    dom.btnModeTable.classList.remove("active");
  } else {
    dom.viewAnimatic.style.display = "none";
    dom.viewTable.style.display = "flex";
    dom.btnModeTable.classList.add("active");
    dom.btnModeAnimatic.classList.remove("active");
  }
}

// ---------------------------------------------------------------------------
// AI 导演一键执行
// ---------------------------------------------------------------------------
async function handleAutoDirect() {
  if (!state.currentFile) {
    alert("请先选择一首歌曲工程！");
    return;
  }

  const btn = dom.btnAutoDirect;
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ AI 导演视听编排中...";
  status("🎬 正在执行音乐特征分析、生成 Visual Bible 并编译 30+ 卡点分镜...");

  try {
    const res = await fetch("/api/director/auto_direct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        audio_path: state.currentFile.audio_path,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "请求失败");
    }

    const data = await res.json();
    state.alignment = data.project;

    status(`✅ AI 导演生成成功！共编译 ${data.shots_count} 个分镜，已自动渲染动态样片`);
    renderAnimaticTimeline();
    renderStoryboard();
    checkAndInitFirstShot();

    // 默认切到 Animatic 视图
    switchViewMode("animatic");
  } catch (err) {
    console.error("AI 导演执行异常:", err);
    alert(`AI 导演生成失败: ${err.message}`);
    status(`❌ 导演生成失败: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// ---------------------------------------------------------------------------
// 动态故事板 (Animatic) 时间轴渲染与同步
// ---------------------------------------------------------------------------
function renderAnimaticTimeline() {
  if (!dom.shotsTimelineTrack) return;
  dom.shotsTimelineTrack.innerHTML = "";

  const shots = (state.alignment && state.alignment.storyboard) || [];
  if (dom.timelineShotStats) {
    dom.timelineShotStats.textContent = `共 ${shots.length} 个分镜`;
  }
  if (dom.animaticStatusSummary) {
    const dur = state.alignment?.duration || (shots.length ? shots[shots.length - 1].end : 0);
    dom.animaticStatusSummary.textContent = `${state.currentFile?.name || ''} • ${shots.length} 镜头 • ${dur.toFixed(1)}s`;
  }

  if (shots.length === 0) return;

  const totalDuration = state.alignment?.duration || shots[shots.length - 1].end || 1;

  shots.forEach((shot, index) => {
    const block = document.createElement("div");
    block.className = "timeline-shot-block";
    block.dataset.index = index;

    if (shot.section_name && shot.section_name.includes("Chorus")) {
      block.classList.add("is-chorus");
    }

    const duration = shot.duration || Math.max(0.1, shot.end - shot.start);
    // 宽度根据持续时间比例分配 (最小保证 42px 便于点击)
    const pct = Math.max(2.5, (duration / totalDuration) * 100);
    block.style.flex = `0 0 ${pct}%`;
    block.style.minWidth = "48px";

    block.innerHTML = `
      <span style="font-weight: 600; margin-right: 4px;">S${shot.shot_id || index + 1}</span>
      <span style="color: #9ca3af; font-size: 10px;">${duration.toFixed(1)}s</span>
    `;

    block.title = `[Shot ${shot.shot_id}] ${shot.section_name || ''} • ${shot.shot_size || 'MS'} • ${shot.action || ''}`;

    block.addEventListener("click", () => {
      selectShot(index, true);
    });

    dom.shotsTimelineTrack.appendChild(block);
  });
}

function checkAndInitFirstShot() {
  const shots = state.alignment?.storyboard || [];
  if (shots.length > 0) {
    selectShot(0, false);
  } else {
    dom.animaticImg.style.display = "none";
    dom.animaticPlaceholder.style.display = "block";
    dom.hudShotBadge.textContent = "SHOT -- • 等待分镜生成";
    dom.hudSpecsBadge.textContent = "[--] • [--]";
    dom.hudLyricBar.textContent = "（点击「⚡ AI 导演一键分镜」立刻生成样片）";
  }
}

// 播放时同步切镜 (Core Magic Moment)
function syncAnimaticPlayback() {
  if (!ws || !state.alignment) return;
  const currentTime = ws.getCurrentTime();
  const shots = state.alignment.storyboard || [];
  if (shots.length === 0) return;

  // 寻找当前时间点匹配的 Shot
  let matchedIndex = -1;
  for (let i = 0; i < shots.length; i++) {
    if (currentTime >= shots[i].start && currentTime < shots[i].end) {
      matchedIndex = i;
      break;
    }
  }

  // 播放未到或超出时
  if (matchedIndex === -1) {
    if (currentTime < shots[0].start) matchedIndex = 0;
    else if (currentTime >= shots[shots.length - 1].end) matchedIndex = shots.length - 1;
  }

  if (matchedIndex !== -1 && matchedIndex !== currentShotIndex) {
    selectShot(matchedIndex, false);
  }
}

function selectShot(index, seekAudio = false) {
  const shots = state.alignment?.storyboard || [];
  if (index < 0 || index >= shots.length) return;

  currentShotIndex = index;
  activeShot = shots[index];

  // 1. 高亮时间轴轨道块
  const blocks = dom.shotsTimelineTrack.querySelectorAll(".timeline-shot-block");
  blocks.forEach((b, idx) => {
    if (idx === index) {
      b.classList.add("active");
      b.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    } else {
      b.classList.remove("active");
    }
  });

  // 2. 更新大屏画面与运镜动效
  updateCinemaScreen(activeShot);

  // 3. 更新检视面板
  updateInspector(activeShot);

  // 4. 如需寻道跳转音频
  if (seekAudio && ws) {
    const dur = ws.getDuration();
    if (dur > 0) {
      ws.seekTo(activeShot.start / dur);
    }
  }
}

function updateCinemaScreen(shot) {
  if (!shot) return;

  dom.animaticPlaceholder.style.display = "none";
  dom.animaticImg.style.display = "block";

  // 构建图片访问 URL (优先使用相对 /api/storyboard_frame 流服务)
  const jsonPath = state.currentFile?.json_path || "";
  const frameName = `${shot.id || 'shot_' + shot.shot_id}.png`;
  const frameUrl = `/api/storyboard_frame?json_path=${encodeURIComponent(jsonPath)}&frame_name=${encodeURIComponent(frameName)}`;

  // 刷新图片并重新触发 Ken Burns 动画
  dom.animaticImg.src = frameUrl;
  applyKenBurnsMotion(shot.camera_motion || shot.camera_movement || "static");

  // 更新 HUD
  updateShotHUD(shot);
}

function applyKenBurnsMotion(motion) {
  const img = dom.animaticImg;
  if (!img) return;

  // 清除旧动画 class
  img.className = "";
  // 触发 reflow 重置动画
  void img.offsetWidth;

  const motionClass = `motion-${(motion || "static").toLowerCase()}`;
  img.classList.add(motionClass);
}

function updateShotHUD(shot) {
  if (dom.hudShotBadge) {
    dom.hudShotBadge.textContent = `SHOT ${shot.shot_id || currentShotIndex + 1}  •  [${shot.section_name || 'Verse'}]`;
  }
  if (dom.hudSpecsBadge) {
    dom.hudSpecsBadge.textContent = `[${shot.shot_size || shot.scale || 'MS'}]  •  [${(shot.camera_motion || shot.camera_movement || 'STATIC').toUpperCase()}]`;
  }
  if (dom.hudLyricBar) {
    dom.hudLyricBar.textContent = shot.lyric_reference || "【器乐流动】";
  }
}

function updateInspector(shot) {
  if (!shot) return;

  if (dom.inspectorTitle) {
    dom.inspectorTitle.textContent = `🎯 镜头检视 — SHOT ${shot.shot_id || currentShotIndex + 1}`;
  }
  if (dom.inspectorDuration) {
    const dur = shot.duration || (shot.end - shot.start);
    dom.inspectorDuration.textContent = `${dur.toFixed(2)}s`;
  }
  if (dom.inspectorStart) dom.inspectorStart.value = shot.start.toFixed(3);
  if (dom.inspectorEnd) dom.inspectorEnd.value = shot.end.toFixed(3);

  if (dom.inspectorScale) dom.inspectorScale.value = shot.shot_size || shot.scale || "MS";
  if (dom.inspectorMotion) dom.inspectorMotion.value = shot.camera_motion || shot.camera_movement || "static";

  if (dom.inspectorAction) dom.inspectorAction.value = shot.action || shot.prompt_zh || "";
  if (dom.inspectorLyric) dom.inspectorLyric.value = `${shot.section_name || ''} | ${shot.lyric_reference || ''}`;
  if (dom.inspectorPrompt) dom.inspectorPrompt.value = shot.prompt_en || "";

  // 渲染 Takes 列表
  if (dom.inspectorTakesList) {
    dom.inspectorTakesList.innerHTML = "";
    const takes = shot.takes || [];
    if (takes.length === 0) {
      dom.inspectorTakesList.innerHTML = `<span style="color: #6b7280;">暂无候选 Takes</span>`;
    } else {
      takes.forEach((take, tIdx) => {
        const item = document.createElement("div");
        item.style.cssText = `
          display: flex; align-items: center; justify-content: space-between;
          padding: 6px 8px; background: #030712; border: 1px solid #1f2937;
          border-radius: 4px;
        `;
        item.innerHTML = `
          <div>
            <span style="font-weight: 600; color: #818cf8;">Take ${String.fromCharCode(65 + tIdx)}</span>
            <span style="color: #9ca3af; margin-left: 6px;">${take.provider || 'mock'}</span>
          </div>
          <span style="color: #10b981; font-weight: 500;">★ 正片已选</span>
        `;
        dom.inspectorTakesList.appendChild(item);
      });
    }
  }
}

async function handleRenderCurrentFrame() {
  if (!activeShot || !state.currentFile) return;
  status(`正在重新渲染分镜卡片: ${activeShot.id}...`);
  try {
    const jsonPath = state.currentFile.json_path;
    const frameName = `${activeShot.id}.png`;
    // 请求即时渲染流
    const res = await fetch(`/api/storyboard_frame?json_path=${encodeURIComponent(jsonPath)}&frame_name=${encodeURIComponent(frameName)}&t=${Date.now()}`);
    if (res.ok) {
      updateCinemaScreen(activeShot);
      status(`✅ 分镜 ${activeShot.id} 卡片已更新！`);
    }
  } catch (err) {
    console.error(err);
    status(`❌ 渲染卡片失败`);
  }
}

// ---------------------------------------------------------------------------
// 传统分镜表格与素材绑定 (兼容逻辑)
// ---------------------------------------------------------------------------
function bindStoryboardEvents() {
  if (dom.songSelect) {
    dom.songSelect.addEventListener("change", () => {
      const idx = dom.songSelect.value;
      if (idx !== "") loadSong(parseInt(idx));
    });
  }
  if (dom.btnSave) dom.btnSave.addEventListener("click", saveAlignment);
  if (dom.btnPlayPause) dom.btnPlayPause.addEventListener("click", togglePlay);
  if (dom.btnPlayLine) {
    dom.btnPlayLine.addEventListener("click", () => {
      if (activeShot) {
        playRange(activeShot.start, activeShot.end);
      } else {
        playSelectedLine();
      }
    });
  }
  if (dom.zoomSlider) {
    dom.zoomSlider.addEventListener("input", () => {
      const z = Number(dom.zoomSlider.value);
      if (ws) ws.zoom(z);
      if (wsInst && instReady) wsInst.zoom(z);
    });
  }

  if (dom.btnMuteVocals) dom.btnMuteVocals.addEventListener("click", () => toggleMuteTrack("vocals"));
  if (dom.btnMuteInst) dom.btnMuteInst.addEventListener("click", () => toggleMuteTrack("instrumental"));

  if (dom.btnSetBg) {
    dom.btnSetBg.addEventListener("click", () => {
      bgPickerMode = true;
      openAssetModal("选择默认背景图");
    });
  }

  if (dom.btnBrowseAssets) {
    dom.btnBrowseAssets.addEventListener("click", () => {
      bgPickerMode = false;
      openAssetModal("选择分镜素材");
    });
  }

  if (dom.assetModalClose) dom.assetModalClose.addEventListener("click", closeAssetModal);
  if (dom.btnAssetSync) dom.btnAssetSync.addEventListener("click", syncTimeWithSelectedLine);
  if (dom.btnAssetAdd) dom.btnAssetAdd.addEventListener("click", addStoryboardEvent);

  if (dom.assetFileInput) dom.assetFileInput.addEventListener("change", handleAssetUpload);

  if (dom.btnGenerate) {
    dom.btnGenerate.addEventListener("click", () => {
      if (dom.generateModal) dom.generateModal.classList.add("open");
    });
  }
  if (dom.btnCloseGenerate) {
    dom.btnCloseGenerate.addEventListener("click", () => {
      if (dom.generateModal) dom.generateModal.classList.remove("open");
    });
  }
  if (dom.btnConfirmGenerate) {
    dom.btnConfirmGenerate.addEventListener("click", handleGenerateOutput);
  }
}

function renderStoryboard() {
  if (!dom.storyboardList) return;
  dom.storyboardList.innerHTML = "";

  const storyboard = (state.alignment && state.alignment.storyboard) || [];
  storyboard.forEach((item, index) => {
    const tr = document.createElement("tr");
    tr.dataset.index = index;

    const pathOrName = item.path ? item.path.split("/").pop().split("\\").pop() : "纯色占位";
    const previewUrl = item.path ? (item.path.startsWith("storyboard/") ? `/api/storyboard_frame?json_path=${encodeURIComponent(state.currentFile?.json_path || '')}&frame_name=${encodeURIComponent(item.path.replace('storyboard/', ''))}` : `/api/asset_file?path=${encodeURIComponent(item.path)}`) : "";

    tr.innerHTML = `
      <td style="padding: 8px 12px; display: flex; align-items: center; gap: 10px;">
        <div style="width: 48px; height: 28px; background: #000; border-radius: 4px; overflow: hidden; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
          ${previewUrl ? `<img src="${previewUrl}" style="width: 100%; height: 100%; object-fit: cover;">` : `<span style="font-size: 10px; color: #888;">无</span>`}
        </div>
        <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          <strong style="color: #818cf8;">S${item.shot_id || index + 1}</strong>
          <span style="font-size: 12px; color: #e0e0e0; margin-left: 6px;">${pathOrName}</span>
        </div>
      </td>
      <td style="padding: 8px 12px;"><input type="text" class="table-time-input start-input" value="${formatTime(item.start)}"></td>
      <td style="padding: 8px 12px;"><input type="text" class="table-time-input end-input" value="${formatTime(item.end)}"></td>
      <td style="padding: 8px 12px;">
        <button class="delete-sb-btn" data-index="${index}" style="background: transparent; border: none; color: #ff5252; cursor: pointer; font-size: 13px;">✕</button>
      </td>
    `;

    tr.querySelector(".start-input").addEventListener("change", (e) => {
      const s = parseTime(e.target.value);
      if (s !== null) { item.start = s; markDirty(); renderAnimaticTimeline(); }
    });
    tr.querySelector(".end-input").addEventListener("change", (e) => {
      const en = parseTime(e.target.value);
      if (en !== null) { item.end = en; markDirty(); renderAnimaticTimeline(); }
    });
    tr.querySelector(".delete-sb-btn").addEventListener("click", () => {
      storyboard.splice(index, 1);
      markDirty();
      renderStoryboard();
      renderAnimaticTimeline();
    });

    dom.storyboardList.appendChild(tr);
  });
}

function renderReferenceLyrics() {
  if (!dom.lyricsList) return;
  dom.lyricsList.innerHTML = "";
  const lines = (state.alignment && state.alignment.lines) || [];
  lines.forEach((line, index) => {
    const row = document.createElement("div");
    row.className = "ref-lyric-row";
    row.dataset.index = index;
    row.innerHTML = `
      <span class="ref-time">${formatTime(line.start)}</span>
      <span class="ref-text">${escapeHtml(line.text)}</span>
    `;
    row.addEventListener("click", () => {
      state.selectedLine = index;
      dom.lyricsList.querySelectorAll(".ref-lyric-row").forEach(r => r.classList.remove("active"));
      row.classList.add("active");
      if (dom.assetStart && dom.assetEnd) {
        dom.assetStart.value = formatTime(line.start);
        dom.assetEnd.value = formatTime(line.end);
      }
    });
    dom.lyricsList.appendChild(row);
  });
}

function highlightReferenceLine() {
  if (!ws || !dom.lyricsList) return;
  const currentTime = ws.getCurrentTime();
  const lines = (state.alignment && state.alignment.lines) || [];
  let activeIndex = -1;
  for (let i = 0; i < lines.length; i++) {
    if (currentTime >= lines[i].start && currentTime <= lines[i].end) {
      activeIndex = i;
      break;
    }
  }
  dom.lyricsList.querySelectorAll(".ref-lyric-row").forEach((row, i) => {
    if (i === activeIndex) {
      row.classList.add("playing");
      row.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      row.classList.remove("playing");
    }
  });
}

function updateBgDisplay() {
  if (!dom.bgName) return;
  if (state.alignment && state.alignment.background) {
    dom.bgName.textContent = state.alignment.background.split("/").pop().split("\\").pop();
    dom.bgName.title = state.alignment.background;
  } else {
    dom.bgName.textContent = "未设置";
    dom.bgName.title = "";
  }
}

function syncTimeWithSelectedLine() {
  if (state.selectedLine < 0 || !state.alignment) return;
  const line = state.alignment.lines[state.selectedLine];
  if (line) {
    dom.assetStart.value = formatTime(line.start);
    dom.assetEnd.value = formatTime(line.end);
    status(`已同步第 ${state.selectedLine + 1} 行歌词时间`);
  }
}

function addStoryboardEvent() {
  if (!state.alignment) return;
  const s = parseTime(dom.assetStart.value);
  const e = parseTime(dom.assetEnd.value);
  if (s === null || e === null || e <= s) {
    alert("请输入正确的开始与结束时间！");
    return;
  }
  const newShot = {
    shot_id: (state.alignment.storyboard?.length || 0) + 1,
    id: `shot_${(state.alignment.storyboard?.length || 0) + 1}`,
    path: selectedAsset ? selectedAsset.path : "",
    preview_image: selectedAsset ? selectedAsset.path : "",
    start: s,
    end: e,
    type: "image",
    scale: "MS",
    camera_movement: "static",
    action: "手动插入分镜",
  };
  if (!state.alignment.storyboard) state.alignment.storyboard = [];
  state.alignment.storyboard.push(newShot);
  state.alignment.storyboard.sort((a, b) => a.start - b.start);
  markDirty();
  renderStoryboard();
  renderAnimaticTimeline();
  status("已添加分镜事件");
}

function openAssetModal(title) {
  if (!dom.assetModal) return;
  dom.assetModal.querySelector("h3").textContent = title;
  dom.assetModal.classList.add("open");
  loadAssets();
}

function closeAssetModal() {
  if (dom.assetModal) dom.assetModal.classList.remove("open");
}

async function loadAssets() {
  if (!dom.assetGrid) return;
  dom.assetGrid.innerHTML = "加载素材中...";
  try {
    const res = await fetch("/api/assets");
    const assets = await res.json();
    dom.assetGrid.innerHTML = "";
    if (assets.length === 0) {
      dom.assetGrid.innerHTML = "<div style='color:#888; font-size:13px;'>暂无素材，请先上传</div>";
      return;
    }
    assets.forEach((asset) => {
      const item = document.createElement("div");
      item.className = "asset-item";
      item.innerHTML = `
        <img src="${asset.url}" style="width:100%; height:80px; object-fit:cover; border-radius:4px;">
        <span style="font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block; margin-top:4px;">${asset.name}</span>
      `;
      item.addEventListener("click", () => {
        if (bgPickerMode) {
          state.alignment.background = asset.path;
          markDirty();
          updateBgDisplay();
          closeAssetModal();
          status(`已设置背景图: ${asset.name}`);
        } else {
          selectedAsset = asset;
          dom.currentAssetName.textContent = asset.name;
          dom.assetPreview.innerHTML = `<img src="${asset.url}" style="width:100%; height:100%; object-fit:cover;">`;
          closeAssetModal();
        }
      });
      dom.assetGrid.appendChild(item);
    });
  } catch (err) {
    dom.assetGrid.innerHTML = `<span style='color:red;'>加载素材失败: ${err.message}</span>`;
  }
}

async function handleAssetUpload(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;
  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append("files", files[i]);
  }
  dom.uploadStatus.textContent = "上传中...";
  try {
    const res = await fetch("/api/upload_asset", { method: "POST", body: formData });
    const data = await res.json();
    dom.uploadStatus.textContent = `成功上传 ${data.uploaded.length} 个文件`;
    loadAssets();
  } catch (err) {
    dom.uploadStatus.textContent = `上传失败: ${err.message}`;
  }
}

async function handleGenerateOutput() {
  if (!state.currentFile) return;
  const renderMode = document.querySelector('input[name="gen-render-mode"]:checked').value;
  const tagType = document.querySelector('input[name="gen-tag-type"]:checked').value;
  const genMode = document.querySelector('input[name="gen-mode"]:checked').value;

  dom.generateModal.classList.remove("open");
  status("开始合成输出...");

  try {
    const res = await fetch("/api/regen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        audio_path: state.currentFile.audio_path,
        mode: genMode,
        tag_type: tagType,
        render_mode: renderMode,
      }),
    });
    const data = await res.json();
    if (data.status === "ok") {
      status("✅ 渲染成功！" + (data.video_path ? " 视频已生成" : " ASS 已生成"));
    } else {
      status("❌ 渲染失败");
    }
  } catch (err) {
    status(`❌ 渲染出错: ${err.message}`);
  }
}
