import test from 'node:test';
import assert from 'node:assert/strict';
import { demo, normalizeProject } from './model.ts';
import {
  buildMarbleTrack,
  evaluateMarblePose,
  marbleDefaults,
  type MarbleNoteInput,
} from './marble-model.ts';

test('buildMarbleTrack uses MIDI notes when available and splits dual tracks', () => {
  const project = normalizeProject(demo);
  const midiNotes: MarbleNoteInput[] = [
    { time: 0.5, duration: 0.3, pitch: 72, velocity: 100, role: 'melody' },
    { time: 1.0, duration: 0.3, pitch: 76, velocity: 105, role: 'melody' },
    { time: 1.5, duration: 0.3, pitch: 79, velocity: 110, role: 'melody' },
    { time: 0.5, duration: 0.2, pitch: 36, velocity: 120, role: 'percussion' },
    { time: 1.5, duration: 0.2, pitch: 40, velocity: 110, role: 'bass' },
  ];

  const track = buildMarbleTrack(project, marbleDefaults, midiNotes);
  assert.equal(track.source, 'midi');
  assert.equal(track.primary.length, 3);
  assert.equal(track.secondary.length, 2);
  assert.ok(track.primary[0].x < track.primary[2].x);
});

test('buildMarbleTrack falls back to audio beats and drum_hits when no MIDI is provided', () => {
  const project = normalizeProject(demo);
  const track = buildMarbleTrack(project, marbleDefaults, []);
  assert.equal(track.source, 'audio_analysis');
  assert.ok(track.allNodes.length > 0);
});

test('evaluateMarblePose hits bar surface at exact note timestamp and arcs in between', () => {
  const project = normalizeProject(demo);
  const midiNotes: MarbleNoteInput[] = [
    { time: 1.0, duration: 0.25, pitch: 60, velocity: 100, role: 'melody' },
    { time: 1.6, duration: 0.25, pitch: 72, velocity: 100, role: 'melody' },
  ];
  const track = buildMarbleTrack(project, marbleDefaults, midiNotes);
  const [n0, n1] = track.primary;

  const p0 = evaluateMarblePose(track.primary, n0.time);
  const p1 = evaluateMarblePose(track.primary, n1.time);
  const pMid = evaluateMarblePose(track.primary, (n0.time + n1.time) / 2);

  assert.ok(Math.abs(p0.y - n0.y) < 1e-6);
  assert.ok(Math.abs(p1.y - n1.y) < 1e-6);
  assert.ok(pMid.y > Math.max(n0.y, n1.y), 'marble should arc upward between consecutive hits');
});
