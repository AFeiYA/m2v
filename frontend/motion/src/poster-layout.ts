import {SONG_THEMES} from './song-theme.ts';
import type {Line, CuePlan, PosterDirection, Project} from './model';
export const POSTER_FONT='"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';
export type Metrics={width:number;ascent:number;descent:number};
export type Measure=(text:string,size:number,weight:number)=>Metrics;
export type CompiledNode={motion_strength?:number;text:string;word_indices:number[];role:'primary'|'secondary'|'support';x:number;y:number;width:number;height:number;fontSize:number;weight:number;color:string;rows:{text:string;x:number;y:number}[];start:number;settled:number;hold:'none'|'drift';beat_reaction:'none'|'pulse';entrance:PosterDirection['nodes'][number]['entrance']};
export type CompiledPoster={visual_intensity:'restrained'|'expanded'|'peak';version:'motion-poster-layout-v1';line_id:string;source:'director'|'automatic';width:number;height:number;background:string;accent:string;motif:'none'|'rings';layout:PosterDirection['layout'];transition_out:'cut'|'fade';relations:NonNullable<PosterDirection['relations']>;semantic_arrangement:SemanticApplication[];start:number;end:number;handover?:{mode:'cut'|'fade'|'layered-fade';visible_end:number;exit_start:number;primary_exit_start:number;next_start:number|null};nodes:CompiledNode[]};

export type DefaultLayoutPreset = 'smart' | 'single' | 'two-stack' | 'three-stack' | 'word-by-word' | 'random';
export type StackLayout = 'hero-stack' | 'center-stack' | 'staggered' | 'right-stack';

export type ThemePalette = {
  id: string;
  name: string;
  accent: string;
  accentDark: string;
  accentLight: string;
  backgroundLight: string;
  backgroundDark: string;
  foregroundDark: string;
  foregroundLight: string;
  mutedDark: string;
  mutedLight: string;
  defaultBackground: 'light' | 'dark';
};

export const THEME_PALETTES: Record<string, ThemePalette> = {
  impact: {
    id: 'impact',
    name: '荧绿 · 极速光效',
    accent: '#c8ff00',
    accentDark: '#c8ff00',
    accentLight: '#2a6100',
    backgroundLight: '#f3f6ee',
    backgroundDark: '#0d120a',
    foregroundDark: '#f4f9ed',
    foregroundLight: '#182214',
    mutedDark: '#76876e',
    mutedLight: '#63735e',
    defaultBackground: 'dark'
  },
  neon: {
    id: 'neon',
    name: '霓虹 · 赛博冷蓝',
    accent: '#00f0ff',
    accentDark: '#00f0ff',
    accentLight: '#006080',
    backgroundLight: '#edf5f8',
    backgroundDark: '#070e17',
    foregroundDark: '#eef8fc',
    foregroundLight: '#101c24',
    mutedDark: '#628299',
    mutedLight: '#557082',
    defaultBackground: 'dark'
  },
  sunset: {
    id: 'sunset',
    name: '落日 · 烈焰赤金',
    accent: '#ff5028',
    accentDark: '#ff5028',
    accentLight: '#b82400',
    backgroundLight: '#fcf0ec',
    backgroundDark: '#140907',
    foregroundDark: '#fdf2f0',
    foregroundLight: '#24120e',
    mutedDark: '#946b64',
    mutedLight: '#7a5852',
    defaultBackground: 'dark'
  },
  amber: {
    id: 'amber',
    name: '琥珀 · 暖金流光',
    accent: '#ffbe1a',
    accentDark: '#ffbe1a',
    accentLight: '#8a5500',
    backgroundLight: '#faf5ea',
    backgroundDark: '#141108',
    foregroundDark: '#faf7ed',
    foregroundLight: '#221c10',
    mutedDark: '#91876b',
    mutedLight: '#756a52',
    defaultBackground: 'dark'
  },
  violet: {
    id: 'violet',
    name: '幻紫 · 极光电子',
    accent: '#c084fc',
    accentDark: '#c084fc',
    accentLight: '#611fa1',
    backgroundLight: '#f5effa',
    backgroundDark: '#100818',
    foregroundDark: '#f7f1fc',
    foregroundLight: '#1c1026',
    mutedDark: '#847199',
    mutedLight: '#6b5880',
    defaultBackground: 'dark'
  },
  sakura: {
    id: 'sakura',
    name: '蔷薇 · 抒情粉黛',
    accent: '#ff5c8a',
    accentDark: '#ff5c8a',
    accentLight: '#b01248',
    backgroundLight: '#fbf0f4',
    backgroundDark: '#160810',
    foregroundDark: '#fef1f5',
    foregroundLight: '#26101a',
    mutedDark: '#966c7d',
    mutedLight: '#7d5364',
    defaultBackground: 'dark'
  },
  monochrome: {
    id: 'monochrome',
    name: '极简 · 黑白高对比',
    accent: '#ffffff',
    accentDark: '#ffffff',
    accentLight: '#0a0a0a',
    backgroundLight: '#f4f4f4',
    backgroundDark: '#0d0d0d',
    foregroundDark: '#dcdcdc',
    foregroundLight: '#2a2a2a',
    mutedDark: '#727272',
    mutedLight: '#787878',
    defaultBackground: 'dark'
  }
};

export function resolvePaletteColors(palette = 'impact', backgroundTone: 'light' | 'dark' | 'auto' = 'auto'): {
  background: string;
  accent: string;
  foreground: string;
  muted: string;
} {
  let p = palette;
  if (p === 'random') {
    const keys = Object.keys(THEME_PALETTES);
    p = keys[Math.floor(Math.random() * keys.length)];
  }
  const theme = THEME_PALETTES[p] || THEME_PALETTES.impact;
  const isDark = backgroundTone === 'dark' ? true : backgroundTone === 'light' ? false : theme.defaultBackground === 'dark';
  return {
    background: isDark ? theme.backgroundDark : theme.backgroundLight,
    accent: isDark ? theme.accentDark : theme.accentLight,
    foreground: isDark ? theme.foregroundDark : theme.foregroundLight,
    muted: isDark ? theme.mutedDark : theme.mutedLight
  };
}

export function pickRandomStackLayout(lineOrExclude?: Line | StackLayout, exclude?: StackLayout): StackLayout {
  const line = typeof lineOrExclude === 'object' && lineOrExclude !== null && 'text' in lineOrExclude ? lineOrExclude : undefined;
  const excl = typeof lineOrExclude === 'string' ? lineOrExclude : exclude;
  const pool: StackLayout[] = [
    'center-stack', 'center-stack', 'center-stack',
    'hero-stack', 'hero-stack',
    'staggered', 'staggered',
    'right-stack'
  ];
  const candidates = excl ? pool.filter(l => l !== excl) : pool;
  const finalPool = candidates.length ? candidates : pool;
  if (line) {
    let hash = 0;
    const str = (line.id || '') + ':' + (line.text || '');
    for (let i = 0; i < str.length; i++) hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    const idx = Math.abs(hash) % finalPool.length;
    return finalPool[idx];
  }
  return finalPool[Math.floor(Math.random() * finalPool.length)];
}

export function pickRandomPreset(line: Line): 'smart' | 'single' | 'two-stack' | 'three-stack' | 'word-by-word' {
  const words = line.words?.length || 0;
  const hasHan = /[\p{Script=Han}]/u.test(line.text);
  const units = hasHan ? line.text.replace(/\s+/gu, '').length : words;

  if (units <= 3) {
    const pool: ('single' | 'smart')[] = ['single', 'single', 'smart'];
    return pool[Math.floor(Math.random() * pool.length)];
  }
  if (units <= 7) {
    const pool: ('two-stack' | 'smart' | 'single' | 'word-by-word')[] = [
      'two-stack', 'two-stack', 'smart', 'single', 'word-by-word'
    ];
    return pool[Math.floor(Math.random() * pool.length)];
  }
  const pool: ('three-stack' | 'two-stack' | 'smart')[] = [
    'three-stack', 'three-stack', 'two-stack', 'smart'
  ];
  return pool[Math.floor(Math.random() * pool.length)];
}

const WESTERN_PREPOSITIONS_ARTICLES = new Set([
  'a', 'an', 'the',
  'in', 'on', 'at', 'to', 'of', 'for', 'with', 'by', 'from', 'as', 'into', 'through', 'after', 'over', 'between', 'out', 'against', 'during', 'without', 'before', 'under', 'around', 'among',
  'and', 'but', 'or', 'so', 'yet', 'nor',
  'de', 'des', 'du', 'le', 'la', 'les', 'un', 'une', 'et', 'ou', 'dans', 'en', 'sur', 'pour', 'avec', 'par', 'ce', 'cette', 'ces', 'mon', 'ton', 'son', 'notre', 'votre', 'leur'
]);

function isPrepositionOrArticle(word: string): boolean {
  const clean = word.toLowerCase().replace(/[^\p{Script=Latin}]/gu, '');
  return WESTERN_PREPOSITIONS_ARTICLES.has(clean);
}

function hasPunctuationEnd(word: string): boolean {
  return /[,;—\-\u2014，。！？、；：!\?]$/u.test(word.trim());
}

function range(start: number, end: number): number[] {
  const r: number[] = [];
  for (let i = start; i < end; i++) r.push(i);
  return r;
}

export function joinWordsWithSpacing(words: { word: string }[], indices: number[]): string {
  let text = '';
  for (let k = 0; k < indices.length; k++) {
    const idx = indices[k];
    const w = words[idx].word;
    text += w;
    if (k < indices.length - 1 && !w.endsWith(' ') && idx < words.length - 1) {
      const nextW = words[indices[k + 1]].word;
      if (!nextW.startsWith(' ') && !/^[,.!?;:)\]}'"’”，。！？、；：]/u.test(nextW)) {
        const pCJK = /[\p{Script=Han}]/u.test(w.slice(-1));
        const nCJK = /[\p{Script=Han}]/u.test(nextW[0]);
        if (!(pCJK && nCJK)) {
          text += ' ';
        }
      }
    }
  }
  return text;
}

export function segmentWordByWord(line: Line, maxBlocks = 8): { text: string; word_indices: number[] }[] {
  const hasHan = /[\p{Script=Han}]/u.test(line.text);
  let rawSegments: string[] = [];

  if (hasHan) {
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
      const seg = new Intl.Segmenter('zh-CN', { granularity: 'word' });
      rawSegments = Array.from(seg.segment(line.text))
        .map(s => s.segment.trim())
        .filter(s => s && !/^[\s\p{P}]+$/u.test(s));
    } else {
      rawSegments = line.text.split(/[\s\p{P}]+/u).filter(Boolean);
    }
    if (rawSegments.length <= 1 && line.words.length > 2) {
      rawSegments = [];
      const cleanChars = line.text.replace(/[\s\p{P}]+/gu, '');
      const chunkSize = cleanChars.length <= 6 ? 2 : cleanChars.length <= 10 ? 3 : 4;
      for (let i = 0; i < cleanChars.length; i += chunkSize) {
        rawSegments.push(cleanChars.slice(i, i + chunkSize));
      }
    }
  } else {
    rawSegments = line.text.split(/\s+/u).filter(Boolean);
  }

  let wordIdx = 0;
  const blocks: { text: string; word_indices: number[] }[] = [];
  for (const seg of rawSegments) {
    const cleanSeg = seg.replace(/[\s\p{P}]+/gu, '');
    if (!cleanSeg) continue;
    const indices: number[] = [];
    let accumulated = '';
    while (wordIdx < line.words.length && accumulated.length < cleanSeg.length) {
      indices.push(wordIdx);
      accumulated += line.words[wordIdx].word.replace(/[\s\p{P}]+/gu, '');
      wordIdx++;
    }
    if (indices.length) {
      blocks.push({
        text: joinWordsWithSpacing(line.words, indices),
        word_indices: indices
      });
    }
  }

  if (wordIdx < line.words.length) {
    if (blocks.length > 0) {
      while (wordIdx < line.words.length) {
        blocks[blocks.length - 1].word_indices.push(wordIdx);
        blocks[blocks.length - 1].text += line.words[wordIdx].word;
        wordIdx++;
      }
    } else {
      blocks.push({
        text: joinWordsWithSpacing(line.words, line.words.map((_, i) => i)),
        word_indices: line.words.map((_, i) => i)
      });
    }
  }

  let merged = blocks;
  while (merged.length > maxBlocks) {
    let bestIdx = -1;
    let minLen = Infinity;
    for (let i = 0; i < merged.length; i++) {
      const len = merged[i].text.trim().length;
      if (len < minLen) {
        minLen = len;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) break;
    if (bestIdx < merged.length - 1) {
      const cur = merged[bestIdx], nxt = merged[bestIdx + 1];
      merged.splice(bestIdx, 2, {
        text: cur.text + nxt.text,
        word_indices: [...cur.word_indices, ...nxt.word_indices]
      });
    } else {
      const prv = merged[bestIdx - 1], cur = merged[bestIdx];
      merged.splice(bestIdx - 1, 2, {
        text: prv.text + cur.text,
        word_indices: [...prv.word_indices, ...cur.word_indices]
      });
    }
  }

  return merged.length ? merged : [{ text: line.text, word_indices: line.words.map((_, i) => i) }];
}

export function automaticPoster(line:Line,palette='impact',preset:DefaultLayoutPreset='smart',backgroundTone:'light'|'dark'|'auto'='auto',layoutOverride?:StackLayout):PosterDirection {
  const {background,accent}=resolvePaletteColors(palette,backgroundTone);
  if(!line.words.length){
    return {
      version:'motion-poster-direction-v1',status:'draft',layout:'center-stack',intent:'整句单行居中海报',
      background,accent,motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',
      nodes:[{text:line.text,word_indices:[],role:'primary',emphasis:'',color_role:'accent',entrance:'slide-up',settle_fraction:.25}]
    };
  }
  const N=line.words.length;
  const sliceWords=(indices:number[])=>({
    text:joinWordsWithSpacing(line.words, indices),
    word_indices:indices
  });

  let effectivePreset:DefaultLayoutPreset=preset==='random'?pickRandomPreset(line):preset;
  let customBlocks:{text:string;word_indices:number[]}[]|null=null;

  if(effectivePreset==='smart'){
    const hasHan=/[\p{Script=Han}]/u.test(line.text);
    if(hasHan){
      const parts=line.text.split(/\s+/u).filter(Boolean);
      if(parts.length>=2&&parts.length<=4){
        let offset=0;
        const b:{text:string;word_indices:number[]}[]=[];
        for(const part of parts){
          const indices:number[]=[];let text='';
          while(offset<line.words.length&&text.length<part.length){
            indices.push(offset);text+=line.words[offset++].word;
          }
          if(indices.length)b.push({text,word_indices:indices});
        }
        if(offset===line.words.length&&b.length>=2)customBlocks=b;
      }
      if(!customBlocks){
        const charCount=line.text.replace(/\s+/gu,'').length;
        if(charCount<=4)effectivePreset='single';
        else if(charCount<=8)effectivePreset='two-stack';
        else effectivePreset='three-stack';
      }
    }else{
      const wordCount=line.words.length;
      if(wordCount<=3)effectivePreset='single';
      else if(wordCount<=7)effectivePreset='two-stack';
      else effectivePreset='three-stack';
    }
  }

  const stackLayout:StackLayout=layoutOverride||pickRandomStackLayout(preset==='random'?undefined:line);
  const layoutLabel={'hero-stack':'居左','center-stack':'居中','right-stack':'靠右','staggered':'错落'}[stackLayout];

  if(customBlocks){
    const primary=customBlocks.length-1;
    return {
      version:'motion-poster-direction-v1',status:'draft',layout:stackLayout,intent:(preset==='random'?'随机短语分行海报':'智能短语分行海报')+`（${layoutLabel}）`,
      background,accent,motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',
      nodes:customBlocks.map((b,i)=>({
        ...b,
        role:i===primary?'primary':i===0?'secondary':'support',
        emphasis:'',
        color_role:i===primary?'accent':i===0?'foreground':'muted',
        entrance:'slide-up',
        settle_fraction:.25
      }))
    };
  }

  if(effectivePreset==='single'||N<=1){
    const blocks=[sliceWords(range(0,N))];
    return {
      version:'motion-poster-direction-v1',status:'draft',layout:'center-stack',intent:preset==='random'?'随机单行居中海报':'整句单行居中海报',
      background,accent,motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',
      nodes:[{...blocks[0],role:'primary',emphasis:'',color_role:'accent',entrance:'slide-up',settle_fraction:.25}]
    };
  }

  if(effectivePreset==='two-stack'||(effectivePreset==='three-stack'&&N===2)){
    let bestCut=1,bestScore=Infinity;
    const totalLen=line.words.reduce((sum,w)=>sum+w.word.trim().length,0);
    for(let c=1;c<N;c++){
      const len1=line.words.slice(0,c).reduce((sum,w)=>sum+w.word.trim().length,0);
      const len2=totalLen-len1;
      let score=Math.abs(len1-len2);
      if(hasPunctuationEnd(line.words[c-1].word))score-=15;
      if(isPrepositionOrArticle(line.words[c-1].word))score+=14;
      if(c===1&&isPrepositionOrArticle(line.words[0].word))score+=15;
      if(c===N-1&&line.words[N-1].word.trim().length<=3)score+=12;
      if(score<bestScore){bestScore=score;bestCut=c;}
    }
    const blocks=[sliceWords(range(0,bestCut)),sliceWords(range(bestCut,N))];
    return {
      version:'motion-poster-direction-v1',status:'draft',layout:stackLayout,intent:(preset==='random'?'随机双行对垒海报':'双行对垒海报')+`（${layoutLabel}）`,
      background,accent,motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',
      nodes:[
        {...blocks[0],role:'secondary',emphasis:'',color_role:'foreground',entrance:'slide-up',settle_fraction:.25},
        {...blocks[1],role:'primary',emphasis:'',color_role:'accent',entrance:'slide-up',settle_fraction:.25}
      ]
    };
  }

  if(effectivePreset==='three-stack'){
    let bestC1=1,bestC2=2,bestScore=Infinity;
    const totalLen=line.words.reduce((sum,w)=>sum+w.word.trim().length,0);
    const targetLen=totalLen/3;
    for(let c1=1;c1<N-1;c1++){
      for(let c2=c1+1;c2<N;c2++){
        const len1=line.words.slice(0,c1).reduce((sum,w)=>sum+w.word.trim().length,0);
        const len2=line.words.slice(c1,c2).reduce((sum,w)=>sum+w.word.trim().length,0);
        const len3=line.words.slice(c2).reduce((sum,w)=>sum+w.word.trim().length,0);
        let score=Math.abs(len1-targetLen)+Math.abs(len2-targetLen)+Math.abs(len3-targetLen);
        if(hasPunctuationEnd(line.words[c1-1].word))score-=12;
        if(hasPunctuationEnd(line.words[c2-1].word))score-=12;
        if(isPrepositionOrArticle(line.words[c1-1].word))score+=10;
        if(isPrepositionOrArticle(line.words[c2-1].word))score+=10;
        if(c1===1&&isPrepositionOrArticle(line.words[0].word))score+=12;
        if(c2===c1+1&&isPrepositionOrArticle(line.words[c1].word))score+=12;
        if(c2===N-1&&line.words[N-1].word.trim().length<=3)score+=12;
        if(score<bestScore){bestScore=score;bestC1=c1;bestC2=c2;}
      }
    }
    const blocks=[sliceWords(range(0,bestC1)),sliceWords(range(bestC1,bestC2)),sliceWords(range(bestC2,N))];
    return {
      version:'motion-poster-direction-v1',status:'draft',layout:stackLayout,intent:(preset==='random'?'随机三段阶梯海报':'三段阶梯海报')+`（${layoutLabel}）`,
      background,accent,motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',
      nodes:[
        {...blocks[0],role:'secondary',emphasis:'',color_role:'foreground',entrance:'slide-up',settle_fraction:.25},
        {...blocks[1],role:'support',emphasis:'',color_role:'muted',entrance:'slide-up',settle_fraction:.25},
        {...blocks[2],role:'primary',emphasis:'',color_role:'accent',entrance:'slide-up',settle_fraction:.25}
      ]
    };
  }

  // Preset: 'word-by-word'
  const blocks = segmentWordByWord(line, 8);
  const primary = blocks.reduce((best, b, i) => b.text.length > blocks[best].text.length ? i : best, 0);
  return {
    version: 'motion-poster-direction-v1', status: 'draft', layout: stackLayout,
    intent: (preset === 'random' ? '随机逐词击打海报' : '逐词击打海报') + `（${layoutLabel}）`,
    background, accent, motif: 'none', visibility: 'cumulative', final_hold: 'available-tail', transition_out: 'cut', transition_note: '',
    nodes: blocks.map((b, i) => ({
      ...b, role: i === primary ? 'primary' : 'secondary', emphasis: '', color_role: i === primary ? 'accent' : 'foreground', entrance: 'slide-up', settle_fraction: .25
    }))
  };
}
export function displayText(text:string){
  return text.replace(/\s+/gu,' ').trim().replace(/(?<=\p{Script=Han}) (?=\p{Script=Han})/gu,'');
}
const NO_LINE_START=/^[，。！？、；：”’）》〉】｝〕…—~～,.!?;:)\]}"']/u;
const NO_LINE_END=/^[“‘（《〈【｛〔([<{]/u;

function rowsFor(text:string,size:number,weight:number,maxWidth:number,measure:Measure){
  // Keep English words intact; Chinese may wrap at glyph boundaries while respecting Kinsoku Shori (行首禁则与标点防孤立).
  const tokens=text.match(/[\p{Script=Latin}\p{N}]+(?:['’\-][\p{Script=Latin}\p{N}]+)*|[^\p{Script=Latin}\p{N}]/gu)||[];
  const rows:string[]=[''];
  for(const token of tokens){
    const i=rows.length-1,current=rows[i];
    if(current&&measure(current+token,size,weight).width>maxWidth&&token.trim()){
      if(NO_LINE_START.test(token)){
        const prevTokens=current.match(/[\p{Script=Latin}\p{N}]+(?:['’\-][\p{Script=Latin}\p{N}]+)*|[^\p{Script=Latin}\p{N}]/gu)||[];
        if(prevTokens.length>1){
          const pulled=prevTokens.pop()!;
          rows[i]=prevTokens.join('').trimEnd();
          rows.push(pulled+token);
          continue;
        }
        rows[i]+=token;
      }else{
        if(NO_LINE_END.test(current.slice(-1))){
          const prevTokens=current.match(/[\p{Script=Latin}\p{N}]+(?:['’\-][\p{Script=Latin}\p{N}]+)*|[^\p{Script=Latin}\p{N}]/gu)||[];
          if(prevTokens.length>1){
            const pulled=prevTokens.pop()!;
            rows[i]=prevTokens.join('').trimEnd();
            rows.push(pulled+token.trimStart());
            continue;
          }
        }
        rows.push(token.trimStart());
      }
    }else rows[i]+=token;
  }
  const cleaned=rows.map(row=>row.trim()).filter(Boolean);
  const result:string[]=[];
  for(const row of cleaned){
    if(result.length&&!/[\p{Script=Han}\p{Script=Latin}\p{N}]/u.test(row)){
      result[result.length-1]+=row;
    }else result.push(row);
  }
  return result;
}
function fitTitle(text:string,size:number,weight:number,maxWidth:number,W:number,measure:Measure,emphasis:string,portrait:boolean){
  const chars=Array.from(text),count=chars.length;
  const fit=(rows:string[])=>Math.min(size,...rows.map(row=>size*maxWidth/Math.max(1,measure(row,size,weight).width)))*.99;
  // Short phrases should not acquire an orphan merely because the default size is large.
  const single=fit([text]);
  if(count<=4)return {size:single,rows:[text]};
  if(portrait?(count<=5||count<=6&&single>=W*.135):single>=size*.72)return {size:single,rows:[text]};
  if(count>12||!/\p{Script=Han}/u.test(text))return null;
  const boundaries=new Set<number>();
  const segmenter=new Intl.Segmenter('zh',{granularity:'word'});
  for(const segment of segmenter.segment(text))boundaries.add(Array.from(text.slice(0,segment.index+segment.segment.length)).length);
  const focus=text.indexOf(emphasis),focusStart=emphasis&&focus>=0?Array.from(text.slice(0,focus)).length:-1;
  const focusEnd=focusStart<0?-1:focusStart+Array.from(emphasis).length;
  let best:{size:number;rows:string[];score:number}|null=null;
  // Compare balanced alternatives using measured widths and soft lexical boundaries.
  for(let i=2;i<=count-2;i++){
    const row0=chars.slice(0,i).join(''),row1=chars.slice(i).join('');
    if(NO_LINE_START.test(row1)||NO_LINE_END.test(row0.slice(-1)))continue;
    const rows=[row0,row1],candidate=fit(rows);
    const score=(size-candidate)/size+Math.abs(i-(count-i))/count*.35+(boundaries.has(i)?0:1.2)+(i>focusStart&&i<focusEnd?2:0);
    if(!best||score<best.score)best={size:candidate,rows,score};
  }
  return best;
}
export type SemanticApplication={kind:NonNullable<PosterDirection['relations']>[number]['kind'];node_indices:number[];status:'applied'|'limited'|'disabled';effects:string[]};
export function resolveSemanticDirection(source:PosterDirection){
  const design={...source,nodes:source.nodes.map(n=>({...n,word_indices:[...n.word_indices]}))};
  const hints=source.nodes.map(()=>({scale:1,offset:0}));
  const applications:SemanticApplication[]=[];
  // Stable priority: structure first, reading hierarchy second, repeated motion last.
  const order={spatial:0,contrast:1,guidance:2,negation:3,repetition:4};
  for(const relation of [...(source.relations||[])].sort((a,b)=>order[a.kind]-order[b.kind])){
    const refs=relation.node_indices;
    const entry:SemanticApplication={kind:relation.kind,node_indices:[...refs],status:'applied',effects:[]};applications.push(entry);
    if(source.semantic_mode==='off'){entry.status='disabled';entry.effects=['已使用手工参数'];continue;}
    if(!refs.length||new Set(refs).size!==refs.length||refs.some(i=>!Number.isInteger(i)||!design.nodes[i])){entry.status='limited';entry.effects=['引用无效，保持原参数'];continue;}
    const focus=refs.find(i=>design.nodes[i].role==='primary')??refs.at(-1)!;
    const common=design.nodes[refs[0]].entrance;
    switch(relation.kind){
      case 'guidance':
        for(const i of refs){const n=design.nodes[i];if(i!==focus){hints[i].scale*=.9;n.color_role='muted';n.entrance='fade';n.settle_fraction=Math.min(n.settle_fraction,.18);}else{n.entrance=n.role==='primary'?'scale-in':'slide-up';n.color_role=n.role==='primary'?'accent':'foreground';}}
        entry.effects=['铺垫轻快落位，焦点承接；主次角色保持原样'];break;
      case 'contrast':
        if(refs.length<2){entry.status='limited';entry.effects=['单块对照保留原排版'];break;}
        for(const [j,i] of refs.entries()){hints[i].offset=j%2?.018:-.018;design.nodes[i].entrance=common;if(design.nodes[i].role!=='primary')hints[i].scale*=1.12;}
        entry.effects=['有限左右错位，相同入场语法，辅文稍增权重'];break;
      case 'negation':
        for(const i of refs){const n=design.nodes[i];n.color_role=i===focus?(n.role==='primary'?'accent':'foreground'):'muted';n.entrance=i===focus?(n.role==='primary'?'scale-in':'slide-up'):'fade';}
        entry.effects=['弱化铺垫，突出判断对象；不新增主标题'];break;
      case 'repetition':
        if(refs.length<2){entry.status='limited';entry.effects=['单块内部重复暂不拆成子动画'];break;}
        for(const i of refs){design.nodes[i].entrance=common;design.nodes[i].settle_fraction=design.nodes[refs[0]].settle_fraction;}
        entry.effects=['重复块复用入场样式和相对落位时长'];break;
      case 'spatial':
        if(refs.length<2){entry.status='limited';entry.effects=['单块空间意象保持原构图'];break;}
        for(const [j,i] of refs.entries()){hints[i].offset=j%2?.018:-.018;design.nodes[i].entrance='slide-up';}
        entry.effects=['有限错位建立层次，主视觉驻留微动；不猜上下或三维方向'];break;
    }
  }
  for(const hint of hints)hint.scale=Math.max(.8,Math.min(1.15,hint.scale));
  return {design,hints,applications};
}
export function compilePoster(line:Line,cue:CuePlan|undefined,W:number,H:number,measure:Measure):CompiledPoster {
  const semantic=resolveSemanticDirection(cue?.poster||automaticPoster(line,cue?.palette)),{design,hints}=semantic;
  const rgb=design.background.slice(1).match(/../g)!.map(v=>parseInt(v,16)/255);
  const dark=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]<.45;
  const themeMatch = Object.values(THEME_PALETTES).find(t =>
    t.backgroundDark.toLowerCase() === design.background.toLowerCase() ||
    t.backgroundLight.toLowerCase() === design.background.toLowerCase() ||
    t.accentDark.toLowerCase() === design.accent.toLowerCase() ||
    t.accentLight.toLowerCase() === design.accent.toLowerCase()
  );
  const foreground = themeMatch ? (dark ? themeMatch.foregroundDark : themeMatch.foregroundLight) : (dark ? '#f4f9ed' : '#182214');
  const muted = themeMatch ? (dark ? themeMatch.mutedDark : themeMatch.mutedLight) : (dark ? '#76876e' : '#63735e');
  const dense=Array.from(line.text.replace(/\s/g,'')).length/Math.max(.001,line.end-line.start)>6;
  const nodes:CompiledNode[]=[];
  const short=Array.from(line.text.replace(/\s/g,'')).length<=6;
  const section=(line.section||'').toLowerCase();
  const portrait=H>W,chorus=section.includes('chorus')||section.includes('副歌'),verse=section.includes('verse')||section.includes('主歌');
  const requested=design.visual_intensity||'auto';
  const resolved=requested==='auto'?(verse||/bridge|outro|桥段|尾奏/.test(section)?'restrained':'expanded'):requested;
  const visual_intensity=dense&&resolved==='peak'?'expanded':resolved;
  const strength={restrained:{size:.82,motion:.65},expanded:{size:1,motion:1},peak:{size:1.12,motion:1.12}}[visual_intensity];
  const maxHeight=H*(portrait?(dense?.40:chorus?.48:.44):(dense?.48:chorus?.66:verse?.48:.56));
  const gap=portrait?W*.012:H*.009,padding=portrait?W*.012:H*.008,width=W*(portrait?.78:.80);
  const fitted=design.nodes.map((n,index)=>{
    const weight=n.role==='primary'?900:n.role==='secondary'?800:600;
    let size=portrait?W*(n.role==='primary'?(short?.30:.22):n.role==='secondary'?.075:.055):H*(n.role==='primary'?(short?.28:.18):n.role==='secondary'?.07:.045);
    size*=hints[index].scale*strength.size;
    const maxWidth=width-W*.018;
    const text=displayText(n.text),focus=displayText(n.emphasis);
    const longestWord=Math.max(0,...(text.match(/[\p{Script=Latin}\p{N}]+(?:['’\-][\p{Script=Latin}\p{N}]+)*/gu)||[]).map(word=>measure(word,size,weight).width));
    if(longestWord>maxWidth)size*=maxWidth/longestWord*.99;
    const title=n.role==='primary'?fitTitle(text,size,weight,maxWidth,W,measure,focus,portrait):null;
    if(title)size=title.size;
    let rows=title?.rows||rowsFor(text,size,weight,maxWidth,measure);
    if(Array.from(text.replace(/\s/gu,'')).length<=4){
      rows=[text.trim()];
      const w=measure(rows[0],size,weight).width;
      if(w>maxWidth)size*=(maxWidth/w)*.99;
    }
    for(let attempt=0;attempt<100&&rows.length>3;attempt++){size*=.92;rows=rowsFor(text,size,weight,maxWidth,measure);}
    return {n,text,weight,size,rows,maxWidth};
  });
  const primarySize=fitted.find(f=>f.n.role==='primary')!.size;
  for(const f of fitted)if(f.n.role!=='primary'&&f.size>primarySize*.55){
    f.size=primarySize*.55;
    f.rows=Array.from(f.text.replace(/\s/gu,'')).length<=4?[f.text.trim()]:rowsFor(f.text,f.size,f.weight,f.maxWidth,measure);
  }
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
    const shift=W*hints[i].offset;
    const x=(W-width)/2+shift;
    const baseline=y+padding+measure(rows[0],size,weight).ascent;

    let nodeAlign: 'left' | 'center' | 'right' = 'left';
    let stagShift = 0;
    if(design.layout === 'center-stack'){
      nodeAlign = 'center';
    } else if(design.layout === 'right-stack'){
      nodeAlign = 'right';
    } else if(design.layout === 'staggered'){
      if(fitted.length <= 1) {
        nodeAlign = 'center';
      } else if(fitted.length === 2) {
        nodeAlign = i === 0 ? 'left' : 'right';
        stagShift = i === 0 ? -W * 0.025 : W * 0.025;
      } else if(fitted.length === 3) {
        nodeAlign = i === 0 ? 'left' : i === 1 ? 'right' : 'center';
        stagShift = i === 0 ? -W * 0.025 : i === 1 ? W * 0.025 : 0;
      } else {
        nodeAlign = i % 2 === 0 ? 'left' : 'right';
        stagShift = i % 2 === 0 ? -W * 0.025 : W * 0.025;
      }
    } else {
      nodeAlign = 'left';
    }

    const resolved = rows.map((text, j) => {
      const rw = measure(text, size, weight).width;
      let rx = leftAxis;
      if(nodeAlign === 'center'){
        rx = leftAxis + (blockWidth - rw) / 2;
      } else if(nodeAlign === 'right'){
        rx = leftAxis + (blockWidth - rw);
      } else {
        rx = leftAxis;
      }
      return { text, x: rx + stagShift + shift, y: baseline + j * size * 1.04 };
    });

    const a=line.words[n.word_indices[0]],b=line.words[n.word_indices.at(-1)!];
    const start=Math.max(line.start,a?.start??line.start),end=Math.min(line.end,b?.end??line.end);
    const entrance=n.entrance!=='none'&&(dense||end-start<.16)?'fade':n.entrance;
    const duration=entrance==='none'?0:Math.min(.6,Math.max(1/30,(end-start)*n.settle_fraction),Math.max(0,(line.end-start)*.5));
    nodes.push({motion_strength:strength.motion,text:n.text,role:n.role,word_indices:[...n.word_indices],x,y,width,height,fontSize:size,weight,color:n.color_role==='accent'?design.accent:n.color_role==='muted'?muted:foreground,rows:resolved,start,settled:start+duration,hold:'none',beat_reaction:n.role==='primary'&&!dense?(n.beat_reaction||'none'):'none',entrance});
    y+=height+gap;
  }
  return {visual_intensity,version:'motion-poster-layout-v1',line_id:line.id,source:cue?.poster?'director':'automatic',width:W,height:H,background:design.background,accent:design.accent,motif:design.motif,layout:design.layout,transition_out:design.transition_out,semantic_arrangement:semantic.applications,relations:(design.relations||[]).map(r=>({...r,node_indices:[...r.node_indices]})),start:line.start,end:line.end,nodes};
}
// Song stage remains continuous; saved direction and alignment are not mutated.
export function compileSongPosters(project:Project,W:number,H:number,measure:Measure):CompiledPoster[]{
  const choice=project.song_identity?.visual_theme;
  const theme=choice&&choice!=='director'?SONG_THEMES[choice]:undefined;
  const first=project.motion_plan?.cues.find(c=>c.poster)?.poster;
  const visual=project.motion_plan?.visual_language;
  const background=theme?.background||visual?.background||first?.background||THEME_PALETTES.impact.backgroundDark;
  const accent=theme?.accent||visual?.accent||first?.accent||THEME_PALETTES.impact.accentDark;
  const motif=theme?.motif||first?.motif||'none';
  const recurring=new Map<string,PosterDirection>();
  const layouts=project.lines.map(line=>{
    const cue=project.motion_plan?.cues.find(c=>c.line_id===line.id);
    let design=cue?.poster||automaticPoster(line,cue?.palette);
    const key=line.text.replace(/\s/g,''),previous=recurring.get(key);
    if(previous&&!cue?.locked&&previous.nodes.length===design.nodes.length&&previous.nodes.every((n,i)=>n.text===design.nodes[i].text)){
      design={...design,layout:previous.layout,nodes:design.nodes.map((n,i)=>({...n,role:previous.nodes[i].role,color_role:previous.nodes[i].color_role}))};
    }else if(!previous)recurring.set(key,design);
    const result=compilePoster(line,{...cue,palette:theme?.palette||cue?.palette,poster:{...design,background,accent:theme?.accent||cue?.poster?.accent||design.accent||accent,motif}} as CuePlan,W,H,measure);
    if(theme)for(const node of result.nodes){node.motion_strength=Math.min(node.motion_strength??1,theme.motion);if(theme!==SONG_THEMES.neon)node.beat_reaction='none';}
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
  const strength=node.motion_strength??1;
  return {alpha:node.entrance==='none'?1:ease,dx:node.entrance==='slide-left'?-(1-ease)*H*.025*strength:0,dy:node.entrance==='slide-up'?(1-ease)*H*.025*strength:0,scale:node.entrance==='scale-in'?1-.08*strength*(1-ease):1};
}
// Frame-time based and shared by preview, static canvas review and video export.
export function posterHoldState(node:CompiledNode,t:number,complete:number,W:number,H:number,beat=0){
  const strength=node.motion_strength??1;
  const drift=0; // Disabled even for previously compiled/saved drift nodes.
  const pulse=t>=complete&&node.beat_reaction==='pulse'?1+Math.max(0,Math.min(1,beat))*.012*strength:1;
  return {drift,pulse};
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
export function paintCompiledPoster(c:CanvasRenderingContext2D,plan:CompiledPoster,t?:number,beat=0,paintBackground=true){
  const W=plan.width,H=plan.height;c.save();if(paintBackground){c.clearRect(0,0,W,H);c.fillStyle=plan.background;c.fillRect(0,0,W,H);}
  c.globalAlpha=1;
  if(plan.motif==='rings'){c.strokeStyle=plan.accent;c.lineWidth=Math.min(W,H)*.003;for(const ring of posterRings(W,H)){c.globalAlpha=ring.opacity;c.beginPath();c.ellipse(ring.cx,ring.cy,ring.rx,ring.ry,0,0,Math.PI*2);c.stroke();}c.globalAlpha=1;}
  const complete=Math.max(...plan.nodes.map(n=>n.settled));
  const alpha=c.globalAlpha;c.textAlign='left';c.textBaseline='alphabetic';
  for(const n of plan.nodes){const state=t===undefined?{alpha:1,dx:0,dy:0,scale:1}:posterNodeState(n,t,H);if(!state.alpha)continue;
    c.save();c.globalAlpha=alpha*state.alpha*(t===undefined?1:posterExitOpacity(plan,n,t));
    const {drift,pulse}=t===undefined?{drift:0,pulse:1}:posterHoldState(n,t,complete,W,H,beat);
    c.translate(n.x+n.width/2+state.dx,n.y+n.height/2+state.dy+drift);c.scale(state.scale*pulse,state.scale*pulse);
    c.font=`${n.weight} ${n.fontSize}px ${POSTER_FONT}`;c.fillStyle=n.color;
    for(const row of n.rows)c.fillText(row.text,row.x-(n.x+n.width/2),row.y-(n.y+n.height/2));c.restore();
  }c.restore();
}
export function canvasMeasure(c:CanvasRenderingContext2D):Measure{return (text,size,weight)=>{c.font=`${weight} ${size}px ${POSTER_FONT}`;const m=c.measureText(text);return {width:Math.max(m.width,(m.actualBoundingBoxLeft||0)+(m.actualBoundingBoxRight||m.width)),ascent:m.actualBoundingBoxAscent||size*.85,descent:m.actualBoundingBoxDescent||size*.15};};}

export type CompiledIntroTitle={text:string;fontSize:number;weight:number;color:string;x:number;y:number;cx:number;cy:number;start:number;settled:number;exitStart:number;end:number};

export function compileIntroTitle(project:Project,W:number,H:number,measure:Measure):CompiledIntroTitle|null{
  const rawTitle=(project.title||'').trim();
  const text=displayText(rawTitle);
  const firstStart=project.lines?.[0]?.start??0;
  if(!text||firstStart<.35)return null;

  const firstCue=project.motion_plan?.cues.find(c=>c.poster)?.poster;
  const visual=project.motion_plan?.visual_language;
  const background=visual?.background||firstCue?.background||THEME_PALETTES.impact.backgroundDark;
  const rgb=background.slice(1).match(/../g)!.map(v=>parseInt(v,16)/255);
  const dark=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]<.45;
  const color=dark?'#f4f9ed':'#182214';

  const portrait=H>W;
  const weight=800;
  const maxWidth=W*.82;
  // Fixed single line layout
  let size=portrait?W*.11:H*.12;
  const m=measure(text,size,weight).width;
  if(m>maxWidth)size*=(maxWidth/m)*.99;
  const textWidth=measure(text,size,weight).width;
  const ascent=measure(text,size,weight).ascent;
  const descent=measure(text,size,weight).descent;

  const cx=W/2;
  const cy=H*(portrait?.46:.48);
  const x=cx-textWidth/2;
  const y=cy+(ascent-descent)/2;

  const enterDuration=Math.min(.8,Math.max(.2,firstStart*.2));
  const exitDuration=Math.min(.5,Math.max(.2,firstStart*.15));
  const settled=enterDuration;
  const exitStart=Math.max(settled,firstStart-exitDuration);

  return {text,fontSize:size,weight,color,x,y,cx,cy,start:0,settled,exitStart,end:firstStart};
}

export function introTitleState(intro:CompiledIntroTitle,t:number,H:number){
  if(t<intro.start||t>=intro.end)return {alpha:0,scale:1,dy:0};
  let enterAlpha=1,enterScale=1,dy=0;
  if(t<intro.settled){
    const p=intro.settled>intro.start?clamp((t-intro.start)/(intro.settled-intro.start)):1;
    const ease=1-Math.pow(1-p,3);
    enterAlpha=ease;enterScale=.94+.06*ease;dy=(1-ease)*H*.02;
  }
  let exitAlpha=1;
  if(t>=intro.exitStart){
    const p=intro.end>intro.exitStart?clamp((intro.end-t)/(intro.end-intro.exitStart)):0;
    exitAlpha=p;
  }
  return {alpha:enterAlpha*exitAlpha,scale:enterScale,dy};
}

