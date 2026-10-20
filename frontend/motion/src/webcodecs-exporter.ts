import { Muxer, ArrayBufferTarget } from 'mp4-muxer';
import {
  compileSongPosters,
  canvasMeasure,
  paintCompiledPoster,
  compileIntroTitle,
  introTitleState,
  visiblePosterAt,
  stageAt,
  POSTER_FONT,
  type CompiledPoster,
  type CompiledIntroTitle,
} from './poster-layout';
import {
  compileSongLayout,
  songLayoutAt,
  coverPlacement,
  coverOpacityAt,
  paintSongLayout,
  type SongLayout,
} from './song-layout';
import { featuresAt, type Project, type Options } from './model';

export type ExportRange = {
  title: string;
  aspect: '16:9' | '9:16';
  start: number;
  length: number;
};

export type ProgressCallback = (progress: {
  frame: number;
  totalFrames: number;
  pct: number;
}) => void;

/** Check if current browser supports WebCodecs hardware-accelerated video encoding */
export function isWebCodecsSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof (window as any).VideoEncoder !== 'undefined' &&
    typeof (window as any).VideoFrame !== 'undefined'
  );
}

/** Standard H.264 profile/level candidate codecs in descending order of quality and preference */
export const H264_CANDIDATE_CODECS = [
  'avc1.64002a', // High Profile Level 4.2 (1080p60 capable, optimal quality & compression)
  'avc1.4d002a', // Main Profile Level 4.2 (broad macOS & Windows GPU support)
  'avc1.420028', // Baseline Profile Level 4.0 (1080p30 capable)
  'avc1.42002a', // Baseline Profile Level 4.2
  'avc1.640034', // High Profile Level 5.2
  'avc1.4d0034', // Main Profile Level 5.2
];

/** Pre-flight probe: asynchronously check whether hardware H.264 video encoding is actually usable */
export async function canUseWebCodecs(options?: { width?: number; height?: number }): Promise<{ supported: boolean; chosenCodec?: string; reason?: string }> {
  if (typeof window === 'undefined') return { supported: false, reason: 'Non-browser environment' };
  if (!isWebCodecsSupported()) {
    return { supported: false, reason: 'Browser lacks WebCodecs API (requires Chrome, Edge, or modern Chromium/Safari 16.4+)' };
  }
  if (window.isSecureContext === false) {
    if (typeof window.location !== 'undefined' && window.location.hostname === '0.0.0.0') {
      const port = window.location.port ? `:${window.location.port}` : '';
      return {
        supported: false,
        reason: `0.0.0.0 is not a secure context in browsers. Please use http://127.0.0.1${port} or http://localhost${port}`,
      };
    }
    return { supported: false, reason: 'WebCodecs requires HTTPS or localhost' };
  }
  try {
    const W = options?.width || 1080;
    const H = options?.height || 1920;
    for (const codec of H264_CANDIDATE_CODECS) {
      try {
        const support = await (window as any).VideoEncoder.isConfigSupported({
          codec,
          width: W,
          height: H,
          bitrate: 10_000_000,
          framerate: 30,
          hardwareAcceleration: 'prefer-hardware',
        });
        if (support && support.supported) {
          return { supported: true, chosenCodec: codec };
        }
      } catch {
        // try next candidate
      }
    }
    return { supported: false, reason: 'GPU does not support H.264 video encoding at this resolution' };
  } catch (err: any) {
    return { supported: false, reason: err?.message || 'Encoder probe failed' };
  }
}

/** Render a single full video frame onto a 2D canvas context */
export function renderCanvasFrame(
  ctx: CanvasRenderingContext2D,
  project: Project,
  layouts: CompiledPoster[],
  songLayout: SongLayout | null,
  intro: CompiledIntroTitle | null,
  coverImage: HTMLImageElement | null,
  t: number,
  W: number,
  H: number
): void {
  const plan = visiblePosterAt(layouts, t);
  const stage = stageAt(layouts, t);
  const background = stage?.background || '#0d120a';
  const accent = stage?.accent || '#b7f34a';

  // 1. Clear & Background
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, W, H);

  // 2. Cover image background & artwork card
  if (coverImage) {
    const opacity = coverOpacityAt(songLayout, t);
    const placement = coverPlacement(project, { x: 0, y: 0, width: W, height: H });
    if (placement) {
      ctx.save();
      ctx.globalAlpha = opacity;
      ctx.drawImage(coverImage, placement.x, placement.y, placement.width, placement.height);
      ctx.restore();
    }
    const songFrame = songLayoutAt(songLayout, t);
    if (songFrame.cover && songLayout?.artwork) {
      const art = songLayout.artwork;
      const artPlacement = coverPlacement(project, art);
      if (artPlacement) {
        ctx.save();
        ctx.globalAlpha = songFrame.alpha;
        ctx.beginPath();
        ctx.rect(art.x, art.y, art.width, art.height);
        ctx.clip();
        ctx.drawImage(coverImage, artPlacement.x, artPlacement.y, artPlacement.width, artPlacement.height);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        ctx.lineWidth = 1;
        ctx.strokeRect(art.x, art.y, art.width, art.height);
        ctx.restore();
      }
    }
  }

  // 3. Intro Title animation
  if (intro) {
    const introState = introTitleState(intro, t, H);
    if (introState.alpha > 0) {
      ctx.save();
      ctx.globalAlpha = introState.alpha;
      ctx.translate(intro.cx, intro.cy + introState.dy);
      ctx.scale(introState.scale, introState.scale);
      ctx.font = `${intro.weight} ${intro.fontSize}px ${POSTER_FONT}`;
      ctx.fillStyle = intro.color;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText(intro.text, intro.x - intro.cx, intro.y - intro.cy);
      ctx.restore();
    }
  }

  // 4. Poster Nodes, typography, and karaoke highlights
  const feature = featuresAt(project, t);
  const beatVal = feature.kick || feature.beat * 0.3;
  if (plan) {
    paintCompiledPoster(ctx, plan, t, beatVal, false);
  }

  // 5. Song Layout texts and section indicator
  paintSongLayout(ctx, songLayout, t, background, accent, POSTER_FONT);
}

/**
 * Fast client-side WebCodecs MP4 video export directly in the browser.
 * Near 0 server compute cost, 10-15s export speed with local GPU acceleration.
 */
export async function exportMotionWebCodecs(params: {
  project: Project;
  range: ExportRange;
  audioBlobOrUrl?: Blob | string | null;
  onProgress?: ProgressCallback;
  isCancelled?: () => boolean;
}): Promise<Blob> {
  const { project, range, audioBlobOrUrl, onProgress, isCancelled } = params;
  if (!isWebCodecsSupported()) {
    throw new Error('WebCodecs is not supported in this browser. Please use Google Chrome or Microsoft Edge.');
  }

  // Ensure fonts are ready before rendering
  if (typeof document !== 'undefined' && document.fonts?.ready) {
    await document.fonts.ready;
  }

  const portrait = range.aspect === '9:16';
  const width = portrait ? 1080 : 1920;
  const height = portrait ? 1920 : 1080;

  // Measure and compile poster layouts
  const measureCanvas = document.createElement('canvas');
  measureCanvas.width = width;
  measureCanvas.height = height;
  const measureCtx = measureCanvas.getContext('2d')!;
  const measure = canvasMeasure(measureCtx);

  const layouts = compileSongPosters(project, width, height, measure);
  const songLayout = compileSongLayout(project, width, height, measure);
  const intro = project.song_identity ? null : compileIntroTitle(project, width, height, measure);

  // Preload cover image if available
  let coverImage: HTMLImageElement | null = null;
  if (project.song_cover?.data_url) {
    coverImage = new Image();
    coverImage.src = project.song_cover.data_url;
    try {
      await coverImage.decode();
    } catch {
      coverImage = null;
    }
  }

  // Prepare Audio Buffer if source available
  let audioBuffer: AudioBuffer | null = null;
  if (audioBlobOrUrl && typeof AudioContext !== 'undefined') {
    try {
      let arrayBuffer: ArrayBuffer;
      if (audioBlobOrUrl instanceof Blob) {
        arrayBuffer = await audioBlobOrUrl.arrayBuffer();
      } else {
        const res = await fetch(audioBlobOrUrl);
        arrayBuffer = await res.arrayBuffer();
      }
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    } catch (err) {
      console.warn('[WebCodecsExporter] Audio decode failed, exporting video without audio:', err);
    }
  }

  const canEncodeAudio =
    typeof (window as any).AudioEncoder !== 'undefined' &&
    audioBuffer !== null &&
    audioBuffer.length > 0;

  const target = new ArrayBufferTarget();
  const muxer = new Muxer({
    target,
    video: {
      codec: 'avc',
      width,
      height,
    },
    audio: canEncodeAudio && audioBuffer ? {
      codec: 'aac',
      numberOfChannels: 2,
      sampleRate: audioBuffer.sampleRate,
    } : undefined,
    fastStart: 'in-memory',
    firstTimestampBehavior: 'offset',
  });

  // 1. Configure VideoEncoder
  let videoError: Error | null = null;
  const videoEncoder = new (window as any).VideoEncoder({
    output: (chunk: any, metadata: any) => {
      muxer.addVideoChunk(chunk, metadata);
    },
    error: (err: any) => {
      videoError = err;
    },
  });

  let selectedCodec = H264_CANDIDATE_CODECS[0];
  for (const candidate of H264_CANDIDATE_CODECS) {
    try {
      const probe = await (window as any).VideoEncoder.isConfigSupported({
        codec: candidate,
        width,
        height,
        bitrate: 10_000_000,
        framerate: 30,
        hardwareAcceleration: 'prefer-hardware',
      });
      if (probe && probe.supported) {
        selectedCodec = candidate;
        break;
      }
    } catch {
      // ignore
    }
  }

  const videoConfig = {
    codec: selectedCodec,
    width,
    height,
    bitrate: 10_000_000, // 10 Mbps
    framerate: 30,
    hardwareAcceleration: 'prefer-hardware' as const,
    avc: { format: 'avc' as const },
  };
  videoEncoder.configure(videoConfig);

  // 2. Configure AudioEncoder (if supported)
  let audioEncoder: any = null;
  if (canEncodeAudio && audioBuffer) {
    try {
      audioEncoder = new (window as any).AudioEncoder({
        output: (chunk: any, metadata: any) => {
          muxer.addAudioChunk(chunk, metadata);
        },
        error: (err: any) => {
          console.warn('[WebCodecsExporter] AudioEncoder error:', err);
        },
      });

      audioEncoder.configure({
        codec: 'mp4a.40.2',
        numberOfChannels: 2,
        sampleRate: audioBuffer.sampleRate,
        bitrate: 192000,
      });

      // Slice & Encode Audio Samples
      const sampleRate = audioBuffer.sampleRate;
      const channels = Math.min(2, audioBuffer.numberOfChannels);
      const startSample = Math.floor(range.start * sampleRate);
      const totalAudioSamples = Math.floor(range.length * sampleRate);
      const endSample = Math.min(audioBuffer.length, startSample + totalAudioSamples);
      const sliceLength = Math.max(0, endSample - startSample);

      if (sliceLength > 0) {
        const chunkSize = 1024;
        const leftChannel = audioBuffer.getChannelData(0);
        const rightChannel = channels > 1 ? audioBuffer.getChannelData(1) : leftChannel;

        for (let offset = 0; offset < sliceLength; offset += chunkSize) {
          const count = Math.min(chunkSize, sliceLength - offset);
          const chunkData = new Float32Array(count * 2);
          for (let s = 0; s < count; s++) {
            chunkData[s * 2] = leftChannel[startSample + offset + s] || 0;
            chunkData[s * 2 + 1] = rightChannel[startSample + offset + s] || 0;
          }
          const audioTimestampUs = Math.round((offset / sampleRate) * 1_000_000);
          const audioData = new (window as any).AudioData({
            format: 'f32',
            sampleRate,
            numberOfChannels: 2,
            numberOfFrames: count,
            timestamp: audioTimestampUs,
            data: chunkData,
          });
          audioEncoder.encode(audioData);
          audioData.close();
        }
      }
    } catch (audioErr) {
      console.warn('[WebCodecsExporter] Audio encoding failed, continuing video only:', audioErr);
      audioEncoder = null;
    }
  }

  // 3. Render and Encode Video Frames
  const fps = 30;
  const totalFrames = Math.max(1, Math.round(range.length * fps));
  const renderCanvas = document.createElement('canvas');
  renderCanvas.width = width;
  renderCanvas.height = height;
  const renderCtx = renderCanvas.getContext('2d', { alpha: false })!;

  try {
    for (let f = 0; f < totalFrames; f++) {
      if (isCancelled?.()) {
        throw new Error('Export cancelled by user');
      }
      if (videoError) {
        throw videoError;
      }

      const t = range.start + f / fps;
      renderCanvasFrame(
        renderCtx,
        project,
        layouts,
        songLayout,
        intro,
        coverImage,
        t,
        width,
        height
      );

      const timestampUs = Math.round((f / fps) * 1_000_000);
      const videoFrame = new (window as any).VideoFrame(renderCanvas, {
        timestamp: timestampUs,
      });
      const isKeyFrame = f % (fps * 2) === 0;
      videoEncoder.encode(videoFrame, { keyFrame: isKeyFrame });
      videoFrame.close();

      // Yield control every few frames so browser remains responsive and encoder queue is drained
      if (f % 6 === 0 || f === totalFrames - 1) {
        onProgress?.({
          frame: f + 1,
          totalFrames,
          pct: ((f + 1) / totalFrames) * 100,
        });
        if (videoEncoder.encodeQueueSize > 4) {
          await new Promise((r) => setTimeout(r, 0));
        }
      }
    }

    await videoEncoder.flush();
    if (audioEncoder) {
      await audioEncoder.flush();
    }
    muxer.finalize();

    const buffer = target.buffer;
    return new Blob([buffer], { type: 'video/mp4' });
  } finally {
    videoEncoder.close();
    audioEncoder?.close();
  }
}
