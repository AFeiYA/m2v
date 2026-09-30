export type Word = { word: string; start: number; end: number };
export type PhrasePlan = {text:string;word_indices:number[];action:'reveal'|'push'|'settle'|'hold';emphasis:string;intensity:number};
export type PosterDirection = {version:'motion-poster-direction-v1';status:'draft';layout:'hero-stack'|'center-stack'|'staggered';intent:string;background:string;accent:string;motif:'none'|'rings';visibility:'cumulative';final_hold:'available-tail';transition_out:'cut'|'fade';transition_note:string;nodes:{text:string;word_indices:number[];role:'primary'|'secondary'|'support';emphasis:string;color_role:'foreground'|'accent'|'muted';hold?:'none'|'drift';beat_reaction?:'none'|'pulse';entrance:'none'|'fade'|'slide-up'|'slide-left'|'scale-in';settle_fraction:number}[]};
export type CuePlan = {poster?:PosterDirection|null;whole_line_visible?:true;intent?:string;groups?:PhrasePlan[];line_id:string; template:'word-impact'|'phrase-rise'|'quiet-hold'; layout:'center'|'left'; palette:'impact'|'neon'; intensity:number; emphasis:string; locked:boolean};
export type MotionPlan = {version:'motion-plan-v1'; source_signature:string; seed:number; visual_language?:{direction:string;background:string;foreground:string;accent:string;rhythm:string}|null; cues:CuePlan[]};
export type Line = { id:string; text: string; start: number; end: number; words: Word[]; section?: string };
export type Project = {
  title: string; duration: number; lines: Line[]; motion_plan?:MotionPlan;
  analysis: { bpm: number; beats: number[]; drum_hits: {time: number; type: string}[]; energy_curve: {time: number; energy: number}[] };
};
export type Options = {
  aspect: '16:9' | '9:16'; preset: 'impact' | 'neon'; mode: 'slam' | 'phrase';
  height?:360|720; bloom: number; grain: number; shake: number; punch: number; post: boolean;
};
export const defaults: Options = { aspect: '16:9', preset: 'impact', mode: 'slam', bloom: 0.7, grain: 0.035, shake: 0.65, punch: 0.7, post: true };
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
export function normalizeProject(input: any): Project {
  if (!input || typeof input !== 'object') throw new Error('工程 JSON 格式无效。');
  input = input.project || input;
  let source = input.lines;
  if (!Array.isArray(source) && Array.isArray(input.scenes)) {
    source = input.scenes.flatMap((s: any) => (s.layers || []).flatMap((l: any) => l.cues || []));
  }
  if (!Array.isArray(source) || !source.length) throw new Error('文件没有歌词 lines 或动效 scenes，请选择 alignment.json。');
  source = source.map((l:any,i:number)=>({...l,_lineId:l.id||`line_${String(i+1).padStart(4,'0')}`})).filter((l:any)=>!(finite(l.start)&&finite(l.end)&&l.end===l.start));
  if(!source.length)throw new Error('没有有效的歌词时间段。');
  const lines: Line[] = source.map((l: any, i: number) => {
    if (!finite(l.start) || !finite(l.end) || l.start < 0 || l.end <= l.start) throw new Error(`第 ${i + 1} 句的起止时间无效。`);
    const words: Word[] = (l.words || []).map((w: any) => {
      if (!finite(w.start) || !finite(w.end) || w.start < l.start - 0.05 || w.end > l.end + 0.05 || w.end < w.start) throw new Error(`第 ${i + 1} 句的字词时间超出句子范围。`);
      return {word: String(w.word ?? w.w ?? ''), start: w.start, end: w.end};
    }).sort((a: Word, b: Word) => a.start - b.start);
    return {id:l._lineId,text: String(l.text || words.map(w => w.word).join('')), start: l.start, end: l.end, words, section: String(l.section || '')};
  }).sort((a:Line, b:Line) => a.start - b.start);
  const a = input.analysis || input.meta || {};
  const beats = Array.from(new Set<number>((a.beats || []).filter((n: any) => finite(n) && n >= 0))).sort((a,b) => a-b);
  return {
    motion_plan: input.motion_plan, title: String(input.title || input.meta?.title || '未命名歌曲'),
    duration: Math.max(finite(input.duration) ? input.duration : 0, ...lines.map(l => l.end)), lines,
    analysis: {
      bpm: finite(a.bpm) && a.bpm > 0 ? a.bpm : 0, beats,
      drum_hits: (a.drum_hits || []).filter((h: any) => finite(h.time) && h.time >= 0).sort((a: any,b: any) => a.time-b.time),
      energy_curve: (a.energy_curve || []).filter((h: any) => finite(h.time) && finite(h.energy)).sort((a: any,b: any) => a.time-b.time),
    },
  };
}
export function beatPhase(t: number, beats: number[], bpm: number): number {
  if (!beats.length) return 1;
  // No invented pulse before the first detected beat or after the last one.
  if (t < beats[0] || t > beats[beats.length - 1] + (bpm > 0 ? 60 / bpm : 0.5)) return 1;
  let i = upperBound(beats, t) - 1;
  const interval = i + 1 < beats.length ? beats[i+1] - beats[i] : bpm > 0 ? 60 / bpm : 0.5;
  return Math.min(1, (t - beats[i]) / Math.max(0.001, interval));
}
export function upperBound(values: number[], t: number): number {
  let lo = 0, hi = values.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (values[mid] <= t) lo = mid + 1; else hi = mid; }
  return lo;
}
export function pulseAt(t: number, start: number, decay = 15): number { return t >= start ? Math.exp(-(t-start)*decay) : 0; }
export function featuresAt(p: Project, t: number) {
  const a = p.analysis;
  let kick = 0, snare = 0, hat = 0;
  for (const h of a.drum_hits) {
    if (h.time > t) break;
    if (t - h.time > 0.6) continue;
    const v = pulseAt(t, h.time);
    if (h.type === 'kick') kick = Math.max(kick, v);
    if (h.type === 'snare') snare = Math.max(snare, v);
    if (h.type === 'hat') hat = Math.max(hat, v);
  }
  const phase = beatPhase(t, a.beats, a.bpm);
  const beat = phase === 1 ? 0 : Math.exp(-8 * phase);
  let energy = 0;
  const c = a.energy_curve;
  if (c.length) {
    const i = Math.max(0, upperBound(c.map(x=>x.time), t)-1), l = c[i], r = c[Math.min(i+1,c.length-1)];
    const f = Math.max(0, Math.min(1,(t-l.time)/Math.max(0.001,r.time-l.time)));
    energy = Math.max(0, Math.min(1,l.energy+(r.energy-l.energy)*f));
  }
  return {beat, kick, snare, hat, energy, impact: a.drum_hits.length ? Math.max(kick, snare*0.65, hat*0.12) : beat*0.55};
}
export const demo: Project = normalizeProject({
  title: '让文字跟着节奏 · 合成节奏演示', duration: 18,
  lines: ['让文字跟着节奏', '把这一刻放大', '穿过霓虹和夜色', '听见心里的回响'].map((text, i) => {
    const start = 1+i*4, end = start+3.5, chars = Array.from(text);
    return {text, start, end, section: i < 2 ? 'VERSE' : 'CHORUS', words: chars.map((word,j) => ({word,start:start+j*3.5/chars.length,end:start+(j+1)*3.5/chars.length}))};
  }),
  analysis: {bpm:120, beats:Array.from({length:36},(_,i)=>i*0.5), drum_hits:Array.from({length:36},(_,i)=>({time:i*0.5,type:i%2?'snare':'kick'}))},
});
export function demoAudio(): Blob {
  const rate=22050, length=18*rate, buf=new ArrayBuffer(44+length*2), v=new DataView(buf);
  const str=(o:number,s:string)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i));};
  str(0,'RIFF');v.setUint32(4,36+length*2,true);str(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);str(36,'data');v.setUint32(40,length*2,true);
  for(let i=0;i<length;i++) {const t=i/rate, b=Math.floor(t/0.5), d=t-b*0.5; const s=b%2?Math.sin(i*123.456)*Math.exp(-d*32)*0.25:Math.sin(2*Math.PI*(55*d+2*(1-Math.exp(-d*30))))*Math.exp(-d*18)*0.5;v.setInt16(44+i*2,Math.round(s*32767),true);}
  return new Blob([buf],{type:'audio/wav'});
}

export function renderSize(options:Options) {
  const short=options.height||720, long=Math.round(short*16/9);
  return options.aspect==='9:16'?{width:short,height:long}:{width:long,height:short};
}

export function groupAt(line:Line,cue:CuePlan|undefined,t:number) {
  const groups=cue?.groups||[];
  return groups.find(group=>{
    const first=line.words[group.word_indices[0]],last=line.words[group.word_indices.at(-1)!];
    return first&&last&&t>=first.start&&t<last.end;
  });
}
