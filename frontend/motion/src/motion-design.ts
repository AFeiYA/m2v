import type {MotionPlan, Options, VisualMode} from './model';
export type Theme = {palette:string;background:'auto'|'dark'|'light'};
export type ModeSettings = {aspect:Options['aspect'];theme:Theme|null;post:boolean;bloom:number;shake:number};
export type KineticDesign = ModeSettings & {layout:'smart'|'random'|'single'|'two-stack'|'three-stack'|'word-by-word';highlight:'none'|'word'|'sweep';plan:MotionPlan|null};
export type AppleDesign = ModeSettings & {font_scale:number;focus_y:number};
export type KaraokeDesign = ModeSettings & {font_scale:number;preview_seconds:number};
export type MotionDesign = {version:'motion-design-v1';active_mode:VisualMode;theme:Theme;height:360|720;modes:{kinetic:KineticDesign;apple:AppleDesign;tv:KaraokeDesign}};
export const visualModes = {
 kinetic:{label:'Kinetic Posters',aspect:'16:9',poster:true},
 apple:{label:'Apple Scroll',aspect:'9:16',poster:false},
 tv:{label:'Dual-line Karaoke',aspect:'16:9',poster:false},
} as const;
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
export function changeTheme(design:MotionDesign,theme:Theme,scope:'mode'|'all'):MotionDesign {
 const next=structuredClone(design);
 if(scope==='all'){next.theme=theme;for(const mode of Object.keys(visualModes) as VisualMode[])next.modes[mode].theme=null;}
 else next.modes[next.active_mode].theme=theme;
 return next;
}
