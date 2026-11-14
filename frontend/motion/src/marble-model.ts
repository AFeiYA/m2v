import type { Project } from './model';

export function seeded(index: number, seed: number): number {
  let n = (index ^ seed) >>> 0;
  n = Math.imul(n ^ (n >>> 16), 0x45d9f3b);
  n = Math.imul(n ^ (n >>> 16), 0x45d9f3b);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
}

export type MarbleSettings = {
  version: 'marble-stage-v1';
  aspect: '16:9' | '9:16';
  height: 360 | 720;
  seed: number;
  density: 'sparse' | 'balanced' | 'dense';
  tracks: 'single' | 'dual';
  camera: 'follow' | 'isometric' | 'rail';
  theme: 'amber' | 'neon' | 'christmas';
  offset: number;
  subtitles: boolean;
};

export const marbleDefaults: MarbleSettings = {
  version: 'marble-stage-v1',
  aspect: '16:9',
  height: 360,
  seed: 42,
  density: 'balanced',
  tracks: 'dual',
  camera: 'follow',
  theme: 'amber',
  offset: 0,
  subtitles: true,
};

export type MarbleNoteInput = {
  time: number;
  duration: number;
  pitch: number;
  velocity: number;
  channel?: number;
  track?: string;
  role?: 'melody' | 'bass' | 'percussion';
};

export type MarbleHitNode = {
  id: string;
  index: number;
  time: number;
  duration: number;
  pitch: number;
  velocity: number;
  lane: 'primary' | 'secondary';
  x: number;
  y: number;
  z: number;
  width: number;
  colorRatio: number;
};

export type MarbleTrack = {
  source: 'midi' | 'audio_analysis';
  primary: MarbleHitNode[];
  secondary: MarbleHitNode[];
  allNodes: MarbleHitNode[];
  warnings: string[];
  seed: number;
};

export type MarblePose = {
  x: number;
  y: number;
  z: number;
  active: boolean;
  lastHitIndex: number;
  flash: number;
  spin: number;
};

const COURSE_SPEED = 7.2;
const DROP_PER_SEC = 1.45;

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function sampleEnergy(project: Project, time: number): number {
  const curve = project.analysis?.energy_curve || [];
  if (!curve.length) return 0.5;
  let lo = 0;
  let hi = curve.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (curve[mid].time < time) lo = mid + 1;
    else hi = mid;
  }
  return clamp(curve[lo]?.energy ?? 0.5, 0, 1);
}

function minSpacingForDensity(density: MarbleSettings['density']): number {
  if (density === 'sparse') return 0.24;
  if (density === 'dense') return 0.085;
  return 0.14;
}

function filterLaneEvents<T extends { time: number; velocity: number }>(
  events: T[],
  minSpacing: number,
  duration: number,
  offset: number,
  limit = 6000
): T[] {
  const sorted = [...events].sort((a, b) => a.time - b.time || b.velocity - a.velocity);
  const kept: T[] = [];
  for (const ev of sorted) {
    const t = Math.round((ev.time + offset) * 1000) / 1000;
    if (!Number.isFinite(t) || t < 0 || t >= duration) continue;
    if (kept.length > 0 && t - (kept[kept.length - 1].time + offset) < minSpacing - 1e-6) {
      // Keep louder note if almost simultaneous
      if (ev.velocity > kept[kept.length - 1].velocity && kept.length >= 2 && t - (kept[kept.length - 2].time + offset) >= minSpacing) {
        kept[kept.length - 1] = ev;
      }
      continue;
    }
    kept.push(ev);
    if (kept.length >= limit) break;
  }
  return kept;
}

function toHitNodes(
  events: { time: number; duration: number; pitch: number; velocity: number }[],
  lane: 'primary' | 'secondary',
  offset: number
): MarbleHitNode[] {
  return events.map((ev, index) => {
    const t = Math.round((ev.time + offset) * 1000) / 1000;
    const normPitch = clamp((ev.pitch - 36) / 60, 0, 1);
    const x = lane === 'primary'
      ? (normPitch - 0.5) * 9.6
      : (normPitch - 0.5) * 6.4 + (normPitch < 0.5 ? -3.2 : 3.2);
    const pitchLift = (normPitch - 0.5) * 0.85;
    const y = -t * DROP_PER_SEC + pitchLift + (lane === 'secondary' ? -1.1 : 0);
    const z = -t * COURSE_SPEED;
    const width = lane === 'primary' ? clamp(1.15 + ev.duration * 0.45, 1.05, 2.1) : 1.35;
    return {
      id: `${lane}-${index}`,
      index,
      time: t,
      duration: ev.duration,
      pitch: ev.pitch,
      velocity: ev.velocity,
      lane,
      x,
      y,
      z,
      width,
      colorRatio: normPitch,
    };
  });
}

export function buildMarbleTrack(
  project: Project,
  settings: MarbleSettings,
  midiNotes: MarbleNoteInput[] = []
): MarbleTrack {
  const minSpacing = minSpacingForDensity(settings.density);
  const warnings: string[] = [];

  if (midiNotes.length > 0) {
    const primaryRaw = midiNotes.filter((n) => n.role !== 'percussion' && n.role !== 'bass');
    const secondaryRaw = midiNotes.filter((n) => n.role === 'percussion' || n.role === 'bass');
    const primaryEvents = filterLaneEvents(
      primaryRaw.length ? primaryRaw : midiNotes,
      minSpacing,
      project.duration,
      settings.offset
    );
    const secondaryEvents =
      settings.tracks === 'dual' && secondaryRaw.length
        ? filterLaneEvents(secondaryRaw, Math.max(minSpacing, 0.16), project.duration, settings.offset)
        : [];
    const primary = toHitNodes(primaryEvents, 'primary', settings.offset);
    const secondary = toHitNodes(secondaryEvents, 'secondary', settings.offset);
    const allNodes = [...primary, ...secondary].sort((a, b) => a.time - b.time);
    if (!allNodes.length) {
      warnings.push('MIDI contains no notes inside song duration.');
    }
    return { source: 'midi', primary, secondary, allNodes, warnings, seed: settings.seed };
  }

  // Fallback: Audio analysis beats + drum hits
  const beats = [...new Set((project.analysis?.beats || []).filter(Number.isFinite))].sort((a, b) => a - b);
  const primaryFallback: { time: number; duration: number; pitch: number; velocity: number }[] = [];
  for (let i = 0; i < beats.length; i++) {
    if (settings.density === 'sparse' && i % 2 === 1) continue;
    const t = beats[i];
    const energy = sampleEnergy(project, t);
    const contour = Math.round(48 + energy * 24 + (seeded(i + 1, settings.seed) - 0.5) * 18);
    primaryFallback.push({
      time: t,
      duration: 0.25,
      pitch: clamp(contour, 40, 88),
      velocity: Math.round(70 + energy * 50),
    });
  }

  const drums = (project.analysis?.drum_hits || []).filter(
    (d) => Number.isFinite(d.time) && ['kick', 'snare', 'hihat'].includes(d.type)
  );
  const secondaryFallback =
    settings.tracks === 'dual'
      ? drums.map((d, idx) => ({
          time: d.time,
          duration: 0.18,
          pitch: d.type === 'kick' ? 38 : d.type === 'snare' ? 54 : 74 + (idx % 5) * 2,
          velocity: d.type === 'kick' ? 115 : d.type === 'snare' ? 105 : 85,
        }))
      : [];

  if (!primaryFallback.length && secondaryFallback.length) {
    primaryFallback.push(...secondaryFallback);
  }
  if (!primaryFallback.length) {
    // Final fallback: word/line onsets so MIDI-aligned songs without audio analysis still play cleanly
    let idx = 0;
    for (const line of project.lines) {
      const words = line.words?.length ? line.words : [{ word: line.text, start: line.start, end: line.end }];
      for (const w of words) {
        if (!Number.isFinite(w.start)) continue;
        const contour = 52 + ((idx * 5 + Math.floor(seeded(idx + 3, settings.seed) * 14)) % 24);
        primaryFallback.push({
          time: w.start,
          duration: Math.max(0.15, (w.end ?? w.start + 0.25) - w.start),
          pitch: contour,
          velocity: 95,
        });
        idx++;
      }
    }
  }

  const primary = toHitNodes(
    filterLaneEvents(primaryFallback, minSpacing, project.duration, settings.offset),
    'primary',
    settings.offset
  );
  const secondary = toHitNodes(
    filterLaneEvents(secondaryFallback, Math.max(minSpacing, 0.16), project.duration, settings.offset),
    'secondary',
    settings.offset
  );
  const allNodes = [...primary, ...secondary].sort((a, b) => a.time - b.time);

  warnings.push('Audio Analysis Fallback: upload a .mid file for pitch-accurate melody rails.');
  if (!allNodes.length) {
    warnings.push('No usable beats or MIDI notes found. Analyze audio in Lyric Editor or upload a MIDI file.');
  }

  return { source: 'audio_analysis', primary, secondary, allNodes, warnings, seed: settings.seed };
}

export function evaluateMarblePose(nodes: MarbleHitNode[], t: number): MarblePose {
  if (!nodes.length) {
    return { x: 0, y: 1.5, z: -t * COURSE_SPEED, active: false, lastHitIndex: -1, flash: 0, spin: t * 6 };
  }

  const first = nodes[0];
  if (t <= first.time) {
    const pre = Math.max(0, first.time - t);
    const chuteProgress = clamp(1 - pre / 1.4, 0, 1);
    const arc = pre < 0.8 ? 4 * 1.1 * chuteProgress * (1 - chuteProgress) : 0;
    return {
      x: lerp(0, first.x, chuteProgress),
      y: first.y + pre * 1.65 + arc,
      z: first.z + pre * COURSE_SPEED,
      active: true,
      lastHitIndex: -1,
      flash: 0,
      spin: t * 7,
    };
  }

  const last = nodes[nodes.length - 1];
  if (t >= last.time) {
    const dt = t - last.time;
    const flash = Math.max(0, 1 - dt / 0.28);
    return {
      x: last.x,
      y: last.y - dt * DROP_PER_SEC + Math.max(0, 0.45 * dt - 4.5 * dt * dt),
      z: last.z - dt * COURSE_SPEED,
      active: true,
      lastHitIndex: nodes.length - 1,
      flash,
      spin: t * 7,
    };
  }

  // Binary search for interval [nodes[lo - 1], nodes[lo]]
  let lo = 0;
  let hi = nodes.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (nodes[mid].time <= t) lo = mid + 1;
    else hi = mid;
  }

  const prev = nodes[lo - 1];
  const next = nodes[lo];
  const dt = Math.max(0.001, next.time - prev.time);
  const elapsed = t - prev.time;
  const u = clamp(elapsed / dt, 0, 1);
  const flash = Math.max(0, 1 - elapsed / 0.28);

  if (dt <= 0.95) {
    // Pure parabolic gravity bounce between exact hit points
    const arcHeight = clamp(0.45 + 0.5 * 11.5 * Math.pow(dt * 0.5, 2), 0.45, 3.4);
    const y = lerp(prev.y, next.y, u) + 4 * arcHeight * u * (1 - u);
    return {
      x: lerp(prev.x, next.x, u),
      y,
      z: lerp(prev.z, next.z, u),
      active: true,
      lastHitIndex: lo - 1,
      flash,
      spin: t * 8,
    };
  }

  // Long rest (> 0.95s): short hop onto guide rail -> smooth roll -> final hop onto next bar
  const hopIn = 0.25;
  const hopOut = 0.35;
  if (elapsed < hopIn) {
    const k = elapsed / hopIn;
    return {
      x: lerp(prev.x, lerp(prev.x, next.x, 0.15), k),
      y: prev.y + 4 * 0.55 * k * (1 - k),
      z: lerp(prev.z, next.z, elapsed / dt),
      active: true,
      lastHitIndex: lo - 1,
      flash,
      spin: t * 8,
    };
  }
  const remain = next.time - t;
  if (remain < hopOut) {
    const k = 1 - remain / hopOut;
    const railStart = lerp(prev.x, next.x, (dt - hopOut) / dt);
    const railY = lerp(prev.y, next.y, (dt - hopOut) / dt);
    return {
      x: lerp(railStart, next.x, k),
      y: lerp(railY, next.y, k) + 4 * 0.85 * k * (1 - k),
      z: lerp(prev.z, next.z, u),
      active: true,
      lastHitIndex: lo - 1,
      flash,
      spin: t * 8,
    };
  }
  return {
    x: lerp(prev.x, next.x, u),
    y: lerp(prev.y, next.y, u),
    z: lerp(prev.z, next.z, u),
    active: true,
    lastHitIndex: lo - 1,
    flash,
    spin: t * 8,
  };
}
