import React, { useLayoutEffect, useMemo, useRef } from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig, useDelayRender } from 'remotion';
import { LyricVideo, type VideoProps } from './lyric-video';
import { automaticPoster } from './poster-layout';
import { MarbleScene } from './marble-scene';
import {
  buildMarbleTrack,
  evaluateMarblePose,
  marbleDefaults,
  type MarbleNoteInput,
  type MarbleSettings,
} from './marble-model';

export type MarbleVideoProps = VideoProps & {
  marble?: MarbleSettings;
  marbleNotes?: MarbleNoteInput[];
};

const THEME_ACCENTS: Record<MarbleSettings['theme'], { bg: string; accent: string; label: string }> = {
  amber: { bg: '#09070c', accent: '#ffd166', label: 'AMBER MARBLE' },
  neon: { bg: '#060b16', accent: '#64f7eb', label: 'NEON MARBLE' },
  christmas: { bg: '#160406', accent: '#fcd34d', label: 'CHRISTMAS BELLS' },
};

export const MarbleVideo: React.FC<MarbleVideoProps> = ({
  project,
  options,
  timeOffset = 0,
  marble = marbleDefaults,
  marbleNotes = [],
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = timeOffset + frame / fps;

  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<MarbleScene | null>(null);
  const { delayRender, continueRender, cancelRender } = useDelayRender();

  const track = useMemo(
    () => buildMarbleTrack(project, marble, marbleNotes),
    [project, marble, marbleNotes]
  );

  useLayoutEffect(() => {
    const handle = delayRender('Preparing 3D Marble Music stage');
    try {
      scene.current = new MarbleScene(canvas.current!, width, height, track, marble);
      scene.current.renderAt(t);
      continueRender(handle);
    } catch (error) {
      cancelRender(error instanceof Error ? error : new Error(String(error)));
    }
    return () => {
      scene.current?.dispose();
      scene.current = null;
    };
  }, [track, marble, width, height, delayRender, continueRender, cancelRender]);

  useLayoutEffect(() => {
    try {
      scene.current?.renderAt(t);
    } catch (error) {
      cancelRender(error instanceof Error ? error : new Error(String(error)));
    }
  }, [t, cancelRender]);

  const themeUi = THEME_ACCENTS[marble.theme] || THEME_ACCENTS.amber;
  const pose = evaluateMarblePose(track.primary, t);
  const section = project.sections?.find((s) => t >= s.start && t < s.end)?.name;

  const subtitleProject = useMemo(
    () => ({
      ...project,
      song_cover: undefined,
      song_identity: {
        version: 'motion-song-identity-v1' as const,
        title: project.title,
        artist: project.artist || '',
        style: 'none' as const,
        show_intro: false,
        show_outro: false,
        show_signature: false,
        show_section: false,
        cover_mode: 'none' as const,
      },
      motion_plan: {
        version: 'motion-plan-v1' as const,
        source_signature: 'marble-subtitles',
        seed: marble.seed,
        cues: project.lines.map((line) => ({
          line_id: line.id,
          template: 'quiet-hold' as const,
          layout: 'center' as const,
          palette: 'neon',
          intensity: 0,
          emphasis: '',
          locked: false,
          poster: {
            ...automaticPoster(line, 'neon', 'single', 'dark'),
            layout: 'center-stack' as const,
            motif: 'none' as const,
            highlight: 'sweep' as const,
            accent: themeUi.accent,
          },
        })),
      },
    }),
    [project, marble.seed, themeUi.accent]
  );

  const hits = Math.max(0, pose.lastHitIndex + 1);

  return (
    <AbsoluteFill
      style={{
        background: themeUi.bg,
        color: '#f8fafc',
        fontFamily: 'Arial,"PingFang SC",sans-serif',
        overflow: 'hidden',
      }}
    >
      <canvas
        ref={canvas}
        width={width}
        height={height}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
        aria-label="3D Marble Music stage"
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(180deg, ${themeUi.bg}aa 0%, transparent 25%, transparent 65%, ${themeUi.bg}ee 100%)`,
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: '6%',
          top: '5%',
          right: '6%',
          display: 'flex',
          justifyContent: 'space-between',
          gap: 12,
          fontSize: Math.min(width, height) * 0.022,
          letterSpacing: 0.6,
        }}
      >
        <span>{project.title}</span>
        <span style={{ color: themeUi.accent }}>
          {track.source === 'midi' ? 'MIDI MARBLE' : 'BEAT MARBLE'} · {hits} HITS
        </span>
      </div>
      {marble.subtitles && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            bottom: '4%',
            width,
            height: height * 0.24,
          }}
        >
          <LyricVideo
            project={subtitleProject}
            options={options}
            timeOffset={timeOffset}
            transparent
            surface={{ width, height: Math.round(height * 0.24) }}
          />
        </div>
      )}
      <div
        style={{
          position: 'absolute',
          bottom: '2%',
          left: '6%',
          right: '6%',
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: Math.min(width, height) * 0.017,
          color: '#94a3b8',
        }}
      >
        <span>{section || themeUi.label}</span>
        <span>{track.source === 'midi' ? 'MULTI-TRACK MIDI PHYSICS' : 'AUDIO BEAT PHYSICS'}</span>
      </div>
    </AbsoluteFill>
  );
};
