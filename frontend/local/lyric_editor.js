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

  if (dom.btnMuteVocals) dom.btnMuteVocals.addEventListener("click", () => toggleMuteTrack("vocals"));
  if (dom.btnMuteInst) dom.btnMuteInst.addEventListener("click", () => toggleMuteTrack("instrumental"));

  document.addEventListener("keydown", handleLyricKey);
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
    const charSpans = line.words.map((w, wi) =>
      `<span class="lyric-char" data-line="${i}" data-word="${wi}">${escHtml(w.word)}</span>`
    ).join("");
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
  const lineStart = line.start, lineEnd = line.end, lineDur = lineEnd - lineStart || 1;

  dom.wordTimeline.innerHTML = "";
  const container = document.createElement("div");
  container.className = "word-bar-container";

  words.forEach((w, i) => {
    const dur = w.end - w.start;
    const widthPct = (dur / lineDur) * 100;
    const bar = document.createElement("div");
    bar.className = "word-bar" + (isPunct(w.word) ? " punct" : "");
    bar.style.width = `${Math.max(widthPct, 1)}%`;
    bar.dataset.idx = i;
    bar.title = `${w.word}  ${fmtTime(w.start)} → ${fmtTime(w.end)}  (${(dur * 1000).toFixed(0)}ms)`;
    bar.innerHTML = `
      <span>${escHtml(w.word)}</span>
      <span class="word-dur">${(dur * 1000).toFixed(0)}</span>
      <div class="drag-handle" title="拖拽调整 | 双击=设为当前播放位置"></div>`;

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

    setupDragHandle(bar, i, lineIdx);
    const handle = bar.querySelector(".drag-handle");
    if (handle) {
      handle.addEventListener("dblclick", (e) => {
        e.preventDefault(); e.stopPropagation();
        snapSplitToPlayhead(lineIdx, i);
      });
    }

    container.appendChild(bar);
  });

  dom.wordTimeline.appendChild(container);
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
function snapSplitToPlayhead(lineIdx, wordIdx) {
  if (!ws) return;
  const line = state.alignment.lines[lineIdx];
  if (!line) return;
  const words = line.words;
  const isLast = (wordIdx === words.length - 1);
  const t = ws.getCurrentTime();

  if (isLast) {
    const clamped = Math.round(Math.max(words[wordIdx].start + 0.01, t) * 1000) / 1000;
    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;
    pushUndo();
    words[wordIdx].end = clamped; line.end = clamped;
    renderLyrics(); selectLine(lineIdx); selectWord(wordIdx); markDirty();
    status(`✂ 行尾 → ${fmtTimeShort(clamped)}`);
  } else {
    const minVal = words[wordIdx].start + 0.01, maxVal = words[wordIdx + 1].end - 0.01;
    const clamped = Math.round(Math.max(minVal, Math.min(maxVal, t)) * 1000) / 1000;
    if (Math.abs(clamped - words[wordIdx].end) < 0.001) return;
    pushUndo();
    words[wordIdx].end = clamped; words[wordIdx + 1].start = clamped;
    syncLineFromWords(lineIdx); renderWords(lineIdx); selectWord(wordIdx); markDirty();
    status(`✂ 分割点 ${wordIdx + 1}|${wordIdx + 2} → ${fmtTimeShort(clamped)}`);
  }
}

function setupDragHandle(bar, wordIdx, lineIdx) {
  const handle = bar.querySelector(".drag-handle");
  if (!handle) return;
  let startX = 0, startEnd = 0, containerWidth = 0, lineDur = 0;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault(); e.stopPropagation();
    const line = state.alignment.lines[lineIdx];
    const words = line.words;
    if (wordIdx >= words.length - 1) return;
    pushUndo();
    startX = e.clientX; startEnd = words[wordIdx].end;
    containerWidth = bar.parentElement.getBoundingClientRect().width;
    lineDur = line.end - line.start;

    const onMove = (ev) => {
      const dx = ev.clientX - startX, dt = (dx / containerWidth) * lineDur;
      const newEnd = Math.round((startEnd + dt) * 1000) / 1000;
      const minEnd = words[wordIdx].start + 0.01, maxEnd = words[wordIdx + 1].end - 0.01;
      const clamped = Math.max(minEnd, Math.min(maxEnd, newEnd));
      words[wordIdx].end = clamped; words[wordIdx + 1].start = clamped;
      renderWords(lineIdx); selectWord(wordIdx); markDirty();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      syncLineFromWords(lineIdx);
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
  pushUndo();
  const newStart = Math.round((words[idx].start + delta) * 1000) / 1000;
  const newEnd   = Math.round((words[idx].end + delta) * 1000) / 1000;
  if (newStart < 0 || newEnd < 0) return;
  if (idx > 0 && newStart < words[idx - 1].start + 0.01) return;
  if (idx < words.length - 1 && newEnd > words[idx + 1].end - 0.01) return;
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
  if (!line) return;
  const parsed = parseTimeInput(input.value);
  if (parsed === null) {
    input.value = fmtTimeShort(line[field]);
    status("时间格式错误，请输入 m:ss.xxx 或 秒数", true); return;
  }
  if (field === "start") resizeLine(idx, parsed - line.start, 0);
  else resizeLine(idx, 0, parsed - line.end);
}
