import { normalizeProject, renderSize, defaults, type Project } from './model';
import {
  buildMarbleTrack,
  marbleDefaults,
  type MarbleNoteInput,
  type MarbleSettings,
} from './marble-model';
import { MarblePreview } from './marble-preview';
import {
  motionJson as api,
  motionUrl,
  serviceAudio,
  cloudService,
  downloadService,
} from './service-api';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const audio = new Audio();

let project: Project | null = null;
let selected = '';
let settings: MarbleSettings = { ...marbleDefaults };
let midiNotes: MarbleNoteInput[] = [];
let midiName: string | null = null;
let saved = '';
let sequence = 0;
let engine: MarblePreview | null = null;
let audioUrl = '';
let audioReady = false;
let playing = false;
let saving = false;
let job = '';
let rendering = false;

const opts = { ...defaults, height: 720 as 360 | 720 };
const status = (text: string) => {
  $('marble-status').textContent = text;
};

function action(fn: () => unknown) {
  return async () => {
    try {
      await fn();
    } catch (e) {
      status(e instanceof Error ? e.message : String(e));
    }
  };
}

function dirty() {
  return !!project && JSON.stringify(settings) !== saved;
}

function saveState() {
  $<HTMLButtonElement>('save-marble').disabled = !dirty() || saving;
  $('draft-state').textContent = saving
    ? 'Saving…'
    : dirty()
      ? 'Unsaved scene preview'
      : project
        ? 'Saved'
        : 'Select a song to start';
}

function preview() {
  if (!project) return;
  engine?.dispose();
  const size = renderSize(opts);
  const canvas = $<HTMLCanvasElement>('marble-stage');
  canvas.width = size.width;
  canvas.height = size.height;
  $('stage-box').style.aspectRatio = `${size.width}/${size.height}`;

  engine = new MarblePreview(
    canvas,
    project,
    opts,
    size.width,
    size.height,
    settings,
    midiNotes,
    audio.currentTime
  );
  engine.renderAt(audio.currentTime);

  const track = buildMarbleTrack(project, settings, midiNotes);
  $('node-count').textContent = String(track.allNodes.length);
  $('source-badge').textContent =
    track.source === 'midi' ? `MIDI (${midiName || 'attached'})` : 'Audio Beats';
  $('marble-warnings').replaceChildren();
  for (const text of track.warnings) {
    const li = document.createElement('li');
    li.textContent = text;
    $('marble-warnings').append(li);
  }
  $('stage-meta').textContent = `${opts.aspect} · ${size.width}×${size.height}`;
  $<HTMLButtonElement>('export-marble').disabled = rendering || !track.allNodes.length;
  saveState();
}

function showSettings() {
  opts.aspect = settings.aspect;
  $<HTMLSelectElement>('marble-aspect').value = settings.aspect;
  $<HTMLSelectElement>('marble-quality').value = String(settings.height);
  for (const key of ['density', 'tracks', 'camera', 'theme', 'seed'] as const) {
    $<HTMLInputElement>('marble-' + key).value = String(settings[key]);
  }
  $<HTMLInputElement>('marble-offset').value = String(Math.round(settings.offset * 1000));
  $<HTMLInputElement>('marble-subtitles').checked = settings.subtitles;
}

function change() {
  if (!project) return;
  const seed = Number($<HTMLInputElement>('marble-seed').value);
  const offset = Number($<HTMLInputElement>('marble-offset').value);
  if (
    !Number.isInteger(seed) ||
    seed < 0 ||
    seed > 2147483647 ||
    !Number.isFinite(offset) ||
    Math.abs(offset) > 500
  ) {
    showSettings();
    throw Error('Seed or timing offset is out of range.');
  }
  settings = {
    ...settings,
    seed,
    offset: offset / 1000,
    density: $<HTMLSelectElement>('marble-density').value as MarbleSettings['density'],
    tracks: $<HTMLSelectElement>('marble-tracks').value as MarbleSettings['tracks'],
    camera: $<HTMLSelectElement>('marble-camera').value as MarbleSettings['camera'],
    theme: $<HTMLSelectElement>('marble-theme').value as MarbleSettings['theme'],
    subtitles: $<HTMLInputElement>('marble-subtitles').checked,
  };
  showSettings();
  preview();
  status('Local 3D marble preview updated. Save when ready.');
}

async function load(id: string) {
  if (dirty() && !confirm('Switch songs and discard unsaved scene changes?')) {
    $<HTMLSelectElement>('marble-project').value = selected;
    return;
  }
  if (!id) return;
  const seq = ++sequence;
  audio.pause();
  playing = false;
  $('play-marble').textContent = '▶';
  audioReady = false;
  $<HTMLButtonElement>('play-marble').disabled = true;
  status('Loading song, MIDI notes, and 3D marble settings…');

  const [data, config, noteData] = await Promise.all([
    api('project?project_id=' + encodeURIComponent(id)),
    api('marble?project_id=' + encodeURIComponent(id)),
    api('marble/notes?project_id=' + encodeURIComponent(id)),
  ]);
  if (seq !== sequence) return;

  project = normalizeProject(data.project);
  selected = id;
  settings = { ...marbleDefaults, ...config.settings };
  midiNotes = Array.isArray(noteData.notes) ? noteData.notes : [];
  midiName = noteData.midi_name || null;
  saved = JSON.stringify(settings);

  showSettings();
  $('track-name').textContent = project.title;
  $<HTMLAnchorElement>('back-studio').href = '/motion-studio?project=' + encodeURIComponent(id);
  $<HTMLInputElement>('marble-seek').max = String(project.duration);
  $<HTMLInputElement>('marble-length').value = String(Math.min(30, Math.floor(project.duration)));
  $('marble-duration').textContent = project.duration.toFixed(1) + 's';

  audio.src = '';
  audio.currentTime = 0;
  preview();

  let next = '';
  if (data.audio_url && cloudService()) {
    const result = await serviceAudio(data.audio_url, id, data.project.audio_cache);
    if (seq !== sequence) return;
    next = URL.createObjectURL(result.blob);
  }
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = next;
  audio.src = next || data.audio_url || '';
  audio.load();
  audioReady = !!(next || data.audio_url);
  $<HTMLButtonElement>('play-marble').disabled = !audioReady;
  $<HTMLInputElement>('marble-midi-file').disabled = false;
  status(
    midiNotes.length
      ? `MIDI Marble stage ready (${midiNotes.length} notes from ${midiName}).`
      : 'Beat Marble stage ready (using audio beats/drums fallback).'
  );
  await history();
}

async function save() {
  if (!project || !selected || saving) return;
  const id = selected;
  const seq = sequence;
  const snapshot = JSON.stringify(settings);
  saving = true;
  saveState();
  try {
    await api('marble', 'PUT', { project_id: id, settings: JSON.parse(snapshot) });
    if (id === selected && seq === sequence) {
      saved = snapshot;
      status('Marble scene settings saved.');
    }
  } finally {
    saving = false;
    saveState();
  }
}

async function uploadMidi() {
  if (!selected) return;
  const input = $<HTMLInputElement>('marble-midi-file');
  const file = input.files?.[0];
  if (!file) return;
  status(`Uploading ${file.name}…`);
  const form = new FormData();
  form.append('project_id', selected);
  form.append('file', file);
  const res = await fetch(motionUrl('marble/midi'), { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'MIDI upload failed');
  }
  const data = await res.json();
  midiNotes = Array.isArray(data.notes) ? data.notes : [];
  midiName = data.midi_name || file.name;
  preview();
  status(`Loaded ${midiNotes.length} MIDI notes from ${midiName}.`);
  input.value = '';
}

async function history() {
  const id = selected;
  const seq = sequence;
  const records = await api('exports?project_id=' + encodeURIComponent(id));
  if (id !== selected || seq !== sequence) return;
  $('marble-history').replaceChildren();
  for (const record of records.filter((r: any) => r.scene === 'marble' && r.status === 'done')) {
    const button = document.createElement('button');
    button.textContent =
      'Download previous export · ' + new Date(record.created_at * 1000).toLocaleString();
    button.onclick = action(() =>
      downloadService(motionUrl('render/' + record.id + '/download'), 'marble-music.mp4')
    );
    $('marble-history').append(button);
  }
}

async function exportClip() {
  if (!project || !selected) return;
  if (dirty()) throw Error('Save the scene before exporting your current preview.');
  if (rendering) throw Error('A Marble export is already running.');
  const start = Number($<HTMLInputElement>('marble-start').value);
  const length = Number($<HTMLInputElement>('marble-length').value);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(length) ||
    start < 0 ||
    length < 1 ||
    length > 60 ||
    start + length > project.duration + 0.001
  ) {
    throw Error('Select a 1–60 second clip within the song.');
  }
  const id = selected;
  rendering = true;
  $<HTMLButtonElement>('export-marble').disabled = true;
  try {
    const result = await api('render', 'POST', {
      project_id: id,
      scene: 'marble',
      aspect: opts.aspect,
      height: settings.height,
      start,
      length,
    });
    job = result.id;
    $('cancel-marble').hidden = false;
    $('download-marble').hidden = true;
    for (;;) {
      const state = await api('render/' + job);
      $('marble-export-status').textContent =
        state.status === 'running'
          ? `3D rendering: ${state.frames}/${state.total} frames`
          : state.status === 'queued'
            ? 'Waiting to render…'
            : state.status === 'done'
              ? 'Marble Music export complete'
              : state.status === 'cancelled'
                ? 'Export cancelled'
                : 'Export failed: ' + state.error;
      if (['done', 'failed', 'cancelled'].includes(state.status)) {
        if (state.status === 'done') {
          $('download-marble').hidden = false;
          await history();
        }
        break;
      }
      await new Promise((r) => setTimeout(r, 1200));
    }
  } finally {
    rendering = false;
    $('cancel-marble').hidden = true;
    $<HTMLButtonElement>('export-marble').disabled =
      !project || !buildMarbleTrack(project, settings, midiNotes).allNodes.length;
  }
}

$('marble-project').onchange = action(() => {
  if (rendering) {
    $<HTMLSelectElement>('marble-project').value = selected;
    throw Error('Wait for the export to finish before switching songs.');
  }
  return load($<HTMLSelectElement>('marble-project').value);
});

for (const id of ['density', 'tracks', 'camera', 'theme', 'offset', 'seed', 'subtitles']) {
  $('marble-' + id).onchange = action(change);
}
$('new-seed').onclick = action(() => {
  $<HTMLInputElement>('marble-seed').value = String(Math.floor(Math.random() * 2147483647));
  change();
});
$('marble-aspect').onchange = () => {
  settings = {
    ...settings,
    aspect: $<HTMLSelectElement>('marble-aspect').value as '16:9' | '9:16',
  };
  opts.aspect = settings.aspect;
  preview();
};
$('marble-quality').onchange = () => {
  settings = {
    ...settings,
    height: Number($<HTMLSelectElement>('marble-quality').value) as 360 | 720,
  };
  saveState();
};
$('marble-midi-file').onchange = action(uploadMidi);
$('save-marble').onclick = action(save);
$('export-marble').onclick = action(exportClip);
$('cancel-marble').onclick = action(async () => {
  if (job) await api('render/' + job + '/cancel', 'POST');
});
$('download-marble').onclick = action(() =>
  downloadService(motionUrl('render/' + job + '/download'), 'marble-music.mp4')
);
$('play-marble').onclick = action(async () => {
  if (!audioReady) throw Error('Audio is not ready.');
  if (playing) {
    audio.pause();
    playing = false;
  } else {
    await audio.play();
    playing = true;
  }
  $('play-marble').textContent = playing ? 'Ⅱ' : '▶';
});
$('marble-seek').oninput = () => {
  audio.currentTime = Number($<HTMLInputElement>('marble-seek').value);
  engine?.renderAt(audio.currentTime);
  $('marble-time').textContent = audio.currentTime.toFixed(2) + 's';
};

function tick() {
  if (playing && engine) {
    engine.renderAt(audio.currentTime);
    $<HTMLInputElement>('marble-seek').value = String(audio.currentTime);
    $('marble-time').textContent = audio.currentTime.toFixed(2) + 's';
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

audio.addEventListener('ended', () => {
  playing = false;
  $('play-marble').textContent = '▶';
});

window.addEventListener('beforeunload', (event) => {
  if (dirty() || rendering) {
    event.preventDefault();
    event.returnValue = '';
  }
});

void action(async () => {
  const rows = await api('projects');
  for (const row of rows) {
    const option = document.createElement('option');
    option.value = row.id;
    option.textContent = row.name;
    $('marble-project').append(option);
  }
  const query = new URLSearchParams(location.search).get('project');
  const chosen = rows.find((r: any) => r.id === query) || rows[0];
  if (chosen) {
    $<HTMLSelectElement>('marble-project').value = chosen.id;
    await load(chosen.id);
  } else {
    status('No songs yet. Import a song and analyze its audio in Lyric Editor.');
  }
})();
