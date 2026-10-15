import React, { useLayoutEffect, useMemo, useRef } from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig, useDelayRender } from 'remotion';
import { LyricVideo, type VideoProps } from './lyric-video';
import { automaticPoster } from './poster-layout';
import { RhythmScene } from './rhythm-scene';
import { buildRhythmChart, rhythmState, rhythmDefaults, type RhythmSettings } from './rhythm-model';
export type RhythmVideoProps = VideoProps & {
    rhythm?: RhythmSettings;
};
export const RhythmVideo: React.FC<RhythmVideoProps> = ({ project, options, timeOffset = 0, rhythm = rhythmDefaults }) => {
    const frame = useCurrentFrame(), { fps, width, height } = useVideoConfig(), t = timeOffset + frame / fps;
    const canvas = useRef<HTMLCanvasElement>(null), scene = useRef<RhythmScene | null>(null);
    const { delayRender, continueRender, cancelRender } = useDelayRender();
    const chart = useMemo(() => buildRhythmChart(project, rhythm), [project, rhythm]);
    useLayoutEffect(() => { const handle = delayRender('准备3D节奏舞台'); try {
        scene.current = new RhythmScene(canvas.current!, width, height, chart, rhythm);
        scene.current.renderAt(t);
        continueRender(handle);
    }
    catch (error) {
        cancelRender(error instanceof Error ? error : new Error(String(error)));
    } return () => { scene.current?.dispose(); scene.current = null; }; }, [chart, rhythm, width, height, delayRender, continueRender, cancelRender]);
    useLayoutEffect(() => { try {
        scene.current?.renderAt(t);
    }
    catch (error) {
        cancelRender(error instanceof Error ? error : new Error(String(error)));
    } }, [t, cancelRender]);
    const subtitleProject = useMemo(() => ({ ...project, song_cover: undefined, song_identity: { version: 'motion-song-identity-v1' as const, title: project.title, artist: project.artist || '', style: 'none' as const, show_intro: false, show_outro: false, show_signature: false, show_section: false, cover_mode: 'none' as const }, motion_plan: { version: 'motion-plan-v1' as const, source_signature: 'rhythm-subtitles', seed: rhythm.seed, cues: project.lines.map(line => ({ line_id: line.id, template: 'quiet-hold' as const, layout: 'center' as const, palette: 'neon', intensity: 0, emphasis: '', locked: false, poster: { ...automaticPoster(line, 'neon', 'single', 'dark'), layout: 'center-stack' as const, motif: 'none' as const, highlight: 'sweep' as const, accent: rhythm.palette === 'violet' ? '#be83ff' : '#64f7eb' } })) } }), [project, rhythm.seed, rhythm.palette]);
    const state = rhythmState(chart, t), section = project.sections?.find(s => t >= s.start && t < s.end)?.name;
    const accent = rhythm.palette === 'violet' ? '#be83ff' : '#64f7eb';
    return <AbsoluteFill style={{ background: '#070d17', color: '#eff7ff', fontFamily: 'Arial,"PingFang SC",sans-serif', overflow: 'hidden' }}>
  <canvas ref={canvas} width={width} height={height} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} aria-label="Three-lane procedural 3D rhythm scene"/>
  <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg,#070d17aa 0%,transparent 30%,transparent 60%,#070d17ee 100%)', pointerEvents: 'none' }}/>
  <div style={{ position: 'absolute', left: '6%', top: '5%', right: '6%', display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: Math.min(width, height) * .022 }}><span>{project.title}</span><span style={{ color: accent }}>AUTO PERFECT</span></div>
  <div style={{ position: 'absolute', top: '17%', width: '100%', textAlign: 'center' }}><div style={{ letterSpacing: 4, fontSize: Math.min(width, height) * .02, color: '#829bb1' }}>COMBO</div><div style={{ fontSize: Math.min(width, height) * .09, fontWeight: 700, color: accent, fontVariantNumeric: 'tabular-nums' }}>{state.combo.toString().padStart(3, '0')}</div><div style={{ height: 28, opacity: state.flash, fontSize: Math.min(width, height) * .026, color: accent }}>PERFECT</div></div>
  {rhythm.subtitles && <div style={{ position: 'absolute', left: 0, bottom: '4%', width, height: height * .24 }}><LyricVideo project={subtitleProject} options={options} timeOffset={timeOffset} transparent surface={{ width, height: Math.round(height * .24) }}/></div>}
  <div style={{ position: 'absolute', bottom: '2%', left: '6%', right: '6%', display: 'flex', justifyContent: 'space-between', fontSize: Math.min(width, height) * .017, color: '#829bb1' }}><span>{section || 'NEON RUN'}</span><span>AUTO PERFORMANCE · ESTIMATED BEATS</span></div>
 </AbsoluteFill>;
};
