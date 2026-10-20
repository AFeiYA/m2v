// ===========================================================================
// M2V Local Editor — Lyric & Subtitle Editor Module (for index.html)
// ===========================================================================

const PORTRAIT_SAFE_AREA = {
  aspect_ratio: "9:16",
  top_pct: 0.14,
  bottom_pct: 0.76,
  left_pct: 0.08,
  right_pct: 0.86,
  unsafe_zones: {
    top: "Top 14%: status bar, creator handle, and live/search chrome",
    bottom: "Bottom 24% (76%–100%): caption copy, sound marquee, and playback scrub bar",
    right: "Right 14% (86%–100%): like, comment, share, and bookmark action rail",
    left: "Left 8% (0%–8%): screen edge breathing margin",
  },
};

const CURATED_EXPORT_THEMES = [
  {
    "id": "impact",
    "name": "Impact Lime",
    "subtitle": "Motion Design palette",
    "theme": "impact",
    "accent": "#c8ff00",
    "secondary": "#f4f9ed",
    "bg_preview": "#0d120a"
  },
  {
    "id": "neon",
    "name": "Neon Cyan",
    "subtitle": "Motion Design palette",
    "theme": "neon",
    "accent": "#00f0ff",
    "secondary": "#eef8fc",
    "bg_preview": "#070e17"
  },
  {
    "id": "sunset",
    "name": "Sunset",
    "subtitle": "Motion Design palette",
    "theme": "sunset",
    "accent": "#ff5028",
    "secondary": "#fdf2f0",
    "bg_preview": "#140907"
  },
  {
    "id": "amber",
    "name": "Amber",
    "subtitle": "Motion Design palette",
    "theme": "amber",
    "accent": "#ffbe1a",
    "secondary": "#faf7ed",
    "bg_preview": "#141108"
  },
  {
    "id": "violet",
    "name": "Violet",
    "subtitle": "Motion Design palette",
    "theme": "violet",
    "accent": "#c084fc",
    "secondary": "#f7f1fc",
    "bg_preview": "#100818"
  },
  {
    "id": "sakura",
    "name": "Sakura",
    "subtitle": "Motion Design palette",
    "theme": "sakura",
    "accent": "#ff5c8a",
    "secondary": "#fef1f5",
    "bg_preview": "#160810"
  },
  {
    "id": "monochrome",
    "name": "Monochrome",
    "subtitle": "Motion Design palette",
    "theme": "monochrome",
    "accent": "#ffffff",
    "secondary": "#dcdcdc",
    "bg_preview": "#0d0d0d"
  }
];

function exportTemplateForRatio(ratio) { return ratio === "16:9" ? "tv" : "apple"; }

function buildExportClips(alignment) {
  const lines = (alignment?.lines || []).filter(l => l.end > l.start);
  const sections = alignment?.sections || [];
  const findSection = (pattern) => {
    const section = sections.find(s => pattern.test(String(s.name || s.label || "").trim().replace(/^\[|\]$/g, "")));
    if (section) {
      const index = sections.indexOf(section);
      const end = Number(section.end ?? sections[index+1]?.start ?? alignment.duration ?? lines.at(-1)?.end);
      const members = lines.filter(l => l.start >= section.start - .05 && l.start < end);
      if (members.length) return {start_time:members[0].start,end_time:members.at(-1).end};
    }
    const first = lines.findIndex(l => pattern.test(String(l.section || "").trim().replace(/^\[|\]$/g, "")));
    if (first < 0) return null;
    let last = first; while (last+1 < lines.length && lines[last+1].section === lines[first].section) last++;
    return {start_time:lines[first].start,end_time:lines[last].end};
  };
  const verse = findSection(/^(?:verse(?:\s*\d+)?|主歌.*)$/i);
  const chorus = findSection(/^(?:(?:final\s+)?chorus(?:\s*\d+)?|副歌.*)$/i);
  const best = recommendExcerptCandidates(alignment)[0];
  return [
    {id:"full",title:"Full song",available:true,start_time:0,end_time:null},
    {id:"verse",title:"Verse",available:!!verse,...verse},
    {id:"chorus",title:"Chorus",available:!!chorus,...chorus},
    {id:"highlight",title:"Highlight (suggested)",available:!!best,start_time:best?.start_time,end_time:best?.end_time},
  ];
}

function countVocalUnits(text) {
  const cleaned = String(text || "").replace(/\\N/g, " ").trim();
  if (!cleaned) return 0;
  const cjkChars = cleaned.match(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g) || [];
  const nonCjk = cleaned.replace(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g, " ");
  const latinWords = nonCjk.match(/[A-Za-z0-9']+/g) || [];
  let latinUnits = 0;
  for (const word of latinWords) {
    const vowels = word.match(/[aeiouyAEIOUY]+/g) || [];
    latinUnits += Math.max(1, Math.min(4, vowels.length));
  }
  return cjkChars.length + latinUnits;
}

function inspectAlignmentTiming(alignment) {
  const counts_by_kind = {
    overlap: 0,
    compressed_duration: 0,
    excessive_gap: 0,
    low_confidence: 0,
  };
  if (!alignment || !Array.isArray(alignment.lines)) {
    return { total_warnings: 0, flagged_line_indices: [], counts_by_kind, warnings: [] };
  }
  const warnings = [];
  const flaggedLines = new Set();

  function addWarning({ kind, severity, line_index, word_index, start, end, title, message, evidence }) {
    counts_by_kind[kind] = (counts_by_kind[kind] || 0) + 1;
    flaggedLines.add(line_index);
    const wSuffix = word_index != null ? `w${word_index}` : "line";
    warnings.push({
      id: `L${line_index}_${wSuffix}_${kind}_${warnings.length}`,
      kind,
      severity,
      line_index,
      word_index,
      start: Math.round(Number(start || 0) * 1000) / 1000,
      end: Math.round(Number(end || 0) * 1000) / 1000,
      title,
      message,
      evidence: evidence || {},
    });
  }

  let prevLineEnd = null;
  let prevLineIdx = null;

  alignment.lines.forEach((line, lineIdx) => {
    if (!line || typeof line !== "object") return;
    const lStart = Number(line.start != null ? line.start : 0);
    const lEnd = Number(line.end != null ? line.end : lStart);
    const lText = String(line.text || "").replace(/\\N/g, " ").trim();
    const lDur = lEnd - lStart;

    if (lEnd <= lStart) {
      addWarning({
        kind: "overlap",
        severity: "error",
        line_index: lineIdx,
        word_index: null,
        start: lStart,
        end: lEnd,
        title: "Inverted line duration",
        message: `Line ${lineIdx + 1} has non-positive duration (${lStart.toFixed(2)}s -> ${lEnd.toFixed(2)}s).`,
        evidence: { start: lStart, end: lEnd, duration_ms: Math.round(lDur * 1000) },
      });
    }

    if (prevLineEnd != null && lStart < prevLineEnd - 0.02) {
      const overlapSec = prevLineEnd - lStart;
      addWarning({
        kind: "overlap",
        severity: "warning",
        line_index: lineIdx,
        word_index: null,
        start: lStart,
        end: Math.min(prevLineEnd, lEnd),
        title: "Line timestamp overlap",
        message: `Line ${lineIdx + 1} starts at ${lStart.toFixed(2)}s before previous line ended at ${prevLineEnd.toFixed(2)}s (overlap: ${Math.round(overlapSec * 1000)}ms).`,
        evidence: {
          overlap_ms: Math.round(overlapSec * 1000),
          prev_line_index: prevLineIdx,
          prev_line_end: prevLineEnd,
          current_line_start: lStart,
        },
      });
    }

    const units = countVocalUnits(lText);
    if (lDur > 0 && lDur < 0.045) {
      addWarning({
        kind: "compressed_duration",
        severity: "warning",
        line_index: lineIdx,
        word_index: null,
        start: lStart,
        end: lEnd,
        title: "Compressed line duration",
        message: `Line ${lineIdx + 1} duration (${Math.round(lDur * 1000)}ms) is below 45ms.`,
        evidence: { duration_ms: Math.round(lDur * 1000), units },
      });
    } else if (units >= 3 && lDur > 0 && (lDur / units) < 0.035) {
      addWarning({
        kind: "compressed_duration",
        severity: "warning",
        line_index: lineIdx,
        word_index: null,
        start: lStart,
        end: lEnd,
        title: "Fast singing / compressed syllables",
        message: `Line ${lineIdx + 1} syllable duration (${Math.round((lDur / units) * 1000)}ms/unit) is implausibly fast.`,
        evidence: { units, sec_per_unit: lDur / units, duration_ms: Math.round(lDur * 1000) },
      });
    }

    if (line.needs_review) {
      addWarning({
        kind: "low_confidence",
        severity: "info",
        line_index: lineIdx,
        word_index: null,
        start: lStart,
        end: lEnd,
        title: "Aligner flagged line for review",
        message: `Line ${lineIdx + 1} was marked as needs_review by the aligner.`,
        evidence: { needs_review: true },
      });
    }

    const words = Array.isArray(line.words) ? line.words : [];
    let prevWordEnd = null;
    let prevWordIdx = null;
    let prevWordText = null;

    words.forEach((w, wIdx) => {
      if (!w || typeof w !== "object") return;
      const wStart = Number(w.start != null ? w.start : lStart);
      const wEnd = Number(w.end != null ? w.end : wStart);
      const wText = String(w.word || "").trim();
      const wDur = wEnd - wStart;

      if (wEnd <= wStart) {
        addWarning({
          kind: "overlap",
          severity: "error",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Inverted word duration",
          message: `Word "${wText}" (idx ${wIdx}) in Line ${lineIdx + 1} has non-positive duration.`,
          evidence: { word: wText, start: wStart, end: wEnd },
        });
      }

      if (wStart < lStart - 0.02) {
        addWarning({
          kind: "overlap",
          severity: "warning",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Word starts before line",
          message: `Word "${wText}" starts at ${wStart.toFixed(2)}s before line start ${lStart.toFixed(2)}s.`,
          evidence: { word: wText, word_start: wStart, line_start: lStart },
        });
      }

      if (wEnd > lEnd + 0.02) {
        addWarning({
          kind: "overlap",
          severity: "warning",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Word ends after line",
          message: `Word "${wText}" ends at ${wEnd.toFixed(2)}s after line end ${lEnd.toFixed(2)}s.`,
          evidence: { word: wText, word_end: wEnd, line_end: lEnd },
        });
      }

      if (prevWordEnd != null && wStart < prevWordEnd - 0.01) {
        const overlapSec = prevWordEnd - wStart;
        addWarning({
          kind: "overlap",
          severity: "warning",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: Math.min(prevWordEnd, wEnd),
          title: "Word timestamp overlap",
          message: `Word "${wText}" overlaps with previous word "${prevWordText}" by ${Math.round(overlapSec * 1000)}ms.`,
          evidence: {
            word: wText,
            prev_word: prevWordText,
            overlap_ms: Math.round(overlapSec * 1000),
          },
        });
      }

      if (prevWordEnd != null && (wStart - prevWordEnd) > 1.2) {
        const gapSec = wStart - prevWordEnd;
        addWarning({
          kind: "excessive_gap",
          severity: "info",
          line_index: lineIdx,
          word_index: wIdx,
          start: prevWordEnd,
          end: wStart,
          title: "Excessive intra-line gap",
          message: `Gap of ${gapSec.toFixed(2)}s between "${prevWordText}" and "${wText}".`,
          evidence: { gap_seconds: gapSec, prev_word: prevWordText, next_word: wText },
        });
      }

      if (wDur > 0 && wDur < 0.045 && !wText.match(/^[，。！？、,.!?]+$/)) {
        addWarning({
          kind: "compressed_duration",
          severity: "warning",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Compressed word duration",
          message: `Word "${wText}" duration (${Math.round(wDur * 1000)}ms) is below 45ms.`,
          evidence: { word: wText, duration_ms: Math.round(wDur * 1000) },
        });
      }

      if (wIdx === words.length - 1 && wDur > 3.5 && lDur > 0 && (wDur / lDur) > 0.72) {
        addWarning({
          kind: "excessive_gap",
          severity: "info",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Stretched tail word",
          message: `Final word "${wText}" lasts ${wDur.toFixed(2)}s (${Math.round((wDur / lDur) * 100)}% of line).`,
          evidence: { word: wText, duration: wDur, line_ratio: wDur / lDur },
        });
      }

      if (w.needs_review) {
        addWarning({
          kind: "low_confidence",
          severity: "info",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Low confidence word alignment",
          message: `Word "${wText}" flagged for manual review.`,
          evidence: { word: wText, needs_review: true },
        });
      }
      if (w.unresolved_compound) {
        addWarning({
          kind: "low_confidence",
          severity: "info",
          line_index: lineIdx,
          word_index: wIdx,
          start: wStart,
          end: wEnd,
          title: "Unresolved compound token",
          message: `Word "${wText}" is an unresolved compound token.`,
          evidence: { word: wText, unresolved_compound: true },
        });
      }

      prevWordEnd = prevWordEnd != null ? Math.max(prevWordEnd, wEnd) : wEnd;
      prevWordIdx = wIdx;
      prevWordText = wText;
    });

    prevLineEnd = prevLineEnd != null ? Math.max(prevLineEnd, lEnd) : lEnd;
    prevLineIdx = lineIdx;
  });

  return {
    total_warnings: warnings.length,
    flagged_line_indices: Array.from(flaggedLines).sort((a, b) => a - b),
    counts_by_kind,
    warnings,
  };
}

function snapExcerptToSentenceBounds(alignment, startTime = 0.0, endTime = null, durationLimit = null) {
  const rawLines = (alignment && Array.isArray(alignment.lines)) ? alignment.lines : [];
  const validLines = [];
  rawLines.forEach((l, idx) => {
    if (!l || typeof l !== "object") return;
    const s = Number(l.start != null ? l.start : 0);
    const e = Number(l.end != null ? l.end : s);
    const text = String(l.text || "").replace(/\\N/g, " ").trim();
    if (e > s) validLines.push({ idx, start: s, end: e, text });
  });

  const reqStart = Math.max(0, Number(startTime || 0));
  let reqEnd;
  if (endTime != null && Number(endTime) > reqStart) {
    reqEnd = Number(endTime);
  } else if (durationLimit != null && Number(durationLimit) > 0) {
    reqEnd = reqStart + Number(durationLimit);
  } else {
    reqEnd = reqStart + 25.0;
  }

  if (!validLines.length) {
    const dur = Math.max(1.0, reqEnd - reqStart);
    return {
      start_time: Math.round(reqStart * 1000) / 1000,
      end_time: Math.round((reqStart + dur) * 1000) / 1000,
      duration: Math.round(dur * 1000) / 1000,
      start_line_index: 0,
      end_line_index: 0,
      line_count: 0,
      preview_text: "",
    };
  }

  let startPos = 0;
  let bestStartDist = Infinity;
  for (let i = 0; i < validLines.length; i++) {
    const { start: ls, end: le } = validLines[i];
    if (ls <= reqStart && reqStart < le - 0.15) {
      startPos = i;
      break;
    }
    const dist = Math.abs(ls - reqStart);
    if (dist < bestStartDist) {
      bestStartDist = dist;
      startPos = i;
    }
  }

  let endPos = startPos;
  let bestEndDist = Infinity;
  for (let i = startPos; i < validLines.length; i++) {
    const { end: le } = validLines[i];
    const dist = Math.abs(le - reqEnd);
    if (dist < bestEndDist) {
      bestEndDist = dist;
      endPos = i;
    }
    if (le >= reqEnd && i > startPos) break;
  }

  const snappedStart = validLines[startPos].start;
  const snappedEnd = validLines[endPos].end;
  const previewLines = [];
  for (let p = startPos; p <= endPos; p++) {
    if (validLines[p].text) previewLines.push(validLines[p].text);
  }
  let previewText = previewLines.slice(0, 3).join(" / ");
  if (previewLines.length > 3) previewText += " …";

  return {
    start_time: Math.round(snappedStart * 1000) / 1000,
    end_time: Math.round(snappedEnd * 1000) / 1000,
    duration: Math.round(Math.max(0.1, snappedEnd - snappedStart) * 1000) / 1000,
    start_line_index: validLines[startPos].idx,
    end_line_index: validLines[endPos].idx,
    line_count: endPos - startPos + 1,
    preview_text: previewText,
  };
}

function recommendExcerptCandidates(alignment, options = {}) {
  const targetDuration = options.target_duration || 25.0;
  const minDuration = options.min_duration || 12.0;
  const maxDuration = options.max_duration || 45.0;
  const maxCandidates = options.max_candidates || 4;

  if (!alignment || !Array.isArray(alignment.lines) || !alignment.lines.length) {
    return [];
  }

  const lines = [];
  alignment.lines.forEach((l, idx) => {
    if (!l || typeof l !== "object") return;
    const s = Number(l.start != null ? l.start : 0);
    const e = Number(l.end != null ? l.end : s);
    const text = String(l.text || "").replace(/\\N/g, " ").trim();
    if (e > s && text) {
      lines.push({ index: idx, start: s, end: e, duration: e - s, text, units: countVocalUnits(text) });
    }
  });
  if (!lines.length) return [];

  const sections = Array.isArray(alignment.sections) ? alignment.sections : [];
  const candidates = [];

  function windowEndForStart(startPos, preferredEndTime = null) {
    const sTime = lines[startPos].start;
    let bestPos = startPos;
    let bestDiff = Infinity;
    let goalEnd = (preferredEndTime && preferredEndTime > sTime + minDuration)
      ? preferredEndTime
      : (sTime + targetDuration);
    goalEnd = Math.min(sTime + maxDuration, Math.max(sTime + minDuration, goalEnd));

    for (let pos = startPos; pos < lines.length; pos++) {
      const eTime = lines[pos].end;
      const dur = eTime - sTime;
      if (dur > maxDuration && pos > startPos) break;
      const diff = Math.abs(eTime - goalEnd);
      if (diff < bestDiff) {
        bestDiff = diff;
        bestPos = pos;
      }
    }
    return bestPos;
  }

  // 1. From Sections
  sections.forEach((sec, sIdx) => {
    if (!sec || typeof sec !== "object") return;
    const sName = String(sec.name || "").toLowerCase();
    const sLabel = String(sec.label || "");
    const secStart = Number(sec.start != null ? sec.start : 0);
    const secEnd = Number(sec.end != null ? sec.end : secStart);

    let startLinePos = null;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].start >= secStart - 0.25) {
        startLinePos = i;
        break;
      }
    }
    if (startLinePos == null) return;
    const endLinePos = windowEndForStart(startLinePos, secEnd);
    const startTime = lines[startLinePos].start;
    const endTime = lines[endLinePos].end;
    const dur = endTime - startTime;
    if (dur < minDuration) return;

    let kind = "section";
    let score = 50.0;
    let title = sLabel || sec.name || `Section ${sIdx + 1}`;

    if (sName.includes("chorus") || sLabel.includes("副歌") || sLabel.includes("高潮")) {
      kind = "chorus";
      score += 40.0;
      title = sLabel || (sName.includes("2") ? "🔥 Chorus 2" : "🔥 Main Chorus");
    } else if (sName.includes("verse") || sLabel.includes("主歌")) {
      kind = "verse";
      score += 15.0;
    } else if (sName.includes("bridge") || sLabel.includes("过渡")) {
      kind = "bridge";
      score += 25.0;
    }

    const previewTexts = [];
    for (let p = startLinePos; p <= endLinePos; p++) previewTexts.push(lines[p].text);
    let preview = previewTexts.slice(0, 3).join(" / ");
    if (previewTexts.length > 3) preview += " …";

    candidates.push({
      id: `cand_sec_${sIdx}`,
      kind,
      title,
      start_time: Math.round(startTime * 1000) / 1000,
      end_time: Math.round(endTime * 1000) / 1000,
      duration: Math.round(dur * 1000) / 1000,
      start_line_index: lines[startLinePos].index,
      end_line_index: lines[endLinePos].index,
      line_count: endLinePos - startLinePos + 1,
      preview_text: preview,
      score,
    });
  });

  // 2. Fallback heuristic windows if candidates < 2
  if (candidates.length < 2) {
    const totalLines = lines.length;
    const hookStartPos = Math.floor(totalLines * 0.35);
    const endPos = windowEndForStart(hookStartPos);
    const st = lines[hookStartPos].start;
    const et = lines[endPos].end;
    candidates.push({
      id: "cand_hook_heuristic",
      kind: "hook",
      title: "🔥 Vocal Hook Highlight",
      start_time: Math.round(st * 1000) / 1000,
      end_time: Math.round(et * 1000) / 1000,
      duration: Math.round((et - st) * 1000) / 1000,
      start_line_index: lines[hookStartPos].index,
      end_line_index: lines[endPos].index,
      line_count: endPos - hookStartPos + 1,
      preview_text: lines.slice(hookStartPos, endPos + 1).map(l => l.text).slice(0, 3).join(" / "),
      score: 75.0,
    });
  }

  candidates.sort((a, b) => b.score - a.score);
  const deduped = [];
  for (const c of candidates) {
    const isDup = deduped.some(d => Math.abs(d.start_time - c.start_time) < 3.0 && Math.abs(d.end_time - c.end_time) < 3.0);
    if (!isDup) deduped.push(c);
    if (deduped.length >= maxCandidates) break;
  }
  return deduped;
}

let currentTimingReview = null;
let flaggedLinesOnlyFilter = false;
let timingWarningsVisible = (() => {
  try {
    return localStorage.getItem("m2v_show_timing_warnings") !== "0";
  } catch (_) {
    return true;
  }
})();

if (typeof document !== "undefined") {
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

    // Phase 2B review elements
    dom.lyricsPanel         = $("#lyrics-panel");
    dom.timingReviewBar     = $("#timing-review-bar");
    dom.timingReviewBadge   = $("#timing-review-badge");
    dom.timingReviewCounts  = $("#timing-review-counts");
    dom.btnPrevAnomaly      = $("#btn-prev-anomaly");
    dom.btnNextAnomaly      = $("#btn-next-anomaly");
    dom.btnFilterAnomalies  = $("#btn-filter-anomalies");
    dom.btnToggleWarnings   = $("#btn-toggle-warnings");
    dom.lineTimingWarnings  = $("#line-timing-warnings");

    try {
      initWaveSurfer();
    } catch (err) {
      console.warn("WaveSurfer 初始化异常:", err);
    }

    bindLyricEvents();
    loadFileList();
  });
}

// ---------------------------------------------------------------------------
// Lifecycle Hooks
// ---------------------------------------------------------------------------
if (typeof window !== "undefined") {
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
}

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
        alert(window.t ? t("msg_select_song_first") : "请先选择或加载一首歌曲");
        return;
      }
      status(window.t ? t("msg_generating_ass") : "正在重新生成 ASS 字幕...");
      try {
        const fetchFn = window.apiFetch || fetch;
        let res;
        if (state.currentFile?.is_saas || state.currentFile?.task_id) {
          res = await fetchFn(`/api/editor/tasks/${state.currentFile.task_id}/regen`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "ass" }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || "生成失败");
          status(`🎉 ASS 字幕已成功同步生成`);
          alert(window.currentLocale === "en" ? "ASS subtitles generated and saved to cloud task!" : "ASS 字幕已成功生成并保存至云端！");
        } else {
          res = await fetchFn("/api/regen", {
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
          status(window.t ? t("msg_ass_generated", null, { path: data.ass_path }) : `🎉 ASS 字幕已生成: ${data.ass_path}`);
          const pathLabel = window.currentLocale === "en" ? "ASS subtitles generated successfully!\nPath: " : "ASS 字幕生成成功！\n保存路径: ";
          alert(pathLabel + data.ass_path);
        }
      } catch (err) {
        status((window.t ? t("msg_ass_failed") : "生成 ASS 失败: ") + err.message, true);
        alert((window.t ? t("msg_ass_failed") : "生成 ASS 失败: ") + err.message);
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

  if (dom.btnPrevAnomaly) dom.btnPrevAnomaly.addEventListener("click", () => jumpAnomaly(-1));
  if (dom.btnNextAnomaly) dom.btnNextAnomaly.addEventListener("click", () => jumpAnomaly(1));
  if (dom.btnFilterAnomalies) {
    dom.btnFilterAnomalies.addEventListener("click", () => {
      flaggedLinesOnlyFilter = !flaggedLinesOnlyFilter;
      if (dom.btnFilterAnomalies?.classList) {
        dom.btnFilterAnomalies.classList.toggle("active", flaggedLinesOnlyFilter);
      }
      const allText = window.t ? t("btn_filter_anomalies_all") : "显示全部歌词";
      const filterText = window.t ? t("btn_filter_anomalies") : "仅看提示行";
      dom.btnFilterAnomalies.textContent = flaggedLinesOnlyFilter ? allText : filterText;
      renderLyrics();
    });
  }

  if (dom.btnToggleWarnings) {
    dom.btnToggleWarnings.addEventListener("click", () => {
      toggleTimingWarningsVisibility();
    });
  }
  if (dom.timingReviewBadge) {
    dom.timingReviewBadge.addEventListener("click", () => {
      if (!timingWarningsVisible) {
        toggleTimingWarningsVisibility(true);
      }
    });
  }

  initLyricExportModal();

  const btnOpenStudio = $("#btn-open-motion-studio");
  if (btnOpenStudio) {
    btnOpenStudio.addEventListener("click", async () => {
      if (state.dirty && typeof saveAlignment === "function") {
        try {
          await saveAlignment();
        } catch (e) {
          console.warn("[LyricEditor] Auto-save before jumping to Motion Studio failed:", e);
        }
      }
      const targetId = state.currentFile?.name || state.currentFile?.task_id || "";
      const url = targetId ? `/motion-studio?song=${encodeURIComponent(targetId)}` : "/motion-studio";
      window.open(url, "_blank");
    });
  }

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
  const btnPreview = $("#btn-preview-lyric-mp4");
  const batchResults = $("#lyric-batch-results");
  const btnModalGoStudio = $("#btn-modal-go-motion-studio");
  if (btnModalGoStudio) {
    btnModalGoStudio.addEventListener("click", () => {
      const targetId = state.currentFile?.name || state.currentFile?.task_id || "";
      const url = targetId ? `/motion-studio?song=${encodeURIComponent(targetId)}` : "/motion-studio";
      window.open(url, "_blank");
    });
  }

  if (!btnOpen || !modal) return;

  let currentDurationLimit = 0; // 0 = 全曲, 20 = 20s
  let creditQuote = null;
  let previewSequence = 0;
  const requestCache = new Map();
  const pendingRequest = async (taskId, payload) => {
    const optionKey = JSON.stringify(payload);
    const key = `m2v_export_request:${taskId}:${optionKey}`;
    const source = JSON.stringify(state.alignment || null);
    let revision;
    if (window.crypto?.subtle && typeof TextEncoder !== "undefined") {
      const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(source));
      revision = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,"0")).join("");
    } else {
      let hash = 2166136261;
      for (let i=0;i<source.length;i++) hash = Math.imul(hash ^ source.charCodeAt(i),16777619);
      revision = String(hash >>> 0);
    }
    const signature = JSON.stringify([state.currentFile.version || null, revision, payload]);
    let previous = requestCache.get(key);
    try { previous = JSON.parse(localStorage.getItem(key)) || previous; } catch (_) {}
    if (!previous || previous.signature !== signature) {
      const id = window.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {const r=Math.random()*16|0;return (c==='x'?r:(r&3|8)).toString(16);});
      previous = {signature, id};
    }
    requestCache.set(key, previous);
    try { localStorage.setItem(key, JSON.stringify(previous)); } catch (_) {}
    return previous.id;
  };
  const clearRequest = (taskId, requestId) => {
    for (const [key, item] of requestCache) {
      if (key.startsWith(`m2v_export_request:${taskId}:`) && item.id === requestId) {
        requestCache.delete(key); try { localStorage.removeItem(key); } catch (_) {}
      }
    }
  };
  const loadCreditQuote = async () => {
    if (!(state.currentFile?.is_saas || state.currentFile?.task_id)) return null;
    const taskId = state.currentFile.task_id;
    const response = await (window.apiFetch || fetch)("/api/credits?page_size=1");
    const data = await response.json();
    if (!response.ok || !Number.isInteger(data.pricing?.lyric_export)) throw Error(data.detail || "Unable to check export credit price. Please retry.");
    if (state.currentFile?.task_id !== taskId) throw Error("Song changed. Please reopen the export dialog.");
    creditQuote = {taskId, cost:data.pricing.lyric_export};
    const label = $("#lyric-credit-price");
    if (label) label.textContent = window.currentLocale === "zh" ? `导出：${creditQuote.cost ? creditQuote.cost+" 积分" : "当前免费"}。失败自动退回预留积分。` : `Export: ${creditQuote.cost ? creditQuote.cost+" credits" : "currently free"}. Failed exports return reserved credits.`;
    updateBatchPrice();
    return creditQuote;
  };

  const closeModal = () => {
    previewSequence++;
    modal.style.display = "none";
    if (resultVideo) { resultVideo.pause(); resultVideo.removeAttribute?.("src"); resultVideo.load(); }
  };

  let activeCuratedTheme = CURATED_EXPORT_THEMES[0];
  let auditionInterval = null;

  function populateCuratedThemes() {
    const container = $("#curated-theme-cards");
    if (!container || typeof container.appendChild !== "function") return;
    container.innerHTML = "";
    CURATED_EXPORT_THEMES.forEach((ct) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "curated-theme-card" + (activeCuratedTheme?.id === ct.id ? " active" : "");
      card.dataset.themeId = ct.id;
      card.innerHTML = `
        <div class="curated-theme-title">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${ct.accent};"></span>
          ${escHtml(ct.name)}
        </div>
        <div class="curated-theme-subtitle">${escHtml(ct.subtitle)}</div>
        <div class="curated-theme-swatch" style="background:${ct.accent};"></div>
      `;
      card.addEventListener("click", () => {
        activeCuratedTheme = ct;
        $$(".curated-theme-card").forEach((c) => {
          if (c.classList) c.classList.toggle("active", c.dataset.themeId === ct.id);
        });
        const tplSelect = $("#export-template-select");
        if (tplSelect) tplSelect.value = exportTemplateForRatio(document.querySelector('input[name="export-ratio"]:checked')?.value || "9:16");
        const themeSelect = $("#export-theme-select");
        if (themeSelect) themeSelect.value = ct.theme;
        const bgRadio = document.querySelector(`input[name="export-bg"][value="${ct.background_mode}"]`);
        if (bgRadio) {
          bgRadio.checked = true;
          $$(".bg-option").forEach((opt) => {
            const r = opt.querySelector('input[type="radio"]');
            if (r && opt.classList) {
              opt.classList.toggle("active", r.value === ct.background_mode);
              opt.style.borderColor = r.value === ct.background_mode ? "#10b981" : "#2d3342";
            }
          });
        }
        updateLivePreview();
      });
      container.appendChild(card);
    });
  }

  function updateLivePreview() {
    const stage = $("#theme-safe-area-preview");
    if (!stage) return;
    const ratio = document.querySelector('input[name="export-ratio"]:checked')?.value || "9:16";
    if (stage.classList) {
      stage.classList.toggle("landscape", ratio === "16:9");
      stage.classList.toggle("portrait", ratio !== "16:9");
    }
    const template = $("#export-template-select");
    if (template) template.value = exportTemplateForRatio(ratio);
    const ct = activeCuratedTheme || CURATED_EXPORT_THEMES[0];
    if (ct && stage.style) {
      stage.style.background = ct.bg_preview || "#0d1117";
    }
    if ($("#preview-lyric-prev")) $("#preview-lyric-prev").hidden = ratio === "16:9";
    const coverChip = $("#preview-cover-chip");
    if (coverChip) coverChip.hidden = true;
    if (coverChip && state.currentFile?.cover_path) {
      coverChip.style.backgroundImage = `url('${state.currentFile.cover_path}')`;
    }
    const activeHook = $("#preview-lyric-active");
    if (activeHook) {
      if (ct?.accent) activeHook.style.color = ct.accent;
      const lines = state.alignment?.lines || [];
      if (lines.length > 0) {
        const previewLine = lines[Math.min(lines.length - 1, Math.floor(lines.length * 0.35))];
        activeHook.textContent = previewLine?.text || "Active singing hook";
      }
    }
  }

  function updateBatchPrice() {
    if (!creditQuote) return;
    const count = $("#export-custom-range")?.checked ? 1 : Array.from($$(".export-clip-check")).filter(c => c.checked && !c.disabled).length;
    if ($("#lyric-credit-price")) $("#lyric-credit-price").textContent = `${count} video${count === 1 ? "" : "s"} · ${creditQuote.cost} credits each · ${count * creditQuote.cost} credits total. Failed exports return unexpired reserved credits.`;
  }
  $("#export-custom-range")?.addEventListener("change", updateBatchPrice);
  function populateExcerptCandidates() {
    const container = $("#excerpt-candidates-list");
    if (!container || typeof container.appendChild !== "function") return;
    container.innerHTML = "";
    const clips = buildExportClips(state.alignment);
    for (const title of ["Clip", "Portrait · Apple", "Landscape · Karaoke"]) {
      const heading = document.createElement("strong"); heading.textContent = title; container.appendChild(heading);
    }
    clips.forEach(clip => {
      const title = document.createElement("span");
      title.textContent = `${clip.title} · ${clip.available ? (clip.end_time == null ? "Complete track" : (clip.end_time-clip.start_time).toFixed(1)+"s") : "Not found"}`;
      container.appendChild(title);
      for (const ratio of ["9:16", "16:9"]) {
        const card = document.createElement("label"); card.className = "excerpt-card";
        const check = document.createElement("input");
        check.type = "checkbox"; check.className = "export-clip-check";
        check.dataset.clipId = clip.id; check.dataset.ratio = ratio;
        check.checked = clip.id === "full" && ratio === "9:16";
        check.disabled = !clip.available;
        check.setAttribute("aria-label", `${clip.title} ${ratio}`);
        check.addEventListener("change", () => {
          updateBatchPrice();
          const radio = document.querySelector(`input[name="export-ratio"][value="${ratio}"]`);
          if (radio) {radio.checked = true;updateLivePreview();}
        });
        card.appendChild(check); container.appendChild(card);
      }
    });
  }

  function populateSentenceSelectors() {
    const startSel = $("#export-start-line-select");
    const endSel = $("#export-end-line-select");
    if (!startSel || typeof startSel.appendChild !== "function") return;
    startSel.innerHTML = "";
    if (endSel) endSel.innerHTML = "";
    const lines = state.alignment?.lines || [];
    lines.forEach((l, idx) => {
      const textSnippet = String(l.text || "").replace(/\\N/g, " ").trim().slice(0, 18);
      const label = `L${idx + 1} (${fmtTimeShort(l.start)}): ${textSnippet}`;
      const opt1 = document.createElement("option");
      opt1.value = String(idx);
      opt1.textContent = label;
      startSel.appendChild(opt1);
      if (endSel) {
        const opt2 = document.createElement("option");
        opt2.value = String(idx);
        opt2.textContent = label;
        endSel.appendChild(opt2);
      }
    });
  }

  function syncSentenceSelectorsFromTimes(st, et) {
    const lines = state.alignment?.lines || [];
    if (!lines.length) return;
    const startSel = $("#export-start-line-select");
    const endSel = $("#export-end-line-select");
    if (startSel) {
      let bestIdx = 0;
      let minDiff = Infinity;
      lines.forEach((l, i) => {
        const diff = Math.abs(l.start - st);
        if (diff < minDiff) { minDiff = diff; bestIdx = i; }
      });
      startSel.value = String(bestIdx);
    }
    if (endSel && et != null) {
      let bestIdx = lines.length - 1;
      let minDiff = Infinity;
      lines.forEach((l, i) => {
        const diff = Math.abs(l.end - et);
        if (diff < minDiff) { minDiff = diff; bestIdx = i; }
      });
      endSel.value = String(bestIdx);
    }
  }

  const openModal = async () => {
    previewSequence++;
    if (btnPreview) btnPreview.hidden = false;
    if (btnDownload) btnDownload.hidden = false;
    if (!state.currentFile) {
      alert(window.t ? t("msg_select_song_first") : "请先选择或加载一首歌曲");
      return;
    }
    modal.style.display = "flex";
    creditQuote = null;
    populateCuratedThemes();
    populateExcerptCandidates();
    populateSentenceSelectors();
    updateLivePreview();
    if (state.currentFile.is_saas || state.currentFile.task_id) {
      btnStart.disabled = true;
      try { await loadCreditQuote(); btnStart.disabled = false; }
      catch (error) { if ($("#lyric-credit-price")) $("#lyric-credit-price").textContent = error.message; }
    } else {
      if ($("#lyric-credit-price")) $("#lyric-credit-price").textContent = "Local export · no cloud credits";
    }
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
      updateLivePreview();
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
      updateLivePreview();
    });
  });

  $("#export-template-select")?.addEventListener("change", updateLivePreview);
  $("#export-theme-select")?.addEventListener("change", () => {
    activeCuratedTheme = CURATED_EXPORT_THEMES.find(c => c.id === $("#export-theme-select").value) || CURATED_EXPORT_THEMES[0];
    populateCuratedThemes(); updateLivePreview();
  });

  $("#export-start-line-select")?.addEventListener("change", (e) => {
    const idx = Number(e.target.value);
    const l = state.alignment?.lines?.[idx];
    if (l) {
      const startInp = $("#export-start-time");
      if (startInp) startInp.value = formatTimeSec(l.start);
      updateTimeRangeBadge();
    }
  });

  $("#export-end-line-select")?.addEventListener("change", (e) => {
    const idx = Number(e.target.value);
    const l = state.alignment?.lines?.[idx];
    if (l) {
      const endInp = $("#export-end-time");
      if (endInp) endInp.value = formatTimeSec(l.end);
      updateTimeRangeBadge();
    }
  });

  $("#btn-start-line-prev")?.addEventListener("click", () => {
    const sel = $("#export-start-line-select");
    if (!sel) return;
    const cur = Math.max(0, Number(sel.value || 0) - 1);
    sel.value = String(cur);
    const l = state.alignment?.lines?.[cur];
    if (l) {
      const startInp = $("#export-start-time");
      if (startInp) startInp.value = formatTimeSec(l.start);
      updateTimeRangeBadge();
    }
  });

  $("#btn-start-line-next")?.addEventListener("click", () => {
    const sel = $("#export-start-line-select");
    const maxIdx = (state.alignment?.lines?.length || 1) - 1;
    if (!sel) return;
    const cur = Math.min(maxIdx, Number(sel.value || 0) + 1);
    sel.value = String(cur);
    const l = state.alignment?.lines?.[cur];
    if (l) {
      const startInp = $("#export-start-time");
      if (startInp) startInp.value = formatTimeSec(l.start);
      updateTimeRangeBadge();
    }
  });

  $("#btn-end-line-prev")?.addEventListener("click", () => {
    const sel = $("#export-end-line-select");
    if (!sel) return;
    const cur = Math.max(0, Number(sel.value || 0) - 1);
    sel.value = String(cur);
    const l = state.alignment?.lines?.[cur];
    if (l) {
      const endInp = $("#export-end-time");
      if (endInp) endInp.value = formatTimeSec(l.end);
      updateTimeRangeBadge();
    }
  });

  $("#btn-end-line-next")?.addEventListener("click", () => {
    const sel = $("#export-end-line-select");
    const maxIdx = (state.alignment?.lines?.length || 1) - 1;
    if (!sel) return;
    const cur = Math.min(maxIdx, Number(sel.value || 0) + 1);
    sel.value = String(cur);
    const l = state.alignment?.lines?.[cur];
    if (l) {
      const endInp = $("#export-end-time");
      if (endInp) endInp.value = formatTimeSec(l.end);
      updateTimeRangeBadge();
    }
  });

  $("#export-snap-sentence")?.addEventListener("change", () => {
    const chk = $("#export-snap-sentence");
    if (chk?.checked) {
      const st = parseTimeString($("#export-start-time")?.value) || 0.0;
      const et = parseTimeString($("#export-end-time")?.value);
      const snapped = snapExcerptToSentenceBounds(state.alignment, st, et);
      const startInp = $("#export-start-time");
      const endInp = $("#export-end-time");
      if (startInp) startInp.value = formatTimeSec(snapped.start_time);
      if (endInp) endInp.value = formatTimeSec(snapped.end_time);
      syncSentenceSelectorsFromTimes(snapped.start_time, snapped.end_time);
      updateTimeRangeBadge();
    }
  });

  $("#btn-audition-excerpt")?.addEventListener("click", () => {
    const st = parseTimeString($("#export-start-time")?.value) || 0.0;
    const et = parseTimeString($("#export-end-time")?.value);
    const stopAt = (et && et > st) ? et : (st + 25.0);
    if (ws) {
      ws.setTime(st);
      ws.play();
      if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(true);
      if (wsInst && instReady) { wsInst.setTime(st); wsInst.play(); }
      if (auditionInterval) clearInterval(auditionInterval);
      auditionInterval = setInterval(() => {
        if (!ws.isPlaying() || ws.getCurrentTime() >= stopAt) {
          ws.pause();
          if (wsInst && instReady) wsInst.pause();
          if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(false);
          clearInterval(auditionInterval);
          auditionInterval = null;
        }
      }, 50);
    }
  });

  $("#toggle-safe-area-guides")?.addEventListener("change", (e) => {
    const stage = $("#theme-safe-area-preview");
    if (stage?.classList) stage.classList.toggle("guides-hidden", !e.target.checked);
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
      badge.textContent = window.t
        ? t("segment_clip", null, { dur, st: formatTimeSec(st), et: formatTimeSec(et) })
        : `片段截取: ${dur}秒 (${formatTimeSec(st)} - ${formatTimeSec(et)})`;
      badge.style.background = "rgba(59, 130, 246, 0.2)";
      badge.style.color = "#60a5fa";
    } else if (st > 0) {
      badge.textContent = window.t
        ? t("segment_from_start", null, { st: formatTimeSec(st) })
        : `从 ${formatTimeSec(st)} 起直至全曲结束`;
      badge.style.background = "rgba(59, 130, 246, 0.2)";
      badge.style.color = "#60a5fa";
    } else {
      badge.textContent = window.t ? t("preset_full_badge") : "全曲完整导出";
      badge.style.background = "rgba(16, 185, 129, 0.15)";
      badge.style.color = "#10b981";
    }
  }

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
    updateTimeRangeBadge();
  });

  if (btnReRender) {
    btnReRender.addEventListener("click", () => {
      previewSequence++;
      resultBox.style.display = "none";
      if (resultVideo) {resultVideo.pause();resultVideo.removeAttribute?.("src");resultVideo.load();}
    });
  }

  // 开始合成
  if (btnStart) {
    btnStart.addEventListener("click", async () => {
      if (!state.currentFile) return;
      previewSequence++;
      if (batchResults) batchResults.innerHTML = "";
      const sourceFile = state.currentFile;

      const ratio = document.querySelector('input[name="export-ratio"]:checked')?.value || "9:16";
      const bg = document.querySelector('input[name="export-bg"]:checked')?.value || "full_bleed";
      const template = exportTemplateForRatio(ratio);
      const theme = $("#export-theme-select")?.value || "impact";

      const st = parseTimeString($("#export-start-time")?.value) || 0.0;
      const et = parseTimeString($("#export-end-time")?.value);
      const durLimit = (et && et > st) ? (et - st) : null;

      btnStart.disabled = true;
      btnStart.textContent = window.t ? t("btn_modal_rendering") : "⏳ 合成中，请稍候...";
      btnStart.style.opacity = "0.6";

      progressBox.style.display = "block";
      resultBox.style.display = "none";
      progressBar.style.width = "5%";
      progressText.textContent = window.currentLocale === "en" ? "Submitting video task..." : "正在提交短视频任务...";
      progressPct.textContent = "5%";

      try {
        const fetchFn = window.apiFetch || fetch;
        const cloud = Boolean(state.currentFile.is_saas || state.currentFile.task_id);
        if (cloud && state.dirty && !(await saveAlignment())) {
          throw new Error("歌词修改保存失败，未提交导出任务");
        }
        if (cloud && creditQuote?.taskId !== state.currentFile.task_id) await loadCreditQuote();
        const resPreset = $("#export-resolution-select")?.value || "1080p";
        const snapSentence = Boolean($("#export-snap-sentence")?.checked);
        if (state.currentFile !== sourceFile) throw Error("Song changed. Reopen the export dialog.");
        const songTaskId = sourceFile.task_id;
        const payload = {
          ...(cloud ? {accepted_cost:creditQuote.cost} : {json_path: state.currentFile.json_path}),
          aspect_ratio: ratio, template, theme, background_mode: bg,
          duration_limit: durLimit, start_time: st, end_time: et,
        };
        if (resPreset && resPreset !== "1080p") {
          payload.resolution = resPreset;
        }
        if (snapSentence) {
          payload.snap_to_sentence = true;
        }
        const customRange = Boolean($("#export-custom-range")?.checked);
        const selected = customRange ? [] : Array.from($$(".export-clip-check")).filter(c => c.checked && !c.disabled);
        if (!customRange && $$(".export-clip-check").length && !selected.length) throw Error("Select at least one clip.");
        const clips = buildExportClips(state.alignment);
        const selectedClips = selected.map(c => ({...clips.find(x => x.id === c.dataset.clipId),aspect_ratio:c.dataset.ratio || ratio}));
        if (selectedClips.length > 1) {
          progressBox.style.display = "none";
          resultBox.style.display = "flex";
          if ($("#lyric-result-heading")) $("#lyric-result-heading").textContent = "Exports in progress";
          if ($("#lyric-my-exports")) $("#lyric-my-exports").hidden = !cloud;
          if (resultVideo) { resultVideo.pause(); resultVideo.hidden = true; }
          if (btnPreview) btnPreview.hidden = true;
          if (btnDownload) btnDownload.hidden = true;
          btnStart.disabled = false;
          btnStart.textContent = "Export videos";
          btnStart.style.opacity = "1";

          let submitted = 0;
          const targetBox = batchResults || resultBox;
          const updateSummary = () => {
            const completedCount = queue.filter(q => q.done).length;
            const renderingCount = queue.filter(q => q.running).length;
            const waitingCount = queue.filter(q => !q.started && !q.done).length;
            resultMeta.textContent = `${submitted}/${selectedClips.length} submitted · ${completedCount} completed` +
              (renderingCount ? ` · ${renderingCount} rendering` : "") +
              (waitingCount ? ` · ${waitingCount} queued` : "") +
              `. ${cloud ? "Follow progress and download in My Exports." : "Keep this dialog open for download links."}`;
          };

          const queue = selectedClips.map((clip) => {
            const row = document.createElement("p");
            row.textContent = `${clip.title} (${clip.aspect_ratio}): In queue…`;
            targetBox.appendChild(row);
            return {
              clip,
              row,
              started: false,
              running: false,
              done: false
            };
          });
          updateSummary();

          let queueRunning = false;
          async function processQueue() {
            if (queueRunning) return;
            queueRunning = true;
            try {
              for (const item of queue) {
                if (item.started || item.done) continue;
                const clip = item.clip;
                const payloadItem = {
                  ...payload,
                  aspect_ratio: clip.aspect_ratio,
                  template: exportTemplateForRatio(clip.aspect_ratio),
                  start_time: clip.start_time,
                  end_time: clip.end_time,
                  duration_limit: clip.end_time == null ? null : clip.end_time - clip.start_time
                };
                if (cloud) payloadItem.request_id = await pendingRequest(songTaskId, payloadItem);

                try {
                  const response = await fetchFn(
                    cloud ? `/api/editor/tasks/${songTaskId}/lyric-video` : "/api/lyric_video/export",
                    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payloadItem) }
                  );
                  const data = await response.json();

                  if (response.status === 429 || response.status === 503 || (data.detail && /slots are full|capacity is full/i.test(data.detail))) {
                    item.row.textContent = `${clip.title} (${clip.aspect_ratio}): Waiting for available render slot…`;
                    updateSummary();
                    break;
                  }

                  if (!response.ok) {
                    item.started = true;
                    item.done = true;
                    item.row.textContent = `${clip.title} (${clip.aspect_ratio}): ${data.detail || "Submission failed"}`;
                    updateSummary();
                    continue;
                  }

                  item.started = true;
                  item.running = true;
                  submitted++;
                  item.row.textContent = `${clip.title} (${clip.aspect_ratio}): Rendering… 0%`;
                  updateSummary();

                  let busy = false, failures = 0;
                  const timer = setInterval(async () => {
                    if (busy) return;
                    busy = true;
                    try {
                      const res = await fetchFn(cloud ? `/api/editor/jobs/${data.task_id}` : `/api/lyric_video/task_status?task_id=${data.task_id}`);
                      if (!res.ok) throw Error(`HTTP ${res.status}`);
                      const job = await res.json();
                      failures = 0;
                      const prog = Math.round(job.progress || 0);
                      if (job.status === "completed") {
                        clearInterval(timer);
                        if (cloud) clearRequest(songTaskId, payloadItem.request_id);
                        item.running = false;
                        item.done = true;
                        item.row.textContent = `${clip.title} ${clip.aspect_ratio}: `;
                        const link = document.createElement("a");
                        link.textContent = cloud ? "View in My Exports" : "Download MP4";
                        link.href = cloud ? "/#exports-section" : job.result.video_url;
                        if (cloud) { link.target = "_blank"; } else link.download = `${clip.id}.mp4`;
                        item.row.appendChild(link);
                        updateSummary();
                        void processQueue();
                      } else if (["failed", "interrupted"].includes(job.status)) {
                        clearInterval(timer);
                        if (cloud) clearRequest(songTaskId, payloadItem.request_id);
                        item.running = false;
                        item.done = true;
                        item.row.textContent = `${clip.title} (${clip.aspect_ratio}): ${job.error || "Export failed"}`;
                        updateSummary();
                        void processQueue();
                      } else {
                        item.row.textContent = `${clip.title} (${clip.aspect_ratio}): Rendering… ${prog}%`;
                      }
                    } catch (error) {
                      if (++failures >= 3) {
                        clearInterval(timer);
                        item.running = false;
                        item.done = true;
                        item.row.textContent = `${clip.title} (${clip.aspect_ratio}): ${error.message}`;
                        updateSummary();
                        void processQueue();
                      }
                    } finally {
                      busy = false;
                    }
                  }, 1000);
                } catch (submitErr) {
                  item.started = true;
                  item.done = true;
                  item.row.textContent = `${clip.title} (${clip.aspect_ratio}): ${submitErr.message}`;
                  updateSummary();
                }
              }
            } finally {
              queueRunning = false;
            }
          }

          const queueTicker = setInterval(() => {
            const hasWaiting = queue.some(q => !q.started && !q.done);
            if (!hasWaiting) {
              clearInterval(queueTicker);
              return;
            }
            void processQueue();
          }, 3000);

          await processQueue();
          return;
        }
        if (selectedClips.length === 1) {
          const clip = selectedClips[0];
          payload.aspect_ratio = clip.aspect_ratio; payload.template = exportTemplateForRatio(clip.aspect_ratio);
          payload.start_time = clip.start_time; payload.end_time = clip.end_time;
          payload.duration_limit = clip.end_time == null ? null : clip.end_time-clip.start_time;
        }
        const requestId = cloud ? await pendingRequest(songTaskId, payload) : null;
        if (cloud) payload.request_id = requestId;
        const res = await fetchFn(cloud ? `/api/editor/tasks/${state.currentFile.task_id}/lyric-video` : "/api/lyric_video/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "任务提交失败");

        const taskId = data.task_id;

        // 轮询任务进度
        let polling = false;
        let pollErrors = 0;
        const pollInterval = setInterval(async () => {
          if (polling) return;
          polling = true;
          try {
            const sRes = await fetchFn(cloud ? `/api/editor/jobs/${taskId}` : `/api/lyric_video/task_status?task_id=${taskId}`);
            if (!sRes.ok) throw new Error(`任务状态读取失败 (HTTP ${sRes.status})`);
            const task = await sRes.json();
            pollErrors = 0;

            const prog = Math.round(task.progress || 0);
            progressBar.style.width = `${prog}%`;
            progressPct.textContent = `${prog}%`;
            progressText.textContent = task.message || (window.currentLocale === "en" ? "Rendering video..." : "视频渲染中...");

            if (task.status === "completed") {
              if (cloud) clearRequest(songTaskId, requestId);
              clearInterval(pollInterval);
              btnStart.disabled = false;
              btnStart.textContent = window.t ? t("btn_modal_start") : "🚀 立即开始合成短视频";
              btnStart.style.opacity = "1";
              progressBox.style.display = "none";

              // 展示结果
              const result = task.result || {};
              // Rendering completion does not wait for video transfer.
              pollErrors = 3;
              if ($("#lyric-result-heading")) $("#lyric-result-heading").textContent = "Video ready";
              if (btnPreview) btnPreview.hidden = false;
              if (btnDownload) btnDownload.hidden = false;
              resultBox.style.display = "flex";
              const libraryLink = $("#lyric-my-exports");
              if (libraryLink) libraryLink.hidden = !cloud;
              const elapsedLabel = window.currentLocale === "en" ? "Elapsed" : "耗时";
              resultMeta.textContent = `${result.resolution ? result.resolution.join('x') : ''} · ${result.size_mb || 0}MB · ${elapsedLabel} ${result.elapsed_seconds || 0}s`;
              if (resultVideo) {
                resultVideo.pause(); resultVideo.removeAttribute?.("src");
                resultVideo.preload = "none"; resultVideo.hidden = true;
              }
              const accessVideo = async (preview) => {
                if (!cloud) return {url: result.video_url, filename: "lyric_video.mp4"};
                const response = await fetchFn(`/api/exports/${result.export_id || taskId}/access?preview=${preview}`);
                const data = await response.json();
                if (!response.ok) throw Error(data.detail || "Unable to access video. Please retry from My Exports.");
                if (data.url.startsWith("/") && window.getApiUrl) data.url = window.getApiUrl(data.url);
                return data;
              };
              if (btnPreview) btnPreview.onclick = async () => {
                const sequence = ++previewSequence;
                btnPreview.disabled = true;
                try {
                  const data = await accessVideo(true);
                  if (sequence !== previewSequence || modal.style.display === "none" || state.currentFile?.task_id !== songTaskId) return;
                  resultVideo.src = data.url; resultVideo.hidden = false;
                  await resultVideo.play().catch(() => {});
                } catch (error) { if (sequence === previewSequence && modal.style.display !== "none") alert(error.message); }
                finally {btnPreview.disabled = false;}
              };
              if (btnDownload) {
                btnDownload.href = cloud ? "#" : result.video_url;
                btnDownload.download = "lyric_video.mp4";
                btnDownload.onclick = cloud ? async (event) => {
                  event.preventDefault();
                  try {
                    const data = await accessVideo(false), link = document.createElement("a");
                    link.href = data.url; link.download = data.filename;
                    document.body.appendChild(link); link.click(); link.remove();
                  } catch(error) {alert(error.message);}
                } : null;
              }
              status(window.t ? t("msg_video_success") : "🎉 动效短视频已生成完成！");
            } else if (["failed", "interrupted"].includes(task.status)) {
              if (cloud) clearRequest(songTaskId, requestId);
              clearInterval(pollInterval);
              btnStart.disabled = false;
              btnStart.textContent = window.t ? t("btn_modal_start") : "🚀 立即开始合成短视频";
              btnStart.style.opacity = "1";
              progressBox.style.display = "none";
              alert((window.currentLocale === "en" ? "Synthesis failed: " : "短视频合成失败: ") + (task.error || task.message));
              status(window.t ? t("msg_video_failed") : "短视频合成失败", true);
            }
          } catch (e) {
            pollErrors++;
            if (pollErrors >= 3 || /HTTP (401|403|404)/.test(e.message)) {
              clearInterval(pollInterval);
              btnStart.disabled = false;
              btnStart.textContent = window.t ? t("btn_modal_start") : "🚀 立即开始合成短视频";
              btnStart.style.opacity = "1";
              progressBox.style.display = "none";
              status(e.message, true);
            }
          } finally { polling = false; }
        }, 800);

      } catch (err) {
        btnStart.disabled = false;
        btnStart.textContent = window.t ? t("btn_modal_start") : "🚀 立即开始合成短视频";
        btnStart.style.opacity = "1";
        progressBox.style.display = "none";
        alert((window.currentLocale === "en" ? "Video task failed: " : "短视频任务异常: ") + err.message);
        status((window.t ? t("msg_export_video_failed") : "导出短视频失败: ") + err.message, true);
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
function jumpAnomaly(delta) {
  if (!currentTimingReview || !currentTimingReview.flagged_line_indices?.length) return;
  const list = currentTimingReview.flagged_line_indices;
  const curIdx = state.selectedLine;
  let target = list[0];
  if (delta > 0) {
    const next = list.find(idx => idx > curIdx);
    target = next !== undefined ? next : list[0];
  } else {
    const prev = [...list].reverse().find(idx => idx < curIdx);
    target = prev !== undefined ? prev : list[list.length - 1];
  }
  selectLine(target, { seek: true, scroll: true });
}

function toggleTimingWarningsVisibility(forceState) {
  timingWarningsVisible = (typeof forceState === "boolean") ? forceState : !timingWarningsVisible;
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("m2v_show_timing_warnings", timingWarningsVisible ? "1" : "0");
    }
  } catch (_) {}
  if (!timingWarningsVisible && flaggedLinesOnlyFilter) {
    flaggedLinesOnlyFilter = false;
    if (typeof dom !== "undefined" && dom.btnFilterAnomalies) {
      dom.btnFilterAnomalies.classList.remove("active");
      dom.btnFilterAnomalies.textContent = (typeof window !== "undefined" && window.t) ? t("btn_filter_anomalies") : "仅看提示行";
    }
  }
  applyTimingWarningsVisibility();
  if (typeof updateTimingReviewBar === "function") updateTimingReviewBar();
  if (typeof renderLyrics === "function") renderLyrics();
}

function applyTimingWarningsVisibility() {
  if (typeof dom !== "undefined") {
    if (dom.lyricsPanel) {
      dom.lyricsPanel.classList.toggle("timing-warnings-hidden", !timingWarningsVisible);
    }
    if (dom.timingReviewBar) {
      dom.timingReviewBar.classList.toggle("collapsed-warnings", !timingWarningsVisible);
    }
  }
}

function updateTimingReviewBar() {
  if (typeof dom === "undefined" || !dom.timingReviewBar) return;
  const lines = state.alignment?.lines || [];
  if (!lines.length) {
    dom.timingReviewBar.style.display = "none";
    return;
  }
  const review = currentTimingReview || inspectAlignmentTiming(state.alignment);
  const badge = dom.timingReviewBadge;
  const counts = dom.timingReviewCounts;

  if (review.total_warnings === 0) {
    dom.timingReviewBar.style.display = "flex";
    dom.timingReviewBar.classList.remove("collapsed-warnings");
    if (badge) {
      badge.textContent = window.t ? t("timing_review_none") : "未检测到时间冲突与异常";
      badge.className = "timing-badge clean";
      badge.title = "";
    }
    if (counts) {
      counts.textContent = "";
      counts.className = "timing-counts";
    }
    if (dom.btnPrevAnomaly) dom.btnPrevAnomaly.disabled = true;
    if (dom.btnNextAnomaly) dom.btnNextAnomaly.disabled = true;
    if (dom.btnFilterAnomalies) dom.btnFilterAnomalies.disabled = true;
    if (dom.btnToggleWarnings) dom.btnToggleWarnings.style.display = "none";
  } else {
    dom.timingReviewBar.style.display = "flex";
    if (dom.btnToggleWarnings) dom.btnToggleWarnings.style.display = "inline-flex";

    if (!timingWarningsVisible) {
      dom.timingReviewBar.classList.add("collapsed-warnings");
      if (badge) {
        const badgeTpl = window.t ? t("timing_review_muted_badge", null, { count: review.total_warnings }) : `${review.total_warnings} warnings hidden`;
        badge.textContent = `⚠ ${badgeTpl}`;
        badge.className = "timing-badge muted";
        badge.title = window.t ? t("timing_review_click_to_unmute") : "点击恢复显示全曲时间提示";
      }
      if (counts) {
        counts.textContent = window.t ? t("timing_review_muted_hint") : "已关闭全曲标记 (部分歌词正常无需修复)";
        counts.className = "timing-counts muted";
      }
      if (dom.btnPrevAnomaly) dom.btnPrevAnomaly.disabled = true;
      if (dom.btnNextAnomaly) dom.btnNextAnomaly.disabled = true;
      if (dom.btnFilterAnomalies) dom.btnFilterAnomalies.disabled = true;
      if (dom.btnToggleWarnings) {
        dom.btnToggleWarnings.textContent = window.t ? t("btn_show_timing_warnings") : "👁️ 显示提示";
        dom.btnToggleWarnings.classList.add("muted-state");
      }
    } else {
      dom.timingReviewBar.classList.remove("collapsed-warnings");
      if (badge) {
        const badgeTpl = window.t ? t("timing_review_badge", null, { count: review.total_warnings }) : `${review.total_warnings} warnings`;
        badge.textContent = badgeTpl;
        badge.className = "timing-badge";
        badge.title = "";
      }
      if (counts) {
        const c = review.counts_by_kind || {};
        const fmt = window.t ? t("timing_counts_fmt", null, {
          overlap: c.overlap || 0,
          compressed: c.compressed_duration || 0,
          gap: c.excessive_gap || 0,
          confidence: c.low_confidence || 0,
        }) : `${c.overlap || 0} overlap · ${c.compressed_duration || 0} compressed · ${c.excessive_gap || 0} gap · ${c.low_confidence || 0} low confidence`;
        counts.textContent = fmt;
        counts.className = "timing-counts";
      }
      if (dom.btnPrevAnomaly) dom.btnPrevAnomaly.disabled = false;
      if (dom.btnNextAnomaly) dom.btnNextAnomaly.disabled = false;
      if (dom.btnFilterAnomalies) dom.btnFilterAnomalies.disabled = false;
      if (dom.btnToggleWarnings) {
        dom.btnToggleWarnings.textContent = window.t ? t("btn_hide_timing_warnings") : "👁️ 隐藏提示";
        dom.btnToggleWarnings.classList.remove("muted-state");
      }
    }
  }
}

function updateLineTimingWarnings(lineIdx) {
  if (typeof dom === "undefined" || !dom.lineTimingWarnings) return;
  if (!timingWarningsVisible || lineIdx < 0 || !currentTimingReview) {
    dom.lineTimingWarnings.style.display = "none";
    dom.lineTimingWarnings.innerHTML = "";
    return;
  }
  const lineWarns = currentTimingReview.warnings.filter(w => w.line_index === lineIdx);
  if (!lineWarns.length) {
    dom.lineTimingWarnings.style.display = "none";
    dom.lineTimingWarnings.innerHTML = "";
    return;
  }
  dom.lineTimingWarnings.style.display = "flex";
  dom.lineTimingWarnings.innerHTML = "";
  lineWarns.forEach((w) => {
    const pill = document.createElement("div");
    pill.className = "timing-warning-pill";
    pill.title = w.message;
    pill.innerHTML = `<strong>⚠️ ${escHtml(w.title)}:</strong> <span>${escHtml(w.message)}</span>`;
    pill.addEventListener("click", () => {
      if (w.word_index != null) {
        selectWord(w.word_index);
      }
    });
    dom.lineTimingWarnings.appendChild(pill);
  });
}

function renderLyrics() {
  if (typeof dom === "undefined" || !dom.lyricsList) return;
  const lines = state.alignment?.lines || [];
  const sections = state.alignment?.sections || [];
  dom.lyricsList.innerHTML = "";

  currentTimingReview = inspectAlignmentTiming(state.alignment);
  applyTimingWarningsVisibility();
  updateTimingReviewBar();

  const flaggedSet = new Set(currentTimingReview?.flagged_line_indices || []);

  // 1. 如果有前奏 (Intro) 且不包含歌词行，先在顶部渲染前奏卡片
  const introSec = sections.find(s => s.name && s.name.toLowerCase().includes("intro") && (!s.line_indices || s.line_indices.length === 0));
  if (introSec) {
    const introDiv = document.createElement("div");
    introDiv.className = "section-header section-intro";
    introDiv.title = window.t ? t("sec_intro_dblclick") : "双击从前奏开始播放";
    introDiv.innerHTML = `
      <div class="sec-left">
        <span class="sec-badge">🎵 ${escHtml(introSec.label || introSec.name)}</span>
        ${introSec.style ? `<span class="sec-style" title="${escHtml(introSec.style)}">${escHtml(introSec.style)}</span>` : ""}
      </div>
      <span class="sec-time">${fmtTimeShort(introSec.start)} → ${fmtTimeShort(introSec.end)}</span>
    `;
    introDiv.addEventListener("dblclick", () => {
      if (ws) {
        ws.setTime(introSec.start); ws.play(); if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(true);
        if (wsInst && instReady) { wsInst.setTime(introSec.start); wsInst.play(); }
      }
    });
    dom.lyricsList.appendChild(introDiv);
  }

  let lastSectionName = "";

  lines.forEach((line, i) => {
    if (flaggedLinesOnlyFilter && !flaggedSet.has(i) && state.selectedLine !== i) {
      return;
    }

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
      secDiv.title = window.t ? t("sec_dblclick") : "双击从本乐段开始播放";
      secDiv.innerHTML = `
        <div class="sec-left">
          <span class="sec-badge">🔖 ${escHtml(secLabel)}</span>
          ${secStyle ? `<span class="sec-style" title="${escHtml(secStyle)}">${escHtml(secStyle)}</span>` : ""}
        </div>
        <span class="sec-time">${fmtTimeShort(secStart)} → ${fmtTimeShort(secEnd)}</span>
      `;
      secDiv.addEventListener("dblclick", () => {
        if (ws) {
          ws.setTime(secStart); ws.play(); if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(true);
          if (wsInst && instReady) { wsInst.setTime(secStart); wsInst.play(); }
        }
      });
      dom.lyricsList.appendChild(secDiv);
    }

    const isFlagged = timingWarningsVisible && flaggedSet.has(i);
    let anomalyBadgeHtml = "";
    if (isFlagged && currentTimingReview?.warnings) {
      const lineWarns = currentTimingReview.warnings.filter(w => w.line_index === i);
      const primaryKind = lineWarns[0]?.kind || "overlap";
      const kindCls = primaryKind === "compressed_duration" ? "compressed" : (primaryKind === "excessive_gap" ? "gap" : (primaryKind === "low_confidence" ? "confidence" : "overlap"));
      const kindLabel = primaryKind === "compressed_duration" ? "Compressed" : (primaryKind === "excessive_gap" ? "Gap" : (primaryKind === "low_confidence" ? "Review" : "Overlap"));
      anomalyBadgeHtml = `<span class="line-anomaly-badge ${kindCls}" title="${escHtml(lineWarns[0]?.message || '')}">⚠ ${kindLabel}</span>`;
    }

    const row = document.createElement("div");
    row.className = "lyric-row" + (isFlagged ? " has-anomaly" : "");
    row.dataset.idx = i;
    const charSpans = renderLineCharSpans(line, i);
    const dur = (line.end - line.start).toFixed(1);
    const startTitle = window.t ? t("line_row_start_title") : "行起始时间";
    const endTitle = window.t ? t("line_row_end_title") : "行结束时间";
    const nudgeLTitle = window.t ? t("line_nudge_left_title") : "整行前移100ms";
    const nudgeRTitle = window.t ? t("line_nudge_right_title") : "整行后移100ms";
    row.innerHTML = `
      <span class="lyric-num">${i + 1}</span>
      <span class="lyric-text">${charSpans}${anomalyBadgeHtml}</span>
      <span class="lyric-time-edit">
        <input type="text" class="time-input line-start-input" value="${fmtTimeShort(line.start)}" data-field="start" data-idx="${i}" title="${startTitle}">
        <span class="time-arrow">→</span>
        <input type="text" class="time-input line-end-input" value="${fmtTimeShort(line.end)}" data-field="end" data-idx="${i}" title="${endTitle}">
        <span class="line-dur">${dur}s</span>
        <button class="line-nudge-btn" data-idx="${i}" data-delta="-0.1" title="${nudgeLTitle}">◁</button>
        <button class="line-nudge-btn" data-idx="${i}" data-delta="0.1" title="${nudgeRTitle}">▷</button>
      </span>`;
    row.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      selectLine(i);
    });
    row.addEventListener("dblclick", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      if (ws) {
        ws.setTime(line.start); ws.play(); if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(true);
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
  updateLineTimingWarnings(idx);
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

  $$(".lyric-syl").forEach((span) => {
    const sStart = Number(span.dataset.start), sEnd = Number(span.dataset.end);
    if (t >= sEnd) { span.classList.add("sung"); span.classList.remove("singing"); }
    else if (t >= sStart) { span.classList.add("singing"); span.classList.remove("sung"); }
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
  const lineLabel = window.t
    ? (window.currentLocale === "en" ? `Line ${lineIdx + 1}` : `第 ${lineIdx + 1} 行`)
    : `第 ${lineIdx + 1} 行`;
  dom.wordTitle.textContent = `${lineLabel} [${fmtTimeShort(line.start)} → ${fmtTimeShort(line.end)}, ${lineDurMs}ms]: ${line.text}`;
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
  const preLabel = preGapSec > 3.0
    ? `${window.t ? t("interlude") : "间奏"} ${preGapSec.toFixed(1)}s`
    : (preGapSec > 0.05 ? `${window.t ? t("gap") : "空隙"} ${preGapSec.toFixed(2)}s` : (window.t ? t("prev_line_connected") : "紧接上句"));
  const preGapTitle = window.t ? t("pre_gap_title") : "前置间奏/静音";
  const preGapHint = window.t ? t("pre_gap_hint") : "双击或拖拽尾部手柄调节首字起唱时间";
  prePill.title = `${preGapTitle} (${preGapSec.toFixed(2)}s) | ${preGapHint}`;
  const handleStartTitle = window.t ? t("handle_start_title") : "拖拽调节首字起唱 | 双击获取当前播放头时间";
  prePill.innerHTML = `
    <span class="gap-text">◀ ${preLabel}</span>
    <div class="edge-handle handle-line-start" title="${handleStartTitle}"></div>
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
    const reviewText = isNeedsReview ? (window.t ? t("word_needs_review") : " [声学边界较弱/连音，建议人工复核]") : "";
    bar.title = `${w.word}  ${fmtTime(w.start)} → ${fmtTime(w.end)}  (${(dur * 1000).toFixed(0)}ms)${reviewText}`;
    const isInternal = (i < words.length - 1);
    const handleTitle = isInternal
      ? (window.t ? t("handle_split_title") : "拖拽分割点 | 双击=对齐至当前播放头")
      : (window.t ? t("handle_end_title") : "拖拽尾字收唱 | 双击=对齐至当前播放头");
    bar.innerHTML = `
      <span>${escHtml(w.word.trim() || w.word)}</span>
      <span class="word-dur">${(dur * 1000).toFixed(0)}</span>
      <div class="drag-handle" title="${handleTitle}"></div>
    `;

    bar.addEventListener("click", (e) => {
      if (e.target.classList.contains("drag-handle")) return;
      selectWord(i);
    });
    bar.addEventListener("dblclick", (e) => {
      if (e.target.classList.contains("drag-handle")) return;
      if (ws) {
        ws.setTime(w.start); ws.play(); if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(true);
        if (wsInst && instReady) { wsInst.setTime(w.start); wsInst.play(); }
        const stopAt = w.end;
        const check = () => {
          if (ws.getCurrentTime() >= stopAt) {
            ws.pause(); if (wsInst && instReady) wsInst.pause();
            if (typeof updatePlayPauseBtn === "function") updatePlayPauseBtn(false);
          } else if (ws.isPlaying()) requestAnimationFrame(check);
        };
        requestAnimationFrame(check);
      }
    });

    setupDragHandle(bar, i, lineIdx, wordsTrack);

    wordsTrack.appendChild(bar);
  });
  container.appendChild(wordsTrack);

  // 3. 后置紧凑标签 (只显示时间)
  const postPill = document.createElement("div");
  postPill.className = "gap-pill gap-post";
  const postLabel = postGapSec > 3.0
    ? `${window.t ? t("interlude") : "间奏"} ${postGapSec.toFixed(1)}s`
    : (postGapSec > 0.05 ? `${window.t ? t("gap") : "空隙"} ${postGapSec.toFixed(2)}s` : (window.t ? t("next_line_connected") : "紧接下句"));
  const postGapTitle = window.t ? t("post_gap_title") : "后置间歇";
  const endSingLabel = window.t ? t("post_gap_end_sing") : "尾字收唱";
  const postGapHint = window.t ? t("post_gap_hint") : "双击或拖拽橙色手柄调节收唱点";
  postPill.title = `${postGapTitle} (${postGapSec.toFixed(2)}s) | ${endSingLabel}: ${fmtTimeShort(line.end)} | ${postGapHint}`;
  const handleEndTitle = window.t ? t("handle_end_edge_title") : "拖拽调节尾字收唱";
  const handleEndHint = window.t ? t("handle_end_edge_hint") : "双击对齐至播放头";
  postPill.innerHTML = `
    <div class="edge-handle handle-line-end" title="${handleEndTitle} (${fmtTimeShort(line.end)}) | ${handleEndHint}"></div>
    <span class="gap-text" title="${postGapTitle}: ${postGapSec.toFixed(2)}s">${postLabel} ▶</span>
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
  if (dom.wordTitle) dom.wordTitle.textContent = window.t ? t("word_panel_placeholder") : "点击左侧歌词行查看字级时间";
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
    status(window.t ? t("bound_early_prev", null, { time: fmtTimeShort(targetT), bound: fmtTimeShort(minStart) }) : `⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 早于上一句结束 (${fmtTimeShort(minStart)})，已自动约束在上一句后`, true);
    targetT = minStart;
  } else if (targetT > maxStart) {
    status(window.t ? t("bound_late_second", null, { time: fmtTimeShort(targetT), bound: fmtTimeShort(maxStart) }) : `⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 晚于第 2 个字起唱 (${fmtTimeShort(maxStart)})，已自动约束在第 2 字前`, true);
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
  status(window.t ? t("snap_start_msg", null, { time: fmtTimeShort(clamped), gap: preGap.toFixed(1) }) : `🎯 首字起唱点已吸附至播放头: ${fmtTimeShort(clamped)}（前置间奏: ${preGap.toFixed(1)}s）`);
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
      status(window.t ? t("bound_early_last", null, { time: fmtTimeShort(targetT), bound: fmtTimeShort(minEnd) }) : `⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 早于尾字起唱 (${fmtTimeShort(minEnd)})`, true);
      targetT = minEnd;
    } else if (targetT > maxEnd) {
      status(window.t ? t("bound_late_next", null, { time: fmtTimeShort(targetT), bound: fmtTimeShort(maxEnd) }) : `⚠️ 播放头位置 (${fmtTimeShort(targetT)}) 晚于下一句起唱 (${fmtTimeShort(maxEnd)})，已约束在下一句前`, true);
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
    status(window.t ? t("snap_end_msg", null, { time: fmtTimeShort(clamped), gap: postGap.toFixed(1) }) : `🎯 尾字收唱点已吸附至播放头: ${fmtTimeShort(clamped)}（后置间歇: ${postGap.toFixed(1)}s）`);
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
    status(window.t ? t("split_snapped_msg", null, { idx1: wordIdx + 1, idx2: wordIdx + 2, time: fmtTimeShort(clamped) }) : `✂ 分割点 ${wordIdx + 1}|${wordIdx + 2} → ${fmtTimeShort(clamped)}`);
  }
}

function setupLineEdgeDragHandle(prePill, postPill, lineIdx, wordsTrack) {
  const handleStart = prePill.querySelector(".handle-line-start");
  const handleEnd = postPill.querySelector(".handle-line-end");

  let lastStartClickTime = 0;
  let lastEndClickTime = 0;

  if (handleStart) {
    handleStart.addEventListener("dblclick", (e) => {
      e.preventDefault(); e.stopPropagation();
      snapFirstWordStartToPlayhead(lineIdx);
    });

    handleStart.addEventListener("mousedown", (e) => {
      e.preventDefault(); e.stopPropagation();

      const now = Date.now();
      if (now - lastStartClickTime < 350) {
        lastStartClickTime = 0;
        snapFirstWordStartToPlayhead(lineIdx);
        return;
      }
      lastStartClickTime = now;

      const line = state.alignment?.lines?.[lineIdx];
      if (!line || !line.words?.length) return;
      const startX = e.clientX;
      const startStart = line.words[0].start;
      const trackWidth = wordsTrack.getBoundingClientRect().width || 400;
      const activeSpan = Math.max(0.1, line.words[line.words.length - 1].end - line.words[0].start);
      const pxPerSec = trackWidth / activeSpan;
      const lines = state.alignment.lines;
      const prevLine = lineIdx > 0 ? lines[lineIdx - 1] : null;
      const minStart = prevLine ? (prevLine.end + 0.01) : 0.0;
      const maxStart = line.words.length > 1 ? (line.words[1].start - 0.05) : (line.end - 0.05);

      let moved = false;
      let hasPushedUndo = false;

      document.body.style.cursor = "col-resize";
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        if (!moved && Math.abs(dx) < 3) return;
        moved = true;
        if (!hasPushedUndo) {
          pushUndo();
          hasPushedUndo = true;
        }
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
        if (moved) {
          syncLineFromWords(lineIdx);
          renderLyrics();
          selectLine(lineIdx);
          selectWord(0);
        }
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

      const now = Date.now();
      if (now - lastEndClickTime < 350) {
        lastEndClickTime = 0;
        const line = state.alignment?.lines?.[lineIdx];
        if (line && line.words?.length) snapSplitToPlayhead(lineIdx, line.words.length - 1);
        return;
      }
      lastEndClickTime = now;

      const line = state.alignment?.lines?.[lineIdx];
      if (!line || !line.words?.length) return;
      const lastIdx = line.words.length - 1;
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

      let moved = false;
      let hasPushedUndo = false;

      document.body.style.cursor = "col-resize";
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        if (!moved && Math.abs(dx) < 3) return;
        moved = true;
        if (!hasPushedUndo) {
          pushUndo();
          hasPushedUndo = true;
        }
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
        if (moved) {
          syncLineFromWords(lineIdx);
          renderLyrics();
          selectLine(lineIdx);
          selectWord(lastIdx);
        }
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
}

function setupDragHandle(bar, wordIdx, lineIdx, wordsTrack) {
  const handle = bar.querySelector(".drag-handle");
  if (!handle) return;

  let lastClickTime = 0;

  handle.addEventListener("dblclick", (e) => {
    e.preventDefault();
    e.stopPropagation();
    snapSplitToPlayhead(lineIdx, wordIdx);
  });

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();

    const now = Date.now();
    if (now - lastClickTime < 350) {
      lastClickTime = 0;
      snapSplitToPlayhead(lineIdx, wordIdx);
      return;
    }
    lastClickTime = now;

    const line = state.alignment?.lines?.[lineIdx];
    if (!line || !line.words?.length) return;
    const words = line.words;
    if (wordIdx < 0 || wordIdx >= words.length) return;

    const isLastWord = (wordIdx === words.length - 1);
    const startX = e.clientX;
    const startEnd = words[wordIdx].end;
    const trackWidth = wordsTrack.getBoundingClientRect().width || 400;
    const activeSpan = Math.max(0.1, words[words.length - 1].end - words[0].start);
    const pxPerSec = trackWidth / activeSpan;

    const lines = state.alignment.lines;
    const nextLine = lineIdx < lines.length - 1 ? lines[lineIdx + 1] : null;
    const audioDur = (ws && ws.getDuration && ws.getDuration() > 0) ? ws.getDuration() : 9999;
    const minEnd = words[wordIdx].start + 0.01;
    const maxEnd = isLastWord ? (nextLine ? (nextLine.start - 0.01) : audioDur) : (words[wordIdx + 1].end - 0.01);

    let moved = false;
    let hasPushedUndo = false;

    document.body.style.cursor = "col-resize";
    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      if (!moved && Math.abs(dx) < 3) return;
      moved = true;
      if (!hasPushedUndo) {
        pushUndo();
        hasPushedUndo = true;
      }
      const dt = dx / pxPerSec;
      const newEnd = Math.round((startEnd + dt) * 1000) / 1000;
      const clamped = Math.max(minEnd, Math.min(maxEnd, newEnd));
      words[wordIdx].end = clamped;
      if (isLastWord) {
        line.end = clamped;
      } else {
        words[wordIdx + 1].start = clamped;
      }
      renderWords(lineIdx);
      selectWord(wordIdx);
      markDirty();
    };

    const onUp = () => {
      document.body.style.cursor = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (moved) {
        delete words[wordIdx].needs_review;
        delete words[wordIdx].unresolved_compound;
        if (!isLastWord && words[wordIdx + 1]) {
          delete words[wordIdx + 1].needs_review;
          delete words[wordIdx + 1].unresolved_compound;
        }
        syncLineFromWords(lineIdx);
        renderLyrics();
        renderWords(lineIdx);
        selectWord(wordIdx);
      }
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
    status(window.t ? t("time_format_error") : "时间格式错误，请输入 m:ss.xxx 或 秒数", true); return;
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
      status(window.t ? t("snap_start_msg", null, { time: fmtTimeShort(line.start), gap: preGap.toFixed(1) }) : `🎯 首字起唱点已调整为 ${fmtTimeShort(line.start)}（前置间奏: ${preGap.toFixed(1)}s）`);
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
      status(window.t ? t("snap_end_msg", null, { time: fmtTimeShort(line.end), gap: postGap.toFixed(1) }) : `🎯 尾字收唱点已调整为 ${fmtTimeShort(line.end)}（后置间歇: ${postGap.toFixed(1)}s）`);
    } else {
      resizeLine(idx, 0, parsed - line.end);
    }
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("languagechange", () => {
    renderLyrics();
    if (state.selectedLine >= 0) {
      renderWords(state.selectedLine);
    } else {
      clearWordPanel();
    }
  });

  window.PORTRAIT_SAFE_AREA = PORTRAIT_SAFE_AREA;
  window.CURATED_EXPORT_THEMES = CURATED_EXPORT_THEMES;
  window.countVocalUnits = countVocalUnits;
  window.inspectAlignmentTiming = inspectAlignmentTiming;
  window.snapExcerptToSentenceBounds = snapExcerptToSentenceBounds;
  window.recommendExcerptCandidates = recommendExcerptCandidates;
  window.toggleTimingWarningsVisibility = toggleTimingWarningsVisibility;
  window.getTimingWarningsVisible = () => timingWarningsVisible;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    PORTRAIT_SAFE_AREA,
    CURATED_EXPORT_THEMES,
    countVocalUnits,
    inspectAlignmentTiming,
    snapExcerptToSentenceBounds,
    recommendExcerptCandidates,
    toggleTimingWarningsVisibility,
    getTimingWarningsVisible: () => timingWarningsVisible,
  };
}
