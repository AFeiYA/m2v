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
  dom.btnModeGallery      = $("#btn-mode-gallery");
  dom.btnModeTable        = $("#btn-mode-table");
  dom.viewAnimatic        = $("#view-animatic");
  dom.viewGallery         = $("#view-gallery");
  dom.viewTable           = $("#view-table");
  dom.galleryGrid         = $("#gallery-grid");
  dom.btnBatchKeyframes   = $("#btn-batch-generate-keyframes");

  dom.animaticViewport    = $("#animatic-viewport");
  dom.animaticImg         = $("#animatic-img");
  dom.animaticPlaceholder = $("#animatic-empty-placeholder");
  dom.hudShotBadge        = $("#hud-shot-badge");
  dom.hudSpecsBadge       = $("#hud-specs-badge");
  dom.shotsTimelineTrack  = $("#shots-timeline-track") || $("#animatic-shots-track") || $(".shots-timeline-track");
  dom.timelineShotStats   = $("#timeline-shot-stats");
  dom.animaticStatusSummary = $("#animatic-status-summary");

  // Inspector DOM
  dom.inspectorTitle      = $("#inspector-title");
  dom.inspectorDuration   = $("#inspector-duration-badge");
  dom.inspectorSequenceBadge = $("#inspector-sequence-badge");
  dom.inspectorIntensityBadge = $("#inspector-intensity-badge");
  dom.inspectorStart      = $("#inspector-start");
  dom.inspectorEnd        = $("#inspector-end");
  dom.inspectorScale      = $("#inspector-scale");
  dom.inspectorMotion     = $("#inspector-motion");
  dom.inspectorSubjectZone= $("#inspector-subject-zone");
  dom.inspectorTextZone   = $("#inspector-text-zone");
  dom.inspectorAction     = $("#inspector-action");
  dom.inspectorRationale  = $("#inspector-rationale");
  dom.inspectorTransition = $("#inspector-transition");
  dom.inspectorLyric      = $("#inspector-lyric");
  dom.inspectorPrompt     = $("#inspector-prompt");
  dom.inspectorKeyframePrompt = $("#inspector-keyframe-prompt");
  dom.inspectorMotionPrompt   = $("#inspector-motion-prompt");
  dom.inspectorEndframePrompt = $("#inspector-endframe-prompt");
  dom.inspectorContinuityMode = $("#inspector-continuity-mode");
  dom.inspectorEndframeBox    = $("#inspector-endframe-box");
  dom.btnGenerateEndframe     = $("#btn-generate-endframe");
  dom.btnLinkOneTake          = $("#btn-link-one-take");
  dom.inspectorTakesList  = $("#inspector-takes-list");
  dom.btnRenderFrame      = $("#btn-render-current-frame");

  // ComfyUI 本机视频引擎 DOM
  dom.comfyuiStatusDot    = $("#comfyui-status-dot");
  dom.comfyuiStatusText   = $("#comfyui-status-text");
  dom.btnComfyuiStart     = $("#btn-comfyui-start");
  dom.animaticVideo       = $("#animatic-video");
  dom.comfyuiEngineTag    = $("#comfyui-engine-tag");
  dom.btnGenerateKeyframe = $("#btn-generate-keyframe");
  dom.btnGenerateI2V      = $("#btn-generate-i2v");
  dom.btnComfyuiTwoStage  = $("#btn-comfyui-two-stage");
  dom.inspectorKeyframeBox = $("#inspector-keyframe-box");
  dom.keyframeStatusTag   = $("#keyframe-status-tag");
  dom.comfyuiResSelect    = $("#comfyui-res-select");
  dom.comfyuiStepsSelect  = $("#comfyui-steps-select");
  dom.comfyuiProgressBox  = $("#comfyui-progress-box");
  dom.comfyuiProgressMsg  = $("#comfyui-progress-msg");
  dom.comfyuiProgressNum  = $("#comfyui-progress-num");
  dom.comfyuiProgressBar  = $("#comfyui-progress-bar");
  dom.takesCountBadge     = $("#takes-count-badge");

  // Cinema Viewport HUD
  dom.btnToggleSafeZone   = $("#btn-toggle-safe-zone");
  dom.safeZoneOverlay     = $("#safe-zone-overlay");
  dom.safeZoneSubjectTarget = $("#safe-zone-subject-target");
  dom.safeZoneTextAnchor  = $("#safe-zone-text-anchor");

  // 提示词复制工具栏 DOM
  dom.btnCopyShotEn       = $("#btn-copy-shot-en");
  dom.btnCopyShotZh       = $("#btn-copy-shot-zh");
  dom.btnCopyShotKf       = $("#btn-copy-shot-kf");
  dom.btnCopyShotMotion   = $("#btn-copy-shot-motion");
  dom.btnCopyShotAll      = $("#btn-copy-shot-all");
  dom.btnCopyFieldAction  = $("#btn-copy-field-action");
  dom.btnCopyFieldRationale = $("#btn-copy-field-rationale");
  dom.btnCopyFieldTransition = $("#btn-copy-field-transition");
  dom.btnCopyFieldKf      = $("#btn-copy-field-kf");
  dom.btnCopyFieldMotion  = $("#btn-copy-field-motion");
  dom.btnCopyFieldEndframe = $("#btn-copy-field-endframe");
  dom.btnCopyFieldLegacy  = $("#btn-copy-field-legacy");

  // 大模型深度导演 Modal DOM
  dom.btnLlmDirector      = $("#btn-llm-director");
  dom.llmDirectorModal    = $("#llm-director-modal");
  dom.btnCloseLlmModal    = $("#btn-close-llm-modal");
  dom.tabLlmPrompt        = $("#tab-llm-prompt");
  dom.tabLlmBackfill      = $("#tab-llm-backfill");
  dom.panelLlmPrompt      = $("#panel-llm-prompt");
  dom.panelLlmBackfill    = $("#panel-llm-backfill");
  dom.selectLlmMode       = $("#select-llm-mode");
  dom.llmPromptTextarea   = $("#llm-prompt-textarea");
  dom.promptFilePath      = $("#prompt-file-path");
  dom.btnRefreshLlmPrompt = $("#btn-refresh-llm-prompt");
  dom.btnCopyLlmPrompt    = $("#btn-copy-llm-prompt");
  dom.llmBackfillTextarea = $("#llm-backfill-textarea");
  dom.backfillStatus      = $("#backfill-status");
  dom.btnSubmitLlmBackfill= $("#btn-submit-llm-backfill");
  dom.backfillCacheBanner = $("#backfill-cache-banner");
  dom.backfillCacheMsg    = $("#backfill-cache-msg");
  dom.btnReapplyCache     = $("#btn-reapply-cache");
  dom.btnClearCache       = $("#btn-clear-cache");
  dom.btnCopyAllEn        = $("#btn-copy-all-en");
  dom.btnCopyAllZh        = $("#btn-copy-all-zh");

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
  renderGalleryView();
  updateBgDisplay();
  checkAndInitFirstShot();
  checkAndRestoreBackfillCache();
};

window.onAlignmentChanged = () => {
  renderReferenceLyrics();
  renderStoryboard();
  renderAnimaticTimeline();
  renderGalleryView();
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
  // 视图模式切换 (Animatic / Gallery / Table)
  if (dom.btnModeAnimatic) {
    dom.btnModeAnimatic.addEventListener("click", () => switchViewMode("animatic"));
  }
  if (dom.btnModeGallery) {
    dom.btnModeGallery.addEventListener("click", () => switchViewMode("gallery"));
  }
  if (dom.btnModeTable) {
    dom.btnModeTable.addEventListener("click", () => switchViewMode("table"));
  }
  if (dom.btnBatchKeyframes) {
    dom.btnBatchKeyframes.addEventListener("click", handleBatchGenerateKeyframes);
  }

  // AI 导演一键分镜
  if (dom.btnAutoDirect) {
    dom.btnAutoDirect.addEventListener("click", handleAutoDirect);
  }

  // 大模型深度导演 Modal
  if (dom.btnLlmDirector) {
    dom.btnLlmDirector.addEventListener("click", openLlmDirectorModal);
  }
  if (dom.btnCloseLlmModal) {
    dom.btnCloseLlmModal.addEventListener("click", closeLlmDirectorModal);
  }
  if (dom.tabLlmPrompt) {
    dom.tabLlmPrompt.addEventListener("click", () => switchLlmTab("prompt"));
  }
  if (dom.tabLlmBackfill) {
    dom.tabLlmBackfill.addEventListener("click", () => switchLlmTab("backfill"));
  }
  if (dom.btnRefreshLlmPrompt) {
    dom.btnRefreshLlmPrompt.addEventListener("click", fetchLlmPrompt);
  }
  if (dom.btnCopyLlmPrompt) {
    dom.btnCopyLlmPrompt.addEventListener("click", copyLlmPrompt);
  }
  if (dom.btnSubmitLlmBackfill) {
    dom.btnSubmitLlmBackfill.addEventListener("click", submitLlmBackfill);
  }
  if (dom.btnReapplyCache) {
    dom.btnReapplyCache.addEventListener("click", submitLlmBackfill);
  }
  if (dom.btnClearCache) {
    dom.btnClearCache.addEventListener("click", clearBackfillCache);
  }
  if (dom.btnCopyAllEn) {
    dom.btnCopyAllEn.addEventListener("click", () => copyAllPrompts("en", dom.btnCopyAllEn));
  }
  if (dom.btnCopyAllZh) {
    dom.btnCopyAllZh.addEventListener("click", () => copyAllPrompts("zh", dom.btnCopyAllZh));
  }

  // 自动缓存回填文本输入草稿 (实时输入防丢)
  if (dom.llmBackfillTextarea) {
    let saveDraftTimer = null;
    dom.llmBackfillTextarea.addEventListener("input", () => {
      clearTimeout(saveDraftTimer);
      saveDraftTimer = setTimeout(() => {
        saveBackfillDraft();
      }, 300);
    });
  }

  // 检视面板顶部快捷复制按钮
  if (dom.btnCopyShotEn) {
    dom.btnCopyShotEn.addEventListener("click", () => handleCopyShotPrompt("video", dom.btnCopyShotEn));
  }
  if (dom.btnCopyShotZh) {
    dom.btnCopyShotZh.addEventListener("click", () => handleCopyShotPrompt("zh", dom.btnCopyShotZh));
  }
  if (dom.btnCopyShotKf) {
    dom.btnCopyShotKf.addEventListener("click", () => handleCopyShotPrompt("keyframe", dom.btnCopyShotKf));
  }
  if (dom.btnCopyShotMotion) {
    dom.btnCopyShotMotion.addEventListener("click", () => handleCopyShotPrompt("motion", dom.btnCopyShotMotion));
  }
  if (dom.btnCopyShotAll) {
    dom.btnCopyShotAll.addEventListener("click", () => handleCopyShotPrompt("all", dom.btnCopyShotAll));
  }

  // 检视面板单字段一键复制
  if (dom.btnCopyFieldAction) {
    dom.btnCopyFieldAction.addEventListener("click", () => copyTextToClipboard(dom.inspectorAction?.value, dom.btnCopyFieldAction, "动作描述"));
  }
  if (dom.btnCopyFieldRationale) {
    dom.btnCopyFieldRationale.addEventListener("click", () => copyTextToClipboard(dom.inspectorRationale?.value, dom.btnCopyFieldRationale, "导演构思"));
  }
  if (dom.btnCopyFieldTransition) {
    dom.btnCopyFieldTransition.addEventListener("click", () => copyTextToClipboard(dom.inspectorTransition?.value, dom.btnCopyFieldTransition, "镜头衔接"));
  }
  if (dom.btnCopyFieldKf) {
    dom.btnCopyFieldKf.addEventListener("click", () => copyTextToClipboard(dom.inspectorKeyframePrompt?.value, dom.btnCopyFieldKf, "首帧提示词"));
  }
  if (dom.btnCopyFieldMotion) {
    dom.btnCopyFieldMotion.addEventListener("click", () => copyTextToClipboard(dom.inspectorMotionPrompt?.value, dom.btnCopyFieldMotion, "运镜提示词"));
  }
  if (dom.btnCopyFieldEndframe) {
    dom.btnCopyFieldEndframe.addEventListener("click", () => copyTextToClipboard(dom.inspectorEndframePrompt?.value, dom.btnCopyFieldEndframe, "尾帧提示词"));
  }
  if (dom.btnCopyFieldLegacy) {
    dom.btnCopyFieldLegacy.addEventListener("click", () => copyTextToClipboard(dom.inspectorPrompt?.value, dom.btnCopyFieldLegacy, "全景提示词"));
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

  if (dom.inspectorStart) {
    dom.inspectorStart.addEventListener("change", () => {
      if (!activeShot) return;
      const val = parseFloat(dom.inspectorStart.value);
      if (!isNaN(val) && val >= 0) {
        activeShot.start = val;
        markDirty();
        renderAnimaticTimeline();
      }
    });
  }

  if (dom.inspectorEnd) {
    dom.inspectorEnd.addEventListener("change", () => {
      if (!activeShot) return;
      const val = parseFloat(dom.inspectorEnd.value);
      if (!isNaN(val) && val >= activeShot.start) {
        activeShot.end = val;
        markDirty();
        renderAnimaticTimeline();
      }
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

  if (dom.inspectorRationale) {
    dom.inspectorRationale.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.design_rationale = dom.inspectorRationale.value;
      markDirty();
    });
  }

  if (dom.inspectorTransition) {
    dom.inspectorTransition.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.transition_rationale = dom.inspectorTransition.value;
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

  if (dom.inspectorKeyframePrompt) {
    dom.inspectorKeyframePrompt.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.keyframe_prompt = dom.inspectorKeyframePrompt.value;
      markDirty();
    });
  }

  if (dom.inspectorMotionPrompt) {
    dom.inspectorMotionPrompt.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.motion_prompt = dom.inspectorMotionPrompt.value;
      markDirty();
    });
  }

  if (dom.inspectorEndframePrompt) {
    dom.inspectorEndframePrompt.addEventListener("input", () => {
      if (!activeShot) return;
      activeShot.endframe_prompt = dom.inspectorEndframePrompt.value;
      markDirty();
    });
  }

  if (dom.inspectorContinuityMode) {
    dom.inspectorContinuityMode.addEventListener("change", () => {
      if (!activeShot) return;
      activeShot.continuity_mode = dom.inspectorContinuityMode.value;
      markDirty();
    });
  }

  if (dom.btnGenerateEndframe) {
    dom.btnGenerateEndframe.addEventListener("click", handleGenerateEndframe);
  }

  if (dom.btnLinkOneTake) {
    dom.btnLinkOneTake.addEventListener("click", handleLinkOneTake);
  }

  if (dom.btnToggleSafeZone) {
    dom.btnToggleSafeZone.addEventListener("click", () => {
      if (!dom.safeZoneOverlay) return;
      const isHidden = dom.safeZoneOverlay.style.display === "none";
      dom.safeZoneOverlay.style.display = isHidden ? "block" : "none";
      dom.btnToggleSafeZone.style.background = isHidden ? "#3730a3" : "#1e1b4b";
      dom.btnToggleSafeZone.style.color = isHidden ? "#ffffff" : "#a5b4fc";
      if (isHidden && activeShot) {
        updateSafeZoneOverlay(activeShot);
      }
    });
  }

  if (dom.inspectorSubjectZone) {
    dom.inspectorSubjectZone.addEventListener("change", () => {
      if (!activeShot) return;
      const zone = dom.inspectorSubjectZone.value;
      if (!activeShot.layout_contract) {
        activeShot.layout_contract = { primary_subject_zone: zone };
      } else {
        activeShot.layout_contract.primary_subject_zone = zone;
      }
      const coords = {
        center: [0.5, 0.5],
        center_left: [0.35, 0.5],
        center_right: [0.65, 0.5],
        top_center: [0.5, 0.3],
        top_left: [0.35, 0.3],
        top_right: [0.65, 0.3],
        bottom_center: [0.5, 0.7],
        bottom_left: [0.35, 0.7],
        bottom_right: [0.65, 0.7],
      };
      const [x, y] = coords[zone] || [0.5, 0.5];
      activeShot.layout_contract.primary_subject_x = x;
      activeShot.layout_contract.primary_subject_y = y;
      updateSafeZoneOverlay(activeShot);
      markDirty();
    });
  }

  if (dom.inspectorTextZone) {
    dom.inspectorTextZone.addEventListener("change", () => {
      if (!activeShot) return;
      const tzone = dom.inspectorTextZone.value;
      if (!activeShot.layout_contract) {
        activeShot.layout_contract = { preferred_text_regions: [tzone] };
      } else {
        activeShot.layout_contract.preferred_text_regions = [tzone];
      }
      updateSafeZoneOverlay(activeShot);
      markDirty();
    });
  }

  if (dom.selectLlmMode) {
    dom.selectLlmMode.addEventListener("change", () => {
      fetchLlmPrompt();
    });
  }

  if (dom.btnRenderFrame) {
    dom.btnRenderFrame.addEventListener("click", handleRenderCurrentFrame);
  }

  // ComfyUI 本机交互事件
  if (dom.btnComfyuiStart) {
    dom.btnComfyuiStart.addEventListener("click", startComfyUIServer);
  }
  if (dom.btnGenerateKeyframe) {
    dom.btnGenerateKeyframe.addEventListener("click", handleGenerateKeyframe);
  }
  if (dom.btnGenerateI2V) {
    dom.btnGenerateI2V.addEventListener("click", handleGenerateI2VTake);
  }
  if (dom.btnComfyuiTwoStage) {
    dom.btnComfyuiTwoStage.addEventListener("click", handleGenerateTwoStage);
  }

  // 初始并定时轮询 ComfyUI 在线状态
  checkComfyUIStatus();
  setInterval(checkComfyUIStatus, 15000);
}

function switchViewMode(mode) {
  if (dom.btnModeAnimatic) dom.btnModeAnimatic.classList.toggle("active", mode === "animatic");
  if (dom.btnModeGallery) dom.btnModeGallery.classList.toggle("active", mode === "gallery");
  if (dom.btnModeTable) dom.btnModeTable.classList.toggle("active", mode === "table");

  if (dom.viewAnimatic) dom.viewAnimatic.style.display = (mode === "animatic") ? "flex" : "none";
  if (dom.viewGallery) dom.viewGallery.style.display = (mode === "gallery") ? "flex" : "none";
  if (dom.viewTable) dom.viewTable.style.display = (mode === "table") ? "flex" : "none";

  if (mode === "gallery") {
    renderGalleryView();
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
// 提示词 (Prompt) 复制与中英文生成辅助体系
// ---------------------------------------------------------------------------
async function copyTextToClipboard(text, btnElement = null, successMsg = "已复制到剪贴板！") {
  const content = (text || "").trim();
  if (!content) {
    alert("没有可复制的内容！");
    return;
  }
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(content);
    } else {
      throw new Error("Clipboard API unavailable");
    }
  } catch (err) {
    const ta = document.createElement("textarea");
    ta.value = content;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(ta);
    }
  }
  if (btnElement) {
    const oldHtml = btnElement.innerHTML;
    btnElement.innerHTML = `✅ 已复制！`;
    btnElement.disabled = true;
    setTimeout(() => {
      btnElement.innerHTML = oldHtml;
      btnElement.disabled = false;
    }, 1800);
  }
  status(`✅ ${successMsg}`);
}

const SHOT_SIZE_NAMES = {
  ECU: "大特写 (Extreme Close-Up)",
  CU: "特写 (Close-Up)",
  MCU: "中近景 (Medium Close-Up)",
  MS: "中景 (Medium Shot)",
  MLS: "中远景 (Medium Long Shot)",
  WS: "全景 (Wide Shot)",
  EWS: "大全景 (Extreme Wide Shot)",
};

const CAMERA_MOTION_NAMES = {
  static: "固定镜头 (Static)",
  slow_dolly_in: "慢速推进 (Slow Dolly In)",
  dolly_out: "镜头拉开 (Dolly Out)",
  pan_left: "向左平摇 (Pan Left)",
  pan_right: "向右平摇 (Pan Right)",
  crane_up: "摇臂升起 (Crane Up)",
  tilt_up: "镜头仰起 (Tilt Up)",
  tilt_down: "镜头俯视 (Tilt Down)",
  tracking: "跟拍滑轨 (Tracking)",
  handheld: "呼吸手持 (Handheld)",
  slow_orbit_with_vertical_roll: "慢速环绕带垂直翻转 (Slow Orbit with Roll)",
};

function getShotSizeNameZH(scale) {
  return SHOT_SIZE_NAMES[scale] || scale || "中景";
}

function getCameraMotionNameZH(motion) {
  return CAMERA_MOTION_NAMES[motion] || motion || "固定镜头";
}

function buildShotPromptEN(shot, type = "video") {
  if (!shot) return "";
  if (type === "keyframe") {
    return shot.keyframe_prompt || shot.prompt_en || shot.video_prompt || "";
  }
  if (type === "motion") {
    if (shot.motion_prompt) return shot.motion_prompt;
    const motion = shot.camera_motion || shot.camera_movement || "static";
    return `${motion} camera motion, primary subject remains anatomically stable and rigid without warping, smooth cinematic lighting shifts, steady continuous movement`;
  }
  if (type === "endframe") {
    return shot.endframe_prompt || "";
  }
  // 完整视频 prompt (T2V)
  return shot.video_prompt || shot.prompt_en || shot.keyframe_prompt || "";
}

function buildShotPromptZH(shot) {
  if (!shot) return "";
  const lines = [];
  const shotNum = shot.shot_id || (currentShotIndex >= 0 ? currentShotIndex + 1 : 1);
  const dur = (shot.end && shot.start) ? (shot.end - shot.start).toFixed(2) : "0.00";
  const sizeName = getShotSizeNameZH(shot.shot_size || shot.scale);
  const motionName = getCameraMotionNameZH(shot.camera_motion || shot.camera_movement);

  lines.push(`【第 ${String(shotNum).padStart(2, '0')} 镜 | 时长: ${dur}s】`);
  lines.push(`【景别与运镜】${sizeName}，${motionName}。`);

  if (shot.lyric_reference || shot.text) {
    lines.push(`【对应歌词】“${shot.lyric_reference || shot.text}”`);
  }

  // 画面构图与动作
  let visualDesc = shot.action || shot.prompt_zh || "";
  if (shot.storyboard_design) {
    if (typeof shot.storyboard_design === "object") {
      const comp = shot.storyboard_design.composition || "";
      const mot = shot.storyboard_design.motion_effect || "";
      if (comp || mot) visualDesc = `构图：${comp} | 动效：${mot}`;
    }
  }
  if (visualDesc) {
    lines.push(`【画面构图与动作】${visualDesc}`);
  }

  // 导演构思
  const rationale = shot.design_rationale || shot.director_note || "";
  if (rationale) {
    lines.push(`【导演构思】${rationale.replace(/^【导演构思】/, "")}`);
  }

  // 镜头衔接
  const trans = shot.transition_rationale || "";
  if (trans) {
    lines.push(`【镜头衔接】${trans.replace(/^【镜头衔接】/, "")}`);
  }

  // 安全区
  if (shot.layout_contract) {
    const sz = shot.layout_contract.primary_subject_zone || "center";
    const tz = (shot.layout_contract.preferred_text_regions || []).join(", ") || "bottom_center";
    lines.push(`【构图安全区】主体区域：${sz} | 推荐字幕区：${tz}`);
  }

  return lines.join("\n");
}

function buildShotPromptCard(shot) {
  if (!shot) return "";
  const zh = buildShotPromptZH(shot);
  const enVideo = buildShotPromptEN(shot, "video");
  const enKf = buildShotPromptEN(shot, "keyframe");
  const enMotion = buildShotPromptEN(shot, "motion");

  return [
    zh,
    "",
    "=== 对应 AI 英文提示词 (English Prompts) ===",
    enVideo ? `【Video Prompt (T2V)】\n${enVideo}` : "",
    enKf ? `【Keyframe Prompt (FLUX 12B T2I)】\n${enKf}` : "",
    enMotion ? `【Motion Prompt (LTX-Video I2V)】\n${enMotion}` : "",
  ].filter(Boolean).join("\n");
}

function handleCopyShotPrompt(type = "video", btn = null) {
  if (!activeShot) {
    alert("请先在时间轴或画廊中选中一个分镜镜头！");
    return;
  }
  let text = "";
  let label = "英文 Prompt";
  if (type === "zh") {
    text = buildShotPromptZH(activeShot);
    label = `Shot ${activeShot.shot_id || currentShotIndex + 1} 中文分镜提示词`;
  } else if (type === "all") {
    text = buildShotPromptCard(activeShot);
    label = `Shot ${activeShot.shot_id || currentShotIndex + 1} 双语分镜全卡`;
  } else if (type === "keyframe") {
    text = buildShotPromptEN(activeShot, "keyframe");
    label = `Shot ${activeShot.shot_id || currentShotIndex + 1} 静态首帧 Prompt`;
  } else if (type === "motion") {
    text = buildShotPromptEN(activeShot, "motion");
    label = `Shot ${activeShot.shot_id || currentShotIndex + 1} 运镜动势 Prompt`;
  } else {
    text = buildShotPromptEN(activeShot, "video");
    label = `Shot ${activeShot.shot_id || currentShotIndex + 1} 英文视频 Prompt`;
  }

  if (!text) {
    alert(`该镜头的${label}为空，请先回填大模型数据或在下方输入！`);
    return;
  }

  copyTextToClipboard(text, btn, `已复制 ${label}`);
}

// ---------------------------------------------------------------------------
// 本地草稿与持久化缓存管理 (解决每次重新回填痛点)
// ---------------------------------------------------------------------------
function getBackfillCacheKey() {
  return state.currentFile ? `suno2mv_backfill_${state.currentFile.name}` : null;
}

function saveBackfillDraft(explicitText = null) {
  const key = getBackfillCacheKey();
  if (!key) return;
  const text = explicitText !== null ? explicitText : (dom.llmBackfillTextarea?.value || "");
  if (text.trim()) {
    try {
      localStorage.setItem(key, text);
    } catch (e) {
      console.warn("保存 localStorage 草稿失败:", e);
    }
  } else {
    try {
      localStorage.removeItem(key);
    } catch (e) {}
  }
}

async function checkAndRestoreBackfillCache() {
  if (!state.currentFile || !dom.llmBackfillTextarea) return;
  const key = getBackfillCacheKey();

  // 1. 优先尝试从 LocalStorage 读取当前歌曲编辑草稿
  let localDraft = null;
  if (key) {
    try {
      localDraft = localStorage.getItem(key);
    } catch (e) {}
  }

  if (localDraft && localDraft.trim()) {
    if (!dom.llmBackfillTextarea.value.trim() || dom.llmBackfillTextarea.value === localDraft) {
      dom.llmBackfillTextarea.value = localDraft;
      if (dom.backfillCacheBanner) {
        dom.backfillCacheBanner.style.display = "flex";
        let count = 0;
        try {
          const p = JSON.parse(localDraft.replace(/```(?:json)?\s*([\s\S]*?)```/, "$1"));
          count = Array.isArray(p) ? p.length : (p.shots?.length || 1);
        } catch (e) {}
        if (dom.backfillCacheMsg) {
          dom.backfillCacheMsg.textContent = `已恢复本地实时草稿 (${count > 0 ? count + ' 个分镜' : '已缓存数据'})`;
        }
      }
      return;
    }
  }

  // 2. 本地草稿为空，尝试从服务端工程目录读取历史回填文件 (llm_director_response.json)
  try {
    const res = await fetch(`/api/director/llm_cached_response?json_path=${encodeURIComponent(state.currentFile.json_path)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.exists && data.data) {
        if (!dom.llmBackfillTextarea.value.trim()) {
          dom.llmBackfillTextarea.value = data.data;
          saveBackfillDraft(data.data);
          if (dom.backfillCacheBanner) {
            dom.backfillCacheBanner.style.display = "flex";
            if (dom.backfillCacheMsg) {
              dom.backfillCacheMsg.textContent = `已恢复已持久化的回填数据 (${data.shots_count} 个分镜，保存于 ${data.mtime || ''})`;
            }
          }
        }
        return;
      }
    }
  } catch (err) {
    console.warn("检查服务端回填缓存异常:", err);
  }

  // 3. 既无本地草稿也无持久化文件
  if (dom.backfillCacheBanner) {
    dom.backfillCacheBanner.style.display = "none";
  }
}

async function clearBackfillCache() {
  if (!state.currentFile) return;
  if (!confirm("确定要清空该歌曲的本地与服务端回填缓存吗？")) return;
  const key = getBackfillCacheKey();
  if (key) {
    try {
      localStorage.removeItem(key);
    } catch (e) {}
  }
  try {
    await fetch(`/api/director/llm_cached_response?json_path=${encodeURIComponent(state.currentFile.json_path)}`, {
      method: "DELETE",
    });
  } catch (e) {
    console.warn("清除服务端缓存失败:", e);
  }
  if (dom.llmBackfillTextarea) dom.llmBackfillTextarea.value = "";
  if (dom.backfillCacheBanner) dom.backfillCacheBanner.style.display = "none";
  if (dom.backfillStatus) dom.backfillStatus.textContent = "缓存已清空";
  status("✅ 本地与磁盘回填缓存已清空");
}

function extractShotsDataForCopy() {
  // 1. 优先尝试解析回填框里的 JSON 数据
  const text = (dom.llmBackfillTextarea && dom.llmBackfillTextarea.value || "").trim();
  if (text) {
    try {
      let clean = text;
      const m = clean.match(/```(?:json)?\s*([\s\S]*?)```/);
      if (m) clean = m[1].trim();
      const parsed = JSON.parse(clean);
      const list = Array.isArray(parsed) ? parsed : (parsed.shots || parsed.data || [parsed]);
      if (list && list.length > 0) {
        return list;
      }
    } catch (e) {
      console.warn("回填框文本非有效 JSON，降级读取当前工程分镜:", e);
    }
  }
  // 2. 降级从当前工程分镜读取
  return (state.alignment && state.alignment.storyboard) || [];
}

async function copyAllPrompts(lang = "en", btnElement = null) {
  const shots = extractShotsDataForCopy();
  if (!shots || shots.length === 0) {
    alert("未找到分镜数据！请先粘贴大模型回填数据或载入歌曲分镜。");
    return;
  }

  const songName = state.currentFile?.name || "歌曲工程";
  const output = [];

  if (lang === "en") {
    output.push(`=== ${songName} 全曲英文 AI 视频提示词 (All Video Prompts) ===`);
    output.push(`共 ${shots.length} 个镜头 | 包含完整 Video Prompt 与动静解耦参数\n`);

    shots.forEach((s, idx) => {
      const shotId = s.shot_id || `shot_${String(idx + 1).padStart(3, '0')}`;
      const start = typeof s.start === 'number' ? s.start.toFixed(3) : "0.000";
      const end = typeof s.end === 'number' ? s.end.toFixed(3) : "0.000";
      const scale = s.shot_size || s.scale || "MS";
      const motion = s.camera_motion || s.camera_movement || "static";
      const videoP = s.video_prompt || s.prompt_en || s.keyframe_prompt || "";
      const kfP = s.keyframe_prompt || s.video_prompt || "";
      const motP = s.motion_prompt || "";
      const endP = s.endframe_prompt || "";

      output.push(`------------------------------------------------------------`);
      output.push(`[SHOT ${idx + 1}] (${start}s - ${end}s | ${scale} | ${motion})`);
      if (s.lyric_reference || s.text) {
        output.push(`Lyric: "${s.lyric_reference || s.text}"`);
      }
      if (videoP) {
        output.push(`🎬 Video Prompt:\n${videoP}`);
      }
      if (kfP && kfP !== videoP) {
        output.push(`📸 Keyframe Prompt (FLUX 12B):\n${kfP}`);
      }
      if (motP) {
        output.push(`🌊 Motion Prompt (I2V):\n${motP}`);
      }
      if (endP) {
        output.push(`🔗 Endframe Prompt:\n${endP}`);
      }
      output.push("");
    });
  } else {
    output.push(`=== ${songName} 全曲中文分镜与导演构思脚本 ===`);
    output.push(`共 ${shots.length} 个镜头 | 包含景别运镜、画面构图、导演构思与转场蒙太奇\n`);

    shots.forEach((s, idx) => {
      const start = typeof s.start === 'number' ? s.start.toFixed(3) : "0.000";
      const end = typeof s.end === 'number' ? s.end.toFixed(3) : "0.000";
      const scaleName = getShotSizeNameZH(s.shot_size || s.scale);
      const motionName = getCameraMotionNameZH(s.camera_motion || s.camera_movement);

      output.push(`------------------------------------------------------------`);
      output.push(`[第 ${String(idx + 1).padStart(2, '0')} 镜] (${start}s - ${end}s | 景别: ${scaleName} | 运镜: ${motionName})`);
      if (s.lyric_reference || s.text) {
        output.push(`歌词原句：“${s.lyric_reference || s.text}”`);
      }

      let visual = s.action || s.prompt_zh || "";
      if (s.storyboard_design && typeof s.storyboard_design === "object") {
        const c = s.storyboard_design.composition || "";
        const m = s.storyboard_design.motion_effect || "";
        if (c || m) visual = `构图: ${c} | 动效: ${m}`;
      }
      if (visual) {
        output.push(`画面构图：${visual}`);
      }

      const desRat = (s.design_rationale || s.director_note || "").trim();
      if (desRat) {
        output.push(`导演构思：${desRat.replace(/^【导演构思】/, "")}`);
      }

      const transRat = (s.transition_rationale || "").trim();
      if (transRat) {
        output.push(`镜头衔接：${transRat.replace(/^【镜头衔接】/, "")}`);
      }
      output.push("");
    });
  }

  const resultText = output.join("\n");
  await copyTextToClipboard(resultText, btnElement, `成功复制全曲 ${shots.length} 个镜头的${lang === 'en' ? '英文 Prompt' : '中文分镜'}！`);
}

// ---------------------------------------------------------------------------
// AI 导演大模型深度模式 (Prompt 导出 / JSON 回填)
// ---------------------------------------------------------------------------
function openLlmDirectorModal() {
  if (!state.currentFile) {
    alert("请先选择歌曲工程！");
    return;
  }
  if (dom.llmDirectorModal) {
    dom.llmDirectorModal.style.display = "block";
    switchLlmTab("prompt");
    fetchLlmPrompt();
    checkAndRestoreBackfillCache();
  }
}

function closeLlmDirectorModal() {
  if (dom.llmDirectorModal) {
    dom.llmDirectorModal.style.display = "none";
  }
}

function switchLlmTab(tab) {
  if (!dom.panelLlmPrompt || !dom.panelLlmBackfill) return;
  if (tab === "prompt") {
    dom.panelLlmPrompt.style.display = "flex";
    dom.panelLlmBackfill.style.display = "none";
    if (dom.tabLlmPrompt) dom.tabLlmPrompt.classList.add("active");
    if (dom.tabLlmBackfill) dom.tabLlmBackfill.classList.remove("active");
  } else {
    dom.panelLlmPrompt.style.display = "none";
    dom.panelLlmBackfill.style.display = "flex";
    if (dom.tabLlmPrompt) dom.tabLlmPrompt.classList.remove("active");
    if (dom.tabLlmBackfill) dom.tabLlmBackfill.classList.add("active");
    checkAndRestoreBackfillCache();
  }
}

async function fetchLlmPrompt() {
  if (!state.currentFile || !dom.llmPromptTextarea) return;
  dom.llmPromptTextarea.value = "⏳ 正在分析歌词与字级时间戳，生成大模型 Prompt...";
  if (dom.promptFilePath) dom.promptFilePath.textContent = "";

  try {
    const mode = dom.selectLlmMode ? dom.selectLlmMode.value : "dual_track";
    const res = await fetch("/api/director/llm_prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        mode: mode,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "生成 Prompt 失败");
    }
    const data = await res.json();
    dom.llmPromptTextarea.value = data.prompt || "";
    if (dom.promptFilePath) {
      dom.promptFilePath.textContent = `已自动保存至: ${data.prompt_path || ''}`;
    }
  } catch (err) {
    console.error("生成 Prompt 失败:", err);
    dom.llmPromptTextarea.value = `❌ 生成失败: ${err.message}`;
  }
}

async function copyLlmPrompt() {
  if (!dom.llmPromptTextarea || !dom.llmPromptTextarea.value) return;
  try {
    await navigator.clipboard.writeText(dom.llmPromptTextarea.value);
    const originalText = dom.btnCopyLlmPrompt.textContent;
    dom.btnCopyLlmPrompt.textContent = "✅ 已复制到剪贴板！";
    setTimeout(() => {
      dom.btnCopyLlmPrompt.textContent = originalText;
    }, 2000);
  } catch (err) {
    dom.llmPromptTextarea.select();
    document.execCommand("copy");
    alert("已选择文本并尝试复制，如未成功请按 Ctrl+C / Cmd+C");
  }
}

async function submitLlmBackfill() {
  if (!state.currentFile) return;
  const content = (dom.llmBackfillTextarea && dom.llmBackfillTextarea.value || "").trim();
  if (!content) {
    alert("请先粘贴大模型返回的 JSON 数据！");
    return;
  }

  const btn = dom.btnSubmitLlmBackfill;
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ 正在回填数据并渲染高清分镜...";
  if (dom.backfillStatus) dom.backfillStatus.textContent = "正在处理分镜与特效样式...";

  try {
    const res = await fetch("/api/director/llm_merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        response_data: content,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "回填请求失败");
    }

    const data = await res.json();
    state.alignment = data.project;

    // 成功回填后，保存草稿与持久化缓存状态
    saveBackfillDraft(content);
    if (dom.backfillCacheBanner) {
      dom.backfillCacheBanner.style.display = "flex";
      if (dom.backfillCacheMsg) {
        dom.backfillCacheMsg.textContent = `已保存并生效 (${data.shots_count} 个分镜)`;
      }
    }

    status(`✅ ${data.message || '大模型分镜回填成功！'}`);
    if (dom.backfillStatus) {
      dom.backfillStatus.textContent = `✅ 成功更新 ${data.shots_count} 个分镜，分镜卡片已重新渲染`;
    }

    renderAnimaticTimeline();
    renderStoryboard();
    checkAndInitFirstShot();
    switchViewMode("animatic");

    setTimeout(() => {
      closeLlmDirectorModal();
    }, 1200);
  } catch (err) {
    console.error("大模型回填失败:", err);
    alert(`回填失败: ${err.message}`);
    if (dom.backfillStatus) {
      dom.backfillStatus.textContent = `❌ 回填失败: ${err.message}`;
    }
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

function resetInspector() {
  activeShot = null;
  currentShotIndex = -1;
  if (dom.inspectorTitle) dom.inspectorTitle.textContent = "🎯 镜头检视 — 未选择镜头";
  if (dom.inspectorDuration) dom.inspectorDuration.textContent = "0.00s";
  if (dom.inspectorSequenceBadge) dom.inspectorSequenceBadge.textContent = "SEQ --";
  if (dom.inspectorIntensityBadge) dom.inspectorIntensityBadge.textContent = "张力: --";
  if (dom.inspectorStart) dom.inspectorStart.value = "0.000";
  if (dom.inspectorEnd) dom.inspectorEnd.value = "0.000";
  if (dom.inspectorScale) dom.inspectorScale.value = "MS";
  if (dom.inspectorMotion) dom.inspectorMotion.value = "static";
  if (dom.inspectorAction) dom.inspectorAction.value = "";
  if (dom.inspectorRationale) dom.inspectorRationale.value = "";
  if (dom.inspectorTransition) dom.inspectorTransition.value = "";
  if (dom.inspectorLyric) dom.inspectorLyric.value = "";
  if (dom.inspectorPrompt) dom.inspectorPrompt.value = "";
  if (dom.inspectorKeyframePrompt) dom.inspectorKeyframePrompt.value = "";
  if (dom.inspectorMotionPrompt) dom.inspectorMotionPrompt.value = "";
  if (dom.inspectorEndframePrompt) dom.inspectorEndframePrompt.value = "";
  if (dom.inspectorKeyframeBox) {
    dom.inspectorKeyframeBox.innerHTML = '<span style="font-size: 8px; color: #64748b;">无首帧</span>';
  }
  if (dom.keyframeStatusTag) {
    dom.keyframeStatusTag.textContent = "未就绪";
    dom.keyframeStatusTag.style.background = "#374151";
    dom.keyframeStatusTag.style.color = "#9ca3af";
  }
  if (dom.inspectorEndframeBox) {
    dom.inspectorEndframeBox.innerHTML = '<span style="font-size: 8px; color: #64748b;">无尾帧</span>';
  }
}

function checkAndInitFirstShot() {
  const shots = state.alignment?.storyboard || [];
  if (shots.length > 0) {
    selectShot(0, false);
  } else {
    resetInspector();
    if (dom.animaticImg) dom.animaticImg.style.display = "none";
    if (dom.animaticPlaceholder) dom.animaticPlaceholder.style.display = "block";
    if (dom.hudShotBadge) dom.hudShotBadge.textContent = "SHOT -- • 等待分镜生成";
    if (dom.hudSpecsBadge) dom.hudSpecsBadge.textContent = "[--] • [--]";
    if (dom.hudLyricBar) dom.hudLyricBar.textContent = "（点击「⚡ AI 导演一键分镜」立刻生成样片）";
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

  // 视频 Take 播放进度同步
  if (dom.animaticVideo && dom.animaticVideo.style.display !== "none" && activeShot) {
    if (ws.isPlaying()) {
      const offset = Math.max(0, currentTime - activeShot.start);
      if (Math.abs(dom.animaticVideo.currentTime - offset) > 0.4) {
        dom.animaticVideo.currentTime = offset;
      }
      if (dom.animaticVideo.paused) {
        dom.animaticVideo.play().catch(() => {});
      }
    } else {
      if (!dom.animaticVideo.paused) {
        dom.animaticVideo.pause();
      }
    }
  }
}

function selectShot(index, seekAudio = false) {
  const shots = state.alignment?.storyboard || [];
  if (index < 0 || index >= shots.length) return;

  currentShotIndex = index;
  activeShot = shots[index];

  // 1. 高亮时间轴轨道块
  if (dom.shotsTimelineTrack) {
    const blocks = dom.shotsTimelineTrack.querySelectorAll(".timeline-shot-block");
    blocks.forEach((b, idx) => {
      if (idx === index) {
        b.classList.add("active");
        b.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
      } else {
        b.classList.remove("active");
      }
    });
  }

  // 2. 更新大屏画面与运镜动效 (根据 Take 自动选择播放视频或卡片)
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

  if (dom.animaticPlaceholder) dom.animaticPlaceholder.style.display = "none";

  // 检查是否有选定的视频/图像 Take
  const takes = shot.takes || [];
  const selectedTake = takes.find(t => t.id === shot.selected_take_id) || takes.find(t => t.selected) || (takes.length > 0 ? takes[0] : null);

  const jsonPath = state.currentFile?.json_path || "";

  if (selectedTake && selectedTake.media_type === "video" && (selectedTake.media_path || selectedTake.video_path)) {
    // 选定素材为原生动态视频 Take
    const videoPath = selectedTake.media_path || selectedTake.video_path;
    const videoUrl = `/api/asset_file?path=${encodeURIComponent(videoPath)}&json_path=${encodeURIComponent(jsonPath)}`;

    if (dom.animaticImg) dom.animaticImg.style.display = "none";
    if (dom.animaticVideo) {
      dom.animaticVideo.style.display = "block";
      const encodedTarget = encodeURIComponent(videoPath);
      if (!dom.animaticVideo.src || !dom.animaticVideo.src.includes(encodedTarget)) {
        dom.animaticVideo.src = videoUrl;
      }
      dom.animaticVideo.play().catch(() => {});
    }
  } else if (selectedTake && selectedTake.media_type === "image" && selectedTake.media_path && selectedTake.provider !== "storyboard_mock") {
    // 选定素材为真实静态图片 Take (如 FLUX 高清关键帧)
    if (dom.animaticVideo) {
      dom.animaticVideo.style.display = "none";
      dom.animaticVideo.pause();
    }
    if (dom.animaticImg) {
      dom.animaticImg.style.display = "block";
      dom.animaticImg.src = `/api/asset_file?path=${encodeURIComponent(selectedTake.media_path)}&json_path=${encodeURIComponent(jsonPath)}&t=${Date.now()}`;
      applyKenBurnsMotion(shot.camera_motion || shot.camera_movement || "static");
    }
  } else {
    // 默认展示合成的故事板卡片 (带构图安全区、信息与 Ken Burns 运镜)
    if (dom.animaticVideo) {
      dom.animaticVideo.style.display = "none";
      dom.animaticVideo.pause();
    }
    if (dom.animaticImg) {
      dom.animaticImg.style.display = "block";
      const frameName = `${shot.id || 'shot_' + shot.shot_id}.png`;
      const frameUrl = `/api/storyboard_frame?json_path=${encodeURIComponent(jsonPath)}&frame_name=${encodeURIComponent(frameName)}&t=${Date.now()}`;
      dom.animaticImg.src = frameUrl;
      applyKenBurnsMotion(shot.camera_motion || shot.camera_movement || "static");
    }
  }

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

function updateSafeZoneOverlay(shot) {
  if (!dom.safeZoneOverlay) return;
  const csz = shot?.layout_contract;
  const px = (csz?.primary_subject_x != null ? csz.primary_subject_x : 0.5) * 100;
  const py = (csz?.primary_subject_y != null ? csz.primary_subject_y : 0.5) * 100;
  if (dom.safeZoneSubjectTarget) {
    dom.safeZoneSubjectTarget.style.left = `${px}%`;
    dom.safeZoneSubjectTarget.style.top = `${py}%`;
  }
  if (dom.safeZoneTextAnchor) {
    const pref = csz?.preferred_text_regions?.[0] || "bottom_center";
    if (pref === "bottom_left") {
      dom.safeZoneTextAnchor.style.left = "24px";
      dom.safeZoneTextAnchor.style.right = "auto";
      dom.safeZoneTextAnchor.style.top = "auto";
      dom.safeZoneTextAnchor.style.bottom = "12px";
      dom.safeZoneTextAnchor.style.transform = "none";
    } else if (pref === "bottom_right") {
      dom.safeZoneTextAnchor.style.right = "24px";
      dom.safeZoneTextAnchor.style.left = "auto";
      dom.safeZoneTextAnchor.style.top = "auto";
      dom.safeZoneTextAnchor.style.bottom = "12px";
      dom.safeZoneTextAnchor.style.transform = "none";
    } else if (pref === "top_center") {
      dom.safeZoneTextAnchor.style.left = "50%";
      dom.safeZoneTextAnchor.style.right = "auto";
      dom.safeZoneTextAnchor.style.top = "20px";
      dom.safeZoneTextAnchor.style.bottom = "auto";
      dom.safeZoneTextAnchor.style.transform = "translateX(-50%)";
    } else {
      dom.safeZoneTextAnchor.style.left = "50%";
      dom.safeZoneTextAnchor.style.right = "auto";
      dom.safeZoneTextAnchor.style.top = "auto";
      dom.safeZoneTextAnchor.style.bottom = "12px";
      dom.safeZoneTextAnchor.style.transform = "translateX(-50%)";
    }
    dom.safeZoneTextAnchor.textContent = `✍️ 建议排版区: ${pref}`;
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

  // 叙事序列与视听张力徽标
  if (dom.inspectorSequenceBadge) {
    let seqName = shot.section_name || "";
    if (state.alignment?.sequences && state.alignment.sequences.length > 0) {
      const foundSeq = state.alignment.sequences.find(s =>
        (s.shot_ids && s.shot_ids.includes(shot.id)) ||
        (shot.start >= s.start && shot.start < s.end)
      );
      if (foundSeq) {
        seqName = foundSeq.title || foundSeq.id;
        dom.inspectorSequenceBadge.title = `戏剧功能: ${foundSeq.dramatic_function || '无'}`;
      }
    }
    dom.inspectorSequenceBadge.textContent = seqName ? `${seqName}` : `SEQ --`;
  }
  if (dom.inspectorIntensityBadge) {
    let intensityVal = 0.5;
    if (state.alignment?.temporal_direction?.visual_intensity) {
      const pts = state.alignment.temporal_direction.visual_intensity;
      const matchPt = pts.find(p => Math.abs(p.time - shot.start) < 3.0);
      if (matchPt) intensityVal = matchPt.value;
    }
    dom.inspectorIntensityBadge.textContent = `张力: ${intensityVal.toFixed(2)}`;
  }

  if (dom.inspectorStart) dom.inspectorStart.value = shot.start.toFixed(3);
  if (dom.inspectorEnd) dom.inspectorEnd.value = shot.end.toFixed(3);

  if (dom.inspectorScale) dom.inspectorScale.value = shot.shot_size || shot.scale || "MS";
  if (dom.inspectorMotion) dom.inspectorMotion.value = shot.camera_motion || shot.camera_movement || "static";

  // 构图安全区
  if (dom.inspectorSubjectZone) {
    dom.inspectorSubjectZone.value = shot.layout_contract?.primary_subject_zone || "center";
  }
  if (dom.inspectorTextZone) {
    dom.inspectorTextZone.value = shot.layout_contract?.preferred_text_regions?.[0] || "bottom_center";
  }
  updateSafeZoneOverlay(shot);

  if (dom.inspectorAction) dom.inspectorAction.value = shot.action || shot.prompt_zh || "";
  if (dom.inspectorRationale) dom.inspectorRationale.value = shot.design_rationale || "";
  if (dom.inspectorTransition) dom.inspectorTransition.value = shot.transition_rationale || "";
  if (dom.inspectorLyric) dom.inspectorLyric.value = `${shot.section_name || ''} | ${shot.lyric_reference || ''}`;
  if (dom.inspectorPrompt) dom.inspectorPrompt.value = shot.prompt_en || "";
  if (dom.inspectorKeyframePrompt) dom.inspectorKeyframePrompt.value = shot.keyframe_prompt || shot.prompt_en || "";
  if (dom.inspectorMotionPrompt) dom.inspectorMotionPrompt.value = shot.motion_prompt || "";
  if (dom.inspectorEndframePrompt) dom.inspectorEndframePrompt.value = shot.endframe_prompt || "";
  if (dom.inspectorContinuityMode) dom.inspectorContinuityMode.value = shot.continuity_mode || "cut";

  const curJson = state.currentFile?.json_path || "";

  if (dom.inspectorEndframeBox) {
    if (shot.endframe_image) {
      const endUrl = shot.endframe_image.startsWith("storyboard/") && state.currentFile
        ? `/api/storyboard_frame?json_path=${encodeURIComponent(curJson)}&frame_name=${encodeURIComponent(shot.endframe_image.replace('storyboard/', ''))}&t=${Date.now()}`
        : `/api/asset_file?path=${encodeURIComponent(shot.endframe_image)}&json_path=${encodeURIComponent(curJson)}&t=${Date.now()}`;
      dom.inspectorEndframeBox.innerHTML = `<img src="${endUrl}" style="width: 100%; height: 100%; object-fit: cover;">`;
    } else {
      dom.inspectorEndframeBox.innerHTML = `<span style="font-size: 8px; color: #64748b;">无尾帧</span>`;
    }
  }

  // 首帧预览与状态更新
  if (dom.inspectorKeyframeBox) {
    if (shot.preview_image) {
      const kfUrl = shot.preview_image.startsWith("storyboard/") && state.currentFile
        ? `/api/storyboard_frame?json_path=${encodeURIComponent(curJson)}&frame_name=${encodeURIComponent(shot.preview_image.replace('storyboard/', ''))}&t=${Date.now()}`
        : `/api/asset_file?path=${encodeURIComponent(shot.preview_image)}&json_path=${encodeURIComponent(curJson)}&t=${Date.now()}`;
      dom.inspectorKeyframeBox.innerHTML = `<img src="${kfUrl}" style="width: 100%; height: 100%; object-fit: cover;">`;
      if (dom.keyframeStatusTag) {
        dom.keyframeStatusTag.textContent = "已就绪";
        dom.keyframeStatusTag.style.background = "#065f46";
        dom.keyframeStatusTag.style.color = "#6ee7b7";
      }
    } else {
      dom.inspectorKeyframeBox.innerHTML = `<span style="font-size: 8px; color: #6b7280;">无首帧</span>`;
      if (dom.keyframeStatusTag) {
        dom.keyframeStatusTag.textContent = "未生成";
        dom.keyframeStatusTag.style.background = "#1f2937";
        dom.keyframeStatusTag.style.color = "#9ca3af";
      }
    }
  }

  // 渲染 Takes 列表
  renderInspectorTakes(shot);
}

function renderInspectorTakes(shot) {
  if (!dom.inspectorTakesList) return;
  dom.inspectorTakesList.innerHTML = "";
  const takes = shot.takes || [];

  if (dom.takesCountBadge) {
    dom.takesCountBadge.textContent = `${takes.length} 个候选`;
  }

  if (takes.length === 0) {
    dom.inspectorTakesList.innerHTML = `<span style="color: #6b7280; font-size: 11px;">暂无候选 Takes（点击上方生成）</span>`;
    return;
  }

  takes.forEach((take, tIdx) => {
    const isSelected = (take.id === shot.selected_take_id) || (take.selected);
    const item = document.createElement("div");
    item.style.cssText = `
      display: flex; align-items: center; justify-content: space-between;
      padding: 6px 8px; background: ${isSelected ? '#111827' : '#030712'};
      border: 1px solid ${isSelected ? '#4f46e5' : '#1f2937'};
      border-radius: 4px;
    `;
    const takeLetter = String.fromCharCode(65 + tIdx);
    const mediaTag = take.media_type === "video" ? "🎬 视频" : "🖼️ 图像";
    let providerName = "LTX-2B";
    if (take.provider && take.provider.includes("wan")) providerName = "Wan-1.3B";
    else if (take.provider && take.provider.includes("flux")) providerName = "FLUX";

    item.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 2px;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <span style="font-weight: 700; color: ${isSelected ? '#818cf8' : '#e5e7eb'};">Take ${takeLetter}</span>
          <span style="font-size: 10px; background: #1e1b4b; color: #a5b4fc; padding: 0 4px; border-radius: 2px;">${providerName}</span>
          <span style="font-size: 10px; color: #9ca3af;">${mediaTag}</span>
        </div>
        ${take.seed ? `<span style="font-size: 9px; color: #6b7280;">Seed: ${take.seed}</span>` : ''}
      </div>
      <div style="display: flex; align-items: center; gap: 4px;">
        <button class="btn-audition-take" style="padding: 2px 6px; font-size: 10px; background: #1f2937; border: 1px solid #374151; color: #93c5fd; border-radius: 3px; cursor: pointer;" title="在视窗临时试看">▶ 试看</button>
        ${isSelected 
          ? `<span style="color: #10b981; font-weight: 600; font-size: 11px; margin-left: 2px;">★ 正片</span>`
          : `<button class="btn-select-take" style="padding: 2px 6px; font-size: 10px; background: #064e3b; border: 1px solid #059669; color: #6ee7b7; border-radius: 3px; cursor: pointer;">设为正片</button>`
        }
        <button class="btn-delete-take" style="padding: 2px 5px; font-size: 10px; background: transparent; border: 1px solid #374151; color: #ef4444; border-radius: 3px; cursor: pointer;" title="删除此 Take">🗑</button>
      </div>
    `;

    item.querySelector(".btn-audition-take")?.addEventListener("click", () => {
      previewSingleTake(shot, take);
    });
    item.querySelector(".btn-select-take")?.addEventListener("click", () => {
      handleSelectTake(shot, take);
    });
    item.querySelector(".btn-delete-take")?.addEventListener("click", () => {
      handleDeleteTake(shot, take);
    });

    dom.inspectorTakesList.appendChild(item);
  });
}

function previewSingleTake(shot, take) {
  if (dom.animaticPlaceholder) dom.animaticPlaceholder.style.display = "none";
  if (take.media_type === "video" && (take.media_path || take.video_path)) {
    const videoPath = take.media_path || take.video_path;
    if (dom.animaticImg) dom.animaticImg.style.display = "none";
    if (dom.animaticVideo) {
      dom.animaticVideo.style.display = "block";
      dom.animaticVideo.src = `/api/asset_file?path=${encodeURIComponent(videoPath)}`;
      dom.animaticVideo.play().catch(() => {});
    }
  } else if (take.media_path) {
    if (dom.animaticVideo) {
      dom.animaticVideo.style.display = "none";
      dom.animaticVideo.pause();
    }
    if (dom.animaticImg) {
      dom.animaticImg.style.display = "block";
      dom.animaticImg.src = `/api/asset_file?path=${encodeURIComponent(take.media_path)}`;
      applyKenBurnsMotion(shot.camera_motion || shot.camera_movement || "static");
    }
  }
  status(`正在视窗试看: Take ${take.id} (${take.provider})`);
}

async function handleSelectTake(shot, take) {
  if (!state.currentFile) return;
  status(`正在设为正片: Take ${take.id}...`);
  try {
    const res = await fetch("/api/comfyui/select_take", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        shot_id: shot.id,
        take_id: take.id,
      }),
    });
    if (!res.ok) throw new Error("设置正片失败");
    shot.selected_take_id = take.id;
    (shot.takes || []).forEach(t => t.selected = (t.id === take.id));
    shot.path = take.media_path;
    shot.type = take.media_type;

    renderInspectorTakes(shot);
    updateCinemaScreen(shot);
    renderAnimaticTimeline();
    status(`✅ 已将 Take ${take.id} 设为镜头 ${shot.id} 的正片素材！`);
  } catch (err) {
    console.error(err);
    status(`❌ 选定失败: ${err.message}`);
  }
}

async function handleDeleteTake(shot, take) {
  if (!state.currentFile) return;
  if (!confirm(`确定要删除镜头 ${shot.id} 的候选 Take (${take.id}) 吗？`)) return;

  status(`正在删除 Take ${take.id}...`);
  try {
    const res = await fetch("/api/comfyui/delete_take", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        shot_id: shot.id,
        take_id: take.id,
      }),
    });
    if (!res.ok) throw new Error("删除 Take 失败");

    shot.takes = (shot.takes || []).filter(t => t.id !== take.id);
    if (shot.selected_take_id === take.id) {
      if (shot.takes.length > 0) {
        shot.takes[0].selected = true;
        shot.selected_take_id = shot.takes[0].id;
        shot.path = shot.takes[0].media_path;
        shot.type = shot.takes[0].media_type;
      } else {
        shot.selected_take_id = null;
        shot.path = shot.preview_image || "";
        shot.type = "image";
      }
    }

    renderInspectorTakes(shot);
    updateCinemaScreen(shot);
    renderAnimaticTimeline();
    status(`🗑️ 已删除 Take ${take.id}`);
  } catch (err) {
    console.error(err);
    status(`❌ 删除失败: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// ComfyUI 本机服务交互
// ---------------------------------------------------------------------------
async function checkComfyUIStatus() {
  try {
    const res = await fetch("/api/comfyui/status");
    if (!res.ok) return;
    const data = await res.json();
    const isOnline = data.health?.online === true;

    if (dom.comfyuiStatusDot) {
      dom.comfyuiStatusDot.style.background = isOnline ? "#10b981" : "#ef4444";
    }
    if (dom.comfyuiStatusText) {
      dom.comfyuiStatusText.textContent = isOnline ? "ComfyUI 🟢 已连接" : "ComfyUI 🔴 未连接";
      dom.comfyuiStatusText.style.color = isOnline ? "#34d399" : "#9ca3af";
    }
    if (dom.btnComfyuiStart) {
      dom.btnComfyuiStart.style.display = isOnline ? "none" : "inline-block";
    }
  } catch (err) {
    console.warn("ComfyUI 状态检查异常:", err);
  }
}

async function startComfyUIServer() {
  if (dom.btnComfyuiStart) {
    dom.btnComfyuiStart.disabled = true;
    dom.btnComfyuiStart.textContent = "启动中...";
  }
  status("正在启动本地 ComfyUI 进程并连接 8188 端口...");
  try {
    const res = await fetch("/api/comfyui/start", { method: "POST" });
    const data = await res.json();
    if (data.online) {
      status("🎉 本地 ComfyUI 服务已成功上线！");
      checkComfyUIStatus();
    } else {
      status("⚠️ 启动 ComfyUI 超时，请检查本地环境或手动启动。");
    }
  } catch (err) {
    status(`启动失败: ${err.message}`);
  } finally {
    if (dom.btnComfyuiStart) {
      dom.btnComfyuiStart.disabled = false;
      dom.btnComfyuiStart.textContent = "🚀 启动";
    }
  }
}

function handleModelSelectChange() {
  const modelType = dom.comfyuiModelSelect?.value || "ltx_video";
  if (dom.comfyuiEngineTag) {
    if (modelType.includes("ltx")) {
      dom.comfyuiEngineTag.textContent = "LTX-Video 2B";
    } else if (modelType.includes("wan")) {
      dom.comfyuiEngineTag.textContent = "Wan 2.1 1.3B";
    } else if (modelType.includes("flux")) {
      dom.comfyuiEngineTag.textContent = "FLUX Schnell";
    }
  }
}

let isGeneratingTask = false;
let taskPollingTimer = null;

function showProgressBox(initMsg) {
  if (dom.comfyuiProgressBox) dom.comfyuiProgressBox.style.display = "flex";
  if (dom.comfyuiProgressBar) dom.comfyuiProgressBar.style.width = "5%";
  if (dom.comfyuiProgressMsg) dom.comfyuiProgressMsg.textContent = initMsg || "任务排队中...";
  if (dom.comfyuiProgressNum) dom.comfyuiProgressNum.textContent = "5%";
}

function hideProgressBox() {
  if (dom.comfyuiProgressBox) {
    setTimeout(() => {
      dom.comfyuiProgressBox.style.display = "none";
    }, 2000);
  }
}

function resetTwoStageBtns() {
  isGeneratingTask = false;
  if (dom.btnGenerateKeyframe) {
    dom.btnGenerateKeyframe.disabled = false;
    dom.btnGenerateKeyframe.innerHTML = "📸 生成/重刷首帧 (~5s)";
  }
  if (dom.btnGenerateEndframe) {
    dom.btnGenerateEndframe.disabled = false;
    dom.btnGenerateEndframe.innerHTML = "📸 生成尾帧 (FLUX)";
  }
  if (dom.btnGenerateI2V) {
    dom.btnGenerateI2V.disabled = false;
    dom.btnGenerateI2V.innerHTML = "🎬 驱动镜头动态 (I2V 生成 Take)";
  }
  if (dom.btnComfyuiTwoStage) {
    dom.btnComfyuiTwoStage.disabled = false;
    dom.btnComfyuiTwoStage.innerHTML = "<span>⚡ 一键两阶段直达 (首帧 + 视频)</span>";
  }
}

async function handleGenerateKeyframe() {
  if (!activeShot || !state.currentFile) {
    status("请先在时间轴上选择一个分镜镜头！");
    return;
  }
  if (isGeneratingTask) {
    status("当前已有生成任务正在进行中，请稍候...");
    return;
  }

  isGeneratingTask = true;
  if (dom.btnGenerateKeyframe) {
    dom.btnGenerateKeyframe.disabled = true;
    dom.btnGenerateKeyframe.innerHTML = "⏳ FLUX 采样中...";
  }
  showProgressBox("正在调用 FLUX 12B 生成电影级写真首帧...");
  status(`正在为镜头 ${activeShot.id} 生成电影首帧 (FLUX)...`);

  const resolution = dom.comfyuiResSelect?.value || "768x448";

  try {
    const res = await fetch("/api/comfyui/generate_keyframe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        shot_id: activeShot.id,
        resolution: resolution,
        steps: 4,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "请求失败");
    }
    const data = await res.json();
    pollTwoStageTask(data.task_id, "keyframe");
  } catch (err) {
    console.error("生成首帧失败:", err);
    status(`生成首帧失败: ${err.message}`);
    resetTwoStageBtns();
  }
}

async function handleGenerateEndframe() {
  if (!activeShot || !state.currentFile) {
    status("请先在时间轴上选择一个分镜镜头！");
    return;
  }
  if (isGeneratingTask) {
    status("当前已有生成任务正在进行中，请稍候...");
    return;
  }

  isGeneratingTask = true;
  if (dom.btnGenerateEndframe) {
    dom.btnGenerateEndframe.disabled = true;
    dom.btnGenerateEndframe.innerHTML = "⏳ FLUX 尾帧采样中...";
  }
  showProgressBox("正在调用 FLUX 生成一镜到底尾帧终态图...");
  status(`正在为镜头 ${activeShot.id} 生成尾帧终态图 (FLUX)...`);

  const resolution = dom.comfyuiResSelect?.value || "768x448";

  try {
    const res = await fetch("/api/comfyui/generate_endframe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        shot_id: activeShot.id,
        resolution: resolution,
        steps: 4,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "请求失败");
    }
    const data = await res.json();
    pollTwoStageTask(data.task_id, "endframe");
  } catch (err) {
    console.error("生成尾帧失败:", err);
    status(`生成尾帧失败: ${err.message}`);
    resetTwoStageBtns();
  }
}

async function handleLinkOneTake() {
  if (!activeShot || !state.currentFile) {
    status("请先在时间轴上选择一个分镜镜头！");
    return;
  }
  const shots = state.alignment?.storyboard || [];
  const currentIdx = shots.findIndex(s => s.id === activeShot.id || String(s.shot_id) === String(activeShot.id));
  if (currentIdx < 0 || currentIdx >= shots.length - 1) {
    status("当前镜头已是全片最后一个镜头，无法链接下一镜头！");
    return;
  }
  const nextShot = shots[currentIdx + 1];

  try {
    const res = await fetch("/api/shots/link_one_take", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        from_shot_id: activeShot.id,
        to_shot_id: nextShot.id,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "绑定失败");
    }
    const data = await res.json();
    activeShot.continuity_mode = "one_take_continuous";
    if (dom.inspectorContinuityMode) dom.inspectorContinuityMode.value = "one_take_continuous";
    nextShot.preview_image = data.inherited_image;
    nextShot.path = data.inherited_image;
    nextShot.type = "image";
    status(`✅ 一镜到底绑定成功！镜头 ${nextShot.id} 已无缝继承镜头 ${activeShot.id} 的尾帧画面。`);
    renderAnimaticTimeline();
    renderGalleryView();
  } catch (err) {
    console.error("绑定一镜到底失败:", err);
    status(`绑定一镜到底失败: ${err.message}`);
  }
}

async function handleGenerateI2VTake() {
  if (!activeShot || !state.currentFile) {
    status("请先在时间轴上选择一个分镜镜头！");
    return;
  }
  if (isGeneratingTask) {
    status("当前已有生成任务正在进行中，请稍候...");
    return;
  }

  if (!activeShot.preview_image) {
    status("当前镜头尚未生成首帧！建议先点击「📸 生成首帧」或使用「⚡ 一键两阶段直达」");
    return;
  }

  isGeneratingTask = true;
  if (dom.btnGenerateI2V) {
    dom.btnGenerateI2V.disabled = true;
    dom.btnGenerateI2V.innerHTML = "⏳ LTX-I2V 推理中...";
  }
  showProgressBox("正在启动 LTX-I2V 图生视频驱动 (STG 增强)...");
  status(`正在为镜头 ${activeShot.id} 以首帧为物理输入生成动态视频 Take...`);

  const resolution = dom.comfyuiResSelect?.value || "768x448";
  const steps = parseInt(dom.comfyuiStepsSelect?.value || "15", 10);

  try {
    const res = await fetch("/api/comfyui/generate_i2v_take", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        shot_id: activeShot.id,
        keyframe_path: activeShot.preview_image,
        resolution: resolution,
        steps: steps,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "请求失败");
    }
    const data = await res.json();
    pollTwoStageTask(data.task_id, "i2v");
  } catch (err) {
    console.error("生成 I2V 视频失败:", err);
    status(`生成 I2V 视频失败: ${err.message}`);
    resetTwoStageBtns();
  }
}

async function handleGenerateTwoStage() {
  if (!activeShot || !state.currentFile) {
    status("请先在时间轴上选择一个分镜镜头！");
    return;
  }
  if (isGeneratingTask) {
    status("当前已有生成任务正在进行中，请稍候...");
    return;
  }

  isGeneratingTask = true;
  if (dom.btnComfyuiTwoStage) {
    dom.btnComfyuiTwoStage.disabled = true;
    dom.btnComfyuiTwoStage.innerHTML = "<span>⏳ 两阶段串联执行中...</span>";
  }
  showProgressBox("【1/2】正在生成电影级写真首帧 (FLUX 12B)...");
  status(`正在为镜头 ${activeShot.id} 执行两阶段全链路生产 (首帧+视频)...`);

  const resolution = dom.comfyuiResSelect?.value || "768x448";
  const steps = parseInt(dom.comfyuiStepsSelect?.value || "15", 10);

  try {
    const res = await fetch("/api/comfyui/generate_two_stage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        json_path: state.currentFile.json_path,
        shot_id: activeShot.id,
        resolution: resolution,
        keyframe_steps: 4,
        video_steps: steps,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "请求失败");
    }
    const data = await res.json();
    pollTwoStageTask(data.task_id, "two_stage");
  } catch (err) {
    console.error("两阶段生成失败:", err);
    status(`两阶段生成失败: ${err.message}`);
    resetTwoStageBtns();
  }
}

function pollTwoStageTask(taskId, taskType) {
  if (taskPollingTimer) clearInterval(taskPollingTimer);
  taskPollingTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/comfyui/task_status?task_id=${encodeURIComponent(taskId)}`);
      if (!res.ok) return;
      const task = await res.json();

      if (dom.comfyuiProgressBar) dom.comfyuiProgressBar.style.width = `${task.progress || 10}%`;
      if (dom.comfyuiProgressNum) dom.comfyuiProgressNum.textContent = `${Math.round(task.progress || 10)}%`;
      if (dom.comfyuiProgressMsg) dom.comfyuiProgressMsg.textContent = task.message || "推理中...";

      if (task.status === "completed") {
        clearInterval(taskPollingTimer);
        taskPollingTimer = null;
        resetTwoStageBtns();
        hideProgressBox();

        await reloadAlignmentData();
        const updatedShots = state.alignment?.storyboard || [];
        activeShot = updatedShots[currentShotIndex] || updatedShots[0];
        updateInspector(activeShot);
        updateCinemaScreen(activeShot);
        renderAnimaticTimeline();
        if (dom.viewGallery && dom.viewGallery.style.display !== "none") {
          renderGalleryView();
        }

        if (taskType === "keyframe") {
          status(`🎉 镜头 ${activeShot.id} 电影首帧生成成功！材质已锁定。`);
        } else if (taskType === "endframe") {
          status(`🎉 镜头 ${activeShot.id} 电影尾帧生成成功！可一键传递给下一镜首帧实现一镜到底。`);
        } else if (taskType === "i2v") {
          status(`🎉 镜头 ${activeShot.id} I2V 动态视频 Take 生成完成并设为正片！`);
        } else {
          status(`🎉 镜头 ${activeShot.id} 两阶段生成全部完成！已设为正片播放素材。`);
        }
      } else if (task.status === "failed") {
        clearInterval(taskPollingTimer);
        taskPollingTimer = null;
        resetTwoStageBtns();
        const errMsg = task.error || task.message || "生成异常中断";
        if (dom.comfyuiProgressBar) dom.comfyuiProgressBar.style.background = "#ef4444";
        if (dom.comfyuiProgressMsg) dom.comfyuiProgressMsg.textContent = `❌ ${errMsg}`;
        status(`❌ 生成失败: ${errMsg}`);
        setTimeout(() => {
          if (dom.comfyuiProgressBar) dom.comfyuiProgressBar.style.background = "";
          hideProgressBox();
        }, 6000);
      }
    } catch (err) {
      console.warn("轮询任务状态异常:", err);
    }
  }, 1500);
}

function renderGalleryView() {
  if (!dom.galleryGrid || !state.alignment?.storyboard) return;
  dom.galleryGrid.innerHTML = "";
  const shots = state.alignment.storyboard;

  const curJson = state.currentFile?.json_path || "";

  shots.forEach((shot, idx) => {
    const card = document.createElement("div");
    card.style.cssText = `
      background: #111827; border: 1px solid #1f2937; border-radius: 6px;
      overflow: hidden; display: flex; flex-direction: column; cursor: pointer;
      transition: all 0.2s ease;
    `;
    card.onmouseover = () => { card.style.borderColor = "#6366f1"; card.style.transform = "translateY(-2px)"; };
    card.onmouseout = () => { card.style.borderColor = "#1f2937"; card.style.transform = "none"; };

    const hasKf = !!shot.preview_image;
    const dur = shot.duration || (shot.end - shot.start);
    const kfUrl = shot.preview_image
      ? (shot.preview_image.startsWith("storyboard/") && state.currentFile
          ? `/api/storyboard_frame?json_path=${encodeURIComponent(curJson)}&frame_name=${encodeURIComponent(shot.preview_image.replace('storyboard/', ''))}&t=${Date.now()}`
          : `/api/asset_file?path=${encodeURIComponent(shot.preview_image)}&json_path=${encodeURIComponent(curJson)}&t=${Date.now()}`)
      : null;

    card.innerHTML = `
      <div style="position: relative; width: 100%; aspect-ratio: 16/9; background: #000; overflow: hidden; display: flex; align-items: center; justify-content: center;">
        ${hasKf 
          ? `<img src="${kfUrl}" style="width: 100%; height: 100%; object-fit: cover;">`
          : `<span style="font-size: 11px; color: #6b7280;">未生成首帧</span>`
        }
        <span style="position: absolute; top: 6px; left: 6px; background: rgba(0,0,0,0.75); color: #fff; font-size: 10px; font-weight: bold; padding: 2px 6px; border-radius: 3px;">
          SHOT ${shot.shot_id || idx + 1}
        </span>
        <span style="position: absolute; bottom: 6px; right: 6px; background: rgba(0,0,0,0.75); color: #818cf8; font-size: 10px; padding: 2px 5px; border-radius: 3px;">
          ${dur.toFixed(1)}s • ${shot.shot_size || 'MS'}
        </span>
      </div>
      <div style="padding: 10px; display: flex; flex-direction: column; gap: 6px; flex: 1;">
        <div style="font-size: 11px; color: #9ca3af; line-height: 1.3; height: 32px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">
          ${shot.action || shot.prompt_zh || shot.prompt_en || '无描述'}
        </div>
        <div style="margin-top: auto; display: flex; gap: 4px;">
          <button class="btn-card-copy" style="padding: 4px 6px; background: #0b1120; border: 1px solid #38bdf8; color: #7dd3fc; border-radius: 3px; font-size: 10px; cursor: pointer;" title="复制英文 Prompt (按住 Shift 或 Alt 复制中文分镜)">
            📋 复制
          </button>
          <button class="btn-card-kf" style="flex: 1; padding: 4px 6px; background: #1e1b4b; border: 1px solid #4f46e5; color: #c7d2fe; border-radius: 3px; font-size: 10px; cursor: pointer;">
            📸 ${hasKf ? '重刷首帧' : '生成首帧'}
          </button>
          <button class="btn-card-edit" style="padding: 4px 6px; background: #1f2937; border: 1px solid #374151; color: #e5e7eb; border-radius: 3px; font-size: 10px; cursor: pointer;">
            🎬 剪辑
          </button>
        </div>
      </div>
    `;

    const copyBtn = card.querySelector(".btn-card-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const copyZh = e.shiftKey || e.altKey;
        const text = copyZh ? buildShotPromptZH(shot) : buildShotPromptEN(shot, "video");
        copyTextToClipboard(text, copyBtn, `已复制 Shot ${shot.shot_id || idx + 1} ${copyZh ? '中文分镜' : '英文 Prompt'}`);
      });
    }

    card.querySelector(".btn-card-kf").addEventListener("click", async (e) => {
      e.stopPropagation();
      selectShot(idx, true);
      handleGenerateKeyframe();
    });

    card.querySelector(".btn-card-edit").addEventListener("click", (e) => {
      e.stopPropagation();
      selectShot(idx, true);
      switchViewMode("animatic");
    });

    card.addEventListener("click", () => {
      selectShot(idx, true);
      switchViewMode("animatic");
    });

    dom.galleryGrid.appendChild(card);
  });
}

async function handleBatchGenerateKeyframes() {
  if (!state.currentFile) return;
  if (!confirm("确定要为前 10 个镜头批量生成电影级首帧 (FLUX 12B) 吗？预计耗时约 60 秒。")) return;
  status("⚡ 正在批量调度 FLUX 生成前 10 镜首帧...");
  const shots = (state.alignment?.storyboard || []).slice(0, 10);
  for (let i = 0; i < shots.length; i++) {
    const s = shots[i];
    status(`[${i+1}/10] 正在生成 Shot ${s.shot_id} 电影首帧...`);
    try {
      const res = await fetch("/api/comfyui/generate_keyframe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          json_path: state.currentFile.json_path,
          shot_id: s.id,
          resolution: "768x448",
          steps: 4,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        // 简单等待完成
        let completed = false;
        while (!completed) {
          await new Promise(r => setTimeout(r, 1200));
          const tr = await fetch(`/api/comfyui/task_status?task_id=${encodeURIComponent(data.task_id)}`);
          if (tr.ok) {
            const td = await tr.json();
            if (td.status === "completed" || td.status === "failed") {
              completed = true;
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
    }
  }
  await reloadAlignmentData();
  renderGalleryView();
  status("🎉 前 10 镜电影级首帧全部生成完毕！");
}

async function reloadAlignmentData() {
  if (!state.currentFile) return;
  try {
    const r = await fetch("/api/alignment?path=" + encodeURIComponent(state.currentFile.json_path));
    if (r.ok) {
      state.alignment = await r.json();
    }
  } catch (e) {
    console.warn("重新拉取工程数据失败:", e);
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
      if (dom.lyricsList) {
        dom.lyricsList.querySelectorAll(".ref-lyric-row").forEach(r => r.classList.remove("active"));
      }
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
