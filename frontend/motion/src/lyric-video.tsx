import {highlightState} from './karaoke';
import {compileRenderPlan} from './render-plan';
import React, {useEffect,useState,useId} from 'react';
import {AbsoluteFill,Img,useCurrentFrame,useVideoConfig,useDelayRender} from 'remotion';
import {featuresAt,type Project,type Options} from './model';
import {stageAt,visiblePosterAt,canvasMeasure,POSTER_FONT,posterNodeState,posterHoldState,posterExitOpacity,posterRings,introTitleState,type CompiledPoster,type CompiledIntroTitle} from './poster-layout';
import {songLayoutAt,songTextColor,coverPlacement,coverOpacityAt,type SongLayout} from './song-layout';
import {ktvDualStateAt,type KtvDualCompiled,appleScrollStateAt,type AppleScrollCompiled} from './stream-layout';
import {computeAmbientOrbs,computeParticles,hexToRgba} from './ambient-particles';

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
  const compiled=compileRenderPlan(project,options,width,height,measure);
  setLayouts(compiled.layouts);setKtvLayout(compiled.ktvLayout);setAppleLayout(compiled.appleLayout);
  setSongLayout(compiled.songLayout);setIntro(compiled.intro);
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
 const isCoverActive=songFrame.cover||(songLayout?.introEnd?t<songLayout.introEnd:false)||(introState?introState.alpha>0:false);
 const backgroundImage=coverPlacement(project,{x:0,y:0,width,height});
 const artworkImage=songLayout?.artwork?coverPlacement(project,songLayout.artwork):null;
 const pulse=1+(feature.kick||feature.beat*.3)*.012;

 return <AbsoluteFill style={{background:transparent?'transparent':background,overflow:'hidden'}}>
  {!transparent&&backgroundImage&&<Img src={project.song_cover!.data_url} style={{position:'absolute',left:backgroundImage.x,top:backgroundImage.y,width:backgroundImage.width,height:backgroundImage.height,opacity:coverOpacityAt(songLayout,t)}}/>}
  {songFrame.cover&&songLayout?.artwork&&artworkImage&&<div style={{position:'absolute',left:songLayout.artwork.x,top:songLayout.artwork.y,width:songLayout.artwork.width,height:songLayout.artwork.height,overflow:'hidden',opacity:songFrame.alpha,border:'1px solid #ffffff25'}}><Img src={project.song_cover!.data_url} style={{position:'absolute',left:artworkImage.x-songLayout.artwork.x,top:artworkImage.y-songLayout.artwork.y,width:artworkImage.width,height:artworkImage.height}}/></div>}
  <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{overflow:'hidden',position:'absolute'}} aria-label="歌词海报动画">
   {!transparent && (() => {
     const { orb1, orb2 } = computeAmbientOrbs(width, height, t, accent);
     const particles = computeParticles(width, height, t, 48, pulse);
     return (
       <g aria-hidden="true">
         <defs>
           <radialGradient id={`ambient-orb1-${highlightId}`} cx="50%" cy="50%" r="50%">
             <stop offset="0%" stopColor={hexToRgba(accent, 0.14)} />
             <stop offset="50%" stopColor={hexToRgba(accent, 0.04)} />
             <stop offset="100%" stopColor={accent} stopOpacity={0} />
           </radialGradient>
           <radialGradient id={`ambient-orb2-${highlightId}`} cx="50%" cy="50%" r="50%">
             <stop offset="0%" stopColor={hexToRgba(accent, 0.09)} />
             <stop offset="60%" stopColor={hexToRgba(accent, 0.02)} />
             <stop offset="100%" stopColor={accent} stopOpacity={0} />
           </radialGradient>
           <radialGradient id={`ambient-vig-${highlightId}`} cx="50%" cy="50%" r="70%">
             <stop offset="0%" stopColor="#000000" stopOpacity={0} />
             <stop offset="45%" stopColor="#000000" stopOpacity={0} />
             <stop offset="75%" stopColor="#000000" stopOpacity={0.22} />
             <stop offset="100%" stopColor="#000000" stopOpacity={0.65} />
           </radialGradient>
         </defs>
         <circle cx={orb1.cx} cy={orb1.cy} r={orb1.r} fill={`url(#ambient-orb1-${highlightId})`} />
         <circle cx={orb2.cx} cy={orb2.cy} r={orb2.r} fill={`url(#ambient-orb2-${highlightId})`} />
         <g>
           {particles.map((p, idx) => (
             <circle
               key={idx}
               cx={p.x}
               cy={p.y}
               r={p.radius}
               fill={p.color}
               opacity={p.alpha}
             />
           ))}
         </g>
         <rect width={width} height={height} fill={`url(#ambient-vig-${highlightId})`} />
       </g>
     );
   })()}
  <g>
   {!transparent&&(!songFrame.cover||!songLayout?.artwork)&&stage?.motif==='rings'&&posterRings(width,height).map((ring,i)=><ellipse key={i} cx={ring.cx} cy={ring.cy} rx={ring.rx} ry={ring.ry} opacity={ring.opacity} stroke={accent} strokeWidth={Math.min(width,height)*.003} fill="none"/>)}
   {introState&&introState.alpha>0&&intro&&<g opacity={introState.alpha} transform={`translate(${intro.cx} ${intro.cy+introState.dy}) scale(${introState.scale*pulse}) translate(${-intro.cx} ${-intro.cy})`}>
    <text x={intro.x} y={intro.y} fill={intro.color} fontSize={intro.fontSize} fontWeight={intro.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{intro.text}</text>
   </g>}

   {/* Lyric presentation: TV Karaoke dual-line / Apple Scroll / Kinetic Posters */}
   <g>
    {!isCoverActive && activeVisualMode === 'tv' && ktvLayout && (()=>{
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

    {!isCoverActive && activeVisualMode === 'apple' && appleLayout && (()=>{
      const { items, countIn } = appleScrollStateAt(appleLayout, t);
      const maskGradId = `apple-scroll-fade-grad-${highlightId}`;
      const maskId = `apple-scroll-fade-mask-${highlightId}`;
      const ambientGlowId = `apple-ambient-glow-${highlightId}`;

      return (
        <g key="apple-scroll-container">
          <defs>
            {/* 上下边缘柔和羽化遮罩：顶部 16% 与底部 20% 保护留白，确保歌词绝不顶格，平滑融入深色背景 */}
            <linearGradient id={maskGradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fff" stopOpacity="0" />
              <stop offset="16%" stopColor="#fff" stopOpacity="0" />
              <stop offset="28%" stopColor="#fff" stopOpacity="1" />
              <stop offset="68%" stopColor="#fff" stopOpacity="1" />
              <stop offset="80%" stopColor="#fff" stopOpacity="0" />
              <stop offset="100%" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
            <mask id={maskId}>
              <rect x="0" y="0" width={width} height={height} fill={`url(#${maskGradId})`} />
            </mask>
            {/* 焦点位置微弱环境晕光 (Ambient Glow) */}
            <radialGradient id={ambientGlowId} cx="38%" cy="42%" r="55%">
              <stop offset="0%" stopColor={appleLayout.palette.accent} stopOpacity={0.12} />
              <stop offset="50%" stopColor={appleLayout.palette.accent} stopOpacity={0.03} />
              <stop offset="100%" stopColor={appleLayout.palette.background} stopOpacity={0} />
            </radialGradient>
          </defs>

          {/* 氛围晕光底层 */}
          <rect x="0" y="0" width={width} height={height} fill={`url(#${ambientGlowId})`} pointerEvents="none" />

          {/* 歌词流式聚焦渲染（带遮罩羽化） */}
          <g mask={`url(#${maskId})`}>
            {items.map(item => {
              const c = item.compiled;
              const fontSize = Math.round(c.fontSize * item.scale);
              if (!item.isActive) {
                return (
                  <g key={c.lineIndex} opacity={item.alpha}>
                    {c.rows.map((row, rIdx) => (
                      <text
                        key={rIdx}
                        x={row.x}
                        y={item.y + row.yOffset}
                        fill={appleLayout.palette.foreground}
                        fontSize={fontSize}
                        fontWeight={700}
                        fontFamily={POSTER_FONT}
                        style={{whiteSpace:'pre'}}
                      >
                        {row.text}
                      </text>
                    ))}
                  </g>
                );
              }
              return (
                <g key={c.lineIndex} opacity={item.alpha}>
                  {c.rows.map((row, rIdx) => (
                    <text
                      key={rIdx}
                      x={row.x}
                      y={item.y + row.yOffset}
                      fill={appleLayout.palette.foreground}
                      fontSize={fontSize}
                      fontWeight={700}
                      fontFamily={POSTER_FONT}
                      style={{whiteSpace:'pre'}}
                    >
                      {row.text}
                    </text>
                  ))}
                  {item.spansWithProgress.map((sp, k) => {
                    if (sp.progress <= 0) return null;
                    const clipId = `apple-clip-${highlightId}-${c.lineIndex}-${k}`;
                    const targetRow = c.rows[sp.span.row] || c.rows[0];
                    return (
                      <g key={k} aria-hidden="true">
                        <defs>
                          <clipPath id={clipId}>
                            <rect
                              x={sp.span.x}
                              y={item.y + sp.span.top}
                              width={sp.span.width * sp.progress}
                              height={sp.span.height}
                            />
                          </clipPath>
                        </defs>
                        <text
                          x={targetRow.x}
                          y={item.y + targetRow.yOffset}
                          fill={appleLayout.palette.accent}
                          clipPath={`url(#${clipId})`}
                          fontSize={fontSize}
                          fontWeight={700}
                          fontFamily={POSTER_FONT}
                          style={{whiteSpace:'pre'}}
                        >
                          {targetRow.text}
                        </text>
                      </g>
                    );
                  })}
                </g>
              );
            })}

            {/* Apple 伴唱起拍 3 拍小圆点 (Count-in Dots) */}
            {countIn && countIn.overallAlpha > 0.01 && (
              <g opacity={countIn.overallAlpha} key={`apple-count-in-${countIn.targetLineIndex}`}>
                {countIn.dots.map(dot => (
                  <g key={dot.index} transform={`translate(${dot.x}, ${dot.y}) scale(${dot.scale})`}>
                    <circle
                      cx={0}
                      cy={0}
                      r={dot.radius}
                      fill="#ffffff"
                      opacity={dot.alpha}
                    />
                  </g>
                ))}
              </g>
            )}
          </g>
        </g>
      );
    })()}

    {!isCoverActive && activeVisualMode === 'kinetic' && plan?.nodes.map((n,i)=>{
      const state=posterNodeState(n,t,height);
      const {drift,pulse:nodePulse}=posterHoldState(n,t,complete,width,height,feature.kick||feature.beat*.3);
      const cx=n.x+n.width/2,cy=n.y+n.height/2,scale=state.scale*nodePulse;
      return <g key={i} opacity={state.alpha*(plan?posterExitOpacity(plan,n,t):0)} transform={`translate(${cx+state.dx} ${cy+state.dy+drift}) scale(${scale}) translate(${-cx} ${-cy})`} style={state.blur&&state.blur>0.1?{filter:`blur(${state.blur.toFixed(1)}px)`}:undefined}>
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
