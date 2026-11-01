/**
 * Cyber Neon (赛博霓虹) 动态视觉排版引擎
 * 模拟 137s 经典暗室物理霓虹灯管质感：高反差深色底、字芯高热白光、外层通透 Bloom 辉光、
 * 通电瞬间微频闪 (Ignition Flicker) 与重音鼓点脉冲 (Beat Pulse)。
 */

import { compileHighlightSpans, highlightState, type HighlightSpan } from './karaoke';
import { wrapSentenceToRows, type StreamPalette } from './stream-layout';
import type { Line, Project } from './model';

export type TextMeasure = (text: string, size: number, weight: number) => {
  width: number;
  ascent: number;
  descent: number;
};

export interface NeonRowCompiled {
  text: string;
  x: number;
  yOffset: number;
  width: number;
}

export interface NeonLineCompiled {
  lineIndex: number;
  line: Line;
  text: string;
  rows: NeonRowCompiled[];
  sentenceHeight: number;
  centerY: number;
  width: number;
  fontSize: number;
  start: number;
  end: number;
  spans: HighlightSpan[];
}

export interface NeonCompiled {
  width: number;
  height: number;
  aspect: '16:9' | '9:16';
  fontSize: number;
  rowLineHeight: number;
  lines: NeonLineCompiled[];
  palette: StreamPalette;
  glowIntensity: number;
  flickerEnabled: boolean;
}

export interface NeonActiveSpan {
  span: HighlightSpan;
  progress: number;
  active: boolean;
}

export interface NeonLineRenderState {
  compiled: NeonLineCompiled;
  y: number;
  alpha: number;
  scale: number;
  isCurrent: boolean;
  flicker: number;
  spansWithProgress: NeonActiveSpan[];
}

export interface NeonRenderState {
  current: NeonLineRenderState | null;
  previous: NeonLineRenderState | null;
  next: NeonLineRenderState | null;
  pulse: number;
  flicker: number;
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

/**
 * 编译整首歌曲的霓虹歌词布局（居中聚焦与长句自适应折行）
 */
export function compileNeonLayout(
  project: Project,
  width: number,
  height: number,
  measure: TextMeasure,
  palette: StreamPalette,
  options?: { font_scale?: number; glow_intensity?: number; flicker?: boolean }
): NeonCompiled {
  const lines = project.lines || [];
  const isPortrait = height > width;

  // 霓虹大字视觉尺寸：竖屏取宽度 6.8%，横屏取高度 7.5%
  const baseFontSize = isPortrait
    ? Math.round(width * 0.068)
    : Math.round(height * 0.075);
  const fontSize = Math.round(baseFontSize * (options?.font_scale || 1));
  const rowLineHeight = Math.round(fontSize * 1.38);

  // 左右边距：给屏幕两侧各留出约 10% 的呼吸区域
  const marginX = Math.round(width * 0.1);
  const maxRowWidth = width - marginX * 2;

  const compiledLines: NeonLineCompiled[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const textRows = wrapSentenceToRows(line.text, fontSize, 800, maxRowWidth, measure);

    // 居中排版：计算每一行文本在屏幕中央的水平起始坐标
    const rows: NeonRowCompiled[] = textRows.map((text, rIdx) => {
      const rowMetrics = measure(text, fontSize, 800);
      const rowX = Math.round((width - rowMetrics.width) / 2);
      return {
        text,
        x: rowX,
        yOffset: rIdx * rowLineHeight,
        width: rowMetrics.width,
      };
    });

    const sentenceHeight = (textRows.length - 1) * rowLineHeight;
    const centerY = sentenceHeight / 2;

    const wordList = line.words || [];
    const indices = wordList.map((_, idx) => idx);
    const spans = compileHighlightSpans(
      wordList,
      indices,
      rows.map(r => ({ text: r.text, x: r.x, y: r.yOffset })),
      fontSize,
      800,
      measure
    );

    const m = measure(line.text, fontSize, 800);

    compiledLines.push({
      lineIndex: i,
      line,
      text: line.text,
      rows,
      sentenceHeight,
      centerY,
      width: m.width,
      fontSize,
      start: line.start,
      end: line.end,
      spans,
    });
  }

  return {
    width,
    height,
    aspect: isPortrait ? '9:16' : '16:9',
    fontSize,
    rowLineHeight,
    lines: compiledLines,
    palette,
    glowIntensity: options?.glow_intensity ?? 1,
    flickerEnabled: options?.flicker ?? true,
  };
}

/**
 * 计算霓虹灯管通电瞬间的点火频闪 (Gas Ignition Flicker)
 */
export function computeNeonFlicker(dt: number, enabled: boolean): number {
  if (!enabled || dt < 0 || dt > 0.26) return 1.0;
  // 0 ~ 0.26s 内模拟微弱电火花跳跃
  if (dt < 0.04) return 0.25;
  if (dt < 0.08) return 1.0;
  if (dt < 0.12) return 0.35;
  if (dt < 0.16) return 0.95;
  if (dt < 0.20) return 0.55;
  return 1.0;
}

/**
 * 获取当前时间点 t 的霓虹动态渲染状态
 */
export function neonStateAt(layout: NeonCompiled, t: number, beatVal = 0): NeonRenderState {
  const lines = layout.lines;
  if (!lines.length) {
    return { current: null, previous: null, next: null, pulse: 1, flicker: 1 };
  }

  // 1. 查找当前活跃行
  let activeIdx = lines.findIndex(l => t >= l.start && t <= l.end);
  if (activeIdx === -1) {
    // 处于间奏或句隙：寻找下一句或上一句
    const nextIdx = lines.findIndex(l => l.start > t);
    activeIdx = nextIdx !== -1 ? Math.max(0, nextIdx - 1) : lines.length - 1;
  }

  const activeLine = lines[activeIdx];
  const dt = t - activeLine.start;
  const flicker = computeNeonFlicker(dt, layout.flickerEnabled);
  const pulse = 1.0 + Math.max(0, beatVal) * 0.35;

  const centerY = Math.round(layout.height * 0.5);
  const lineSpacing = Math.round(layout.fontSize * 2.3);

  // 活跃行状态
  const activeSpans: NeonActiveSpan[] = activeLine.spans.map(sp => {
    const st = highlightState(sp, t, 'sweep');
    return { span: sp, progress: st.progress, active: st.active };
  });

  const current: NeonLineRenderState = {
    compiled: activeLine,
    y: centerY - activeLine.centerY,
    alpha: 1.0,
    scale: 1.0 + (pulse - 1) * 0.06,
    isCurrent: true,
    flicker,
    spansWithProgress: activeSpans,
  };

  // 上一句 (淡出至上方)
  let previous: NeonLineRenderState | null = null;
  if (activeIdx > 0) {
    const prevLine = lines[activeIdx - 1];
    previous = {
      compiled: prevLine,
      y: centerY - activeLine.centerY - lineSpacing - prevLine.sentenceHeight,
      alpha: 0.22,
      scale: 0.88,
      isCurrent: false,
      flicker: 1.0,
      spansWithProgress: [],
    };
  }

  // 下一句 (淡入预热于下方)
  let next: NeonLineRenderState | null = null;
  if (activeIdx < lines.length - 1) {
    const nextLine = lines[activeIdx + 1];
    next = {
      compiled: nextLine,
      y: centerY + activeLine.centerY + lineSpacing,
      alpha: 0.28,
      scale: 0.90,
      isCurrent: false,
      flicker: 1.0,
      spansWithProgress: [],
    };
  }

  return { current, previous, next, pulse, flicker };
}

/**
 * 绘制完整的 Cyber Neon 霓虹画面至 Canvas 2D
 */
export function paintNeonCanvas(
  ctx: CanvasRenderingContext2D,
  layout: NeonCompiled,
  t: number,
  fontFamily: string,
  beatVal = 0
): void {
  const { current, previous, next, pulse, flicker } = neonStateAt(layout, t, beatVal);

  ctx.save();

  // 1. 绘制暗室纵深环境氛围辉光 (Ambient Room Glow)
  if (typeof ctx.createRadialGradient === 'function') {
    const glowY = current ? current.y : layout.height * 0.5;
    const ambient = ctx.createRadialGradient(
      layout.width * 0.5,
      glowY,
      layout.width * 0.06,
      layout.width * 0.5,
      glowY,
      layout.width * 0.65
    );
    const haloIntensity = (0.16 * pulse * flicker * layout.glowIntensity);
    ambient.addColorStop(0, hexToRgba(layout.palette.accent, Math.min(0.35, haloIntensity)));
    ambient.addColorStop(0.45, hexToRgba(layout.palette.accent, Math.min(0.12, haloIntensity * 0.35)));
    ambient.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = ambient;
    ctx.fillRect(0, 0, layout.width, layout.height);
  }

  // 2. 绘制上下邻句（冷色熄灭灯管 / 未通电状态）
  const neighborSlots = [previous, next].filter((s): s is NeonLineRenderState => Boolean(s));
  for (const slot of neighborSlots) {
    const c = slot.compiled;
    ctx.save();
    ctx.globalAlpha = slot.alpha;
    ctx.font = `800 ${Math.round(c.fontSize * slot.scale)}px ${fontFamily}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    // 冷态灯管：微弱灰白半透外壳
    ctx.fillStyle = hexToRgba(layout.palette.foreground, 0.35);
    for (const row of c.rows) {
      ctx.fillText(row.text, row.x, slot.y + row.yOffset);
    }
    ctx.restore();
  }

  // 3. 绘制当前活跃行（高能通电霓虹灯管）
  if (current) {
    const c = current.compiled;
    ctx.save();
    ctx.font = `800 ${Math.round(c.fontSize * current.scale)}px ${fontFamily}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    // 3.1 绘制整句的未唱底色：深暗待激发的灯管形态
    ctx.fillStyle = hexToRgba(layout.palette.foreground, 0.25);
    for (const row of c.rows) {
      ctx.fillText(row.text, row.x, current.y + row.yOffset);
    }

    // 3.2 绘制正在演唱 / 已唱过的逐字霓虹激活动效 (Neon Ignite Sweep)
    for (const sp of current.spansWithProgress) {
      if (sp.progress <= 0) continue;
      const targetRow = c.rows[sp.span.row] || c.rows[0];

      ctx.save();
      ctx.beginPath();
      ctx.rect(
        sp.span.x,
        current.y + sp.span.top,
        sp.span.width * sp.progress,
        sp.span.height
      );
      ctx.clip();

      const glowRadius = Math.round(26 * pulse * current.flicker * layout.glowIntensity);

      // Pass 1: 外部宽广漫反射辉光 (Outer Diffuse Bloom)
      ctx.shadowColor = layout.palette.accent;
      ctx.shadowBlur = glowRadius;
      ctx.fillStyle = hexToRgba(layout.palette.accent, 0.85 * current.flicker);
      ctx.fillText(targetRow.text, targetRow.x, current.y + targetRow.yOffset);

      // Pass 2: 内部灯管强光晕 (Inner Neon Tube Halo)
      ctx.shadowBlur = Math.round(glowRadius * 0.45);
      ctx.fillStyle = layout.palette.accent;
      ctx.fillText(targetRow.text, targetRow.x, current.y + targetRow.yOffset);

      // Pass 3: 灯管中心高热纯白放电芯 (High-heat Gas Discharge Core)
      ctx.shadowBlur = 0;
      ctx.fillStyle = hexToRgba('#ffffff', 0.95 * current.flicker);
      ctx.fillText(targetRow.text, targetRow.x, current.y + targetRow.yOffset);

      ctx.restore();
    }

    ctx.restore();
  }

  ctx.restore();
}
