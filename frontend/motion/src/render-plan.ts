/** Deterministic layouts shared by preview, browser encoding, and cloud rendering. */
import type {Options,Project,VisualMode} from './model';
import {modeTheme} from './motion-design';
import {compileSongPosters,compileIntroTitle,resolvePaletteColors,type CompiledPoster,type CompiledIntroTitle,type Measure} from './poster-layout';
import {compileSongLayout,type SongLayout} from './song-layout';
import {compileKtvDualLayout,compileAppleScrollLayout,type KtvDualCompiled,type AppleScrollCompiled} from './stream-layout';
export type RenderPlan={mode:VisualMode;layouts:CompiledPoster[]|null;ktvLayout:KtvDualCompiled|null;appleLayout:AppleScrollCompiled|null;songLayout:SongLayout|null;intro:CompiledIntroTitle|null};
const compilers={
 kinetic:(p:Project,w:number,h:number,m:Measure,_palette:ReturnType<typeof resolvePaletteColors>)=>({layouts:compileSongPosters(p,w,h,m)}),
 tv:(p:Project,w:number,h:number,m:Measure,palette:ReturnType<typeof resolvePaletteColors>)=>({ktvLayout:compileKtvDualLayout(p,w,h,m,palette,p.motion_design?.modes.tv)}),
 apple:(p:Project,w:number,h:number,m:Measure,palette:ReturnType<typeof resolvePaletteColors>)=>({appleLayout:compileAppleScrollLayout(p,w,h,m,palette,p.motion_design?.modes.apple)}),
};
export function compileRenderPlan(project:Project,options:Pick<Options,'visualMode'>,width:number,height:number,measure:Measure):RenderPlan {
 const mode=options.visualMode||project.motion_design?.active_mode||'kinetic';
 const design=project.motion_design;
 // The poster compiler's input is derived here, never written back to the project.
 const source:Project=design?{...project,motion_plan:design.modes.kinetic.plan||undefined,
  song_identity:project.song_identity?{...project.song_identity,visual_theme:'director'}:undefined}:project;
 const theme=design?modeTheme(design,mode):{palette:source.motion_plan?.cues[0]?.palette||'impact',background:'auto' as const};
 const palette=resolvePaletteColors(theme.palette,theme.background);
 const stageProject:Project=mode==='kinetic'?source:{...source,motion_plan:{version:'motion-plan-v1',source_signature:'render-stage',seed:0,cues:[],
  visual_language:{direction:'',rhythm:'',background:palette.background,foreground:palette.foreground,accent:palette.accent}}};
 return {mode,layouts:null,ktvLayout:null,appleLayout:null,...compilers[mode](source,width,height,measure,palette),
  songLayout:compileSongLayout(source,width,height,measure),intro:source.song_identity?null:compileIntroTitle(stageProject,width,height,measure)};
}
