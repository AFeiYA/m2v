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
function saveState() { $<HTMLButtonElement>('save-rhythm').disabled = !dirty() || saving; $('draft-state').textContent = saving ? '保存中…' : dirty() ? '场景预览尚未保存' : project ? '已保存' : '选择歌曲开始'; }
function preview() { if (!project)
    return; engine?.dispose(); const size = renderSize(opts), canvas = $<HTMLCanvasElement>('rhythm-stage'); canvas.width = size.width; canvas.height = size.height; $('stage-box').style.aspectRatio = `${size.width}/${size.height}`; engine = new RhythmPreview(canvas, project, opts, size.width, size.height, settings, audio.currentTime); engine.renderAt(audio.currentTime); const chart = buildRhythmChart(project, settings); $('note-count').textContent = String(chart.notes.length); $('rhythm-warnings').replaceChildren(); for (const text of chart.warnings) {
    const li = document.createElement('li');
    li.textContent = text;
    $('rhythm-warnings').append(li);
} $('stage-meta').textContent = `${opts.aspect} · ${size.width}×${size.height}`; $<HTMLButtonElement>('export-rhythm').disabled = rendering || !chart.notes.length; saveState(); }
function showSettings() { opts.aspect = settings.aspect; $<HTMLSelectElement>('rhythm-aspect').value = settings.aspect; $<HTMLSelectElement>('rhythm-quality').value = String(settings.height); for (const key of ['density', 'approach', 'palette', 'seed'] as const)
    $<HTMLInputElement>('rhythm-' + key).value = String(settings[key]); $<HTMLInputElement>('rhythm-offset').value = String(Math.round(settings.offset * 1000)); $<HTMLInputElement>('rhythm-subtitles').checked = settings.subtitles; $('approach-value').textContent = settings.approach.toFixed(1) + ' 秒 · 调整预判距离，不移动命中时间'; }
function change() { if (!project)
    return; const seed = Number($<HTMLInputElement>('rhythm-seed').value), offset = Number($<HTMLInputElement>('rhythm-offset').value), approach = Number($<HTMLInputElement>('rhythm-approach').value); if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647 || !Number.isFinite(offset) || Math.abs(offset) > 500 || !Number.isFinite(approach) || approach < 1.2 || approach > 4) {
    showSettings();
    throw Error('种子或节奏参数超出范围');
} settings = { ...settings, seed, offset: offset / 1000, approach, density: $<HTMLSelectElement>('rhythm-density').value as RhythmSettings['density'], palette: $<HTMLSelectElement>('rhythm-palette').value as RhythmSettings['palette'], subtitles: $<HTMLInputElement>('rhythm-subtitles').checked }; showSettings(); preview(); status('已更新本地场景预览，满意后保存。'); }
async function load(id: string) { if (dirty() && !confirm('切换歌曲将放弃未保存的场景修改，是否继续？')) {
    $<HTMLSelectElement>('rhythm-project').value = selected;
    return;
} if (!id)
    return; const seq = ++sequence; audio.pause(); playing = false; $('play-rhythm').textContent = '▶'; audioReady = false; $<HTMLButtonElement>('play-rhythm').disabled = true; status('正在读取歌曲、节奏与场景设置…'); const [data, config] = await Promise.all([api('project?project_id=' + encodeURIComponent(id)), api('rhythm?project_id=' + encodeURIComponent(id))]); if (seq !== sequence)
    return; project = normalizeProject(data.project); selected = id; settings = { ...rhythmDefaults, ...config.settings }; saved = JSON.stringify(settings); showSettings(); $('track-name').textContent = project.title; $<HTMLAnchorElement>('back-studio').href = '/motion-studio?project=' + encodeURIComponent(id); $<HTMLInputElement>('rhythm-seek').max = String(project.duration); $<HTMLInputElement>('rhythm-length').value = String(Math.min(30, Math.floor(project.duration))); $('rhythm-duration').textContent = project.duration.toFixed(1) + 's'; audio.src = ''; audio.currentTime = 0; preview(); let next = ''; if (data.audio_url && cloudService()) {
    const result = await serviceAudio(data.audio_url, id, data.project.audio_cache);
    if (seq !== sequence)
        return;
    next = URL.createObjectURL(result.blob);
} if (audioUrl)
    URL.revokeObjectURL(audioUrl); audioUrl = next; audio.src = next || data.audio_url || ''; audio.load(); audioReady = !!(next || data.audio_url); $<HTMLButtonElement>('play-rhythm').disabled = !audioReady; status('3D 演出已就绪 · 拖动进度检查卡点；自动 Perfect 不代表真人成绩。'); await history(); }
async function save() { if (!project || !selected || saving)
    return; const id = selected, seq = sequence, snapshot = JSON.stringify(settings); saving = true; saveState(); try {
    await api('rhythm', 'PUT', { project_id: id, settings: JSON.parse(snapshot) });
    if (id === selected && seq === sequence) {
        saved = snapshot;
        status(dirty() ? '已保存提交版本，后续修改仍在本地。' : '场景设置已保存，原海报方案保持不变。');
    }
}
finally {
    saving = false;
    saveState();
} }
async function history() { const id = selected, seq = sequence, records = await api('exports?project_id=' + encodeURIComponent(id)); if (id !== selected || seq !== sequence)
    return; $('rhythm-history').replaceChildren(); for (const record of records.filter((r: any) => r.scene === 'rhythm' && r.status === 'done')) {
    const button = document.createElement('button');
    button.textContent = '下载历史演出 · ' + new Date(record.created_at * 1000).toLocaleString();
    button.onclick = action(() => downloadService(motionUrl('render/' + record.id + '/download'), 'rhythm-stage.mp4'));
    $('rhythm-history').append(button);
} }
async function exportClip() { if (!project || !selected)
    return; if (dirty())
    throw Error('请先保存场景，再导出与当前预览一致的视频。'); if (rendering)
    throw Error('已有节奏演出正在导出。'); const start = Number($<HTMLInputElement>('rhythm-start').value), length = Number($<HTMLInputElement>('rhythm-length').value); if (!Number.isFinite(start) || !Number.isFinite(length) || start < 0 || length < 1 || length > 60 || start + length > project.duration + .001)
    throw Error('请选择歌曲范围内 1–60 秒的片段。'); const id = selected; rendering = true; $<HTMLButtonElement>('export-rhythm').disabled = true; try {
    const result = await api('render', 'POST', { project_id: id, scene: 'rhythm', aspect: opts.aspect, height: settings.height, start, length });
    job = result.id;
    $('cancel-rhythm').hidden = false;
    $('download-rhythm').hidden = true;
    for (;;) {
        const state = await api('render/' + job);
        $('rhythm-export-status').textContent = state.status === 'running' ? `3D 渲染 ${state.frames}/${state.total} 帧` : state.status === 'queued' ? '等待渲染…' : state.status === 'done' ? '节奏演出已完成' : state.status === 'cancelled' ? '导出已取消' : '导出失败：' + state.error;
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
    throw Error('导出中请等待完成，再切换歌曲。');
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
    throw Error('音频尚未就绪'); if (playing) {
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
    status('还没有歌曲，请先到歌词编辑器导入并分析音频。'); })();
