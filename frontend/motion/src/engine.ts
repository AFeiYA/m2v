import * as THREE from 'three';
import { FSPass, makeRT } from './vendor/pdoom/gl';
import { Post, DEFAULT_POST } from './vendor/pdoom/post';
import { featuresAt, pulseAt, groupAt, type Project, type Options, type Line } from './model';

// Text is rasterized with the platform's Chinese-capable font into a texture.
// All animation is evaluated from absolute song time, including noise/grain.
const FONT = '"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';
const clamp=(x:number)=>Math.max(0,Math.min(1,x));
const fract=(x:number)=>x-Math.floor(x);
const noise=(x:number)=>fract(Math.sin(x*127.1)*43758.5453);

export class MotionEngine {
  renderer: THREE.WebGLRenderer;
  private canvas = document.createElement('canvas');
  private ctx: CanvasRenderingContext2D;
  private texture: THREE.CanvasTexture;
  private hdr: THREE.WebGLRenderTarget;
  private output: THREE.WebGLRenderTarget;
  private post: Post;
  private scene: FSPass;
  private blit: FSPass;
  private empty: THREE.DataTexture;
  private W:number; private H:number;
  project: Project;
  options: Options;
  constructor(element: HTMLCanvasElement, project:Project, options:Options, width=1280, height=720) {
    this.project=project; this.options={...options}; this.W=width; this.H=height;
    this.renderer=new THREE.WebGLRenderer({canvas:element,alpha:false,antialias:false,preserveDrawingBuffer:true});
    this.renderer.setSize(width,height,false); this.renderer.setPixelRatio(1);
    this.renderer.autoClear=false; this.renderer.toneMapping=THREE.NoToneMapping;
    if (!this.renderer.extensions.has('EXT_color_buffer_float')) throw new Error('当前浏览器不支持浮点 WebGL 渲染，请使用最新版 Chrome。');
    this.canvas.width=width; this.canvas.height=height;
    this.ctx=this.canvas.getContext('2d')!;
    this.texture=new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace=THREE.SRGBColorSpace;
    this.texture.minFilter=THREE.LinearFilter; this.texture.magFilter=THREE.LinearFilter;
    this.hdr=makeRT(width,height); this.output=makeRT(width,height,{type:THREE.UnsignedByteType});
    this.empty=new THREE.DataTexture(new Uint8Array([0,0,0,0]),1,1);this.empty.needsUpdate=true;
    this.post=new Post(width,height);
    this.scene=new FSPass(`
      uniform sampler2D letters; uniform vec2 res; uniform float time, beat, energy, neon;
      void main(){
        vec2 p=(vUv-.5)*vec2(res.x/res.y,1.0);
        vec3 accent=mix(vec3(.12,.75,.42),vec3(.02,.42,.85),neon);
        vec3 bg=vec3(.004,.006,.009)+accent*.035*exp(-length(p)*3.0);
        float z=1.0/(abs(p.y+.14)+.14);
        vec2 grid=vec2(p.x*z*2.0,z+time*.5);
        vec2 d=abs(fract(grid-.5)-.5)/max(fwidth(grid),vec2(.001));
        float g=(1.0-min(min(d.x,d.y),1.0))*.07;
        bg+=accent*g*(1.0-smoothstep(-.48,-.08,p.y));
        float radius=.32+.025*sin(time*.5)+beat*.012;
        float ring=exp(-abs(length(p)-radius)*350.0);
        bg+=accent*ring*(.12+.2*energy);
        vec4 txt=texture(letters,vUv);
        fragColor=vec4(mix(bg,txt.rgb*1.25,txt.a),1.0);
      }`,{letters:{value:this.texture},res:{value:new THREE.Vector2(width,height)},time:{value:0},beat:{value:0},energy:{value:0},neon:{value:0}});
    this.blit=new FSPass('uniform sampler2D src; void main(){fragColor=texture(src,vUv);}',{src:{value:this.output.texture}});
  }

  renderAt(t:number, present=true) {
    const {W,H,ctx:c,project:p}=this;
    const selected=p.lines.find(l=>t>=l.start&&t<l.end);
    const cue=p.motion_plan?.cues.find(cue=>cue.line_id===selected?.id);
    const o=cue?{...this.options,preset:cue.palette,mode:cue.template==='word-impact'?'slam' as const:'phrase' as const,punch:this.options.punch*cue.intensity,shake:cue.template==='quiet-hold'?0:this.options.shake*cue.intensity}:this.options;
    const f=featuresAt(p,t);
    const index=p.lines.findIndex(l=>t>=l.start && t<l.end);
    const line=index<0?null:p.lines[index];
    c.clearRect(0,0,W,H);
    const scale=Math.min(W/1280,H/720);
    const accent=o.preset==='neon'?'#55dbff':'#b9ff70';
    const side=W*.075;
    c.textBaseline='middle'; c.textAlign='left';
    c.fillStyle='#81918e';c.font=`500 ${Math.max(12,14*scale)}px ${FONT}`;
    if(!p.motion_plan)c.fillText('MOTION / '+(line?.section || 'LYRIC STUDY'),side,H*.09);
    c.textAlign='right';if(!p.motion_plan)c.fillText(`${String(index+1).padStart(2,'0')} / ${String(p.lines.length).padStart(2,'0')}`,W-side,H*.09);
    c.strokeStyle='#263530';c.lineWidth=1;c.beginPath();c.moveTo(side,H*.13);c.lineTo(W-side,H*.13);c.stroke();
    if(line) this.drawLine(line,t,accent,f.impact,o,cue);
    else {
      const next=p.lines.find(l=>l.start>t);
      c.textAlign='center';c.fillStyle='#dee8dc';c.font=`800 ${Math.min(W*.065,H*.07)}px ${FONT}`;
      this.drawWrapped(p.title,W/2,H*.46,W*.8,Math.min(W*.065,H*.07));
      c.fillStyle=accent;c.font=`400 ${Math.max(12,16*scale)}px ${FONT}`;
      c.fillText('',W/2,H*.58);
    }
    if(!p.motion_plan){
    c.fillStyle='#263530';c.fillRect(side,H*.89,W-side*2,2);
    c.fillStyle=accent;c.fillRect(side,H*.89,(W-side*2)*clamp(t/p.duration),2);
    c.fillStyle='#70847a';c.font=`500 ${Math.max(11,12*scale)}px ${FONT}`;c.textAlign='left';
    c.fillText(o.mode==='slam'?'WORD / IMPACT':'LINE / FLOW',side,H*.93);
    c.textAlign='right';c.fillText(`${t.toFixed(2)} s`,W-side,H*.93);
    }
    this.texture.needsUpdate=true;
    this.scene.u.time.value=t;this.scene.u.beat.value=f.beat;
    this.scene.u.energy.value=f.energy;this.scene.u.neon.value=o.preset==='neon'?1:0;
    this.scene.render(this.renderer,this.hdr);
    const impulse=f.impact*o.shake;
    const post={...DEFAULT_POST,hud:0,bloom:o.post?o.bloom:0,halation:o.post?0.13:0,
      grain:o.post?o.grain:0,ca:o.post?impulse*2:0,vignette:o.post?0.25:0,
      zoom:1+impulse*.014,shake:[Math.sin(t*87)*impulse*W*.003,Math.sin(t*71)*impulse*H*.004] as [number,number]};
    this.post.render(this.renderer,this.hdr.texture,this.empty,this.output,post,t);
    if(present)this.blit.render(this.renderer,null);
  }

  private drawLine(l:Line,t:number,accent:string,impact:number,o:Options,cue?:import('./model').CuePlan) {
    const {W,H,ctx:c}=this;
    const active=l.words.find(w=>t>=w.start && t<w.end);
    const visible=l.words.filter(w=>w.start<=t);
    const word=active || visible[visible.length-1];
    const group=groupAt(l,cue,t);
    const hero=group?group.text:o.mode==='slam' && word ? word.word : l.text;
    const start=group?l.words[group.word_indices[0]].start:o.mode==='slam' && word ? word.start : l.start;
    const attack=group?group.action==='hold'?0:pulseAt(t,start,12)*group.intensity:cue?.template==='quiet-hold'?0:pulseAt(t,start,18);
    const enter=clamp((t-l.start)/.09),exit=clamp((l.end-t)/.14);
    const base=Math.min(W*.23,H*.31,hero.length>4?W*.12:Infinity);
    c.save();c.translate(W/2,H*.43+(cue?.template==='phrase-rise'?(1-clamp((t-l.start)/.45))*H*.08:0));
    // Keep oversized words inside the frame even during their attack.
    const zoom=1+attack*o.punch*.18+(cue?.template==='quiet-hold'?0:impact*.018);
    const groupZoom=group?.action==='push'?1+attack*.12:group?.action==='settle'?1-attack*.06:zoom;
    c.scale(groupZoom,groupZoom);
    if(group?.action==='reveal')c.translate(-attack*W*.035,0);c.rotate(Math.sin(start*3)*.025*attack*o.punch);
    c.globalAlpha=enter*exit;
    c.textAlign='center';c.font=`900 ${base}px ${FONT}`;
    c.strokeStyle=o.preset==='neon'?'#134252':'#2e4939';c.lineWidth=Math.max(1,W/900);
    c.save();c.translate(0,-base*.16-attack*base*.08);
    c.textAlign=cue?.layout==='left'?'left':'center';this.drawWrapped(hero,cue?.layout==='left'?-W*.36/zoom:0,0,W*.73/zoom,base,true);c.restore();
    c.fillStyle=cue?.emphasis && o.mode==='slam' && cue.emphasis.includes(hero)?accent:active || !word?'#f3f7e9':'#adbba8';
    c.textAlign=cue?.layout==='left'?'left':'center';this.drawWrapped(hero,cue?.layout==='left'?-W*.36/zoom:0,0,W*.73/zoom,base);
    c.restore();
    // The full line remains visible and is laid out by glyph widths, not fixed character cells.
    const chars=Array.from(l.text),matched:number[]=[];
    let offset=0;
    l.words.forEach(w=>{const at=l.text.indexOf(w.word,offset);if(at>=0){const from=Array.from(l.text.slice(0,at)).length;for(let j=0;j<Array.from(w.word).length;j++)matched[from+j]=t>=w.start&&t<w.end?2:t>=w.end?1:0;offset=at+w.word.length;}});
    const font=Math.min(W*.037,H*.043);
    const highlight=group?.emphasis||cue?.emphasis||'';
    const groupPositions=new Set<number>();
    if(group){let cursor=0;l.words.forEach((token,i)=>{const at=l.text.indexOf(token.word,cursor);if(at>=0){if(group.word_indices.includes(i)){const from=Array.from(l.text.slice(0,at)).length;for(let j=0;j<Array.from(token.word).length;j++)groupPositions.add(from+j);}cursor=at+token.word.length;}});}
    c.font=`600 ${font}px ${FONT}`;
    const rows:{ch:string;i:number}[][]=[[]]; let rowWidth=0;
    chars.forEach((ch,i)=>{const cw=c.measureText(ch).width;if(rowWidth+cw>W*.79&&rows.at(-1)!.length){rows.push([]);rowWidth=0;}rows.at(-1)!.push({ch,i});rowWidth+=cw;});
    let y=H*.72-(rows.length-1)*font*.7;
    for(const row of rows){let x=cue?.layout==='left'?W*.105:(W-row.reduce((v,g)=>v+c.measureText(g.ch).width,0))/2;c.textAlign='left';for(const g of row){const highlightAt=highlight?l.text.indexOf(highlight):-1;const emphasisStart=highlightAt>=0?Array.from(l.text.slice(0,highlightAt)).length:-1;const emphasized=!!highlight&&emphasisStart>=0&&g.i>=emphasisStart&&g.i<emphasisStart+Array.from(highlight).length;c.fillStyle=emphasized||groupPositions.has(g.i)||matched[g.i]===2?accent:matched[g.i]===1?'#c1ccbc':'#657169';c.fillText(g.ch,x,y);x+=c.measureText(g.ch).width;}y+=font*1.4;}
    // Small deterministic particles react to word attacks, never to a wall clock.
    for(let i=0;i<14;i++){const a=noise(i+start+(this.project.motion_plan?.seed||0))*Math.PI*2,r=(.12+(1-attack)*.28)*Math.min(W,H);c.globalAlpha=attack*.55;c.fillStyle=accent;c.fillRect(W/2+Math.cos(a)*r,H*.43+Math.sin(a)*r,2+noise(i)*3,2);}
    c.globalAlpha=1;
  }

  private drawWrapped(text:string,x:number,y:number,maxWidth:number,size:number,outline=false) {
    const c=this.ctx;
    // Fit long phrases by shrinking before wrapping; punctuation and spaces are preserved.
    let fontSize=size;
    while(c.measureText(text).width>maxWidth*2 && fontSize>size*.35){fontSize*=.92;c.font=`900 ${fontSize}px ${FONT}`;}
    const rows:string[]=[''];
    for(const ch of Array.from(text)){const last=rows.length-1;if(c.measureText(rows[last]+ch).width>maxWidth && rows[last])rows.push(ch);else rows[last]+=ch;}
    const fit=Math.min(1,this.H*.42/(rows.length*fontSize*1.12));
    c.save();c.translate(x,y);c.scale(fit,fit);
    rows.forEach((s,i)=>{const yy=(i-(rows.length-1)/2)*fontSize*1.12; if(outline)c.strokeText(s,0,yy);else c.fillText(s,0,yy);});c.restore();
  }

  readPixels(){const bytes=new Uint8Array(this.W*this.H*4);this.renderer.readRenderTargetPixels(this.output,0,0,this.W,this.H,bytes);return bytes;}
  dispose(){this.texture.dispose();this.empty.dispose();this.hdr.dispose();this.output.dispose();this.post.dispose();this.scene.dispose();this.blit.dispose();this.renderer.dispose();}
}
