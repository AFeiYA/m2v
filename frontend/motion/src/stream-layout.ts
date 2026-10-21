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
}

export interface AppleScrollCompiled {
  aspect: '9:16';
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
  // Apple Music 移动端规范：左边距安全边距约 8%，给歌词留出 84% 舒适阅读宽度
  const startX = Math.round(width * 0.08);
  const maxWidth = width - startX * 2;
  const activeFontSize = Math.round(width * 0.052); // ~56px on 1080w
  const contextFontSize = Math.round(activeFontSize * 0.72);
  const rowLineHeight = Math.round(activeFontSize * 1.34);
  const paragraphGap = Math.round(activeFontSize * 1.65);

  const compiledLines: AppleLineCompiled[] = [];
  let cumulativeY = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
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
    });

    cumulativeY += sentenceHeight + paragraphGap;
  }

  return {
    aspect: '9:16',
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
    palette,
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

  // 2. 平滑过渡因子 (如果正在接近下一行，平滑上滚)
  const currentLine = lines[activeIndex];
  const nextLine = lines[activeIndex + 1];
  let scrollFraction = 0.0;
  if (nextLine && t > currentLine.end) {
    const leadDuration = Math.max(0.3, Math.min(1.5, nextLine.start - currentLine.end));
    scrollFraction = Math.max(0, Math.min(1, (t - currentLine.end) / leadDuration));
    // 平滑缓动 (ease-out cubic)
    scrollFraction = 1 - Math.pow(1 - scrollFraction, 3);
  }

  // Apple Music 移动端光学焦点约在视口高 44% 偏上方，留给下方预读更多空间
  const focalCenterY = Math.round(layout.height * 0.44);
  const focalWorldY = currentLine.centerY + (nextLine ? (nextLine.centerY - currentLine.centerY) * scrollFraction : 0);

  const items: AppleLineRenderItem[] = [];

  for (let i = 0; i < lines.length; i++) {
    const c = lines[i];
    // 当前句子的视觉中心
    const itemCenterY = Math.round(focalCenterY + (c.centerY - focalWorldY));
    // 当前句子首行基线
    const itemTopY = Math.round(itemCenterY - c.sentenceHeight / 2);

    // 剔除完全超出可视区域外的句子
    if (itemTopY + c.sentenceHeight < -200 || itemTopY > layout.height + 250) {
      continue;
    }

    const distFromFocus = (c.centerY - focalWorldY) / Math.max(1, layout.paragraphGap);
    const isActive = i === activeIndex;

    const scale = isActive ? 1.0 : Math.max(0.85, 1.0 - Math.min(3, Math.abs(distFromFocus)) * 0.05);
    const alpha = isActive
      ? 1.0
      : Math.max(0.2, 0.6 - Math.min(3, Math.abs(distFromFocus)) * 0.14);

    const spansWithProgress = c.spans.map(span => {
      const h = highlightState(span, t, 'sweep');
      return { span, progress: h.progress, active: h.active };
    });

    items.push({
      compiled: c,
      y: itemTopY,
      scale,
      alpha,
      isActive,
      spansWithProgress,
    });
  }

  return {
    items,
    currentScrollY: focalCenterY - focalWorldY,
  };
}

export function paintAppleScrollCanvas(
  ctx: CanvasRenderingContext2D,
  layout: AppleScrollCompiled,
  t: number,
  fontFamily: string
): void {
  const { items } = appleScrollStateAt(layout, t);

  for (const item of items) {
    const c = item.compiled;
    ctx.save();
    ctx.globalAlpha = item.alpha;
    ctx.font = `700 ${Math.round(c.fontSize * item.scale)}px ${fontFamily}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    // 1. 绘制底色文字（所有子行）
    ctx.fillStyle = layout.palette.foreground;
    for (const row of c.rows) {
      ctx.fillText(row.text, row.x, item.y + row.yOffset);
    }

    // 2. 焦点行绘制卡拉OK高亮扫光
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
}
