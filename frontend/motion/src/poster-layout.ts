import type {Line, CuePlan, PosterDirection} from './model';
export const POSTER_FONT='"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';
export type Metrics={width:number;ascent:number;descent:number};
export type Measure=(text:string,size:number,weight:number)=>Metrics;
export type CompiledNode={text:string;word_indices:number[];x:number;y:number;width:number;height:number;fontSize:number;weight:number;color:string;rows:{text:string;x:number;y:number}[];start:number;settled:number;hold:'none'|'drift';beat_reaction:'none'|'pulse';entrance:PosterDirection['nodes'][number]['entrance']};
export type CompiledPoster={version:'motion-poster-layout-v1';line_id:string;source:'director'|'automatic';width:number;height:number;background:string;accent:string;motif:'none'|'rings';layout:PosterDirection['layout'];transition_out:'cut'|'fade';start:number;end:number;nodes:CompiledNode[]};

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
export function compilePoster(line:Line,cue:CuePlan|undefined,W:number,H:number,measure:Measure):CompiledPoster {
  const design=cue?.poster||automaticPoster(line,cue?.palette);
  const rgb=design.background.slice(1).match(/../g)!.map(v=>parseInt(v,16)/255);
  const dark=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]<.45;
  const foreground=dark?'#f3f7e9':'#20261e',muted=dark?'#adbba8':'#697263';
  const dense=Array.from(line.text.replace(/\s/g,'')).length/Math.max(.001,line.end-line.start)>6;
  const nodes:CompiledNode[]=[];const gap=H*.016,top=H*.09,usable=H*.82-gap*(design.nodes.length-1);
  const weights=design.nodes.map(n=>design.layout==='hero-stack'?(n.role==='primary'?2.8:n.role==='secondary'?1.2:1):1);
  const total=weights.reduce((a,b)=>a+b,0);let y=top;
  for(let i=0;i<design.nodes.length;i++){
    const n=design.nodes[i],height=usable*weights[i]/total;
    const x=W*(design.layout==='staggered'?(i%2?.20:.09):.09),width=W*(design.layout==='staggered'?.71:.82);
    const weight=n.role==='primary'?900:n.role==='secondary'?800:600;
    // Reserve internal padding so actual glyphs and entering offsets stay in safe slots.
    const innerWidth=width-W*.012,innerHeight=height-H*.012;
    let size=Math.min(H*(n.role==='primary'?.19:n.role==='secondary'?.075:.048),innerHeight*.85);
    let rows=rowsFor(n.text,size,weight,innerWidth,measure);
    for(let attempt=0;attempt<100;attempt++){
      const maxInk=Math.max(...rows.map(r=>{const m=measure(r,size,weight);return m.ascent+m.descent;}));
      if(rows.every(r=>measure(r,size,weight).width<=innerWidth)&&maxInk+(rows.length-1)*size*1.2<=innerHeight)break;
      size*=.92;rows=rowsFor(n.text,size,weight,innerWidth,measure);
    }
    const first=measure(rows[0],size,weight),last=measure(rows.at(-1)!,size,weight);
    const inkHeight=first.ascent+last.descent+(rows.length-1)*size*1.2;
    const baseline=y+(height-inkHeight)/2+first.ascent;
    const resolved=rows.map((text,j)=>({text,x:design.layout==='center-stack'?x+(width-measure(text,size,weight).width)/2:x+W*.006,y:baseline+j*size*1.2}));
    const a=line.words[n.word_indices[0]],b=line.words[n.word_indices.at(-1)!];
    const start=Math.max(line.start,a?.start??line.start),end=Math.min(line.end,b?.end??line.end);
    const entrance=n.entrance!=='none'&&(dense||end-start<.16)?'fade':n.entrance;
    const duration=entrance==='none'?0:Math.min(.6,Math.max(1/30,(end-start)*n.settle_fraction),Math.max(0,(line.end-start)*.5));
    nodes.push({text:n.text,word_indices:[...n.word_indices],x,y,width,height,fontSize:size,weight,color:n.color_role==='accent'?design.accent:n.color_role==='muted'?muted:foreground,rows:resolved,start,settled:start+duration,hold:dense?'none':n.hold||'none',beat_reaction:n.role==='primary'&&!dense?(n.beat_reaction||'none'):'none',entrance});
    y+=height+gap;
  }
  return {version:'motion-poster-layout-v1',line_id:line.id,source:cue?.poster?'director':'automatic',width:W,height:H,background:design.background,accent:design.accent,motif:design.motif,layout:design.layout,transition_out:design.transition_out,start:line.start,end:line.end,nodes};
}
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
export function posterNodeState(node:CompiledNode,t:number,H:number){
  if(t<node.start)return {alpha:0,dx:0,dy:0,scale:1};
  const progress=node.settled===node.start?1:clamp((t-node.start)/(node.settled-node.start)),ease=1-Math.pow(1-progress,3);
  return {alpha:node.entrance==='none'?1:ease,dx:node.entrance==='slide-left'?-(1-ease)*H*.025:0,dy:node.entrance==='slide-up'?(1-ease)*H*.025:0,scale:node.entrance==='scale-in'?.92+.08*ease:1};
}
export function posterOpacity(plan:CompiledPoster,t:number){
  if(t<plan.start||t>=plan.end)return 0;
  if(plan.transition_out==='cut')return 1;
  const settled=Math.max(...plan.nodes.map(n=>n.settled));
  const start=Math.max(settled,plan.end-.15);return start>=plan.end?1:1-clamp((t-start)/(plan.end-start));
}
export function paintCompiledPoster(c:CanvasRenderingContext2D,plan:CompiledPoster,t?:number,beat=0){
  const W=plan.width,H=plan.height;c.save();c.clearRect(0,0,W,H);c.fillStyle=plan.background;c.fillRect(0,0,W,H);
  c.globalAlpha=t===undefined?1:posterOpacity(plan,t);
  if(plan.motif==='rings'){c.strokeStyle=plan.accent;c.lineWidth=H*.003;for(let i=0;i<3;i++){c.beginPath();c.ellipse(W*.81,H*.20,W*(.08+i*.012),H*(.12+i*.017),0,0,Math.PI*2);c.stroke();}}
  const complete=Math.max(...plan.nodes.map(n=>n.settled));
  const alpha=c.globalAlpha;c.textAlign='left';c.textBaseline='alphabetic';
  for(const n of plan.nodes){const state=t===undefined?{alpha:1,dx:0,dy:0,scale:1}:posterNodeState(n,t,H);if(!state.alpha)continue;
    c.save();c.globalAlpha=alpha*state.alpha;const holding=t!==undefined&&t>=complete;
    const drift=holding&&n.hold==='drift'?Math.sin((t!-complete)*1.4)*H*.002:0;
    const pulse=holding&&n.beat_reaction==='pulse'?1+Math.max(0,Math.min(1,beat))*.012:1;
    c.translate(n.x+n.width/2+state.dx,n.y+n.height/2+state.dy+drift);c.scale(state.scale*pulse,state.scale*pulse);
    c.font=`${n.weight} ${n.fontSize}px ${POSTER_FONT}`;c.fillStyle=n.color;
    for(const row of n.rows)c.fillText(row.text,row.x-(n.x+n.width/2),row.y-(n.y+n.height/2));c.restore();
  }c.restore();
}
export function canvasMeasure(c:CanvasRenderingContext2D):Measure{return (text,size,weight)=>{c.font=`${weight} ${size}px ${POSTER_FONT}`;const m=c.measureText(text);return {width:Math.max(m.width,(m.actualBoundingBoxLeft||0)+(m.actualBoundingBoxRight||m.width)),ascent:m.actualBoundingBoxAscent||size*.85,descent:m.actualBoundingBoxDescent||size*.15};};}
