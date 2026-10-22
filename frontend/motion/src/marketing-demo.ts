/** Public sample only: original demo text and synthetic timings, no user assets. */
import {defaults,normalizeProject,type MotionPlan,type Options,type VisualMode} from './model';
import {automaticPoster} from './poster-layout';
export const demoModes = {
  apple: {visualMode:'apple',aspect:'9:16',width:720,height:1280},
  karaoke: {visualMode:'tv',aspect:'16:9',width:1280,height:720},
  poster: {visualMode:'kinetic',aspect:'9:16',width:720,height:1280},
} as const;
export type DemoMode=keyof typeof demoModes;

export function demoScene(mode:DemoMode){
  const lines=['Every word finds its moment','Let the music carry us home','Somewhere between sound and feeling','This is where our story begins'];
  const project=normalizeProject({title:'Every Word',artist:'Sonicflow Studio',duration:18,
    song_identity:{version:'motion-song-identity-v1',title:'Every Word',artist:'Sonicflow Studio',style:'editorial',
      show_intro:false,show_signature:true,show_section:true,show_outro:false,cover_mode:'none',visual_theme:'director'},
    lines:lines.map((text,i)=>{
      const start=1+i*4,end=start+3.5,words=text.split(' '),step=(end-start)/words.length;
      return {id:`sample_${i}`,text,start,end,section:'Demo',words:words.map((word,j)=>({word,start:start+j*step,end:start+(j+1)*step}))};
    }),analysis:{beats:[],drum_hits:[],energy_curve:[]}});
  const plan:MotionPlan={version:'motion-plan-v1',source_signature:'public-synthetic-demo-v1',seed:42,
    cues:project.lines.map(line=>({line_id:line.id,template:'phrase-rise',layout:'left',palette:'impact',intensity:.6,emphasis:'',locked:false,
      poster:automaticPoster(line,'impact','three-stack','dark','hero-stack')}))};
  project.motion_plan=plan;
  const format=demoModes[mode];
  const options:Options={...defaults,aspect:format.aspect,visualMode:format.visualMode as VisualMode};
  return {project,options,width:format.width,height:format.height};
}
