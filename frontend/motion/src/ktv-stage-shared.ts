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

export interface KtvStageTheme {
  id: string;
  isChristmas: boolean;
  bgBase: string;
  bgGradientCss: string;
  bgRadialCenterY: number;
  bgStops: Array<{ offset: number; color: string }>;
  accent: string;
  sungHighlight: string;
  pastWordColor: string;
  titleColor: string;
  subtitleColor: string;
  badgeBg: string;
  badgeBorder: string;
  badgeText: string;
  cardBg: { singing: string; upcoming: string; past: string };
  cardBorder: { singing: string; upcoming: string; past: string };
  singingBoxShadow: string;
  singingShadowColor: string;
  activeBloomCss: string;
  activeBloomColor: string;
  activeBloomBlur: number;
  singingCueIcon: string;
  interludeIcons: string;
  interludeText: string;
  defaultSubtitleTag: string;
  progressCss: string;
  progressStops: Array<{ offset: number; color: string }>;
  timelineTextColor: string;
  ornateFrame?: {
    outerBorder: string;
    innerBorder: string;
    topCornerIcon: string;
    bottomCornerIcon: string;
  };
  hasBokehAndSnow: boolean;
}

export function resolveKtvStageTheme(
  project: Pick<Project, 'song_identity'>,
  preset?: string,
  palette?: { accent?: string; background?: string }
): KtvStageTheme {
  const isChristmas = isKtvChristmasTheme(project, preset, palette?.accent);
  if (isChristmas) {
    const accent = '#FFD700';
    return {
      id: 'christmas2026',
      isChristmas: true,
      bgBase: '#120303',
      bgGradientCss: 'radial-gradient(circle at 50% 28%, #3d0707 0%, #260404 42%, #140202 78%, #080101 100%)',
      bgRadialCenterY: 0.28,
      bgStops: [
        { offset: 0, color: '#3d0707' },
        { offset: 0.42, color: '#260404' },
        { offset: 0.78, color: '#140202' },
        { offset: 1, color: '#080101' },
      ],
      accent,
      sungHighlight: '#FEF08A',
      pastWordColor: '#FDE047',
      titleColor: '#FEF08A',
      subtitleColor: '#FDE68A',
      badgeBg: 'rgba(20, 20, 20, 0.72)',
      badgeBorder: '#F59E0B',
      badgeText: '#FEF08A',
      cardBg: {
        singing: 'rgba(42, 5, 5, 0.88)',
        upcoming: 'rgba(22, 3, 3, 0.68)',
        past: 'rgba(18, 2, 2, 0.52)',
      },
      cardBorder: {
        singing: '#F59E0B',
        upcoming: 'rgba(245, 158, 11, 0.35)',
        past: 'rgba(245, 158, 11, 0.15)',
      },
      singingBoxShadow: '0 0 28px rgba(245, 158, 11, 0.45), 0 16px 40px rgba(0, 0, 0, 0.8)',
      singingShadowColor: 'rgba(245, 158, 11, 0.45)',
      activeBloomCss: '0 0 20px #F59E0B, 0 0 38px #FBBF24, 0 0 60px rgba(220, 38, 38, 0.7)',
      activeBloomColor: '#F59E0B',
      activeBloomBlur: 22,
      singingCueIcon: '🔔',
      interludeIcons: '🛷 ❄️ 🔔',
      interludeText: 'Listen to the sleigh bells... Get ready to sing!',
      defaultSubtitleTag: 'VICTORIAN CHRISTMAS',
      progressCss: 'linear-gradient(90deg, #DC2626 0%, #F59E0B 50%, #FEF08A 100%)',
      progressStops: [
        { offset: 0, color: '#DC2626' },
        { offset: 0.5, color: '#F59E0B' },
        { offset: 1, color: '#FEF08A' },
      ],
      timelineTextColor: '#FDE68A',
      ornateFrame: {
        outerBorder: 'rgba(245, 158, 11, 0.5)',
        innerBorder: 'rgba(245, 158, 11, 0.3)',
        topCornerIcon: '🎄',
        bottomCornerIcon: '❄️',
      },
      hasBokehAndSnow: true,
    };
  }

  const accent = palette?.accent || '#b7f34a';
  return {
    id: 'standard',
    isChristmas: false,
    bgBase: palette?.background || '#090d14',
    bgGradientCss: 'radial-gradient(circle at 50% 30%, rgba(18, 26, 40, 0.75) 0%, rgba(6, 10, 16, 0.96) 100%)',
    bgRadialCenterY: 0.3,
    bgStops: [
      { offset: 0, color: 'rgba(18, 26, 40, 0.75)' },
      { offset: 1, color: 'rgba(6, 10, 16, 0.96)' },
    ],
    accent,
    sungHighlight: accent,
    pastWordColor: accent,
    titleColor: '#FFFFFF',
    subtitleColor: 'rgba(255, 255, 255, 0.75)',
    badgeBg: 'rgba(12, 18, 28, 0.75)',
    badgeBorder: accent,
    badgeText: accent,
    cardBg: {
      singing: 'rgba(12, 18, 28, 0.85)',
      upcoming: 'rgba(8, 12, 20, 0.72)',
      past: 'rgba(6, 10, 16, 0.55)',
    },
    cardBorder: {
      singing: accent,
      upcoming: 'rgba(255, 255, 255, 0.18)',
      past: 'rgba(255, 255, 255, 0.08)',
    },
    singingBoxShadow: `0 0 28px ${accent}55, 0 16px 40px rgba(0, 0, 0, 0.8)`,
    singingShadowColor: `${accent}55`,
    activeBloomCss: `0 0 18px ${accent}, 0 0 32px ${accent}`,
    activeBloomColor: accent,
    activeBloomBlur: 18,
    singingCueIcon: '🎤',
    interludeIcons: '🎵 ⚡ 🎧',
    interludeText: 'Feel the groove... Get ready to sing!',
    defaultSubtitleTag: 'KARAOKE',
    progressCss: `linear-gradient(90deg, ${accent}88 0%, ${accent} 100%)`,
    progressStops: [
      { offset: 0, color: `${accent}88` },
      { offset: 1, color: accent },
    ],
    timelineTextColor: 'rgba(255, 255, 255, 0.8)',
    hasBokehAndSnow: false,
  };
}
