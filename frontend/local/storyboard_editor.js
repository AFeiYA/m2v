// ===========================================================================
// M2V Local Editor — Video Storyboard & Asset Editor Module (for storyboard.html)
// ===========================================================================

let selectedAsset = null;
let bgPickerMode = false;

document.addEventListener("DOMContentLoaded", () => {
  dom.songSelect          = $("#song-select");
  dom.btnSave             = $("#btn-save");
  dom.btnSetBg            = $("#btn-set-bg");
  dom.bgName              = $("#bg-name");
  dom.btnGenerate         = $("#btn-generate");
  dom.generateModal       = $("#generate-modal");
  dom.btnCloseGenerate    = $("#btn-close-generate");
  dom.btnConfirmGenerate  = $("#btn-confirm-generate");
  dom.statusMsg           = $("#status-msg");

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

  dom.lyricsList          = $("#lyrics-list");

  // Storyboard DOM
  dom.btnBrowseAssets     = $("#btn-browse-assets");
  dom.assetModal          = $("#asset-modal");
  dom.assetGrid           = $("#asset-grid");
  dom.assetPreview        = $("#asset-preview");
  dom.currentAssetName    = $("#current-asset-name");
  dom.assetStart          = $("#asset-start");
  dom.assetEnd            = $("#asset-end");
  dom.btnAssetSync        = $("#btn-asset-sync");
  dom.btnAssetAdd         = $("#btn-asset-add");
  dom.storyboardList      = $("#storyboard-list");
  dom.assetModalClose     = $("#btn-close-asset");
  dom.assetFileInput      = $("#asset-file-input");
  dom.uploadStatus        = $("#upload-status");

  try {
    initWaveSurfer();
  } catch (err) {
    console.warn("WaveSurfer 初始化异常:", err);
  }

  bindStoryboardEvents();
  loadFileList();
});

// ---------------------------------------------------------------------------
// Lifecycle Hooks
// ---------------------------------------------------------------------------
window.onSongLoaded = () => {
  renderReferenceLyrics();
  renderStoryboard();
  updateBgDisplay();
};

window.onAlignmentChanged = () => {
  renderReferenceLyrics();
  renderStoryboard();
  updateBgDisplay();
};

window.onPlaybackTick = () => {
  highlightReferenceLine();
};

// ---------------------------------------------------------------------------
// Event Listeners
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
  if (dom.btnPlayLine) dom.btnPlayLine.addEventListener("click", playSelectedLine);
  if (dom.zoomSlider) {
    dom.zoomSlider.addEventListener("input", () => {
      const z = Number(dom.zoomSlider.value);
      if (ws) ws.zoom(z);
      if (wsInst && instReady) wsInst.zoom(z);
    });
  }

  if (dom.btnMuteVocals) dom.btnMuteVocals.addEventListener("click", () => toggleMuteTrack("vocals"));
  if (dom.btnMuteInst) dom.btnMuteInst.addEventListener("click", () => toggleMuteTrack("instrumental"));

  if (dom.btnGenerate) dom.btnGenerate.addEventListener("click", () => dom.generateModal.style.display = "flex");
  if (dom.btnCloseGenerate) dom.btnCloseGenerate.addEventListener("click", () => dom.generateModal.style.display = "none");
  if (dom.btnConfirmGenerate) {
    dom.btnConfirmGenerate.addEventListener("click", () => {
      if (dom.generateModal) dom.generateModal.style.display = "none";
      generateOutput();
    });
  }

  if (dom.btnBrowseAssets) dom.btnBrowseAssets.addEventListener("click", openAssetModal);
  if (dom.assetModalClose) dom.assetModalClose.addEventListener("click", () => dom.assetModal.style.display = "none");
  if (dom.btnAssetSync) dom.btnAssetSync.addEventListener("click", syncAssetToCurrentLine);
  if (dom.btnAssetAdd) dom.btnAssetAdd.addEventListener("click", addOrUpdateAssetEvent);
  if (dom.assetFileInput) dom.assetFileInput.addEventListener("change", handleAssetUpload);
  if (dom.btnSetBg) dom.btnSetBg.addEventListener("click", openBgPicker);

  if (dom.assetModal) {
    dom.assetModal.addEventListener("click", (e) => {
      if (e.target === dom.assetModal) dom.assetModal.style.display = "none";
    });
  }
  if (dom.generateModal) {
    dom.generateModal.addEventListener("click", (e) => {
      if (e.target === dom.generateModal) dom.generateModal.style.display = "none";
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (ctrl && e.code === "KeyS") { e.preventDefault(); saveAlignment(); }
    else if (ctrl && e.code === "KeyZ" && !e.shiftKey) { e.preventDefault(); undo(); }
    else if (ctrl && (e.code === "KeyY" || (e.code === "KeyZ" && e.shiftKey))) { e.preventDefault(); redo(); }
    else if (e.code === "Enter") { e.preventDefault(); playSelectedLine(); }
  });
}

// ---------------------------------------------------------------------------
// Left Column: Reference Lyrics List
// ---------------------------------------------------------------------------
function renderReferenceLyrics() {
  if (!dom.lyricsList) return;
  const lines = state.alignment?.lines || [];
  const sections = state.alignment?.sections || [];
  dom.lyricsList.innerHTML = "";

  lines.forEach((line, i) => {
    const matchedSec = sections.find(s => s.line_indices && s.line_indices[0] === i);
    if (matchedSec) {
      const secDiv = document.createElement("div");
      secDiv.className = "section-header";
      secDiv.innerHTML = `
        <span class="sec-badge">🔖 ${escHtml(matchedSec.label || matchedSec.name)}</span>
        <span class="sec-time">${fmtTimeShort(matchedSec.start)} → ${fmtTimeShort(matchedSec.end)}</span>
      `;
      dom.lyricsList.appendChild(secDiv);
    }

    const row = document.createElement("div");
    row.className = "lyric-row";
    row.dataset.idx = i;
    row.innerHTML = `
      <span class="lyric-num">${i + 1}</span>
      <span class="lyric-text" style="flex:1;">${escHtml(line.text)}</span>
      <span class="sec-time">${fmtTimeShort(line.start)} → ${fmtTimeShort(line.end)}</span>
    `;

    row.addEventListener("click", () => {
      selectReferenceLine(i);
    });
    row.addEventListener("dblclick", () => {
      if (ws) {
        ws.setTime(line.start);
        ws.play();
        if (dom.btnPlayPause) dom.btnPlayPause.textContent = "⏸ 暂停";
        if (wsInst && instReady) { wsInst.setTime(line.start); wsInst.play(); }
      }
    });
    dom.lyricsList.appendChild(row);
  });
}

function selectReferenceLine(idx) {
  state.selectedLine = idx;
  $$(".lyric-row").forEach((row, i) => row.classList.toggle("selected", i === idx));
  const line = state.alignment?.lines?.[idx];
  if (line) {
    if (dom.assetStart && !dom.assetStart.value) dom.assetStart.value = fmtTimeShort(line.start);
    if (dom.assetEnd && !dom.assetEnd.value) dom.assetEnd.value = fmtTimeShort(line.end);
  }
}

function highlightReferenceLine() {
  if (!ws || !state.alignment) return;
  const t = ws.getCurrentTime();
  const lines = state.alignment.lines;

  $$(".lyric-row").forEach((row, i) => {
    const line = lines[i];
    const playing = line && t >= line.start && t <= line.end;
    row.classList.toggle("playing", playing);
  });
}

// ---------------------------------------------------------------------------
// Storyboard / Asset Logic
// ---------------------------------------------------------------------------
async function openAssetModal() {
  dom.assetModal.style.display = "flex";
  dom.uploadStatus.textContent = "";
  loadAssetGrid();
}

async function loadAssetGrid() {
  dom.assetGrid.innerHTML = "加载中…";
  try {
    const r = await fetch("/api/assets");
    const assets = await r.json();
    if (assets.length === 0) {
      dom.assetGrid.innerHTML = '<span style="color:var(--text-dim);font-size:13px;">暂无素材，请点击"上传图片"添加</span>';
      return;
    }
    dom.assetGrid.innerHTML = assets.map(a => `
      <div class="asset-card" data-path="${escHtml(a.path)}" data-url="${escHtml(a.url)}" data-name="${escHtml(a.name)}">
        ${isImage(a.name) ? `<img src="${a.url}" alt="">` : `<div style="height:80px; display:flex; align-items:center; justify-content:center; background:#000;">📹</div>`}
        <span>${escHtml(a.name)}</span>
      </div>
    `).join("");

    $$(".asset-card").forEach(card => {
      card.addEventListener("click", () => {
        selectAsset({
          name: card.dataset.name,
          path: card.dataset.path,
          url: card.dataset.url,
        });
        dom.assetModal.style.display = "none";
      });
    });
  } catch (e) {
    dom.assetGrid.innerHTML = "加载素材失败: " + e;
  }
}

async function handleAssetUpload(e) {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  dom.uploadStatus.textContent = `上传中 (0/${files.length})…`;
  let ok = 0;
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/upload_asset", { method: "POST", body: fd });
      if (r.ok) ok++;
      else {
        const j = await r.json();
        dom.uploadStatus.textContent = "上传失败: " + (j.detail || r.status);
      }
    } catch (err) {
      dom.uploadStatus.textContent = "上传失败: " + err;
    }
  }
  e.target.value = "";
  dom.uploadStatus.textContent = `✅ 已上传 ${ok}/${files.length}`;
  loadAssetGrid();
}

function selectAsset(asset) {
  selectedAsset = asset;
  dom.currentAssetName.textContent = asset.name;
  if (isImage(asset.name)) {
    dom.assetPreview.innerHTML = `<img src="${asset.url}" alt="" style="max-width:100%; max-height:100%; object-fit:contain;">`;
  } else {
    dom.assetPreview.innerHTML = `<span>📹 视频素材</span>`;
  }
}

function syncAssetToCurrentLine() {
  if (state.selectedLine < 0) { status("请先在左侧选择一行歌词", true); return; }
  const line = state.alignment.lines[state.selectedLine];
  dom.assetStart.value = fmtTimeShort(line.start);
  dom.assetEnd.value = fmtTimeShort(line.end);
  status(`已同步第 ${state.selectedLine + 1} 行时间: ${fmtTimeShort(line.start)} ~ ${fmtTimeShort(line.end)}`);
}

function addOrUpdateAssetEvent() {
  if (!selectedAsset) { status("请先选择素材", true); return; }
  const start = parseTimeInput(dom.assetStart.value);
  const end = parseTimeInput(dom.assetEnd.value);

  if (start === null || end === null || end <= start) {
    status("时间输入无效 (结束时间需大于起始时间)", true);
    return;
  }

  pushUndo();
  if (!state.alignment.storyboard) state.alignment.storyboard = [];

  state.alignment.storyboard.push({
    shot_id: state.alignment.storyboard.length + 1,
    type: isImage(selectedAsset.name) ? "image" : "video",
    path: selectedAsset.path,
    start: start,
    end: end,
    speed_align: true,
  });

  // 按时间排序
  state.alignment.storyboard.sort((a, b) => a.start - b.start);

  renderStoryboard();
  markDirty();
  status("✅ 已添加分镜镜头");
}

function renderStoryboard() {
  if (!dom.storyboardList) return;
  const events = state.alignment?.storyboard || [];
  dom.storyboardList.innerHTML = events.map((e, i) => `
    <tr>
      <td title="${escHtml(e.path)}">${escHtml(e.path.split(/[\\/]/).pop())}</td>
      <td>${fmtTimeShort(e.start)}</td>
      <td>${fmtTimeShort(e.end)}</td>
      <td><button class="btn-delete-asset" data-idx="${i}" style="padding: 2px 8px; border-radius: 4px; background: #ef4444; color:#fff; border:none; cursor:pointer;">删除</button></td>
    </tr>
  `).join("");

  dom.storyboardList.querySelectorAll(".btn-delete-asset").forEach(btn => {
    btn.addEventListener("click", () => {
      pushUndo();
      state.alignment.storyboard.splice(Number(btn.dataset.idx), 1);
      renderStoryboard();
      markDirty();
    });
  });
}

function isImage(filename) {
  return /\.(jpg|jpeg|png|webp)$/i.test(filename);
}

// ---------------------------------------------------------------------------
// Background Image Picker
// ---------------------------------------------------------------------------
function openBgPicker() {
  bgPickerMode = true;
  dom.assetModal.style.display = "flex";
  dom.uploadStatus.textContent = "";
  loadAssetGridForBg();
}

async function loadAssetGridForBg() {
  dom.assetGrid.innerHTML = "加载中…";
  try {
    const r = await fetch("/api/assets");
    const assets = await r.json();
    const images = assets.filter(a => isImage(a.name));
    if (images.length === 0) {
      dom.assetGrid.innerHTML = '<span style="color:var(--text-dim);font-size:13px;">暂无图片素材，请点击"上传图片"添加</span>';
      return;
    }

    dom.assetGrid.innerHTML = `
      <div class="asset-card" data-path="" data-name="无背景">
        <div style="height:80px; display:flex; align-items:center; justify-content:center; background:#111; color:var(--text-dim); font-size:24px;">✖</div>
        <span>清除背景</span>
      </div>
    ` + images.map(a => `
      <div class="asset-card" data-path="${escHtml(a.path)}" data-url="${escHtml(a.url)}" data-name="${escHtml(a.name)}">
        <img src="${a.url}" alt="">
        <span>${escHtml(a.name)}</span>
      </div>
    `).join("");

    $$(".asset-card").forEach(card => {
      card.addEventListener("click", () => {
        if (bgPickerMode) {
          setBackground(card.dataset.path, card.dataset.name);
          dom.assetModal.style.display = "none";
          bgPickerMode = false;
        } else {
          selectAsset({
            name: card.dataset.name,
            path: card.dataset.path,
            url: card.dataset.url,
          });
          dom.assetModal.style.display = "none";
        }
      });
    });
  } catch (e) {
    dom.assetGrid.innerHTML = "加载素材失败: " + e;
  }
}

function setBackground(path, name) {
  if (!state.alignment) return;
  pushUndo();
  state.alignment.background = path || null;
  updateBgDisplay();
  markDirty();
  status(path ? `✅ 背景已设置: ${name}` : "背景已清除");
}

function updateBgDisplay() {
  if (!dom.bgName) return;
  const bg = state.alignment?.background;
  if (bg) {
    const name = bg.split(/[\\/]/).pop();
    dom.bgName.textContent = name;
    dom.bgName.title = bg;
  } else {
    dom.bgName.textContent = "未设置";
    dom.bgName.title = "";
  }
}
