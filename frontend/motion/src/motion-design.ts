import type {MotionPlan, Options, VisualMode} from './model';
export type Theme = {palette:string;background:'auto'|'dark'|'light'};
export type ModeSettings = {aspect:Options['aspect'];theme:Theme|null;post:boolean;bloom:number;shake:number};
export type KineticDesign = ModeSettings & {layout:'smart'|'random'|'single'|'two-stack'|'three-stack'|'word-by-word';highlight:'none'|'word'|'sweep';plan:MotionPlan|null};
export type AppleDesign = ModeSettings & {font_scale:number;focus_y:number};
export type KaraokeDesign = ModeSettings & {font_scale:number;preview_seconds:number};
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
  apple:{...mode('9:16'),font_scale:1,focus_y:.42},
  tv:{...mode('16:9'),font_scale:1,preview_seconds:2.5},
 }};
}
export function modeTheme(design:MotionDesign,mode:VisualMode=design.active_mode):Theme{return design.modes[mode].theme||design.theme;}
export function modeOptions(design:MotionDesign,mode:VisualMode=design.active_mode):Options {
 const value=design.modes[mode];return {aspect:value.aspect,post:value.post,bloom:value.bloom,shake:value.shake,preset:modeTheme(design,mode).palette,mode:'phrase',grain:.035,punch:.7,height:design.height,visualMode:mode};
}
/** Selection never regenerates or mutates another mode's design. */
export function selectMode(design:MotionDesign,mode:VisualMode):MotionDesign{return {...design,active_mode:mode};}

export function setModeAspect(design:MotionDesign,aspect:Options['aspect'],mode:VisualMode=design.active_mode):MotionDesign {
  const next = structuredClone(design);
  next.modes[mode].aspect = aspect;
  return next;
}

export function changeTheme(design:MotionDesign,theme:Theme,scope:'mode'|'all'):MotionDesign {
 const next=structuredClone(design);
 if(scope==='all'){next.theme=theme;for(const mode of Object.keys(visualModes) as VisualMode[])next.modes[mode].theme=null;}
 else next.modes[next.active_mode].theme=theme;
 return next;
}
