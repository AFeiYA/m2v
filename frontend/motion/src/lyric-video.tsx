import {highlightState} from './karaoke';
import React, {useEffect,useState,useId} from 'react';
import {AbsoluteFill,Img,useCurrentFrame,useVideoConfig,useDelayRender} from 'remotion';
import {featuresAt,type Project,type Options} from './model';
import {compileSongPosters,stageAt,visiblePosterAt,canvasMeasure,POSTER_FONT,posterNodeState,posterHoldState,posterExitOpacity,posterRings,compileIntroTitle,introTitleState,resolvePaletteColors,type CompiledPoster,type CompiledIntroTitle} from './poster-layout';
import {compileSongLayout,songLayoutAt,songTextColor,coverPlacement,coverOpacityAt,type SongLayout} from './song-layout';
import {compileKtvDualLayout,ktvDualStateAt,type KtvDualCompiled,compileAppleScrollLayout,appleScrollStateAt,type AppleScrollCompiled} from './stream-layout';

export type VideoProps={project:Project;options:Options;timeOffset?:number;renderLength?:number;transparent?:boolean;surface?:{width:number;height:number}};

export const LyricVideo:React.FC<VideoProps>=({project,options,timeOffset=0,transparent=false,surface})=>{
 const highlightId=useId().replace(/:/g,'');
 const frame=useCurrentFrame(),config=useVideoConfig(),{fps}=config,{width,height}=surface||config,t=timeOffset+frame/fps;
 const {delayRender,continueRender,cancelRender}=useDelayRender();
 const [handle]=useState(()=>delayRender('等待字体与排版'));
 const [layouts,setLayouts]=useState<CompiledPoster[]|null>(null);
 const [ktvLayout,setKtvLayout]=useState<KtvDualCompiled|null>(null);
 const [appleLayout,setAppleLayout]=useState<AppleScrollCompiled|null>(null);
 const [songLayout,setSongLayout]=useState<SongLayout|null>(null);
 const [intro,setIntro]=useState<CompiledIntroTitle|null>(null);

 const activeVisualMode = options?.visualMode || 'kinetic';

 useEffect(()=>{let active=true;(async()=>{await document.fonts.ready;if(!active)return;
  const context=document.createElement('canvas').getContext('2d')!;
  const measure=canvasMeasure(context);
  const basePaletteName = project.motion_plan?.cues?.[0]?.palette || 'impact';
  const palette = resolvePaletteColors(basePaletteName, 'auto');

  if (activeVisualMode === 'tv') {
    setKtvLayout(compileKtvDualLayout(project, width, height, measure, palette));
    setLayouts(null);
    setAppleLayout(null);
  } else if (activeVisualMode === 'apple') {
    setAppleLayout(compileAppleScrollLayout(project, width, height, measure, palette));
    setLayouts(null);
    setKtvLayout(null);
  } else {
    setLayouts(compileSongPosters(project, width, height, measure));
    setKtvLayout(null);
    setAppleLayout(null);
  }

  const introResult=project.song_identity?null:compileIntroTitle(project,width,height,measure);
  setSongLayout(compileSongLayout(project,width,height,measure));
  setIntro(introResult);
  continueRender(handle);
 })().catch(cancelRender);return()=>{active=false;};},[project,activeVisualMode,width,height,handle,continueRender,cancelRender]);

 const isReady = (activeVisualMode === 'tv' && ktvLayout) || (activeVisualMode === 'apple' && appleLayout) || (activeVisualMode === 'kinetic' && layouts);
 if(!isReady)return <AbsoluteFill style={{background:'#0d120a'}}/>;

 const plan=layouts?visiblePosterAt(layouts,t):undefined;
 const stage=layouts?stageAt(layouts,t):undefined;
 const background = stage?.background || (ktvLayout || appleLayout)?.palette.background || '#0d120a';
 const accent = stage?.accent || (ktvLayout || appleLayout)?.palette.accent || '#b7f34a';

 const feature=featuresAt(project,t);
 const complete=plan?Math.max(...plan.nodes.map(n=>n.settled)):Infinity;
 const introState=intro?introTitleState(intro,t,height):null;
 const songFrame=songLayoutAt(songLayout,t);
 const backgroundImage=coverPlacement(project,{x:0,y:0,width,height});
 const artworkImage=songLayout?.artwork?coverPlacement(project,songLayout.artwork):null;
 const pulse=1+(feature.kick||feature.beat*.3)*.012;

 return <AbsoluteFill style={{background:transparent?'transparent':background,overflow:'hidden'}}>
  {!transparent&&backgroundImage&&<Img src={project.song_cover!.data_url} style={{position:'absolute',left:backgroundImage.x,top:backgroundImage.y,width:backgroundImage.width,height:backgroundImage.height,opacity:coverOpacityAt(songLayout,t)}}/>}
  {songFrame.cover&&songLayout?.artwork&&artworkImage&&<div style={{position:'absolute',left:songLayout.artwork.x,top:songLayout.artwork.y,width:songLayout.artwork.width,height:songLayout.artwork.height,overflow:'hidden',opacity:songFrame.alpha,border:'1px solid #ffffff25'}}><Img src={project.song_cover!.data_url} style={{position:'absolute',left:artworkImage.x-songLayout.artwork.x,top:artworkImage.y-songLayout.artwork.y,width:artworkImage.width,height:artworkImage.height}}/></div>}
  <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{overflow:'hidden',position:'absolute'}} aria-label="歌词海报动画">
  <g>
   {!transparent&&(!songFrame.cover||!songLayout?.artwork)&&stage?.motif==='rings'&&posterRings(width,height).map((ring,i)=><ellipse key={i} cx={ring.cx} cy={ring.cy} rx={ring.rx} ry={ring.ry} opacity={ring.opacity} stroke={accent} strokeWidth={Math.min(width,height)*.003} fill="none"/>)}
   {introState&&introState.alpha>0&&intro&&<g opacity={introState.alpha} transform={`translate(${intro.cx} ${intro.cy+introState.dy}) scale(${introState.scale*pulse}) translate(${-intro.cx} ${-intro.cy})`}>
    <text x={intro.x} y={intro.y} fill={intro.color} fontSize={intro.fontSize} fontWeight={intro.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{intro.text}</text>
   </g>}

   {/* Lyric presentation: TV Karaoke dual-line / Apple Scroll / Kinetic Posters */}
   <g>
    {!songFrame.cover && activeVisualMode === 'tv' && ktvLayout && (()=>{
      const { upper, lower } = ktvDualStateAt(ktvLayout, t);
      const slots = [upper, lower].filter((s): s is NonNullable<typeof upper> => Boolean(s));
      return slots.map(slot => {
        const c = slot.compiled;
        const textColor = slot.phase === 'stay' ? slot.sungColor : slot.dimColor;
        return (
          <g key={c.lineIndex}>
            <text x={c.x} y={c.y} fill={textColor} fontSize={c.fontSize} fontWeight={700} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>
              {c.line.text}
            </text>
            {slot.phase === 'active' && slot.spansWithProgress.map((item, k) => {
              if (item.progress <= 0) return null;
              const clipId = `ktv-clip-${highlightId}-${c.lineIndex}-${k}`;
              return (
                <g key={k} aria-hidden="true">
                  <defs>
                    <clipPath id={clipId}>
                      <rect x={item.span.x} y={item.span.top} width={item.span.width * item.progress} height={item.span.height} />
                    </clipPath>
                  </defs>
                  <text x={c.x} y={c.y} fill={slot.sungColor} clipPath={`url(#${clipId})`} fontSize={c.fontSize} fontWeight={700} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>
                    {c.line.text}
                  </text>
                </g>
              );
            })}
          </g>
        );
      });
    })()}

    {!songFrame.cover && activeVisualMode === 'apple' && appleLayout && (()=>{
      const { items } = appleScrollStateAt(appleLayout, t);
      const startX = Math.round(width * 0.12);
      return items.map(item => {
        const c = item.compiled;
        const fontSize = Math.round(c.fontSize * item.scale);
        if (!item.isActive) {
          return (
            <text key={c.lineIndex} x={startX} y={item.y} fill={appleLayout.palette.foreground} opacity={item.alpha} fontSize={fontSize} fontWeight={700} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>
              {c.text}
            </text>
          );
        }
        return (
          <g key={c.lineIndex} opacity={item.alpha}>
            <text x={startX} y={item.y} fill={appleLayout.palette.foreground} fontSize={fontSize} fontWeight={700} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>
              {c.text}
            </text>
            {item.spansWithProgress.map((sp, k) => {
              if (sp.progress <= 0) return null;
              const clipId = `apple-clip-${highlightId}-${c.lineIndex}-${k}`;
              return (
                <g key={k} aria-hidden="true">
                  <defs>
                    <clipPath id={clipId}>
                      <rect x={sp.span.x} y={item.y - Math.round(c.fontSize * 0.9)} width={sp.span.width * sp.progress} height={Math.round(c.fontSize * 1.3)} />
                    </clipPath>
                  </defs>
                  <text x={startX} y={item.y} fill={appleLayout.palette.accent} clipPath={`url(#${clipId})`} fontSize={fontSize} fontWeight={700} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>
                    {c.text}
                  </text>
                </g>
              );
            })}
          </g>
        );
      });
    })()}

    {!songFrame.cover && activeVisualMode === 'kinetic' && plan?.nodes.map((n,i)=>{
      const state=posterNodeState(n,t,height);
      const {drift,pulse:nodePulse}=posterHoldState(n,t,complete,width,height,feature.kick||feature.beat*.3);
      const cx=n.x+n.width/2,cy=n.y+n.height/2,scale=state.scale*nodePulse;
      return <g key={i} opacity={state.alpha*(plan?posterExitOpacity(plan,n,t):0)} transform={`translate(${cx+state.dx} ${cy+state.dy+drift}) scale(${scale}) translate(${-cx} ${-cy})`}>
       {n.rows.map((row,j)=><text key={j} x={row.x} y={row.y} fill={n.highlight?n.highlight.pending:n.color} fontSize={n.fontSize} fontWeight={n.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{row.text}</text>)}
       {n.highlight?.spans.map((span,k)=>{const state=highlightState(span,t,n.highlight!.mode);if(!state.progress)return null;const row=n.rows[span.row],id=`karaoke-${highlightId}-${i}-${k}`;return <g key={k} aria-hidden="true"><defs><clipPath id={id}><rect x={span.x} y={span.top} width={span.width*state.progress} height={span.height}/></clipPath></defs><text x={row.x} y={row.y} fill={state.active?n.highlight!.accent:n.highlight!.foreground} clipPath={`url(#${id})`} fontSize={n.fontSize} fontWeight={n.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{row.text}</text></g>;})}
      </g>;
    })}
   </g>

   <g opacity={songFrame.alpha}>
    {songFrame.rule&&<line x1={width*.07} x2={width*.93} y1={height*(songFrame.cover?(songLayout?.artwork?.82:.3):.125)} y2={height*(songFrame.cover?(songLayout?.artwork?.82:.3):.125)} stroke={accent} strokeWidth={Math.max(1,Math.min(width,height)*.0015)} opacity={.5}/>}
    {songFrame.texts.map((item,i)=><text key={i} x={item.x} y={item.y} fill={songTextColor(background)} fontSize={item.fontSize} fontWeight={item.weight} textAnchor={item.anchor} fontFamily={POSTER_FONT}>{item.text}</text>)}
    {songFrame.section&&<text x={width*.07} y={height*(height>width?.84:.94)} fill={accent} fontSize={Math.min(width,height)*.022} fontFamily={POSTER_FONT}>{songFrame.section}</text>}
   </g>
  </g>
 </svg></AbsoluteFill>;
};
