import type { Line, Project, Word } from './model';

export interface SlotState {
  line: Line;
  lineIndex: number;
  isSinging: boolean;
  isUpcoming: boolean;
  isPast: boolean;
  opacity: number;
  timeUntilStart: number;
}

export const BOKEH_LIGHTS = [
  { x: 220, y: 180, size: 140, color: 'rgba(220, 38, 38, 0.28)', pulseSpeed: 0.04 },
  { x: 1700, y: 220, size: 160, color: 'rgba(16, 185, 129, 0.24)', pulseSpeed: 0.035 },
  { x: 960, y: 240, size: 220, color: 'rgba(245, 158, 11, 0.25)', pulseSpeed: 0.05 },
  { x: 380, y: 520, size: 180, color: 'rgba(245, 158, 11, 0.22)', pulseSpeed: 0.045 },
  { x: 1540, y: 560, size: 190, color: 'rgba(220, 38, 38, 0.26)', pulseSpeed: 0.038 },
  { x: 180, y: 840, size: 150, color: 'rgba(16, 185, 129, 0.26)', pulseSpeed: 0.04 },
  { x: 1740, y: 860, size: 160, color: 'rgba(245, 158, 11, 0.28)', pulseSpeed: 0.048 },
  { x: 620, y: 150, size: 130, color: 'rgba(254, 240, 138, 0.3)', pulseSpeed: 0.055 },
  { x: 1300, y: 160, size: 130, color: 'rgba(254, 240, 138, 0.3)', pulseSpeed: 0.052 },
  { x: 820, y: 780, size: 170, color: 'rgba(220, 38, 38, 0.22)', pulseSpeed: 0.042 },
  { x: 1100, y: 800, size: 170, color: 'rgba(16, 185, 129, 0.24)', pulseSpeed: 0.046 },
];

export const SNOW_FLAKES = Array.from({ length: 75 }, (_, i) => ({
  id: i,
  x: (i * 179) % 1920,
  speed: 1.0 + ((i * 31) % 25) / 10,
  size: 2.2 + ((i * 17) % 6),
  swayAmp: 16 + ((i * 13) % 24),
  swaySpeed: 0.02 + ((i * 11) % 20) / 450,
  opacity: 0.35 + ((i * 23) % 55) / 100,
}));

export function getKtvSlotState(slot: 0 | 1, lines: Line[], currentTime: number): SlotState | null {
  const candidates: Array<{ line: Line; index: number }> = [];
  for (let i = 0; i < lines.length; i++) {
    if (i % 2 === slot) {
      candidates.push({ line: lines[i], index: i });
    }
  }

  for (let k = 0; k < candidates.length; k++) {
    const { line, index } = candidates[k];
    const prev = k > 0 ? candidates[k - 1].line : null;

    let appearTime = 0;
    if (prev) {
      const gap = line.start - prev.end;
      if (gap > 4.0) {
        appearTime = line.start - 2.8;
      } else {
        appearTime = prev.end + 0.25;
      }
    } else {
      appearTime = 0.0;
    }

    const leaveTime = line.end + 0.45;

    if (currentTime >= appearTime && currentTime <= leaveTime) {
      const isSinging = currentTime >= line.start && currentTime <= line.end;
      const isUpcoming = currentTime < line.start;
      const isPast = currentTime > line.end;
      const fadeIn = Math.min(1.0, Math.max(0.0, (currentTime - appearTime) / 0.35));
      const timeUntilStart = Math.max(0, line.start - currentTime);

      return {
        line,
        lineIndex: index,
        isSinging,
        isUpcoming,
        isPast,
        opacity: fadeIn,
        timeUntilStart,
      };
    }
  }

  return null;
}

export function getLineWords(line: Line): Word[] {
  if (line.words && line.words.length > 0) {
    return line.words;
  }
  const tokens = line.text.split(/(\s+)/).filter(Boolean);
  const dur = Math.max(0.1, line.end - line.start);
  const step = dur / Math.max(1, tokens.length);
  return tokens.map((w, idx) => ({
    word: w,
    start: line.start + idx * step,
    end: line.start + (idx + 1) * step,
  }));
}

export function getKtvSectionInfo(
  sections: { name: string; start: number; end: number }[] | undefined,
  lines: Pick<Line, 'start' | 'end' | 'section'>[],
  currentTime: number,
  isChristmas: boolean
): { currentSection: string; sectionIcon: string } {
  let currentSection = 'Intro';
  if (sections && sections.length > 0) {
    for (const s of sections) {
      if (currentTime >= s.start - 0.2) {
        currentSection = s.name.replace(/^\[|\]$/g, '').trim();
      }
    }
  } else {
    const activeLine = lines.find(l => currentTime >= l.start - 0.5 && currentTime <= l.end + 0.5);
    if (activeLine?.section) {
      currentSection = activeLine.section.replace(/^\[|\]$/g, '').trim();
    }
  }

  const sLower = currentSection.toLowerCase();
  const isChorus = sLower.includes('chorus') || currentSection.includes('副歌');
  const isInterlude = sLower.includes('interlude') || sLower.includes('solo') || currentSection.includes('间奏');
  const isVerse = sLower.includes('verse') || currentSection.includes('主歌');

  const sectionIcon = isChristmas
    ? (isChorus ? '🔔' : isInterlude ? '🛷' : '🎄')
    : (isChorus ? '🎵' : isInterlude ? '⚡' : isVerse ? '🎤' : '✨');

  return { currentSection, sectionIcon };
}

export function isKtvChristmasTheme(
  project: Pick<Project, 'song_identity'>,
  preset?: string,
  paletteAccent?: string
): boolean {
  const effectivePreset = preset || project.song_identity?.visual_theme || '';
  return (
    effectivePreset === 'christmas2026' ||
    effectivePreset === 'christmas_special' ||
    project.song_identity?.visual_theme === 'christmas2026' ||
    project.song_identity?.visual_theme === 'christmas_special' ||
    paletteAccent?.toLowerCase() === '#ffd700'
  );
}
