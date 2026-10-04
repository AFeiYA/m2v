import type {Project} from './model';
import type {Measure} from './poster-layout';

export type SongText={text:string;x:number;y:number;fontSize:number;weight:number;anchor:'start'|'middle'|'end';accent?:boolean};
export type SongLayout={header:SongText[];cover:SongText[];introEnd:number;outroStart:number;duration:number;editorial:boolean;sections:{start:number;name:string}[];W:number;H:number};

// All presentation geometry is measured once; playback only evaluates opacity.
export function compileSongLayout(project:Project,W:number,H:number,measure:Measure):SongLayout|null{
 const identity=project.song_identity;if(!identity||identity.style==='none')return null;
 const portrait=H>W,margin=W*.07,base=Math.min(W,H),title=identity.title.trim(),artist=identity.artist.trim();
 const fit=(text:string,size:number,maxWidth:number,weight=600)=>Math.min(size,size*maxWidth/Math.max(1,measure(text,size,weight).width));
 const header:SongText[]=[];
 if(identity.show_signature){
  header.push({text:title,x:margin,y:H*.065,fontSize:fit(title,base*.027,portrait?W*.86:W*.55),weight:600,anchor:'start'});
  if(artist)header.push({text:artist,x:portrait?margin:W-margin,y:H*(portrait?.095:.065),fontSize:fit(artist,base*.022,portrait?W*.86:W*.27),weight:500,anchor:portrait?'start':'end'});
 }
 const maxWidth=W*.82,heroSize=portrait?W*.13:H*.15;
 let rows=[title];
 if(measure(title,heroSize,800).width>maxWidth){
  // Split at a word boundary for Latin text, otherwise balance CJK glyphs.
  const tokens=/\s/.test(title)?title.split(/\s+/):Array.from(title);
  let best=Infinity;
  for(let i=1;i<tokens.length;i++){
   const join=/\s/.test(title)?' ':'';
   const pair=[tokens.slice(0,i).join(join),tokens.slice(i).join(join)];
   const score=Math.max(...pair.map(s=>measure(s,heroSize,800).width));
   if(score<best){best=score;rows=pair;}
  }
 }
 const size=Math.min(...rows.map(row=>fit(row,heroSize,maxWidth,800))),lineHeight=size*1.2;
 const cover:SongText[]=rows.map((text,i)=>({text,x:W/2,y:H*.46+(i-(rows.length-1)/2)*lineHeight,fontSize:size,weight:800,anchor:'middle'}));
 if(artist)cover.push({text:artist,x:W/2,y:H*.46+(rows.length-1)/2*lineHeight+size*.85,fontSize:fit(artist,base*.037,maxWidth,500),weight:500,anchor:'middle'});
 const first=project.lines[0]?.start||0,last=Math.max(0,...project.lines.map(l=>l.end));
 const introEnd=identity.show_intro&&first>=1?Math.min(first,5):0;
 const outroStart=identity.show_outro&&project.duration-last>=1.5?Math.max(last+.3,project.duration-5):project.duration;
 const sections:SongLayout['sections']=[];
 if(identity.show_section&&identity.style==='editorial')for(const line of project.lines){
  const name=(line.section||'').trim();if(name&&sections.at(-1)?.name!==name)sections.push({start:line.start,name});
 }
 return {header,cover,introEnd,outroStart,duration:project.duration,editorial:identity.style==='editorial',sections,W,H};
}
export function songLayoutAt(layout:SongLayout|null,t:number){
 if(!layout)return {texts:[] as SongText[],alpha:0,cover:false,rule:false,section:''};
 const intro=t>=0&&t<layout.introEnd,outro=t>=layout.outroStart&&t<layout.duration,cover=intro||outro;
 const start=intro?0:layout.outroStart,end=intro?layout.introEnd:layout.duration;
 const alpha=cover?Math.max(0,Math.min(1,(t-start)/.3,(end-t)/.3)):1;
 const section=layout.sections.filter(s=>s.start<=t).at(-1)?.name||'';
 return {texts:cover?layout.cover:layout.header,alpha,cover,rule:layout.editorial,section:cover?'':section};
}

export function songTextColor(background:string){
 const rgb=background.replace('#','').match(/../g)?.map(v=>parseInt(v,16)/255)||[0,0,0];
 return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]<.45?'#f4f9ed':'#182214';
}
export function paintSongLayout(c:CanvasRenderingContext2D,layout:SongLayout|null,t:number,background:string,accent:string,font:string){
 if(!layout)return;const state=songLayoutAt(layout,t),{W,H}=layout;
 c.save();c.globalAlpha=state.alpha;
 if(state.rule){c.strokeStyle=accent;c.lineWidth=Math.max(1,Math.min(W,H)*.0015);c.globalAlpha=state.alpha*.5;c.beginPath();c.moveTo(W*.07,H*(state.cover?.3:.125));c.lineTo(W*.93,H*(state.cover?.3:.125));c.stroke();c.globalAlpha=state.alpha;}
 c.fillStyle=songTextColor(background);
 for(const item of state.texts){c.textAlign=item.anchor==='middle'?'center':item.anchor==='end'?'right':'left';c.font=`${item.weight} ${item.fontSize}px ${font}`;c.fillText(item.text,item.x,item.y);}
 if(state.section){c.textAlign='left';c.fillStyle=accent;c.font=`${Math.min(W,H)*.022}px ${font}`;c.fillText(state.section,W*.07,H*.94);}
 c.restore();
}
