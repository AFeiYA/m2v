import type { Project } from './model';
export type RhythmSettings = {
    version: 'rhythm-stage-v1';
    aspect: '16:9' | '9:16';
    height: 360 | 720;
    seed: number;
    density: 'sparse' | 'balanced' | 'dense';
    approach: number;
    offset: number;
    palette: 'cyan' | 'violet';
    subtitles: boolean;
};
export const rhythmDefaults: RhythmSettings = { version: 'rhythm-stage-v1', aspect: '16:9', height: 360, seed: 42, density: 'balanced', approach: 2.8, offset: 0, palette: 'cyan', subtitles: true };
export type RhythmNote = {
    id: string;
    time: number;
    lane: number;
    strength: number;
    source: 'beat' | 'drum';
};
export type RhythmChart = {
    notes: RhythmNote[];
    warnings: string[];
    seed: number;
};
export function seeded(index: number, seed: number) { let n = (index ^ seed) >>> 0; n = Math.imul(n ^ n >>> 16, 0x45d9f3b); n = Math.imul(n ^ n >>> 16, 0x45d9f3b); return ((n ^ n >>> 16) >>> 0) / 4294967296; }
export function buildRhythmChart(project: Project, settings: RhythmSettings): RhythmChart {
    const candidates: {
        time: number;
        source: 'beat' | 'drum';
        strength: number;
    }[] = [];
    const beats = [...new Set(project.analysis.beats.filter(Number.isFinite))].sort((a, b) => a - b);
    for (let i = 0; i < beats.length; i++)
        if (settings.density !== 'sparse' || i % 2 === 0)
            candidates.push({ time: beats[i], source: 'beat', strength: .65 });
    if (settings.density === 'dense' || !beats.length)
        for (const hit of project.analysis.drum_hits) {
            if (Number.isFinite(hit.time) && ['kick', 'snare'].includes(hit.type))
                candidates.push({ time: hit.time, source: 'drum', strength: .95 });
        }
    candidates.sort((a, b) => a.time - b.time || b.strength - a.strength);
    const notes: RhythmNote[] = [];
    for (const candidate of candidates) {
        const time = Math.round((candidate.time + settings.offset) * 1000) / 1000;
        if (time < 0 || time >= project.duration || notes.length && time - notes.at(-1)!.time < .18 - 1e-6)
            continue;
        let lane = Math.floor(seeded(notes.length + 1, settings.seed) * 3);
        if (notes.length >= 2 && notes.at(-1)!.lane === lane && notes.at(-2)!.lane === lane)
            lane = (lane + 1) % 3;
        notes.push({ id: `note-${notes.length}`, time, lane, strength: candidate.strength, source: candidate.source });
        if (notes.length >= 12000)
            break;
    }
    const warnings = ['拍点和鼓点是估计结果；AUTO PERFECT 是程序演出，不是玩家成绩。'];
    if (!notes.length)
        warnings.push('没有可用拍点：请先在歌词编辑器分析音频，再重新载入歌曲。');
    else if (notes[0].time < settings.approach)
        warnings.push('开头音符使用歌曲开始前的虚拟进场，不移动音频或命中时间。');
    return { notes, warnings, seed: settings.seed };
}
export function rhythmState(chart: RhythmChart, t: number) {
    let lo = 0, hi = chart.notes.length;
    while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (chart.notes[mid].time <= t)
            lo = mid + 1;
        else
            hi = mid;
    }
    const last = chart.notes[lo - 1];
    return { combo: lo, last, flash: last ? Math.max(0, 1 - (t - last.time) / .24) : 0 };
}
export function notePose(note: RhythmNote, t: number, approach: number) { return { x: (note.lane - 1) * 2.3, z: (t - note.time) * 16, visible: note.time - t <= approach && note.time - t >= -.08 }; }
