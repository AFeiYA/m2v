import type {MotionPlan,Project} from './model';
import {automaticPoster,resolvePaletteColors,pickRandomStackLayout,type DefaultLayoutPreset,type StackLayout} from './poster-layout';

export function localRulePlan(project:Project,base:MotionPlan,palette:string,preset:DefaultLayoutPreset,background:'auto'|'dark'|'light',lineId?:string):MotionPlan{
 const next=structuredClone(base);let previous:StackLayout|undefined;
 for(const cue of next.cues){
  if(cue.locked||(lineId&&cue.line_id!==lineId))continue;
  const line=project.lines.find(l=>l.id===cue.line_id);if(!line)continue;
  cue.palette=palette;cue.poster=automaticPoster(line,palette,preset,background);
  if(cue.poster.nodes.length>1&&cue.poster.layout===previous)cue.poster.layout=pickRandomStackLayout(previous);
  previous=cue.poster.layout as StackLayout;
 }
 return next;
}

export function localPalette(base:MotionPlan,palette:string,background:'auto'|'dark'|'light'):MotionPlan{
 const next=structuredClone(base);
 for(const cue of next.cues){
  if(cue.locked)continue;
  cue.palette=palette;
  if(cue.poster){const colors=resolvePaletteColors(palette,background);cue.poster.background=colors.background;cue.poster.accent=colors.accent;}
 }
 return next;
}
