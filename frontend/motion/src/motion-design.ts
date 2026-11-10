import type {MotionPlan, Options, VisualMode} from './model';
export type Theme = {palette:string;background:'auto'|'dark'|'light'};
export type ModeSettings = {aspect:Options['aspect'];theme:Theme|null;post:boolean;bloom:number;shake:number};
export type KineticDesign = ModeSettings & {layout:'smart'|'random'|'single'|'two-stack'|'three-stack'|'word-by-word';highlight:'none'|'word'|'sweep';plan:MotionPlan|null};
export type AppleDesign = ModeSettings & {font_scale:number;focus_y:number;count_in?:boolean};
export type KaraokeDesign = ModeSettings & {font_scale:number;preview_seconds:number;alignment?:'center'|'classic';position_y?:number};
export type MotionDesign = {version:'motion-design-v1';active_mode:VisualMode;theme:Theme;height:360|720;modes:{kinetic:KineticDesign;apple:AppleDesign;tv:KaraokeDesign}};

export interface VisualTemplate {
  id: VisualMode;
  nameKey: string;
  defaultName: string;
  descriptionKey: string;
  defaultDescription: string;
  icon: string;
  badge: string;
  defaultAspect: Options['aspect'];
  supportedAspects: Array<Options['aspect']>;
  hasPosters: boolean;
  exportFormatName: string;
}

export const VISUAL_TEMPLATES: Record<VisualMode, VisualTemplate> = {
  kinetic: {
    id: 'kinetic',
    nameKey: 'ms_tpl_kinetic',
    defaultName: 'Kinetic Posters',
    descriptionKey: 'ms_tpl_kinetic_desc',
    defaultDescription: 'Dynamic typography & expressive layout with word-level visual punch.',
    icon: '🌟',
    badge: 'Poster Layout',
    defaultAspect: '16:9',
    supportedAspects: ['16:9', '9:16'],
    hasPosters: true,
    exportFormatName: 'Kinetic Posters',
  },
  apple: {
    id: 'apple',
    nameKey: 'ms_tpl_apple',
    defaultName: 'Apple Scroll',
    descriptionKey: 'ms_tpl_apple_desc',
    defaultDescription: 'Smooth focal scrolling with elegant lyric transitions & focus glow.',
    icon: '📱',
    badge: 'Modern Stream',
    defaultAspect: '9:16',
    supportedAspects: ['9:16', '16:9'],
    hasPosters: false,
    exportFormatName: 'Apple Scroll',
  },
  tv: {
    id: 'tv',
    nameKey: 'ms_tpl_tv',
    defaultName: 'Dual-line Karaoke',
    descriptionKey: 'ms_tpl_tv_desc',
    defaultDescription: 'Classic two-line alternating karaoke with real-time sweep.',
    icon: '📺',
    badge: 'KTV Classic',
    defaultAspect: '16:9',
    supportedAspects: ['16:9', '9:16'],
    hasPosters: false,
    exportFormatName: 'Dual-line Karaoke',
  },
};

export const visualModes = {
 kinetic:{label:'Kinetic Posters',aspect:'16:9',poster:true},
 apple:{label:'Apple Scroll',aspect:'9:16',poster:false},
 tv:{label:'Dual-line Karaoke',aspect:'16:9',poster:false},
} as const;

export function getTemplate(mode: VisualMode): VisualTemplate {
  return VISUAL_TEMPLATES[mode] || VISUAL_TEMPLATES.kinetic;
}

export function listTemplates(): VisualTemplate[] {
  return Object.values(VISUAL_TEMPLATES);
}

export function createMotionDesign():MotionDesign {
 const mode=(aspect:Options['aspect']):ModeSettings=>({aspect,theme:null,post:true,bloom:.7,shake:.65});
 return {version:'motion-design-v1',active_mode:'kinetic',theme:{palette:'impact',background:'auto'},height:720,modes:{
  kinetic:{...mode('16:9'),layout:'smart',highlight:'none',plan:null},
  apple:{...mode('9:16'),font_scale:1,focus_y:.42,count_in:false},
  tv:{...mode('16:9'),font_scale:1,preview_seconds:2.5,alignment:'center',position_y:0.52},
 }};
}
export function normalizeMotionDesign(raw?: Partial<MotionDesign> | null): MotionDesign {
  const base = createMotionDesign();
  if (!raw || typeof raw !== 'object') return base;
  const active_mode = (raw.active_mode && raw.active_mode in visualModes) ? raw.active_mode : base.active_mode;
  const theme = raw.theme ? { ...base.theme, ...raw.theme } : base.theme;
  const height = raw.height === 360 ? 360 : 720;
  const rawModes = raw.modes || ({} as any);
  return {
    version: 'motion-design-v1',
    active_mode,
    theme,
    height,
    modes: {
      kinetic: { ...base.modes.kinetic, ...(rawModes.kinetic || {}) },
      apple: { ...base.modes.apple, ...(rawModes.apple || {}) },
      tv: { ...base.modes.tv, ...(rawModes.tv || {}) },
    },
  };
}

export function modeTheme(design:MotionDesign,mode:VisualMode=design?.active_mode||'kinetic'):Theme{
  const safe = normalizeMotionDesign(design);
  return safe.modes[mode]?.theme || safe.theme;
}

export function modeOptions(design:MotionDesign,mode:VisualMode=design?.active_mode||'kinetic'):Options {
  const safe = normalizeMotionDesign(design);
  const value = safe.modes[mode] || safe.modes.kinetic;
  return {
    aspect: value.aspect || (visualModes[mode]?.aspect ?? '16:9'),
    post: value.post ?? true,
    bloom: value.bloom ?? 0.7,
    shake: value.shake ?? 0.65,
    preset: modeTheme(safe, mode).palette,
    mode: 'phrase',
    grain: 0.035,
    punch: 0.7,
    height: safe.height,
    visualMode: mode,
  };
}

/** Selection never regenerates or mutates another mode's design. */
export function selectMode(design:MotionDesign,mode:VisualMode):MotionDesign {
  const next = normalizeMotionDesign(design);
  next.active_mode = (mode in visualModes) ? mode : 'kinetic';
  return next;
}

export function setModeAspect(design:MotionDesign,aspect:Options['aspect'],mode:VisualMode=design?.active_mode||'kinetic'):MotionDesign {
  const next = normalizeMotionDesign(design);
  if (next.modes[mode]) {
    next.modes[mode].aspect = aspect;
  }
  return next;
}

export function changeTheme(design:MotionDesign,theme:Theme,scope:'mode'|'all'):MotionDesign {
  const next = normalizeMotionDesign(design);
  if (scope === 'all') {
    next.theme = theme;
    for (const mode of Object.keys(visualModes) as VisualMode[]) {
      if (next.modes[mode]) next.modes[mode].theme = null;
    }
  } else {
    if (next.modes[next.active_mode]) next.modes[next.active_mode].theme = theme;
  }
  return next;
}
