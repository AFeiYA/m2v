import React,{createRef} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {Player,type PlayerRef} from '@remotion/player';
import {LyricVideo} from './lyric-video';
import type {Project,Options} from './model';
/** Existing audio controls provide the master clock; Player receives absolute frame seeks. */
export class RemotionPreview {
 private root:Root;private host:HTMLDivElement;private ref=createRef<PlayerRef>();private latest=0;private raf=0;
 constructor(canvas:HTMLCanvasElement,project:Project,options:Options,width:number,height:number){
  this.host=document.createElement('div');this.host.style.cssText='position:absolute;inset:0;width:100%;height:100%';canvas.hidden=true;canvas.parentElement!.append(this.host);
  this.root=createRoot(this.host);this.root.render(<Player ref={this.ref} component={LyricVideo} inputProps={{project,options}} durationInFrames={Math.max(1,Math.ceil(project.duration*30))} compositionWidth={width} compositionHeight={height} fps={30} controls={false} clickToPlay={false} doubleClickToFullscreen={false} spaceKeyToPlayOrPause={false} style={{width:'100%',height:'100%'}}/>);
  const ready=()=>{if(this.ref.current)this.ref.current.seekTo(this.latest);else this.raf=requestAnimationFrame(ready);};this.raf=requestAnimationFrame(ready);
 }
 renderAt(t:number){const frame=Math.max(0,Math.floor(t*30));if(frame!==this.latest||!this.ref.current){this.latest=frame;this.ref.current?.seekTo(frame);}}
 dispose(){cancelAnimationFrame(this.raf);this.root.unmount();this.host.remove();}
}
