import type {Line, CuePlan, PosterDirection, Project} from './model';
export const POSTER_FONT='"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';
export type Metrics={width:number;ascent:number;descent:number};
export type Measure=(text:string,size:number,weight:number)=>Metrics;
export type CompiledNode={text:string;word_indices:number[];role:'primary'|'secondary'|'support';x:number;y:number;width:number;height:number;fontSize:number;weight:number;color:string;rows:{text:string;x:number;y:number}[];start:number;settled:number;hold:'none'|'drift';beat_reaction:'none'|'pulse';entrance:PosterDirection['nodes'][number]['entrance']};
export type CompiledPoster={version:'motion-poster-layout-v1';line_id:string;source:'director'|'automatic';width:number;height:number;background:string;accent:string;motif:'none'|'rings';layout:PosterDirection['layout'];transition_out:'cut'|'fade';relations:NonNullable<PosterDirection['relations']>;start:number;end:number;handover?:{mode:'cut'|'fade'|'layered-fade';visible_end:number;exit_start:number;primary_exit_start:number;next_start:number|null};nodes:CompiledNode[]};

export function automaticPoster(line:Line,palette='impact'):PosterDirection {
  let blocks:{text:string;word_indices:number[]}[]=[];
  if(line.words.length){
    const parts=line.text.split(/\s+/u).filter(Boolean);let offset=0;
    for(const part of parts){const indices:number[]=[];let text='';while(offset<line.words.length&&text.length<part.length){indices.push(offset);text+=line.words[offset++].word;}if(indices.length)blocks.push({text,word_indices:indices});}
    if(offset!==line.words.length||blocks.length>12)blocks=[{text:line.words.map(w=>w.word).join(''),word_indices:line.words.map((_,i)=>i)}];
  }else blocks=[{text:line.text,word_indices:[]}];
  if(!blocks.length)blocks=[{text:line.text,word_indices:[]}];
  const primary=blocks.reduce((best,b,i)=>b.text.length>blocks[best].text.length?i:best,0);
  return {version:'motion-poster-direction-v1',status:'draft',layout:'hero-stack',intent:'自动基础排版，最长词组为主视觉',background:'#eeeee6',accent:palette==='neon'?'#63d9ed':'#c1ee47',motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',nodes:blocks.map((b,i)=>({...b,role:i===primary?'primary':'secondary',emphasis:'',color_role:'foreground',entrance:'slide-up',settle_fraction:.25}))};
}
function rowsFor(text:string,size:number,weight:number,maxWidth:number,measure:Measure){
  const rows:string[]=[''];for(const ch of Array.from(text)){const i=rows.length-1;if(rows[i]&&measure(rows[i]+ch,size,weight).width>maxWidth)rows.push(ch);else rows[i]+=ch;}return rows;
}
function fitPortraitTitle(text:string,size:number,weight:number,maxWidth:number,W:number,measure:Measure,emphasis:string){
  const chars=Array.from(text),count=chars.length;
  const fit=(rows:string[])=>Math.min(size,...rows.map(row=>size*maxWidth/Math.max(1,measure(row,size,weight).width)))*.99;
  // Four/five-character titles should not acquire an orphan merely because the default size is large.
  const single=fit([text]);
  if(count<=5||count<=6&&single>=W*.135)return {size:single,rows:[text]};
  if(count>12)return null;
  const boundaries=new Set<number>();
  const segmenter=new Intl.Segmenter('zh',{granularity:'word'});
  for(const segment of segmenter.segment(text))boundaries.add(Array.from(text.slice(0,segment.index+segment.segment.length)).length);
  const focus=text.indexOf(emphasis),focusStart=emphasis&&focus>=0?Array.from(text.slice(0,focus)).length:-1;
  const focusEnd=focusStart<0?-1:focusStart+Array.from(emphasis).length;
  let best:{size:number;rows:string[];score:number}|null=null;
  // Compare balanced alternatives using measured widths and soft lexical boundaries.
  for(let i=2;i<=count-2;i++){
    const rows=[chars.slice(0,i).join(''),chars.slice(i).join('')],candidate=fit(rows);
    const score=(size-candidate)/size+Math.abs(i-(count-i))/count*.35+(boundaries.has(i)?0:1.2)+(i>focusStart&&i<focusEnd?2:0);
    if(!best||score<best.score)best={size:candidate,rows,score};
  }
  return best;
}
export function compilePoster(line:Line,cue:CuePlan|undefined,W:number,H:number,measure:Measure):CompiledPoster {
  const design=cue?.poster||automaticPoster(line,cue?.palette);
  const rgb=design.background.slice(1).match(/../g)!.map(v=>parseInt(v,16)/255);
  const dark=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]<.45;
  const foreground=dark?'#f3f7e9':'#20261e',muted=dark?'#adbba8':'#697263';
  const dense=Array.from(line.text.replace(/\s/g,'')).length/Math.max(.001,line.end-line.start)>6;
  const nodes:CompiledNode[]=[];
  const short=Array.from(line.text.replace(/\s/g,'')).length<=6;
  const section=(line.section||'').toLowerCase();
  const portrait=H>W,chorus=section.includes('chorus')||section.includes('副歌'),verse=section.includes('verse')||section.includes('主歌');
  const maxHeight=H*(portrait?(dense?.40:chorus?.48:.44):(dense?.48:chorus?.66:verse?.48:.56));
  const gap=portrait?W*.012:H*.009,padding=portrait?W*.012:H*.008,width=W*(portrait?.78:.80);
  const fitted=design.nodes.map(n=>{
    const weight=n.role==='primary'?900:n.role==='secondary'?800:600;
    let size=portrait?W*(n.role==='primary'?(short?.30:.22):n.role==='secondary'?.075:.055):H*(n.role==='primary'?(short?.28:.18):n.role==='secondary'?.07:.045);
    const maxWidth=width-W*.018;
    const title=portrait&&n.role==='primary'?fitPortraitTitle(n.text,size,weight,maxWidth,W,measure,n.emphasis):null;
    if(title)size=title.size;
    let rows=title?.rows||rowsFor(n.text,size,weight,maxWidth,measure);
    for(let attempt=0;attempt<100&&rows.length>3;attempt++){size*=.92;rows=rowsFor(n.text,size,weight,maxWidth,measure);}
    return {n,weight,size,rows,maxWidth};
  });
  const primarySize=fitted.find(f=>f.n.role==='primary')!.size;
  for(const f of fitted)if(f.n.role!=='primary'&&f.size>primarySize*.55){f.size=primarySize*.55;f.rows=rowsFor(f.n.text,f.size,f.weight,f.maxWidth,measure);}
  const ink=(f:typeof fitted[number])=>measure(f.rows[0],f.size,f.weight).ascent+measure(f.rows.at(-1)!,f.size,f.weight).descent+(f.rows.length-1)*f.size*1.04;
  const content=fitted.reduce((sum,f)=>sum+ink(f),0);
  const scale=Math.min(1,Math.max(H*.1,maxHeight-padding*2*fitted.length-gap*(fitted.length-1))/content);
  for(const f of fitted)f.size*=scale;
  const blockWidth=Math.max(...fitted.flatMap(f=>f.rows.map(row=>measure(row,f.size,f.weight).width)));
  const leftAxis=(W-blockWidth)/2;
  const heights=fitted.map(f=>ink(f)+padding*2),totalHeight=heights.reduce((a,b)=>a+b,0)+gap*(fitted.length-1);
  const primaryIndex=fitted.findIndex(f=>f.n.role==='primary');
  const before=heights.slice(0,primaryIndex).reduce((a,b)=>a+b+gap,0);
  // Keep the primary near one central baseline while retaining safe bounds.
  let y=Math.max(H*(portrait?.16:.12),Math.min(H*(portrait?.74:.88)-totalHeight,H*(portrait?.42:.5)-before-heights[primaryIndex]/2));
  for(let i=0;i<fitted.length;i++){
    const {n,weight,size,rows}=fitted[i],height=heights[i];
    const shift=design.layout==='staggered'?(i%2?W*.025:-W*.025):0;
    const x=(W-width)/2+shift;
    const baseline=y+padding+measure(rows[0],size,weight).ascent;
    const resolved=rows.map((text,j)=>({text,x:design.layout==='hero-stack'?leftAxis:x+(width-measure(text,size,weight).width)/2,y:baseline+j*size*1.04}));
    const a=line.words[n.word_indices[0]],b=line.words[n.word_indices.at(-1)!];
    const start=Math.max(line.start,a?.start??line.start),end=Math.min(line.end,b?.end??line.end);
    const entrance=n.entrance!=='none'&&(dense||end-start<.16)?'fade':n.entrance;
    const duration=entrance==='none'?0:Math.min(.6,Math.max(1/30,(end-start)*n.settle_fraction),Math.max(0,(line.end-start)*.5));
    nodes.push({text:n.text,role:n.role,word_indices:[...n.word_indices],x,y,width,height,fontSize:size,weight,color:n.color_role==='accent'?design.accent:n.color_role==='muted'?muted:foreground,rows:resolved,start,settled:start+duration,hold:dense?'none':n.hold||'none',beat_reaction:n.role==='primary'&&!dense?(n.beat_reaction||'none'):'none',entrance});
    y+=height+gap;
  }
  return {version:'motion-poster-layout-v1',line_id:line.id,source:cue?.poster?'director':'automatic',width:W,height:H,background:design.background,accent:design.accent,motif:design.motif,layout:design.layout,transition_out:design.transition_out,relations:(design.relations||[]).map(r=>({...r,node_indices:[...r.node_indices]})),start:line.start,end:line.end,nodes};
}
// Song stage remains continuous; saved direction and alignment are not mutated.
export function compileSongPosters(project:Project,W:number,H:number,measure:Measure):CompiledPoster[]{
  const first=project.motion_plan?.cues.find(c=>c.poster)?.poster;
  const visual=project.motion_plan?.visual_language;
  const background=visual?.background||first?.background||'#eeeee6';
  const accent=visual?.accent||first?.accent||'#c1ee47';
  const motif=first?.motif||'none';
  const recurring=new Map<string,PosterDirection>();
  const layouts=project.lines.map(line=>{
    const cue=project.motion_plan?.cues.find(c=>c.line_id===line.id);
    let design=cue?.poster||automaticPoster(line,cue?.palette);
    const key=line.text.replace(/\s/g,''),previous=recurring.get(key);
    if(previous&&!cue?.locked&&previous.nodes.length===design.nodes.length&&previous.nodes.every((n,i)=>n.text===design.nodes[i].text)){
      design={...design,layout:previous.layout,nodes:design.nodes.map((n,i)=>({...n,role:previous.nodes[i].role,color_role:previous.nodes[i].color_role}))};
    }else if(!previous)recurring.set(key,design);
    const result=compilePoster(line,{...cue,poster:{...design,background,accent,motif}} as CuePlan,W,H,measure);
    result.source=cue?.poster?'director':'automatic';return result;
  });
  for(let i=0;i<layouts.length;i++)bindHandover(layouts[i],layouts[i+1]?.start??null,project.duration);
  return layouts;
}
export function bindHandover(plan:CompiledPoster,nextStart:number|null,duration:number){
  const boundary=Math.min(duration,nextStart??duration);
  const gap=Math.max(0,boundary-plan.end);
  // Short gaps hand off at the next anchor; long instrumental gaps breathe after a bounded tail.
  const visibleEnd=Math.max(plan.start,Math.min(boundary,plan.end+(gap>1.5?1.2:gap)));
  const complete=Math.max(...plan.nodes.map(n=>n.settled));
  const exitStart=Math.min(visibleEnd,Math.max(plan.end,complete+.18,visibleEnd-(gap<=.22?.12:.36)));
  const layered=visibleEnd-exitStart>=.18;
  plan.handover={mode:plan.transition_out==='cut'||exitStart>=visibleEnd?'cut':layered?'layered-fade':'fade',visible_end:visibleEnd,exit_start:exitStart,primary_exit_start:layered?Math.min(visibleEnd-.06,exitStart+.10):exitStart,next_start:nextStart};
}
export function visiblePosterAt(layouts:CompiledPoster[],t:number):CompiledPoster|undefined{
  return layouts.filter(p=>t>=p.start&&t<(p.handover?.visible_end??p.end)).at(-1);
}
export function stageAt(layouts:CompiledPoster[],t:number):CompiledPoster|undefined{
  return layouts.find(p=>t>=p.start&&t<p.end)||layouts.filter(p=>p.start<=t).at(-1)||layouts[0];
}
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
export function posterNodeState(node:CompiledNode,t:number,H:number){
  if(t<node.start)return {alpha:0,dx:0,dy:0,scale:1};
  const progress=node.settled===node.start?1:clamp((t-node.start)/(node.settled-node.start)),ease=1-Math.pow(1-progress,3);
  return {alpha:node.entrance==='none'?1:ease,dx:node.entrance==='slide-left'?-(1-ease)*H*.025:0,dy:node.entrance==='slide-up'?(1-ease)*H*.025:0,scale:node.entrance==='scale-in'?.92+.08*ease:1};
}
export function posterExitOpacity(plan:CompiledPoster,node:CompiledNode,t:number){
  if(!plan.handover)return posterOpacity(plan,t);
  const h=plan.handover;
  if(t<plan.start||t>=h.visible_end)return 0;
  if(h.mode==='cut')return 1;
  const start=node.role==='primary'?h.primary_exit_start:h.exit_start;
  return start>=h.visible_end?1:1-clamp((t-start)/(h.visible_end-start));
}
export function posterOpacity(plan:CompiledPoster,t:number):number{
  if(plan.handover)return Math.max(...plan.nodes.map(n=>posterExitOpacity(plan,n,t)));
  if(t<plan.start||t>=plan.end)return 0;
  if(plan.transition_out==='cut')return 1;
  const settled=Math.max(...plan.nodes.map(n=>n.settled));
  const start=Math.max(settled,plan.end-.15);return start>=plan.end?1:1-clamp((t-start)/(plan.end-start));
}
export function posterRings(W:number,H:number){
  const portrait=H>W;
  return [0,1,2].map(i=>({cx:W*(portrait?.96:.81),cy:H*(portrait?.14:.20),rx:W*(portrait?(.20+i*.022):(.08+i*.012)),ry:portrait?W*(.20+i*.022):H*(.12+i*.017),opacity:portrait?.24:1}));
}
export function paintCompiledPoster(c:CanvasRenderingContext2D,plan:CompiledPoster,t?:number,beat=0){
  const W=plan.width,H=plan.height;c.save();c.clearRect(0,0,W,H);c.fillStyle=plan.background;c.fillRect(0,0,W,H);
  c.globalAlpha=1;
  if(plan.motif==='rings'){c.strokeStyle=plan.accent;c.lineWidth=Math.min(W,H)*.003;for(const ring of posterRings(W,H)){c.globalAlpha=ring.opacity;c.beginPath();c.ellipse(ring.cx,ring.cy,ring.rx,ring.ry,0,0,Math.PI*2);c.stroke();}c.globalAlpha=1;}
  const complete=Math.max(...plan.nodes.map(n=>n.settled));
  const alpha=c.globalAlpha;c.textAlign='left';c.textBaseline='alphabetic';
  for(const n of plan.nodes){const state=t===undefined?{alpha:1,dx:0,dy:0,scale:1}:posterNodeState(n,t,H);if(!state.alpha)continue;
    c.save();c.globalAlpha=alpha*state.alpha*(t===undefined?1:posterExitOpacity(plan,n,t));const holding=t!==undefined&&t>=complete;
    const drift=holding&&n.hold==='drift'?Math.sin((t!-complete)*1.4)*H*.002:0;
    const pulse=holding&&n.beat_reaction==='pulse'?1+Math.max(0,Math.min(1,beat))*.012:1;
    c.translate(n.x+n.width/2+state.dx,n.y+n.height/2+state.dy+drift);c.scale(state.scale*pulse,state.scale*pulse);
    c.font=`${n.weight} ${n.fontSize}px ${POSTER_FONT}`;c.fillStyle=n.color;
    for(const row of n.rows)c.fillText(row.text,row.x-(n.x+n.width/2),row.y-(n.y+n.height/2));c.restore();
  }c.restore();
}
export function canvasMeasure(c:CanvasRenderingContext2D):Measure{return (text,size,weight)=>{c.font=`${weight} ${size}px ${POSTER_FONT}`;const m=c.measureText(text);return {width:Math.max(m.width,(m.actualBoundingBoxLeft||0)+(m.actualBoundingBoxRight||m.width)),ascent:m.actualBoundingBoxAscent||size*.85,descent:m.actualBoundingBoxDescent||size*.15};};}
