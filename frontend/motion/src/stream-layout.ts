import { compileHighlightSpans, highlightState, type HighlightSpan } from './karaoke';
import type { Project, Line } from './model';

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
  align: 'left' | 'right';
  previewStart: number;
  activeStart: number;
  activeEnd: number;
  stayEnd: number;
  spans: HighlightSpan[];
}

export interface KtvDualCompiled {
  aspect: '16:9';
  width: number;
  height: number;
  uniformFontSize: number;
  lines: KtvLineCompiled[];
  palette: StreamPalette;
}

export function compileKtvDualLayout(
  project: Project,
  width: number,
  height: number,
  measure: TextMeasure,
  palette: StreamPalette
): KtvDualCompiled {
  const lines = project.lines || [];
  const maxWidth = Math.round(width * 0.65);
  const baseFontSize = Math.round(width * 0.038); // ~72px on 1920

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

  const yUpper = Math.round(height * 0.76);
  const yLower = Math.round(height * 0.88);
  const leftX = Math.round(width * 0.16);
  const rightBoundaryX = Math.round(width * 0.84);

  const compiledLines: KtvLineCompiled[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const isUpper = i % 2 === 0;
    const y = isUpper ? yUpper : yLower;
    const m = measure(line.text, uniformFontSize, 700);
    const lineWidth = m.width;
    // 上行靠左，下行靠右 (从右边界往左算起)
    const x = isUpper ? leftX : Math.max(leftX, rightBoundaryX - lineWidth);
    const align: 'left' | 'right' = isUpper ? 'left' : 'right';

    // ── 状态生命周期计算 ──
    // 严格槽位衔接：同槽位上一句驻留结束时间 = 同槽位下一句预读开始时间
    let previewStart = 0;
    if (i === 0) {
      previewStart = Math.max(0, line.start - 2.5);
    } else if (i === 1) {
      previewStart = Math.max(0, lines[0].start);
    } else {
      // 距离本句开唱前 2.5 秒，且不早于同槽位前一句 (i-2) 唱完时间
      previewStart = Math.max(lines[i - 2].end, line.start - 2.5);
    }
    const activeStart = line.start;
    const activeEnd = Math.max(activeStart + 0.5, line.end);

    // 唱完常驻：保持高亮，直到同槽位下一句 (i+2) 进入 preview
    let stayEnd = activeEnd + 2.5;
    if (i + 2 < lines.length) {
      stayEnd = Math.max(activeEnd, lines[i + 2].start - 2.5);
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

  return {
    aspect: '16:9',
    width,
    height,
    uniformFontSize,
    lines: compiledLines,
    palette,
  };
}

export interface KtvLineRenderState {
  compiled: KtvLineCompiled;
  phase: 'preview' | 'active' | 'stay' | 'hidden';
  dimColor: string;
  sungColor: string;
  spansWithProgress: { span: HighlightSpan; progress: number; active: boolean }[];
}

export function ktvDualStateAt(
  layout: KtvDualCompiled,
  t: number
): { upper: KtvLineRenderState | null; lower: KtvLineRenderState | null } {
  let upper: KtvLineRenderState | null = null;
  let lower: KtvLineRenderState | null = null;

  for (const c of layout.lines) {
    if (t < c.previewStart || (c.lineIndex + 2 < layout.lines.length ? t >= c.stayEnd : t > c.stayEnd)) {
      continue;
    }
    let phase: 'preview' | 'active' | 'stay' = 'stay';
    if (t < c.activeStart) {
      phase = 'preview';
    } else if (t <= c.activeEnd) {
      phase = 'active';
    } else {
      phase = 'stay';
    }

    const spansWithProgress = c.spans.map(span => {
      const h = highlightState(span, t, 'sweep');
      return { span, progress: h.progress, active: h.active };
    });

    const state: KtvLineRenderState = {
      compiled: c,
      phase,
      dimColor: layout.palette.muted,
      sungColor: layout.palette.accent,
      spansWithProgress,
    };

    if (c.isUpper) {
      upper = state;
    } else {
      lower = state;
    }
  }

  return { upper, lower };
}

export function paintKtvDualCanvas(
  ctx: CanvasRenderingContext2D,
  layout: KtvDualCompiled,
  t: number,
  fontFamily: string
): void {
  const { upper, lower } = ktvDualStateAt(layout, t);
  const slots = [upper, lower].filter((s): s is KtvLineRenderState => Boolean(s));

  for (const slot of slots) {
    const c = slot.compiled;
    ctx.save();
    ctx.font = `700 ${c.fontSize}px ${fontFamily}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    if (slot.phase === 'preview') {
      // 暗色预览
      ctx.fillStyle = slot.dimColor;
      ctx.fillText(c.line.text, c.x, c.y);
    } else if (slot.phase === 'stay') {
      // 唱完高亮常驻
      ctx.fillStyle = slot.sungColor;
      ctx.fillText(c.line.text, c.x, c.y);
    } else {
      // 正在演唱扫光：先画未唱底色，再用剪裁绘制已扫光文字
      ctx.fillStyle = slot.dimColor;
      ctx.fillText(c.line.text, c.x, c.y);

      for (const item of slot.spansWithProgress) {
        if (item.progress <= 0) continue;
        ctx.save();
        ctx.beginPath();
        ctx.rect(
          item.span.x,
          item.span.top,
          item.span.width * item.progress,
          item.span.height
        );
        ctx.clip();
        ctx.fillStyle = slot.sungColor;
        ctx.fillText(c.line.text, c.x, c.y);
        ctx.restore();
      }
    }
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// 2. Apple Music 灵动流式歌词模型 (9:16 垂直居中滚动聚焦)
// ---------------------------------------------------------------------------

export interface AppleLineCompiled {
  lineIndex: number;
  line: Line;
  text: string;
  width: number;
  fontSize: number;
  start: number;
  end: number;
  spans: HighlightSpan[];
}

export interface AppleScrollCompiled {
  aspect: '9:16';
  width: number;
  height: number;
  activeFontSize: number;
  contextFontSize: number;
  lineGap: number;
  lines: AppleLineCompiled[];
  palette: StreamPalette;
}

export function compileAppleScrollLayout(
  project: Project,
  width: number,
  height: number,
  measure: TextMeasure,
  palette: StreamPalette
): AppleScrollCompiled {
  const lines = project.lines || [];
  const activeFontSize = Math.round(width * 0.052); // ~56px on 1080
  const contextFontSize = Math.round(activeFontSize * 0.72); // ~40px
  const lineGap = Math.round(activeFontSize * 1.55);

  const compiledLines: AppleLineCompiled[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = measure(line.text, activeFontSize, 700);
    // 水平居中或者靠左边距
    const startX = Math.round(width * 0.12);
    const wordList = line.words || [];
    const indices = wordList.map((_, idx) => idx);
    const spans = compileHighlightSpans(
      wordList,
      indices,
      [{ text: line.text, x: startX, y: 0 }],
      activeFontSize,
      700,
      measure
    );

    compiledLines.push({
      lineIndex: i,
      line,
      text: line.text,
      width: m.width,
      fontSize: activeFontSize,
      start: line.start,
      end: line.end,
      spans,
    });
  }

  return {
    aspect: '9:16',
    width,
    height,
    activeFontSize,
    contextFontSize,
    lineGap,
    lines: compiledLines,
    palette,
  };
}

export interface AppleLineRenderItem {
  compiled: AppleLineCompiled;
  y: number;
  scale: number;
  alpha: number;
  isActive: boolean;
  spansWithProgress: { span: HighlightSpan; progress: number; active: boolean }[];
}

export function appleScrollStateAt(
  layout: AppleScrollCompiled,
  t: number
): {
  items: AppleLineRenderItem[];
  currentScrollY: number;
} {
  const lines = layout.lines;
  if (!lines.length) return { items: [], currentScrollY: 0 };

  // 1. 确定当前活跃焦点行
  let activeIndex = 0;
  for (let i = 0; i < lines.length; i++) {
    if (t >= lines[i].start) {
      activeIndex = i;
    }
  }

  // 2. 平滑过渡因子 (如果正在接近下一行，适度向上平移)
  const currentLine = lines[activeIndex];
  const nextLine = lines[activeIndex + 1];
  let scrollFraction = 0.0;
  if (nextLine && t > currentLine.end) {
    const leadDuration = Math.max(0.3, Math.min(1.5, nextLine.start - currentLine.end));
    scrollFraction = Math.max(0, Math.min(1, (t - currentLine.end) / leadDuration));
    // 平滑缓动 (ease-out cubic)
    scrollFraction = 1 - Math.pow(1 - scrollFraction, 3);
  }

  const focalCenterY = Math.round(layout.height * 0.45);
  const continuousIndex = activeIndex + scrollFraction;

  const items: AppleLineRenderItem[] = [];

  for (let i = 0; i < lines.length; i++) {
    const dist = i - continuousIndex;
    // 距离焦点超过 4 行的不在视口渲染
    if (Math.abs(dist) > 4.5) continue;

    const y = Math.round(focalCenterY + dist * layout.lineGap);
    const isActive = Math.abs(dist) < 0.5;

    // 距离中心越远，字体越小、越暗
    const scale = isActive ? 1.0 : Math.max(0.75, 1.0 - Math.abs(dist) * 0.08);
    const alpha = isActive
      ? 1.0
      : Math.max(0.18, 0.72 - Math.abs(dist) * 0.16);

    const c = lines[i];
    const spansWithProgress = c.spans.map(span => {
      const h = highlightState(span, t, 'sweep');
      return { span, progress: h.progress, active: h.active };
    });

    items.push({
      compiled: c,
      y,
      scale,
      alpha,
      isActive,
      spansWithProgress,
    });
  }

  return {
    items,
    currentScrollY: focalCenterY - continuousIndex * layout.lineGap,
  };
}

export function paintAppleScrollCanvas(
  ctx: CanvasRenderingContext2D,
  layout: AppleScrollCompiled,
  t: number,
  fontFamily: string
): void {
  const { items } = appleScrollStateAt(layout, t);
  const startX = Math.round(layout.width * 0.12);

  for (const item of items) {
    const c = item.compiled;
    ctx.save();
    ctx.globalAlpha = item.alpha;
    ctx.font = `700 ${Math.round(c.fontSize * item.scale)}px ${fontFamily}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    if (!item.isActive) {
      // 非焦点行：半透明暗色
      ctx.fillStyle = layout.palette.foreground;
      ctx.fillText(c.text, startX, item.y);
    } else {
      // 焦点行：先画待唱底色，再裁剪画高亮扫光
      ctx.fillStyle = layout.palette.foreground;
      ctx.fillText(c.text, startX, item.y);

      for (const sp of item.spansWithProgress) {
        if (sp.progress <= 0) continue;
        ctx.save();
        ctx.beginPath();
        ctx.rect(
          sp.span.x,
          item.y - Math.round(c.fontSize * 0.9),
          sp.span.width * sp.progress,
          Math.round(c.fontSize * 1.3)
        );
        ctx.clip();
        ctx.fillStyle = layout.palette.accent;
        ctx.fillText(c.text, startX, item.y);
        ctx.restore();
      }
    }
    ctx.restore();
  }
}
