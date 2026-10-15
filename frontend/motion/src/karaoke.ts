/** Timing is independent of layout. Geometry is compiled once, never during playback. */
export type HighlightMode='none'|'word'|'sweep';
export type HighlightSpan={wordIndex:number;row:number;x:number;y:number;width:number;top:number;height:number;start:number;end:number;fractionStart?:number;fractionEnd?:number};
type Row={text:string;x:number;y:number};
type Measure=(text:string,size:number,weight:number)=>{width:number;advance?:number;ascent:number;descent:number};
const letter=/[\p{L}\p{N}]/u;
function letters(text:string){return Array.from(text).filter(c=>letter.test(c)).map(c=>c.toLocaleLowerCase('en'));}
export function compileHighlightSpans(words:{word:string;start:number;end:number}[],indices:number[],rows:Row[],size:number,weight:number,measure:Measure):HighlightSpan[]{
 if(indices.some(i=>!Number.isInteger(i)||i<0||!words[i]))return [];
 // A left-to-right wipe cannot represent bidirectional shaping safely yet.
 if(rows.some(r=>/[\p{Script=Arabic}\p{Script=Hebrew}]/u.test(r.text)))return [];
 const positions:{row:number;begin:number;end:number;key:string}[]=[];
 rows.forEach((row,i)=>{let offset=0;for(const ch of row.text){if(letter.test(ch))positions.push({row:i,begin:offset,end:offset+ch.length,key:ch.toLocaleLowerCase('en')});offset+=ch.length;}});
 const expected=indices.flatMap(i=>letters(words[i]?.word||''));
 if(!expected.length||expected.length!==positions.length||expected.some((c,i)=>c!==positions[i].key))return [];
 const spans:HighlightSpan[]=[];let cursor=0;
 for(const index of indices){
  const word=words[index],count=letters(word.word).length,part=positions.slice(cursor,cursor+count);cursor+=count;
  for(const rowIndex of new Set(part.map(p=>p.row))){
   const glyphs=part.filter(p=>p.row===rowIndex),row=rows[rowIndex],first=glyphs[0],last=glyphs.at(-1)!;
   const metric=measure(row.text,size,weight);
   const advance=(text:string)=>{const m=measure(text,size,weight);return m.advance??m.width;};
   let begin=first.begin,end=last.end;
   while(begin>0&&/\p{P}/u.test(row.text[begin-1]))begin--;
   while(end<row.text.length&&/\p{P}/u.test(row.text[end]))end++;
   const left=advance(row.text.slice(0,begin)),right=advance(row.text.slice(0,end));
   spans.push({wordIndex:index,row:rowIndex,x:row.x+left,y:row.y,width:Math.max(0,right-left),top:row.y-metric.ascent-1,height:metric.ascent+metric.descent+2,start:word.start,end:word.end,fractionStart:part.indexOf(first)/count,fractionEnd:(part.indexOf(last)+1)/count});
  }
 }
 return spans;
}
export function highlightState(span:HighlightSpan,t:number,mode:HighlightMode){
 if(t<span.start)return {progress:0,active:false};
 if(t>=span.end||span.end<=span.start)return {progress:1,active:false};
 const progress=(t-span.start)/(span.end-span.start),from=span.fractionStart??0,to=span.fractionEnd??1;
 return {progress:mode==='word'?1:Math.max(0,Math.min(1,(progress-from)/Math.max(.00001,to-from))),active:true};
}
