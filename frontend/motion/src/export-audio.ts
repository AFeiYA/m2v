/** A lyric video without its song is a failed export, never a silent success. */
export async function decodeExportAudio(source:Blob|string|null):Promise<AudioBuffer>{
 if(!source||typeof (window as any).AudioEncoder==='undefined')throw new Error('Local audio encoding is unavailable.');
 const Context=window.AudioContext||(window as any).webkitAudioContext;
 if(!Context)throw new Error('Local audio decoding is unavailable.');
 let bytes:ArrayBuffer;
 if(source instanceof Blob)bytes=await source.arrayBuffer();
 else{
  const response=await fetch(source);
  if(!response.ok)throw new Error('Unable to load the song for export.');
  bytes=await response.arrayBuffer();
 }
 const context=new Context();
 try{
  const buffer=await context.decodeAudioData(bytes);
  if(!buffer.length)throw new Error('The song audio is empty.');
  return buffer;
 }finally{await context.close();}
}
