import { normalizeProject, renderSize, defaults, type Project } from './model';
import { rhythmDefaults, buildRhythmChart, type RhythmSettings } from './rhythm-model';
import { RhythmPreview } from './rhythm-preview';
import { motionJson as api, motionUrl, serviceAudio, cloudService, downloadService } from './service-api';
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const audio = new Audio();
let project: Project | null = null, selected = '', settings = { ...rhythmDefaults }, saved = '', sequence = 0, engine: RhythmPreview | null = null, audioUrl = '', audioReady = false, playing = false, saving = false, job = '', rendering = false;
const opts = { ...defaults, height: 720 as 360 | 720 };
const status = (text: string) => { $('rhythm-status').textContent = text; };
function action(fn: () => unknown) { return async () => { try {
    await fn();
}
catch (e) {
    status(e instanceof Error ? e.message : String(e));
} }; }
function dirty() { return !!project && JSON.stringify(settings) !== saved; }
function saveState() { $<HTMLButtonElement>('save-rhythm').disabled = !dirty() || saving; $('draft-state').textContent = saving ? 'Saving…' : dirty() ? 'Unsaved scene preview' : project ? 'Saved' : 'Select a song to start'; }
function preview() { if (!project)
    return; engine?.dispose(); const size = renderSize(opts), canvas = $<HTMLCanvasElement>('rhythm-stage'); canvas.width = size.width; canvas.height = size.height; $('stage-box').style.aspectRatio = `${size.width}/${size.height}`; engine = new RhythmPreview(canvas, project, opts, size.width, size.height, settings, audio.currentTime); engine.renderAt(audio.currentTime); const chart = buildRhythmChart(project, settings); $('note-count').textContent = String(chart.notes.length); $('rhythm-warnings').replaceChildren(); for (const text of chart.warnings) {
    const li = document.createElement('li');
    li.textContent = text;
    $('rhythm-warnings').append(li);
} $('stage-meta').textContent = `${opts.aspect} · ${size.width}×${size.height}`; $<HTMLButtonElement>('export-rhythm').disabled = rendering || !chart.notes.length; saveState(); }
function showSettings() { opts.aspect = settings.aspect; $<HTMLSelectElement>('rhythm-aspect').value = settings.aspect; $<HTMLSelectElement>('rhythm-quality').value = String(settings.height); for (const key of ['density', 'approach', 'palette', 'seed'] as const)
    $<HTMLInputElement>('rhythm-' + key).value = String(settings[key]); $<HTMLInputElement>('rhythm-offset').value = String(Math.round(settings.offset * 1000)); $<HTMLInputElement>('rhythm-subtitles').checked = settings.subtitles; $('approach-value').textContent = settings.approach.toFixed(1) + 's · Changes approach distance, not hit timing'; }
function change() { if (!project)
    return; const seed = Number($<HTMLInputElement>('rhythm-seed').value), offset = Number($<HTMLInputElement>('rhythm-offset').value), approach = Number($<HTMLInputElement>('rhythm-approach').value); if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647 || !Number.isFinite(offset) || Math.abs(offset) > 500 || !Number.isFinite(approach) || approach < 1.2 || approach > 4) {
    showSettings();
    throw Error('Seed or rhythm settings are out of range.');
} settings = { ...settings, seed, offset: offset / 1000, approach, density: $<HTMLSelectElement>('rhythm-density').value as RhythmSettings['density'], palette: $<HTMLSelectElement>('rhythm-palette').value as RhythmSettings['palette'], subtitles: $<HTMLInputElement>('rhythm-subtitles').checked }; showSettings(); preview(); status('Local preview updated. Save when ready.'); }
async function load(id: string) { if (dirty() && !confirm('Switch songs and discard unsaved scene changes?')) {
    $<HTMLSelectElement>('rhythm-project').value = selected;
    return;
} if (!id)
    return; const seq = ++sequence; audio.pause(); playing = false; $('play-rhythm').textContent = '▶'; audioReady = false; $<HTMLButtonElement>('play-rhythm').disabled = true; status('Loading song, rhythm, and scene settings…'); const [data, config] = await Promise.all([api('project?project_id=' + encodeURIComponent(id)), api('rhythm?project_id=' + encodeURIComponent(id))]); if (seq !== sequence)
    return; project = normalizeProject(data.project); selected = id; settings = { ...rhythmDefaults, ...config.settings }; saved = JSON.stringify(settings); showSettings(); $('track-name').textContent = project.title; $<HTMLAnchorElement>('back-studio').href = '/motion-studio?project=' + encodeURIComponent(id); $<HTMLInputElement>('rhythm-seek').max = String(project.duration); $<HTMLInputElement>('rhythm-length').value = String(Math.min(30, Math.floor(project.duration))); $('rhythm-duration').textContent = project.duration.toFixed(1) + 's'; audio.src = ''; audio.currentTime = 0; preview(); let next = ''; if (data.audio_url && cloudService()) {
    const result = await serviceAudio(data.audio_url, id, data.project.audio_cache);
    if (seq !== sequence)
        return;
    next = URL.createObjectURL(result.blob);
} if (audioUrl)
    URL.revokeObjectURL(audioUrl); audioUrl = next; audio.src = next || data.audio_url || ''; audio.load(); audioReady = !!(next || data.audio_url); $<HTMLButtonElement>('play-rhythm').disabled = !audioReady; status('3D preview ready. Seek to check timing. Auto Perfect is a simulation, not a player score.'); await history(); }
async function save() { if (!project || !selected || saving)
    return; const id = selected, seq = sequence, snapshot = JSON.stringify(settings); saving = true; saveState(); try {
    await api('rhythm', 'PUT', { project_id: id, settings: JSON.parse(snapshot) });
    if (id === selected && seq === sequence) {
        saved = snapshot;
        status(dirty() ? 'Submitted version saved. Newer changes remain local.' : 'Scene settings saved. Your poster plan is unchanged.');
    }
}
finally {
    saving = false;
    saveState();
} }
async function history() { const id = selected, seq = sequence, records = await api('exports?project_id=' + encodeURIComponent(id)); if (id !== selected || seq !== sequence)
    return; $('rhythm-history').replaceChildren(); for (const record of records.filter((r: any) => r.scene === 'rhythm' && r.status === 'done')) {
    const button = document.createElement('button');
    button.textContent = 'Download previous export · ' + new Date(record.created_at * 1000).toLocaleString();
    button.onclick = action(() => downloadService(motionUrl('render/' + record.id + '/download'), 'rhythm-stage.mp4'));
    $('rhythm-history').append(button);
} }
async function exportClip() { if (!project || !selected)
    return; if (dirty())
    throw Error('Save the scene before exporting your current preview.'); if (rendering)
    throw Error('A rhythm export is already running.'); const start = Number($<HTMLInputElement>('rhythm-start').value), length = Number($<HTMLInputElement>('rhythm-length').value); if (!Number.isFinite(start) || !Number.isFinite(length) || start < 0 || length < 1 || length > 60 || start + length > project.duration + .001)
    throw Error('Select a 1–60 second clip within the song.'); const id = selected; rendering = true; $<HTMLButtonElement>('export-rhythm').disabled = true; try {
    const result = await api('render', 'POST', { project_id: id, scene: 'rhythm', aspect: opts.aspect, height: settings.height, start, length });
    job = result.id;
    $('cancel-rhythm').hidden = false;
    $('download-rhythm').hidden = true;
    for (;;) {
        const state = await api('render/' + job);
        $('rhythm-export-status').textContent = state.status === 'running' ? `3D rendering: ${state.frames}/${state.total} frames` : state.status === 'queued' ? 'Waiting to render…' : state.status === 'done' ? 'Rhythm export complete' : state.status === 'cancelled' ? 'Export cancelled' : 'Export failed: ' + state.error;
        if (['done', 'failed', 'cancelled'].includes(state.status)) {
            if (state.status === 'done') {
                $('download-rhythm').hidden = false;
                await history();
            }
            break;
        }
        await new Promise(r => setTimeout(r, 1200));
    }
}
finally {
    rendering = false;
    $('cancel-rhythm').hidden = true;
    $<HTMLButtonElement>('export-rhythm').disabled = !project || !buildRhythmChart(project, settings).notes.length;
} }
$('rhythm-project').onchange = action(() => { if (rendering) {
    $<HTMLSelectElement>('rhythm-project').value = selected;
    throw Error('Wait for the export to finish before switching songs.');
} return load($<HTMLSelectElement>('rhythm-project').value); });
for (const id of ['density', 'approach', 'offset', 'palette', 'seed', 'subtitles'])
    $('rhythm-' + id).onchange = action(change);
$('new-seed').onclick = action(() => { $<HTMLInputElement>('rhythm-seed').value = String(Math.floor(Math.random() * 2147483647)); change(); });
$('rhythm-aspect').onchange = () => { settings = { ...settings, aspect: $<HTMLSelectElement>('rhythm-aspect').value as '16:9' | '9:16' }; opts.aspect = settings.aspect; preview(); };
$('rhythm-quality').onchange = () => { settings = { ...settings, height: Number($<HTMLSelectElement>('rhythm-quality').value) as 360 | 720 }; saveState(); };
$('save-rhythm').onclick = action(save);
$('export-rhythm').onclick = action(exportClip);
$('cancel-rhythm').onclick = action(async () => { if (job)
    await api('render/' + job + '/cancel', 'POST'); });
$('download-rhythm').onclick = action(() => downloadService(motionUrl('render/' + job + '/download'), 'rhythm-stage.mp4'));
$('play-rhythm').onclick = action(async () => { if (!audioReady)
    throw Error('Audio is not ready.'); if (playing) {
    audio.pause();
    playing = false;
}
else {
    await audio.play();
    playing = true;
} $('play-rhythm').textContent = playing ? 'Ⅱ' : '▶'; });
$('rhythm-seek').oninput = () => { audio.currentTime = Number($<HTMLInputElement>('rhythm-seek').value); engine?.renderAt(audio.currentTime); $('rhythm-time').textContent = audio.currentTime.toFixed(2) + 's'; };
function tick() { if (playing && engine) {
    engine.renderAt(audio.currentTime);
    $<HTMLInputElement>('rhythm-seek').value = String(audio.currentTime);
    $('rhythm-time').textContent = audio.currentTime.toFixed(2) + 's';
} requestAnimationFrame(tick); }
requestAnimationFrame(tick);
audio.addEventListener('ended', () => { playing = false; $('play-rhythm').textContent = '▶'; });
window.addEventListener('beforeunload', event => { if (dirty() || rendering) {
    event.preventDefault();
    event.returnValue = '';
} });
void action(async () => { const rows = await api('projects'); for (const row of rows) {
    const option = document.createElement('option');
    option.value = row.id;
    option.textContent = row.name;
    $('rhythm-project').append(option);
} const query = new URLSearchParams(location.search).get('project'), chosen = rows.find((r: any) => r.id === query) || rows[0]; if (chosen) {
    $<HTMLSelectElement>('rhythm-project').value = chosen.id;
    await load(chosen.id);
}
else
    status('No songs yet. Import a song and analyze its audio in Lyric Editor.'); })();
