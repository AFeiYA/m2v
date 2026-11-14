import { compileHighlightSpans, highlightState, type HighlightSpan } from './karaoke.ts';
import type { Project, Line } from './model.ts';
import { computeIntroEnd } from './song-layout.ts';
import {
  BOKEH_LIGHTS,
  SNOW_FLAKES,
  getKtvSlotState,
  getLineWords,
  getKtvSectionInfo,
  isKtvChristmasTheme,
  resolveKtvParticlesMode,
  type SlotState,
} from './ktv-stage-shared.ts';

export type TextMeasure = (text: string, size: number, weight: number) => {
  width: number;
  advance?: number;
  ascent: number;
  descent: number;
};

export interface StreamPalette {
  accent: string;
  background: string;
  foreground: string;
  muted: string;
}

// ---------------------------------------------------------------------------
// 1. 经典 KTV 双行交替卡拉OK模型 (16:9 专用)
// ---------------------------------------------------------------------------

export interface KtvLineCompiled {
  lineIndex: number;
  line: Line;
  isUpper: boolean;
  x: number;
  y: number;
  width: number;
  fontSize: number;
  align: 'left' | 'right' | 'center';
  previewStart: number;
  activeStart: number;
  activeEnd: number;
  stayEnd: number;
  spans: HighlightSpan[];
}

export interface KtvLeadInDot {
  index: number;
  x: number;
  y: number;
  radius: number;
  scale: number;
  alpha: number;
  isLit: boolean;
  isActive: boolean;
}

export interface KtvLeadInState {
  targetLineIndex: number;
  dots: [KtvLeadInDot, KtvLeadInDot, KtvLeadInDot, KtvLeadInDot];
  overallAlpha: number;
  activeBeat: number;
}

export interface KtvDualCompiled {
  aspect: '16:9' | '9:16';
  width: number;
  height: number;
  uniformFontSize: number;
  lines: KtvLineCompiled[];
  palette: StreamPalette;
  introEnd?: number;
  title?: string;
  artist?: string;
  bpm?: number;
  duration?: number;
  sections?: { name: string; start: number; end: number }[];
  showHud?: boolean;
  isChristmas?: boolean;
  particlesMode?: 'snow' | 'particles' | 'none';
  alignment?: 'center' | 'classic';
}

export function compileKtvDualLayout(
  project: Project,
  width: number,
  height: number,
  measure: TextMeasure,
  palette: StreamPalette,
  options?: {
    font_scale?: number;
    preview_seconds?: number;
    alignment?: 'center' | 'classic';
    position_y?: number;
    show_hud?: boolean;
  }
): KtvDualCompiled {
  const lines = project.lines || [];
  const title = project.title || project.song_identity?.title || '';
  const artist = project.artist || project.song_identity?.artist || '';
  const bpm = Math.round(project.features?.tempo || project.analysis?.bpm || (project as any).bpm || 0);
  const sections = (project.sections || []).map(s => ({
    name: s.name,
    start: s.start,
    end: s.end,
  }));
  const maxWidth = Math.round(width * 0.68);
  const baseFontSize = Math.round(Math.min(width,height*1.5) * 0.038 * (options?.font_scale||1));
  const previewSeconds = options?.preview_seconds ?? 2.5;

  // 首句预览时机计算：若存在前奏封面，必须在封面彻底淡出后才进场预读，杜绝视觉撞车
  const introEnd = computeIntroEnd(project);

  // 1. 预先测量全曲所有歌词单句在基准字号下的宽度，找出最长句
  let maxMeasured = 1.0;
  for (const line of lines) {
    const m = measure(line.text, baseFontSize, 700);
    if (m.width > maxMeasured) {
      maxMeasured = m.width;
    }
  }

  // 2. 计算全局统一字号，全曲上下行严格一致，杜绝忽大忽小
  const minUniformSize = Math.max(22, Math.round(baseFontSize * 0.58));
  const uniformFontSize = Math.max(
    minUniformSize,
    Math.floor(baseFontSize * Math.min(1.0, maxWidth / maxMeasured))
  );

  const alignment = options?.alignment || 'classic';
  const posY = options?.position_y ?? (alignment === 'center' ? 0.52 : 0.82);
  const lineSpacing = Math.round(uniformFontSize * 1.85);

  const centerY = Math.round(height * posY);
  const yUpper = Math.round(centerY - lineSpacing * 0.55);
  const yLower = Math.round(centerY + lineSpacing * 0.55);
  const leftX = Math.round(width * 0.16);
  const rightBoundaryX = Math.round(width * 0.84);

  const compiledLines: KtvLineCompiled[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const isUpper = i % 2 === 0;
    const y = isUpper ? yUpper : yLower;
    const m = measure(line.text, uniformFontSize, 700);
    const lineWidth = m.width;

    let x: number;
    let align: 'left' | 'right' | 'center';
    if (alignment === 'center') {
      x = Math.round((width - lineWidth) / 2);
      align = 'center';
    } else {
      x = isUpper ? leftX : Math.max(leftX, rightBoundaryX - lineWidth);
      align = isUpper ? 'left' : 'right';
    }

    // ── 状态生命周期计算 ──
    // 严格槽位衔接：同槽位上一句驻留结束时间 = 同槽位下一句预读开始时间
    let previewStart = 0;
    if (i === 0) {
      const idealPreview = line.start - previewSeconds;
      previewStart = Math.max(introEnd > 0 ? introEnd + 0.15 : 0, idealPreview);
    } else if (i === 1) {
      previewStart = Math.max(0, lines[0].start);
    } else {
      // 距离本句开唱前 2.5 秒，且不早于同槽位前一句 (i-2) 唱完时间
      previewStart = Math.max(lines[i - 2].end, line.start - previewSeconds);
    }
    const activeStart = line.start;
    const activeEnd = Math.max(activeStart + 0.5, line.end);

    // 唱完常驻：保持高亮，直到同槽位下一句 (i+2) 进入 preview
    let stayEnd = activeEnd + previewSeconds;
    if (i + 2 < lines.length) {
      stayEnd = Math.max(activeEnd, lines[i + 2].start - previewSeconds);
    }

    // 编译单句高亮区间
    const wordList = line.words || [];
    const indices = wordList.map((_, idx) => idx);
    const spans = compileHighlightSpans(
      wordList,
      indices,
      [{ text: line.text, x, y }],
      uniformFontSize,
      700,
      measure
    );

    compiledLines.push({
      lineIndex: i,
      line,
      isUpper,
      x,
      y,
      width: lineWidth,
      fontSize: uniformFontSize,
      align,
      previewStart,
      activeStart,
      activeEnd,
      stayEnd,
      spans,
    });
  }

  const isChristmas = isKtvChristmasTheme(project, (options as any)?.preset, palette.accent);
  const particlesMode = resolveKtvParticlesMode(project, (options as any)?.ambient_particles, isChristmas);

  return {
    aspect: height>width?'9:16':'16:9',
    width,
    height,
    uniformFontSize,
    lines: compiledLines,
    palette,
    introEnd,
    title,
    artist,
    bpm,
    duration: project.duration || lines.at(-1)?.end || 180,
    sections,
    showHud: options?.show_hud ?? true,
    isChristmas,
    particlesMode,
    alignment,
  };
}

export interface KtvLineRenderState {
  compiled: KtvLineCompiled;
  phase: 'preview' | 'active' | 'stay' | 'hidden';
  dimColor: string;
  sungColor: string;
  spansWithProgress: { span: HighlightSpan; progress: number; active: boolean }[];
  alpha: number;
  dy: number;
  leadIn?: KtvLeadInState | null;
  timeUntilStart: number;
}

export function ktvDualStateAt(
  layout: KtvDualCompiled,
  t: number
): {
  upper: KtvLineRenderState | null;
  lower: KtvLineRenderState | null;
  currentSection?: string;
  sectionIcon?: string;
} {
  let upper: KtvLineRenderState | null = null;
  let lower: KtvLineRenderState | null = null;

  for (const c of layout.lines) {
    if (t < c.previewStart || (c.lineIndex + 2 < layout.lines.length ? t >= c.stayEnd : t > c.stayEnd)) {
      continue;
    }
    let phase: 'preview' | 'active' | 'stay' = 'stay';
    let alpha = 1.0;
    let dy = 0;

    const timeUntilStart = Math.max(0, c.activeStart - t);
    let leadIn: KtvLeadInState | null = null;

    if (t < c.activeStart) {
      phase = 'preview';
      const elapsed = t - c.previewStart;
      const enterProg = Math.min(1, Math.max(0, elapsed / 0.28));
      const ease = 1 - Math.pow(1 - enterProg, 3);
      dy = Math.round((1 - ease) * 10);
      alpha = Number(ease.toFixed(3));

      // 4-beat rhythm countdown indicator when within 2.0s of singing
      if (timeUntilStart <= 2.0 && timeUntilStart > 0.05) {
        const dotSpacing = Math.round(c.fontSize * 0.45);
        const dotRadius = Math.max(4, Math.round(c.fontSize * 0.12));
        const dotsStartX = c.x - dotSpacing * 4 - 8;
        const dotsY = c.y - Math.round(c.fontSize * 0.32);

        const activeBeat = Math.min(4, Math.max(1, Math.floor((2.0 - timeUntilStart) / 0.5) + 1));
        const overallAlpha = Math.min(1, Math.max(0, (t - c.previewStart) / 0.25));

        const dots = [0, 1, 2, 3].map(i => {
          const isLit = (i + 1) <= activeBeat;
          const isActive = (i + 1) === activeBeat;
          return {
            index: i,
            x: dotsStartX + i * dotSpacing,
            y: dotsY,
            radius: dotRadius,
            scale: isActive ? 1.35 : (isLit ? 1.1 : 1.0),
            alpha: isLit ? 1.0 : 0.3,
            isLit,
            isActive,
          };
        }) as [KtvLeadInDot, KtvLeadInDot, KtvLeadInDot, KtvLeadInDot];

        leadIn = {
          targetLineIndex: c.lineIndex,
          dots,
          overallAlpha,
          activeBeat,
        };
      }
    } else if (t <= c.activeEnd) {
      phase = 'active';
      dy = 0;
      alpha = 1.0;
    } else {
      phase = 'stay';
      const remaining = c.stayEnd - t;
      if (remaining < 0.25) {
        const exitProg = Math.min(1, Math.max(0, remaining / 0.25));
        alpha = Number(exitProg.toFixed(3));
        dy = Math.round((1 - exitProg) * -6);
      }
    }

    const spansWithProgress = c.spans.map(span => {
      const h = highlightState(span, t, 'sweep');
      return { span, progress: h.progress, active: h.active };
    });

    const state: KtvLineRenderState = {
      compiled: c,
      phase,
      dimColor: '#FFFFFF', // High-contrast pure white for un-sung lyrics (NEVER black!)
      sungColor: layout.isChristmas ? '#FEF08A' : layout.palette.accent,
      spansWithProgress,
      alpha,
      dy,
      leadIn,
      timeUntilStart,
    };

    if (c.isUpper) {
      upper = state;
    } else {
      lower = state;
    }
  }

  // Derive current section marker and icon
  let currentSection = 'Intro';
  if (layout.sections && layout.sections.length > 0) {
    for (const s of layout.sections) {
      if (t >= s.start - 0.2) {
        currentSection = s.name.replace(/^\[|\]$/g, '').trim();
      }
    }
  } else {
    const active = layout.lines.find(l => t >= l.activeStart - 0.5 && t <= l.stayEnd);
    if (active?.line?.section) {
      currentSection = active.line.section.replace(/^\[|\]$/g, '').trim();
    }
  }

  const sLower = currentSection.toLowerCase();
  let sectionIcon = '🎵';
  if (sLower.includes('chorus') || sLower.includes('副歌')) {
    sectionIcon = layout.isChristmas ? '🔔' : '🎵';
  } else if (sLower.includes('solo') || sLower.includes('interlude') || sLower.includes('间奏')) {
    sectionIcon = layout.isChristmas ? '🛷' : '⚡';
  } else if (sLower.includes('verse') || sLower.includes('主歌')) {
    sectionIcon = '🎤';
  } else if (sLower.includes('outro') || sLower.includes('尾声')) {
    sectionIcon = '✨';
  } else if (sLower.includes('intro') || sLower.includes('前奏')) {
    sectionIcon = layout.isChristmas ? '🎄' : '🎧';
  }

  return { upper, lower, currentSection, sectionIcon };
}

export function paintKtvDualCanvas(
  ctx: CanvasRenderingContext2D,
  layout: KtvDualCompiled,
  t: number,
  fontFamily: string
): void {
  const width = layout.width;
  const height = layout.height;
  const isLandscape = width >= height;
  const isChristmas = Boolean(layout.isChristmas);
  const accent = isChristmas ? '#FFD700' : (layout.palette.accent || '#b7f34a');
  const sungHighlight = isChristmas ? '#FEF08A' : accent;
  const frame = t * 30;
  const rawLines = layout.lines.map(c => c.line);
  const { currentSection, sectionIcon } = getKtvSectionInfo(layout.sections, rawLines, t, isChristmas);

  // 0. Background & Radial Stage Vignette (NO raw cover image)
  ctx.save();
  ctx.fillStyle = isChristmas ? '#120303' : (layout.palette.background || '#090d14');
  ctx.fillRect(0, 0, width, height);

  const bgGrad = ctx.createRadialGradient(
    width * 0.5,
    height * (isChristmas ? 0.28 : 0.3),
    0,
    width * 0.5,
    height * (isChristmas ? 0.28 : 0.3),
    Math.max(width, height) * 0.72
  );
  if (isChristmas) {
    bgGrad.addColorStop(0, '#3d0707');
    bgGrad.addColorStop(0.42, '#260404');
    bgGrad.addColorStop(0.78, '#140202');
    bgGrad.addColorStop(1, '#080101');
  } else {
    bgGrad.addColorStop(0, 'rgba(18, 26, 40, 0.75)');
    bgGrad.addColorStop(1, 'rgba(6, 10, 16, 0.96)');
  }
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, width, height);
  ctx.restore();

  // 0.5 Warm Bokeh Fairy Lights & Snow Particles (driven by theme & particlesMode)
  const effectiveParticles = layout.particlesMode ?? (isChristmas ? 'snow' : 'particles');
  if (isChristmas && effectiveParticles !== 'none') {
    ctx.save();
    for (let i = 0; i < BOKEH_LIGHTS.length; i++) {
      const orb = BOKEH_LIGHTS[i];
      const pulse = 0.82 + Math.sin(frame * orb.pulseSpeed + i) * 0.18;
      const cx = (orb.x / 1920) * width;
      const cy = (orb.y / 1080) * height;
      const r = ((orb.size / 1920) * width) * 0.85 * pulse;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(1, r));
      g.addColorStop(0, orb.color);
      g.addColorStop(0.55, orb.color);
      g.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(1, r), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  if (effectiveParticles === 'snow') {
    ctx.save();
    for (const flake of SNOW_FLAKES) {
      const yOffset = ((frame * flake.speed * 2.2 + flake.id * 73) % (height + 60)) - 30;
      const xOffset = ((flake.x + Math.sin(frame * flake.swaySpeed + flake.id) * flake.swayAmp) / 1920) * width;
      const r = Math.max(1, ((flake.size / 1920) * width) * 0.5);
      ctx.globalAlpha = flake.opacity;
      ctx.fillStyle = '#FFFFFF';
      ctx.shadowColor = `rgba(255, 255, 255, ${flake.opacity * 0.8})`;
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.arc(xOffset, yOffset, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  // 1. Victorian Ornate Gold Double Frame (Christmas Special Only in 16:9)
  if (isChristmas && isLandscape) {
    ctx.save();
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.5)';
    ctx.lineWidth = 2;
    if (typeof ctx.roundRect === 'function') {
      ctx.beginPath();
      ctx.roundRect(24, 24, width - 48, height - 48, 16);
      ctx.stroke();

      ctx.strokeStyle = 'rgba(245, 158, 11, 0.3)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([8, 8]);
      ctx.beginPath();
      ctx.roundRect(32, 32, width - 64, height - 64, 10);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.font = '22px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('🎄', 48, 48);
    ctx.fillText('🎄', width - 48, 48);
    ctx.fillText('❄️', 48, height - 48);
    ctx.fillText('❄️', width - 48, height - 48);
    ctx.restore();
  }

  // 2. Center Dual Slots (matching KtvKaraokeStage 1:1)
  const slotTop = getKtvSlotState(0, rawLines, t);
  const slotBottom = getKtvSlotState(1, rawLines, t);
  const isInstrumental = slotTop === null && slotBottom === null;

  const cardFontSize = isLandscape
    ? Math.max(30, Math.round(width * 0.024))
    : Math.max(22, Math.round(width * 0.055));

  if (isInstrumental) {
    ctx.save();
    const interW = Math.min(width * 0.78, 560);
    const interH = 180;
    const interX = (width - interW) / 2;
    const interY = (height - interH) / 2;

    ctx.fillStyle = isChristmas ? 'rgba(30, 4, 4, 0.68)' : 'rgba(12, 18, 28, 0.75)';
    ctx.strokeStyle = isChristmas ? 'rgba(245, 158, 11, 0.4)' : `${accent}55`;
    ctx.lineWidth = 1.5;
    ctx.shadowColor = 'rgba(0, 0, 0, 0.7)';
    ctx.shadowBlur = 30;
    ctx.beginPath();
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(interX, interY, interW, interH, isLandscape ? 28 : 20);
    } else {
      ctx.rect(interX, interY, interW, interH);
    }
    ctx.fill();
    ctx.stroke();

    ctx.shadowBlur = 0;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = `${isLandscape ? 40 : 32}px sans-serif`;
    ctx.fillText(isChristmas ? '🛷 ❄️ 🔔' : '🎵 ⚡ 🎧', width / 2, interY + 46);

    ctx.font = `800 ${isLandscape ? 22 : 16}px ${fontFamily}`;
    ctx.fillStyle = sungHighlight;
    ctx.shadowColor = accent;
    ctx.shadowBlur = 14;
    ctx.fillText(`♫ ${(currentSection || 'Intro').toUpperCase()} ♫`, width / 2, interY + 104);

    ctx.font = `500 ${isLandscape ? 14 : 12}px ${fontFamily}`;
    ctx.fillStyle = '#E2E8F0';
    ctx.shadowBlur = 0;
    ctx.fillText(
      isChristmas ? 'Listen to the sleigh bells... Get ready to sing!' : 'Feel the groove... Get ready to sing!',
      width / 2,
      interY + 144
    );
    ctx.restore();
  } else {
    const activeSlots: Array<{ state: SlotState; slotType: 'top' | 'bottom' }> = [];
    if (slotTop) activeSlots.push({ state: slotTop, slotType: 'top' });
    if (slotBottom) activeSlots.push({ state: slotBottom, slotType: 'bottom' });

    const stagePadX = isLandscape ? 48 : 18;
    const staggerPad = isLandscape ? 60 : 0;
    const cardPadX = isLandscape ? 36 : 20;
    const cardPadY = isLandscape ? 16 : 12;
    const colGap = isLandscape ? 16 : 10;
    const rowGap = 8;
    const lineHeight = Math.round(cardFontSize * 1.25);
    const maxCardW = Math.round(width * (isLandscape ? 0.85 : 0.92));
    const maxContentW = maxCardW - cardPadX * 2;
    const stageGap = isLandscape ? 36 : 24;

    interface MeasuredWord {
      word: string;
      start: number;
      end: number;
      width: number;
      x: number;
      row: number;
    }
    interface PreparedCard {
      state: SlotState;
      slotType: 'top' | 'bottom';
      cardW: number;
      cardH: number;
      headWidth: number;
      showLeadIn: boolean;
      activeBeat: number;
      rowsCount: number;
      words: MeasuredWord[];
    }

    const prepared: PreparedCard[] = [];
    ctx.save();
    ctx.font = `900 ${cardFontSize}px ${fontFamily}`;

    for (const item of activeSlots) {
      const { state, slotType } = item;
      const showLeadIn = state.isUpcoming && state.timeUntilStart <= 2.0 && state.timeUntilStart > 0;
      const activeBeat = showLeadIn ? Math.floor((2.0 - state.timeUntilStart) / 0.5) + 1 : 0;

      // Head indicator width + marginRight (8px) + colGap
      const headWidth = showLeadIn
        ? (isLandscape ? 12 * 4 + 6 * 3 : 9 * 4 + 6 * 3)
        : state.isSinging
          ? (isLandscape ? 28 : 22)
          : (isLandscape ? 18 : 14);
      const headSlotW = headWidth + 8;

      const rawWords = getLineWords(state.line).filter(w => w.word.trim().length > 0);
      const measuredWords: MeasuredWord[] = [];
      let curX = headSlotW + colGap;
      let curRow = 0;
      let maxRowW = headSlotW;

      for (const w of rawWords) {
        const wWidth = ctx.measureText(w.word).width;
        if (curX > 0 && curX + wWidth > maxContentW && (curRow > 0 || curX > headSlotW + colGap)) {
          maxRowW = Math.max(maxRowW, curX - colGap);
          curRow++;
          curX = 0;
        }
        measuredWords.push({
          word: w.word,
          start: w.start,
          end: w.end,
          width: wWidth,
          x: curX,
          row: curRow,
        });
        curX += wWidth + colGap;
      }
      if (measuredWords.length > 0) {
        maxRowW = Math.max(maxRowW, curX - colGap);
      }

      const rowsCount = curRow + 1;
      const contentH = rowsCount * lineHeight + Math.max(0, rowsCount - 1) * rowGap;
      const cardW = Math.min(maxCardW, Math.ceil(maxRowW + cardPadX * 2));
      const cardH = Math.ceil(contentH + cardPadY * 2);

      prepared.push({
        state,
        slotType,
        cardW,
        cardH,
        headWidth,
        showLeadIn,
        activeBeat,
        rowsCount,
        words: measuredWords,
      });
    }
    ctx.restore();

    const totalStackH = prepared.reduce((acc, c) => acc + c.cardH, 0) + Math.max(0, prepared.length - 1) * stageGap;
    let curTopY = Math.round((height - totalStackH) / 2);

    for (const card of prepared) {
      const { state, slotType, cardW, cardH, headWidth, showLeadIn, activeBeat, words } = card;
      const { isSinging, isUpcoming, isPast, opacity } = state;
      const isTop = slotType === 'top';

      const isCenterAlign = layout.alignment === 'center';
      const cardX = isLandscape && !isCenterAlign
        ? (isTop ? stagePadX + staggerPad : width - stagePadX - staggerPad - cardW)
        : Math.round((width - cardW) / 2);
      const cardY = curTopY + Math.round((1 - opacity) * 8);
      curTopY += card.cardH + stageGap;

      ctx.save();
      ctx.globalAlpha = opacity;

      // 3.1 Luxury Glassmorphism Card Container
      const cardRadius = isLandscape ? 24 : 18;
      ctx.save();
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(cardX, cardY, cardW, cardH, cardRadius);
      } else {
        ctx.rect(cardX, cardY, cardW, cardH);
      }

      if (isSinging) {
        ctx.fillStyle = isChristmas ? 'rgba(42, 5, 5, 0.88)' : 'rgba(12, 18, 28, 0.85)';
        ctx.shadowColor = isChristmas ? 'rgba(245, 158, 11, 0.45)' : `${accent}55`;
        ctx.shadowBlur = 28;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = isChristmas ? '#F59E0B' : accent;
        ctx.lineWidth = 2;
        ctx.stroke();
      } else if (isUpcoming) {
        ctx.fillStyle = isChristmas ? 'rgba(22, 3, 3, 0.68)' : 'rgba(8, 12, 20, 0.72)';
        ctx.shadowColor = 'rgba(0, 0, 0, 0.6)';
        ctx.shadowBlur = 24;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = isChristmas ? 'rgba(245, 158, 11, 0.35)' : 'rgba(255, 255, 255, 0.18)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else {
        ctx.fillStyle = isChristmas ? 'rgba(18, 2, 2, 0.52)' : 'rgba(6, 10, 16, 0.55)';
        ctx.shadowColor = 'rgba(0, 0, 0, 0.6)';
        ctx.shadowBlur = 24;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = isChristmas ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();

      const contentStartX = cardX + cardPadX;
      const firstRowCenterY = cardY + cardPadY + lineHeight / 2;

      // 3.2 Head Indicator: Oscillating Singing Cue / 4-Beat Countdown / Arrow
      if (isSinging) {
        ctx.save();
        const iconScale = 1 + Math.sin(frame * 0.3) * 0.15;
        const iconRot = (Math.sin(frame * 0.2) * 8 * Math.PI) / 180;
        ctx.translate(contentStartX + headWidth / 2, firstRowCenterY);
        ctx.scale(iconScale, iconScale);
        ctx.rotate(iconRot);
        ctx.font = `${isLandscape ? 24 : 18}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.shadowColor = accent;
        ctx.shadowBlur = 8;
        ctx.fillText(isChristmas ? '🔔' : '🎤', 0, 0);
        ctx.restore();
      } else if (showLeadIn) {
        ctx.save();
        const dotSize = isLandscape ? 12 : 9;
        const dotRadius = dotSize / 2;
        const dotGap = 6;
        for (let b = 1; b <= 4; b++) {
          const dx = contentStartX + dotRadius + (b - 1) * (dotSize + dotGap);
          const isLit = b <= activeBeat;
          const isBeatActive = b === activeBeat;
          ctx.save();
          ctx.translate(dx, firstRowCenterY);
          ctx.scale(isBeatActive ? 1.4 : 1.0, isBeatActive ? 1.4 : 1.0);
          ctx.beginPath();
          ctx.arc(0, 0, dotRadius, 0, Math.PI * 2);
          if (isLit) {
            ctx.fillStyle = accent;
            ctx.shadowColor = accent;
            ctx.shadowBlur = 12;
          } else {
            ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
          }
          ctx.fill();
          ctx.restore();
        }
        ctx.restore();
      } else {
        ctx.save();
        ctx.font = `700 ${isLandscape ? 16 : 13}px ${fontFamily}`;
        ctx.fillStyle = isPast ? `${accent}55` : `${accent}99`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(isTop ? '▲' : '▼', contentStartX + headWidth / 2, firstRowCenterY);
        ctx.restore();
      }

      // 3.3 Word-by-word Rendering with Dynamic 1.12x Active Word Zoom & Bloom
      ctx.font = `900 ${cardFontSize}px ${fontFamily}`;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';

      for (const wObj of words) {
        const isWordPast = t >= wObj.end;
        const isWordActive = t >= wObj.start && t < wObj.end;
        let wordProgress = 0;
        if (isWordPast) wordProgress = 1;
        else if (isWordActive) {
          wordProgress = (t - wObj.start) / Math.max(0.01, wObj.end - wObj.start);
        }

        const wx = contentStartX + wObj.x;
        const wy = cardY + cardPadY + wObj.row * (lineHeight + rowGap);
        const wCenterY = wy + lineHeight / 2;

        ctx.save();
        if (isWordActive) {
          const midX = wx + wObj.width / 2;
          ctx.translate(midX, wCenterY);
          ctx.scale(1.12, 1.12);
          ctx.translate(-midX, -wCenterY);
        }

        // Unsung / Past base layer
        ctx.fillStyle = isWordPast
          ? (isChristmas ? '#FDE047' : accent)
          : isSinging
            ? 'rgba(255, 255, 255, 0.78)'
            : '#FFFFFF';
        if (isWordPast) {
          ctx.shadowColor = accent;
          ctx.shadowBlur = 16;
        } else {
          ctx.shadowColor = 'rgba(0, 0, 0, 0.95)';
          ctx.shadowBlur = 8;
          ctx.shadowOffsetY = 2;
        }
        ctx.fillText(wObj.word, wx, wCenterY);

        // Active singing sweep layer with bloom
        if (isWordActive && wordProgress > 0) {
          ctx.save();
          ctx.beginPath();
          ctx.rect(wx - 4, wy - 8, wObj.width * wordProgress + 4, lineHeight + 16);
          ctx.clip();
          ctx.fillStyle = sungHighlight;
          ctx.shadowColor = isChristmas ? '#F59E0B' : accent;
          ctx.shadowBlur = isChristmas ? 22 : 18;
          ctx.shadowOffsetY = 0;
          ctx.fillText(wObj.word, wx, wCenterY);
          ctx.restore();
        }
        ctx.restore();
      }

      ctx.restore();
    }
  }

  // 4. Top Header HUD (matching KtvKaraokeStage 1:1)
  if (layout.showHud !== false && (layout.title || currentSection)) {
    const topY = isLandscape ? 44 : 28;
    const badgeFontSize = isLandscape ? 16 : 13;
    const badgeText = `${sectionIcon}  ${(currentSection || 'Intro').toUpperCase()}`;

    ctx.save();
    ctx.font = `800 ${badgeFontSize}px ${fontFamily}`;
    const badgeTextW = ctx.measureText(badgeText).width;
    const badgePadX = isLandscape ? 20 : 14;
    const badgePadY = isLandscape ? 6 : 4;
    const badgeW = badgeTextW + badgePadX * 2;
    const badgeH = badgeFontSize + badgePadY * 2 + 4;
    const badgeX = Math.round((width - badgeW) / 2);

    ctx.beginPath();
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(badgeX, topY, badgeW, badgeH, badgeH / 2);
    } else {
      ctx.rect(badgeX, topY, badgeW, badgeH);
    }
    ctx.fillStyle = isChristmas ? 'rgba(20, 20, 20, 0.72)' : 'rgba(12, 18, 28, 0.75)';
    ctx.shadowColor = isChristmas ? 'rgba(245, 158, 11, 0.4)' : `${accent}44`;
    ctx.shadowBlur = 16;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = isChristmas ? '#F59E0B' : accent;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = isChristmas ? '#FEF08A' : accent;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(0, 0, 0, 0.8)';
    ctx.shadowBlur = 3;
    ctx.fillText(badgeText, width / 2, topY + badgeH / 2);

    const displayTitle = (layout.title || 'Untitled Track').replace(/[-_]/g, ' ').toUpperCase();
    const titleFontSize = isLandscape ? 34 : 22;
    const titleY = topY + badgeH + (isLandscape ? 10 : 6) + titleFontSize / 2;
    ctx.font = `900 ${titleFontSize}px ${fontFamily}`;
    ctx.fillStyle = isChristmas ? '#FEF08A' : '#FFFFFF';
    ctx.shadowColor = isChristmas ? 'rgba(245, 158, 11, 0.4)' : 'rgba(0, 0, 0, 0.9)';
    ctx.shadowBlur = isChristmas ? 20 : 8;
    ctx.fillText(displayTitle, width / 2, titleY);

    if (isLandscape) {
      const subY = titleY + titleFontSize / 2 + 12;
      const tempoStr = layout.bpm && layout.bpm > 0
        ? `${layout.bpm} BPM`
        : (isChristmas ? 'VICTORIAN CHRISTMAS' : 'KARAOKE');
      const subText = layout.artist ? `${layout.artist} • ${tempoStr}` : tempoStr;
      ctx.font = `600 14px ${fontFamily}`;
      ctx.fillStyle = isChristmas ? '#FDE68A' : 'rgba(255, 255, 255, 0.75)';
      ctx.shadowColor = 'rgba(0, 0, 0, 0.8)';
      ctx.shadowBlur = 4;
      ctx.fillText(subText, width / 2, subY);
    }
    ctx.restore();
  }

  // 5. Bottom Timeline HUD Progress Bar
  ctx.save();
  const barMargin = isLandscape ? 80 : 24;
  const barBottom = height - (isLandscape ? 44 : 24);
  const barH = isLandscape ? 6 : 4;
  const barY = barBottom - barH;
  const barW = width - barMargin * 2;

  const timeFontSize = isLandscape ? 14 : 11;
  ctx.font = `600 ${timeFontSize}px ${fontFamily}`;
  ctx.fillStyle = isChristmas ? '#FDE68A' : 'rgba(255, 255, 255, 0.8)';
  ctx.textBaseline = 'bottom';
  const curMin = Math.floor(t / 60).toString().padStart(2, '0');
  const curSec = Math.floor(t % 60).toString().padStart(2, '0');
  ctx.textAlign = 'left';
  ctx.fillText(`${curMin}:${curSec}`, barMargin, barY - 8);

  const dur = layout.duration || layout.lines.at(-1)?.stayEnd || 180;
  const totMin = Math.floor(dur / 60).toString().padStart(2, '0');
  const totSec = Math.floor(dur % 60).toString().padStart(2, '0');
  ctx.textAlign = 'right';
  ctx.fillText(`${totMin}:${totSec}`, width - barMargin, barY - 8);

  ctx.textAlign = 'center';
  ctx.font = `800 ${timeFontSize}px ${fontFamily}`;
  ctx.fillStyle = sungHighlight;
  const centerStatusText = isChristmas
    ? `🎄 ${layout.bpm && layout.bpm > 0 ? `${layout.bpm} BPM` : 'DUAL KTV'} ❄️`
    : (layout.bpm && layout.bpm > 0 ? `${layout.bpm} BPM` : 'DUAL KTV');
  ctx.fillText(centerStatusText, width / 2, barY - 8);

  ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
  ctx.beginPath();
  if (typeof ctx.roundRect === 'function') {
    ctx.roundRect(barMargin, barY, barW, barH, barH / 2);
  } else {
    ctx.rect(barMargin, barY, barW, barH);
  }
  ctx.fill();

  const progW = Math.max(0, Math.min(barW, (t / Math.max(1, dur)) * barW));
  if (progW > 0) {
    const grad = ctx.createLinearGradient(barMargin, barY, barMargin + progW, barY);
    if (isChristmas) {
      grad.addColorStop(0, '#DC2626');
      grad.addColorStop(0.5, '#F59E0B');
      grad.addColorStop(1.0, '#FEF08A');
    } else {
      grad.addColorStop(0, `${accent}88`);
      grad.addColorStop(1.0, accent);
    }
    ctx.fillStyle = grad;
    ctx.shadowColor = accent;
    ctx.shadowBlur = 12;
    ctx.beginPath();
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(barMargin, barY, progW, barH, barH / 2);
    } else {
      ctx.rect(barMargin, barY, progW, barH);
    }
    ctx.fill();
  }
  ctx.restore();
}

// ---------------------------------------------------------------------------
// 2. Apple Music 灵动流式歌词模型 (9:16 垂直居中滚动聚焦)
// ---------------------------------------------------------------------------

const NO_LINE_START = /^[，。！？、；：”’）》〉】｝〕…—~～,.!?;:)\]}"']/u;
const NO_LINE_END = /^[“‘（《〈【｛〔([<{]/u;

/**
 * 依行宽与避头尾法则 (Kinsoku Shori) 将长句折为多行。
 * 英文保持词完整、中日韩允许字间换行、标点不单独孤立在行首或行尾。
 */
export function wrapSentenceToRows(
  text: string,
  size: number,
  weight: number,
  maxWidth: number,
  measure: TextMeasure
): string[] {
  if (!text || !text.trim()) return [text || ''];
  if (measure(text, size, weight).width <= maxWidth) return [text.trim()];

  // Token 分词：英文完整单词（含缩写与连字符）及后随标点、汉字单字、其它符号及空白
  const tokenRegex = /[\p{Script=Latin}\p{N}]+(?:['’\-][\p{Script=Latin}\p{N}]+)*[^\p{Script=Latin}\p{N}\s\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]*|[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]|[^\p{Script=Latin}\p{N}\s\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]+|\s+/gu;

  const tokens = text.match(tokenRegex) || [text];
  const rows: string[] = [''];

  for (const token of tokens) {
    const i = rows.length - 1;
    const current = rows[i];
    const candidate = current + token;

    if (current && measure(candidate, size, weight).width > maxWidth && token.trim()) {
      // 避尾法则：上一行末尾是开括号或前引号时，将该字符拉到新行
      const lastChar = current.trim().slice(-1);
      if (NO_LINE_END.test(lastChar)) {
        const prevTokens = current.match(tokenRegex) || [];
        if (prevTokens.length > 1) {
          const pulled = prevTokens.pop()!;
          rows[i] = prevTokens.join('').trimEnd();
          rows.push((pulled + token).trimStart());
          continue;
        }
      }

      // 避头法则：当前 token 以行首禁用标点开头时，将上一行末尾单词一起拉下
      if (NO_LINE_START.test(token.trim())) {
        const prevTokens = current.match(tokenRegex) || [];
        if (prevTokens.length > 1) {
          const pulled = prevTokens.pop()!;
          rows[i] = prevTokens.join('').trimEnd();
          rows.push((pulled + token).trimStart());
          continue;
        }
      }

      rows.push(token.trimStart());
    } else {
      rows[i] += token;
    }
  }

  const cleaned = rows.map(r => r.trim()).filter(Boolean);
  return cleaned.length ? cleaned : [text.trim()];
}

export interface AppleRowCompiled {
  text: string;
  x: number;
  yOffset: number; // 相对当前句子基线的纵向偏移 (0, rowLineHeight, 2*rowLineHeight...)
  width: number;
}

export interface AppleLineCompiled {
  lineIndex: number;
  line: Line;
  text: string;
  rows: AppleRowCompiled[];
  sentenceHeight: number; // (rows.length - 1) * rowLineHeight
  cumulativeY: number;    // 虚拟长列表中的句首基线位置
  centerY: number;        // 该句的纵向视觉中心
  width: number;
  fontSize: number;
  start: number;
  end: number;
  spans: HighlightSpan[];
  hasInterlude?: boolean;
  interludeGap?: number;
}

export interface AppleInterludeCompiled {
  targetLineIndex: number;
  startTime: number;
  endTime: number;
  gap: number;
  centerY: number;
  height: number;
}

export interface AppleScrollCompiled {
  focusY?: number;
  aspect: '16:9' | '9:16';
  width: number;
  height: number;
  startX: number;
  maxWidth: number;
  activeFontSize: number;
  contextFontSize: number;
  rowLineHeight: number;
  paragraphGap: number;
  lineGap: number;
  lines: AppleLineCompiled[];
  interludes?: AppleInterludeCompiled[];
  palette: StreamPalette;
  introEnd?: number;
}

export function compileAppleScrollLayout(
  project: Project,
  width: number,
  height: number,
  measure: TextMeasure,
  palette: StreamPalette,
  options?: {font_scale?:number;focus_y?:number;count_in?:boolean}
): AppleScrollCompiled {
  const lines = project.lines || [];
  // Apple Music 移动端规范：左边距安全边距约 8%，给歌词留出 84% 舒适阅读宽度
  const startX = Math.round(width * 0.08);
  const maxWidth = width - startX * 2;
  const activeFontSize = Math.round(Math.min(width,height*.9) * 0.052 * (options?.font_scale||1));
  const contextFontSize = Math.round(activeFontSize * 0.72);
  const rowLineHeight = Math.round(activeFontSize * 1.34);
  // Apple Music 句子间距舒展留白：设为字号的 1.9x，营造优雅自然的呼吸感
  const paragraphGap = Math.round(activeFontSize * 1.9);

  // 首句展示时机：若存在前奏封面，必须在封面彻底淡出后才进场，杜绝视觉撞车
  const introEnd = computeIntroEnd(project);

  const compiledLines: AppleLineCompiled[] = [];
  const interludes: AppleInterludeCompiled[] = [];
  let cumulativeY = 0;

  // 官方标准：伴奏空隙达到 3.0s 且启用了 count_in 开关时才作为独立间奏段，展示 3 拍起跑倒计时圆点
  const MIN_INTERLUDE_GAP = 3.0;
  const enableCountIn = options?.count_in === true;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const prevEnd = i > 0 ? lines[i - 1].end : introEnd;
    const gap = line.start - prevEnd;
    const hasInterlude = (i === 0 ? line.start >= MIN_INTERLUDE_GAP : gap >= MIN_INTERLUDE_GAP);

    // 前奏或间奏空隙 >= 3.0s 且用户开启了间奏倒计时小圆点时，注册独立间奏段
    if (hasInterlude && enableCountIn) {
      interludes.push({
        targetLineIndex: i,
        startTime: prevEnd,
        endTime: line.start,
        gap,
        centerY: 0, // 在 appleScrollStateAt 中结合视觉焦点动态计算
        height: paragraphGap,
      });
    }

    const textRows = wrapSentenceToRows(line.text, activeFontSize, 700, maxWidth, measure);
    const rowList: AppleRowCompiled[] = textRows.map((text, rIdx) => ({
      text,
      x: startX,
      yOffset: rIdx * rowLineHeight,
      width: measure(text, activeFontSize, 700).width,
    }));

    const sentenceHeight = (textRows.length - 1) * rowLineHeight;
    const centerY = cumulativeY + sentenceHeight / 2;

    const wordList = line.words || [];
    const indices = wordList.map((_, idx) => idx);
    const spans = compileHighlightSpans(
      wordList,
      indices,
      rowList.map(r => ({ text: r.text, x: r.x, y: r.yOffset })),
      activeFontSize,
      700,
      measure
    );

    const m = measure(line.text, activeFontSize, 700);

    compiledLines.push({
      lineIndex: i,
      line,
      text: line.text,
      rows: rowList,
      sentenceHeight,
      cumulativeY,
      centerY,
      width: m.width,
      fontSize: activeFontSize,
      start: line.start,
      end: line.end,
      spans,
      hasInterlude,
      interludeGap: gap,
    });

    cumulativeY += sentenceHeight + paragraphGap;
  }

  return {
    aspect: height>width?'9:16':'16:9',
    focusY: options?.focus_y ?? .42,
    width,
    height,
    startX,
    maxWidth,
    activeFontSize,
    contextFontSize,
    rowLineHeight,
    paragraphGap,
    lineGap: paragraphGap,
    lines: compiledLines,
    interludes,
    palette,
    introEnd,
  };
}

export interface AppleLineRenderItem {
  compiled: AppleLineCompiled;
  y: number; // 句首第一行 (row 0) 的基线 Y 坐标
  scale: number;
  alpha: number;
  isActive: boolean;
  spansWithProgress: { span: HighlightSpan; progress: number; active: boolean }[];
}

/**
 * 视口上下边缘羽化衰减函数 (Hermite 曲线)。
 * 顶部 16% 与底部 20% 属于受保护的负空间呼吸区，歌词接近边缘时平滑融入背景。
 */
export function computeAppleEdgeFade(centerY: number, height: number): number {
  const topFadeStart = height * 0.10; // 顶部 10% 呼吸安全区
  const topFadeEnd = height * 0.22;   // 22% 处达到全透
  const bottomFadeStart = height * 0.78; // 78% 开始衰减
  const bottomFadeEnd = height * 0.95;   // 底部 95% 呼吸安全区

  if (centerY <= topFadeStart || centerY >= bottomFadeEnd) return 0;
  if (centerY < topFadeEnd) {
    const p = (centerY - topFadeStart) / (topFadeEnd - topFadeStart);
    return p * p * (3 - 2 * p);
  }
  if (centerY > bottomFadeStart) {
    const p = (bottomFadeEnd - centerY) / (bottomFadeEnd - bottomFadeStart);
    return p * p * (3 - 2 * p);
  }
  return 1;
}

export interface AppleCountInDot {
  index: number;
  x: number;
  y: number;
  radius: number;
  lit: boolean;
  scale: number;
  alpha: number;
  glowAlpha: number;
}

export interface AppleCountInState {
  targetLineIndex: number;
  dots: [AppleCountInDot, AppleCountInDot, AppleCountInDot];
  overallAlpha: number;
}

export function appleScrollStateAt(
  layout: AppleScrollCompiled,
  t: number
): {
  items: AppleLineRenderItem[];
  currentScrollY: number;
  countIn?: AppleCountInState | null;
} {
  const lines = layout.lines;
  if (!lines.length) return { items: [], currentScrollY: 0 };

  const introEnd = layout.introEnd ?? 0;
  // 前奏封面展示期间，Apple 滚动歌词保持隐蔽，避免与封面重叠
  if (introEnd > 0 && t < introEnd) {
    return { items: [], currentScrollY: 0 };
  }
  const introFade = introEnd > 0 ? Math.min(1, Math.max(0, (t - introEnd) / 0.35)) : 1;

  // 1. 查找当前时刻是否有正在进行的独立间奏段 (空隙 >= 3.0s)
  const interludes = layout.interludes || [];
  const activeInterlude = interludes.find(it => t >= it.startTime && t <= it.endTime);

  // 2. 确定平滑世界焦点 Y 坐标与当前聚焦行
  let focalWorldY = lines[0].centerY;
  let focusedLineIdx = 0;
  let isFocalPreLight = false; // 是否处于开唱前的纯白先亮状态 (白色底字就绪)
  let preLightFadeProgress = 1.0; // 间奏尾声平滑淡入进度 (0.40 -> 1.0)

  // 间奏退场缓冲参数：圆点在开唱前 0.35s ~ 0.10s 完全淡出至 0；下一句在 0.20s ~ 0s 上移淡入吸附
  const exitLead = 0.35;
  const exitDotsDone = 0.10; // 距开唱 0.10s 时圆点透明度完全归零并彻底消失

  let dotsWorldY = 0;
  let currentInterludeOffset = 0;

  if (activeInterlude) {
    const targetIdx = activeInterlude.targetLineIndex;
    focusedLineIdx = targetIdx;

    // 字形度量与圆点真实包围盒尺寸
    const F = layout.activeFontSize;
    const fontAscender = Math.round(F * 0.85);  // 基线向上字形高度 (大写/顶端)
    const fontDescender = Math.round(F * 0.25); // 基线向下字形延伸 (下延/标点)
    const dotRadius = Math.max(8, Math.round(F * 0.26));
    const margin = Math.round(F * 0.50); // 呼吸安全留白

    let fullInterludeOffset = 0;

    if (targetIdx > 0) {
      const prevLine = lines[targetIdx - 1];
      // 上一句在世界坐标系中的真实最底沿边界 (包含全部折行高度与字形下延边界)
      const prevActualBottom = prevLine.cumulativeY + prevLine.sentenceHeight + fontDescender;

      // 圆点在世界坐标系中的基准视觉中心：位于上一句真实底沿下方安全留白处
      dotsWorldY = prevActualBottom + margin + dotRadius;

      // 下一句在开辟间奏空间后所需的实际顶沿边界 (位于圆点下方安全留白处)
      const targetNextActualTop = dotsWorldY + dotRadius + margin;
      const targetNextCumulativeY = targetNextActualTop + fontAscender;

      // 为圆点与折行歌词预留的真实下推空间 (下一句实际顶沿不与圆点产生任何干涉)
      const nextLine = lines[targetIdx];
      fullInterludeOffset = Math.max(0, targetNextCumulativeY - nextLine.cumulativeY);
    } else {
      // 歌曲首句前奏：无前序歌词，首句无需下推，圆点自然置于首句上方舒适距离
      const line0ActualTop = lines[0].cumulativeY - fontAscender;
      dotsWorldY = line0ActualTop - margin - dotRadius;
      fullInterludeOffset = 0;
    }

    // 入场开辟阶段：前 0.40s 平滑向下推开下一行歌词 (歌词一行行 offset 进入)
    let openFraction = 1.0;
    const enterLead = Math.min(0.40, activeInterlude.gap * 0.35);
    const enterElapsed = t - activeInterlude.startTime;
    if (enterElapsed < enterLead) {
      const pe = Math.max(0, enterElapsed / enterLead);
      openFraction = pe * pe * (3 - 2 * pe);
    }

    // 退场折叠阶段：开唱前 0.35s 间距平滑归零收拢 (“追行贴上去”，平滑恢复正常句距)
    let collapseFraction = 1.0;
    const timeUntilSinging = activeInterlude.endTime - t;
    if (timeUntilSinging < exitLead) {
      const px = Math.max(0, Math.min(1, (exitLead - timeUntilSinging) / exitLead));
      collapseFraction = 1.0 - px * px * (3 - 2 * px);
    }

    currentInterludeOffset = Math.round(fullInterludeOffset * openFraction * collapseFraction);

    if (timeUntilSinging > exitLead) {
      // 间奏主阶段：相机稳健对准圆点
      if (targetIdx > 0) {
        if (enterElapsed < enterLead) {
          const pe = Math.max(0, enterElapsed / enterLead);
          const scrollFraction = pe * pe * (3 - 2 * pe);
          const prevCenter = lines[targetIdx - 1].centerY;
          focalWorldY = prevCenter + (dotsWorldY - prevCenter) * scrollFraction;
        } else {
          focalWorldY = dotsWorldY;
        }
      } else {
        focalWorldY = dotsWorldY;
      }
    } else {
      // 间奏尾声 (距开唱 0.35s ~ 0s)：相机平滑对准下一句歌词，下一句淡入并纯白先亮
      const pe = Math.max(0, Math.min(1, (exitLead - timeUntilSinging) / exitLead));
      const scrollFraction = pe * pe * (3 - 2 * pe);
      focalWorldY = dotsWorldY + (lines[targetIdx].centerY - dotsWorldY) * scrollFraction;
      isFocalPreLight = true;
      preLightFadeProgress = scrollFraction;
    }
  } else {
    // 正常歌词行播放滚动
    let curLineIdx = 0;
    for (let i = 0; i < lines.length; i++) {
      if (t >= lines[i].start) {
        curLineIdx = i;
      }
    }

    const curLine = lines[curLineIdx];
    if (t <= curLine.end) {
      focalWorldY = curLine.centerY;
      focusedLineIdx = curLineIdx;
    } else {
      // 唱完后：上一句结束，下一句立即先亮白字并平滑上滚至下一句
      const nextLine = lines[curLineIdx + 1];
      if (nextLine) {
        focusedLineIdx = curLineIdx + 1;
        isFocalPreLight = true;
        preLightFadeProgress = 1.0;
        const gap = nextLine.start - curLine.end;
        const leadDuration = Math.max(0.3, Math.min(0.8, gap));
        const fraction = Math.max(0, Math.min(1, (t - curLine.end) / leadDuration));
        const scrollFraction = 1 - Math.pow(1 - fraction, 3);
        focalWorldY = curLine.centerY + (nextLine.centerY - curLine.centerY) * scrollFraction;
      } else {
        focalWorldY = curLine.centerY;
        focusedLineIdx = curLineIdx;
      }
    }
  }

  // Apple Music 移动端光学焦点约在视口高 42% 偏上方，留给下方预读更多空间
  const focalCenterY = Math.round(layout.height * (layout.focusY ?? .42));

  const items: AppleLineRenderItem[] = [];

  for (let i = 0; i < lines.length; i++) {
    const c = lines[i];
    const effectiveCenterY = (activeInterlude && i >= activeInterlude.targetLineIndex)
      ? c.centerY + currentInterludeOffset
      : c.centerY;
    const itemCenterY = Math.round(focalCenterY + (effectiveCenterY - focalWorldY));
    const itemTopY = Math.round(itemCenterY - c.sentenceHeight / 2);

    // 剔除进入上下绝对安全保护区的句子
    if (itemCenterY < layout.height * 0.08 || itemCenterY > layout.height * 0.96) {
      continue;
    }

    const isSinging = t >= c.start && t <= c.end;
    const isTargetPreLight = isFocalPreLight && i === focusedLineIdx;

    const distPx = itemCenterY - focalCenterY;
    const distUnits = distPx / (layout.activeFontSize * 1.8);
    const absDist = Math.abs(distUnits);

    let baseAlpha = 0;
    if (isSinging) {
      baseAlpha = 1.0;
    } else if (isTargetPreLight) {
      // 间奏尾声平滑淡入先亮 (0.45 -> 1.0) 或普通跨行直接 1.0
      baseAlpha = 0.45 + (1.0 - 0.45) * preLightFadeProgress;
    } else if (distUnits < 0) {
      // 上方已唱句子：低调退场
      baseAlpha = Math.max(0, 0.36 * (1 - (absDist - 0.5) / 1.8));
    } else {
      // 下方即将唱的句子：适度清晰方便伴唱预读，自然延伸至视口底部
      baseAlpha = 0.45;
    }

    // 叠加视口边缘平滑羽化衰减，彻底避免靠近边界时顶格
    const edgeFade = computeAppleEdgeFade(itemCenterY, layout.height);
    const alpha = Number((baseAlpha * edgeFade * introFade).toFixed(3));
    if (alpha <= 0.02) {
      continue;
    }

    // 焦点微缩放层级（非焦点句轻微缩放 0.88 ~ 0.96，焦点句 1.0）
    let scale = Math.max(0.88, 1.0 - absDist * 0.05);
    if (isSinging) {
      scale = 1.0;
    } else if (isTargetPreLight) {
      scale = 0.94 + 0.06 * preLightFadeProgress;
    }

    const spansWithProgress = c.spans.map(span => {
      const h = highlightState(span, t, 'sweep');
      return { span, progress: h.progress, active: h.active };
    });

    items.push({
      compiled: c,
      y: itemTopY,
      scale,
      alpha,
      isActive: isSinging, // 仅在正式开唱后激活卡拉OK高亮扫光，待唱时显示完整白色底字
      spansWithProgress,
    });
  }

  // 3. 计算 Apple 伴唱起跑 3 拍小圆点行 (Apple Music Interlude Countdown Dots)
  // 仅在伴奏活跃且圆点尚未完全淡出 (t < activeInterlude.endTime - exitDotsDone) 期间渲染
  let countIn: AppleCountInState | null = null;

  if (activeInterlude) {
    const timeUntilSinging = activeInterlude.endTime - t;
    // 距开唱 0.20s 时圆点已完全消失，绝不在开唱前与文字撞车
    if (timeUntilSinging > exitDotsDone && !(introEnd > 0 && t < introEnd)) {
      const dotRadius = Math.max(8, Math.round(layout.activeFontSize * 0.26));
      const dotSpacing = Math.round(dotRadius * 3.6);
      const dotsStartX = layout.startX + dotRadius;
      const dotsScreenY = Math.round(focalCenterY + (dotsWorldY - focalWorldY));

      if (dotsScreenY >= layout.height * 0.08 && dotsScreenY <= layout.height * 0.96) {
        // 倒计时间隔与起跑时机
        const countInLead = Math.min(2.7, Math.max(1.8, activeInterlude.gap * 0.75));
        const countInStart = activeInterlude.endTime - countInLead;
        const beatDuration = countInLead / 3;

        // 入场淡入
        let entranceFade = 1.0;
        if (t < activeInterlude.startTime + 0.25) {
          entranceFade = Math.min(1, Math.max(0, (t - activeInterlude.startTime) / 0.25));
        }

        // 退场淡出：在开唱前 [exitLead, exitDotsDone] (0.35s ~ 0.10s) 区间完全渐隐消失 (1.0 -> 0.0)
        let exitFade = 1.0;
        let exitProgress = 0;
        if (timeUntilSinging < exitLead) {
          exitProgress = Math.max(0, Math.min(1, (exitLead - timeUntilSinging) / (exitLead - exitDotsDone)));
          exitFade = 1.0 - exitProgress * exitProgress * (3 - 2 * exitProgress);
        }

        const edgeFade = computeAppleEdgeFade(dotsScreenY, layout.height);
        const overallAlpha = Number((entranceFade * exitFade * edgeFade * introFade).toFixed(3));

        if (overallAlpha > 0.01) {
          const fillDuration = Math.min(0.35, beatDuration * 0.75);

          const dots: [AppleCountInDot, AppleCountInDot, AppleCountInDot] = [0, 1, 2].map(dIdx => {
            const beatTime = countInStart + dIdx * beatDuration;
            const dt = t - beatTime;

            let fillProgress = 0.0;
            let dotScale = 1.0;
            let dotAlpha = 0.28;
            let isLit = false;

            if (t >= beatTime) {
              isLit = true;
              if (dt < fillDuration) {
                // 白色过光：按时间平滑充盈 (0.28 -> 1.0)
                const p = Math.max(0, Math.min(1, dt / fillDuration));
                fillProgress = p * p * (3 - 2 * p);
                dotAlpha = 0.28 + (1.0 - 0.28) * fillProgress;
              } else {
                fillProgress = 1.0;
                dotAlpha = 1.0;
              }
            }

            // 退出缩放动画：开唱前平滑缩小 (1.0 -> 0.70)
            if (exitProgress > 0) {
              dotScale = Number((1.0 - 0.30 * exitProgress).toFixed(3));
            }

            return {
              index: dIdx,
              x: dotsStartX + dIdx * dotSpacing,
              y: dotsScreenY,
              radius: dotRadius,
              lit: isLit,
              scale: dotScale,
              alpha: Number(dotAlpha.toFixed(3)),
              glowAlpha: 0,
            };
          }) as unknown as [AppleCountInDot, AppleCountInDot, AppleCountInDot];

          countIn = {
            targetLineIndex: activeInterlude.targetLineIndex,
            dots,
            overallAlpha,
          };
        }
      }
    }
  }

  return {
    items,
    currentScrollY: focalCenterY - focalWorldY,
    countIn,
  };
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16);
    const g = parseInt(clean[1] + clean[1], 16);
    const b = parseInt(clean[2] + clean[2], 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  if (clean.length >= 6) {
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  return `rgba(255,255,255,${alpha})`;
}

export function paintAppleScrollCanvas(
  ctx: CanvasRenderingContext2D,
  layout: AppleScrollCompiled,
  t: number,
  fontFamily: string
): void {
  const { items, countIn } = appleScrollStateAt(layout, t);

  // 1. 绘制焦点区域轻微的环境氛围晕光 (Ambient Glow)
  if (typeof ctx.createRadialGradient === 'function') {
    ctx.save();
    const focalCenterY = Math.round(layout.height * (layout.focusY ?? .42));
    const glow = ctx.createRadialGradient(
      layout.width * 0.38,
      focalCenterY,
      layout.width * 0.05,
      layout.width * 0.38,
      focalCenterY,
      layout.width * 0.65
    );
    glow.addColorStop(0, hexToRgba(layout.palette.accent, 0.10));
    glow.addColorStop(0.5, hexToRgba(layout.palette.accent, 0.03));
    glow.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, layout.width, layout.height);
    ctx.restore();
  }

  // 2. 绘制歌词句子
  for (const item of items) {
    const c = item.compiled;
    ctx.save();
    ctx.globalAlpha = item.alpha;
    ctx.font = `700 ${Math.round(c.fontSize * item.scale)}px ${fontFamily}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    // 绘制底色文字（所有子行）
    ctx.fillStyle = layout.palette.foreground;
    for (const row of c.rows) {
      ctx.fillText(row.text, row.x, item.y + row.yOffset);
    }

    // 焦点行绘制卡拉OK高亮扫光
    if (item.isActive) {
      for (const sp of item.spansWithProgress) {
        if (sp.progress <= 0) continue;
        const targetRow = c.rows[sp.span.row] || c.rows[0];
        ctx.save();
        ctx.beginPath();
        ctx.rect(
          sp.span.x,
          item.y + sp.span.top,
          sp.span.width * sp.progress,
          sp.span.height
        );
        ctx.clip();
        ctx.fillStyle = layout.palette.accent;
        ctx.fillText(targetRow.text, targetRow.x, item.y + targetRow.yOffset);
        ctx.restore();
      }
    }
    ctx.restore();
  }

  // 3. 绘制 Apple 伴唱起跑 3 拍小圆点 (Count-in Dots)
  if (countIn && countIn.overallAlpha > 0.01) {
    ctx.save();
    ctx.globalAlpha = countIn.overallAlpha;
    for (const dot of countIn.dots) {
      ctx.save();
      ctx.translate(dot.x, dot.y);
      ctx.scale(dot.scale, dot.scale);

      ctx.beginPath();
      ctx.arc(0, 0, dot.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, 255, 255, ${dot.alpha})`;
      ctx.fill();

      ctx.restore();
    }
    ctx.restore();
  }
}
