#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suno2MV 音乐智能与视听特征感知分析器
---------------------------------------
基于 Librosa 与音频分轨数据，提取：
1. BPM 与节拍 (Beats)、小节重拍 (Downbeats)。
2. 鼓点打击事件 (Kick, Snare, Hi-Hat) 与 Drums Onset 律动。
3. 时域能量曲线 (RMS Energy Curve) 与能量跃迁检测。
4. 影视级推荐剪辑硬切点 (Cut Candidates) 自动规划。
5. 兼容历史 3D 轨迹与音符事件导出。
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Any, List, Optional
import numpy as np
import scipy.signal

# Monkeypatch scipy.signal.hann for newer scipy versions and older librosa versions
if not hasattr(scipy.signal, "hann"):
    import scipy.signal.windows
    scipy.signal.hann = scipy.signal.windows.hann

import librosa

from src.storyboard_schema import SongAnalysis, MusicCutPoint, MusicSection


def find_peaks(envelope, times, sr, hop_length, min_dist_sec=0.18, threshold_factor=1.2) -> list[float]:
    """
    在能量包络中寻找超过自适应阈值的局部峰值 (鼓点/重音)
    """
    mean_val = np.mean(envelope)
    std_val = np.std(envelope)
    threshold = mean_val + threshold_factor * std_val

    peaks: list[float] = []
    min_dist_frames = int(round(min_dist_sec * sr / hop_length))
    last_peak_frame = -min_dist_frames

    for i in range(1, len(envelope) - 1):
        if envelope[i] > envelope[i - 1] and envelope[i] > envelope[i + 1]:
            if envelope[i] > threshold:
                if i - last_peak_frame >= min_dist_frames:
                    peaks.append(float(times[i]))
                    last_peak_frame = i
    return peaks


def detect_cut_candidates(
    duration: float,
    beat_times: list[float],
    downbeats: list[float],
    drum_hits: list[dict[str, Any]],
    energy_curve: list[dict[str, float]],
    sections: Optional[list[MusicSection]] = None,
    min_shot_duration: float = 1.8,
    max_shot_duration: float = 6.0,
) -> list[MusicCutPoint]:
    """
    基于影视剪辑语法合成推荐切刀点 (Cut Candidates)
    
    规则网：
    1. 乐段起始点 (Section Boundary) 是最高优先级的切镜点 (confidence=1.0)
    2. 下降拍 (Downbeat) 配合鼓点 Kick/Snare 或能量跃迁是天然硬切点 (confidence=0.85~0.9)
    3. 控制节奏：镜头最短不少于 min_shot_duration，最长不超过 max_shot_duration
    """
    cut_points: list[MusicCutPoint] = []
    cut_times_set: set[float] = set()

    # 起始点 0.0s 必切
    cut_points.append(
        MusicCutPoint(
            time=0.0,
            confidence=1.0,
            source="section_boundary",
            strength=0.5,
            suggested_shot_size="EWS",
        )
    )
    cut_times_set.add(0.0)

    # 1. 乐段边界注入
    if sections:
        for sec in sections:
            t = round(sec.start, 3)
            if t > 0.5 and t < duration - 1.0 and t not in cut_times_set:
                cut_points.append(
                    MusicCutPoint(
                        time=t,
                        confidence=1.0,
                        source="section_boundary",
                        strength=sec.energy,
                        suggested_shot_size="EWS" if "Chorus" in sec.name else "WS",
                    )
                )
                cut_times_set.add(t)

    # 2. 鼓点打击与重拍提取
    kick_times = {round(hit["time"], 2) for hit in drum_hits if hit.get("type") == "kick"}
    snare_times = {round(hit["time"], 2) for hit in drum_hits if hit.get("type") == "snare"}

    # 3. 扫描 downbeats
    for db in downbeats:
        t = round(db, 3)
        if t <= 0.5 or t >= duration - 0.8:
            continue

        # 检查是否与已有切点过近
        too_close = any(abs(t - existing.time) < min_shot_duration for existing in cut_points)
        if too_close:
            continue

        # 检查是否伴随重低音或军鼓
        is_kick = any(abs(t - kt) < 0.12 for kt in kick_times)
        is_snare = any(abs(t - st) < 0.12 for st in snare_times)

        # 查找对应时刻的能量值
        energy_val = 0.5
        for pt in energy_curve:
            if abs(pt["time"] - t) < 0.15:
                energy_val = pt["energy"]
                break

        confidence = 0.75
        source = "downbeat"
        if is_kick or is_snare:
            confidence = 0.90
            source = "drum_onset"
        if energy_val > 0.7:
            confidence = max(confidence, 0.88)

        shot_size = "MS"
        if energy_val > 0.8:
            shot_size = "EWS" if is_kick else "ECU"
        elif energy_val < 0.35:
            shot_size = "MCU"

        cut_points.append(
            MusicCutPoint(
                time=t,
                confidence=confidence,
                source=source,
                strength=round(energy_val, 2),
                suggested_shot_size=shot_size,
            )
        )

    # 按时间升序排序
    cut_points.sort(key=lambda x: x.time)

    # 4. 间隙补全 (若两个切点间距超过 max_shot_duration，在强拍上插入补位切点)
    filled_cuts: list[MusicCutPoint] = [cut_points[0]]
    for i in range(1, len(cut_points)):
        prev_time = filled_cuts[-1].time
        curr_time = cut_points[i].time
        gap = curr_time - prev_time

        while beat_times and gap > max_shot_duration:
            # 在中间选一个合适的 beat
            ideal_split = prev_time + (gap / 2.0)
            best_beat = min(beat_times, key=lambda b: abs(b - ideal_split)) if beat_times else ideal_split
            if abs(best_beat - prev_time) >= min_shot_duration and abs(curr_time - best_beat) >= min_shot_duration:
                filled_cuts.append(
                    MusicCutPoint(
                        time=round(best_beat, 3),
                        confidence=0.7,
                        source="downbeat",
                        strength=0.5,
                        suggested_shot_size="MCU",
                    )
                )
                prev_time = best_beat
                gap = curr_time - prev_time
            else:
                break
        filled_cuts.append(cut_points[i])

    # 确保终点覆盖到 duration
    if filled_cuts[-1].time < duration - 1.0:
        filled_cuts.append(
            MusicCutPoint(
                time=round(duration, 3),
                confidence=1.0,
                source="section_boundary",
                strength=0.3,
                suggested_shot_size="EWS",
            )
        )

    filled_cuts.sort(key=lambda x: x.time)
    return filled_cuts


ANALYZER_VERSION = "motion-audio-v1"


def _normalized(values):
    values = np.asarray(values, dtype=float)
    scale = float(np.percentile(values, 99)) if values.size else 0.0
    if scale <= 1e-10 and values.size:
        scale = float(np.max(values))
    return np.clip(values / scale, 0, 1) if scale > 1e-10 else np.zeros_like(values)


def analyze_audio_for_director(
    audio_path: str | Path,
    drums_path: Optional[str | Path] = None,
    bass_path: Optional[str | Path] = None,
    sections: Optional[list[MusicSection]] = None,
    sr: int = 22050,
    feature_rate_hz: int = 100,
) -> SongAnalysis:
    """Measured envelopes and estimated rhythm; never invent a pulse for silence.

    Downbeats assume 4/4 with an energy-based phase, and drum names are spectral
    heuristics, not instrument recognition. These limitations travel with data.
    """
    if not 10 <= feature_rate_hz <= 200 or sr < 16000:
        raise ValueError("feature_rate_hz must be 10–200 and sr >=16000")
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"音频文件不存在: {path}")
    y, _ = librosa.load(path, sr=sr, mono=True)
    if not len(y) or not np.isfinite(y).all():
        raise ValueError("Audio must contain finite, non-empty samples")
    duration = len(y) / sr
    hop = max(1, round(sr / feature_rate_hz))
    n_fft = 2048
    spectrum = librosa.stft(y, n_fft=n_fft, hop_length=hop)
    _, percussion = librosa.decompose.hpss(spectrum)
    percussion_source = 'hpss_mix'
    if drums_path:
        drums, _ = librosa.load(drums_path, sr=sr, mono=True)
        if abs(len(drums) / sr - duration) > .1:
            raise ValueError("Drum stem duration differs from original audio")
        percussion = librosa.stft(librosa.util.fix_length(drums, size=len(y)), n_fft=n_fft, hop_length=hop)
        percussion_source = 'drums_stem'
    magnitude = np.abs(spectrum)
    percussive = np.abs(percussion)
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    frame_times = librosa.frames_to_time(np.arange(magnitude.shape[1]), sr=sr, hop_length=hop)
    target_times = np.arange(int(np.ceil(duration * feature_rate_hz))) / feature_rate_hz
    def sample(values):
        return np.interp(target_times, frame_times, _normalized(values))
    def band(spec, low, high):
        mask = (frequencies >= low) & (frequencies < high)
        return np.sqrt(np.mean(spec[mask] ** 2, axis=0))
    low = band(magnitude, 20, 200)
    if bass_path:
        bass, _ = librosa.load(bass_path, sr=sr, mono=True)
        if abs(len(bass) / sr - duration) > .1:
            raise ValueError("Bass stem duration differs from original audio")
        low = band(np.abs(librosa.stft(librosa.util.fix_length(bass, size=len(y)), n_fft=n_fft, hop_length=hop)), 20, 200)
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop)[0]
    onset = librosa.onset.onset_strength(S=librosa.amplitude_to_db(percussive, ref=np.max), sr=sr, hop_length=hop)
    silent = float(np.max(np.abs(y))) < 1e-7
    bpm, beat_times = 0.0, []
    if not silent and duration >= 2 and np.max(onset) > 1e-8:
        tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop)
        detected = librosa.frames_to_time(frames, sr=sr, hop_length=hop)
        beat_times = [float(t) for t in detected if 0 <= t < duration]
        bpm = float(np.asarray(tempo).reshape(-1)[0]) if len(beat_times) >= 2 else 0.0
    beat_times = sorted(set(round(t, 3) for t in beat_times))
    # Energy phase heuristic; no claim of measured musical meter.
    phase = 0
    if len(beat_times) >= 8:
        strengths = np.interp(beat_times, frame_times, _normalized(band(percussive, 20, 150)))
        phase = int(np.argmax([np.mean(strengths[i::4]) for i in range(4)]))
    downbeats = beat_times[phase::4]
    onsets = []
    drum_hits = []
    for label, env, spacing in [
        ('kick', band(percussive, 20, 150), .18),
        ('snare', band(percussive, 150, 3000), .18),
        ('hat', band(percussive, 4000, 10000), .08),
        ('onset', onset, .08),
    ]:
        norm = _normalized(env)
        peaks, _ = scipy.signal.find_peaks(norm, height=.15, prominence=.08, distance=max(1, round(spacing * sr / hop)))
        for i in peaks:
            time = float(frame_times[i])
            if time >= duration or silent:
                continue
            event = {'time': round(time, 3), 'strength': round(float(norm[i]), 4)}
            if label == 'onset': onsets.append(event)
            else: drum_hits.append({**event, 'type': label, 'confidence': .4})
    curves = [sample(v) for v in (rms, low, band(magnitude, 200, 4000), band(magnitude, 4000, 10000), onset)]
    envelopes = [{ 'time': round(float(t), 4), **{k: round(float(v[i]), 4) for k, v in zip(('rms','low','mid','high','flux'), curves)}} for i, t in enumerate(target_times)]
    energy_curve = [{'time': row['time'], 'energy': row['rms']} for row in envelopes]
    coarse = curves[0][::max(1, feature_rate_hz // 2)]
    changes = np.abs(np.diff(coarse, prepend=coarse[0]))
    peaks, _ = scipy.signal.find_peaks(changes, height=.18, distance=10)
    boundaries = [{'time': round(float(target_times[min(int(i * max(1, feature_rate_hz // 2)), len(target_times)-1)]), 3),
                   'strength': round(float(changes[i]), 4), 'confidence': .35} for i in peaks]
    drum_hits.sort(key=lambda h: (h['time'], h['type']))
    return SongAnalysis(bpm=round(bpm, 2), duration=duration, beats=beat_times, downbeats=downbeats,
        energy_curve=energy_curve, drum_hits=drum_hits, sections=sections or [], feature_rate_hz=feature_rate_hz,
        envelopes=envelopes, onsets=onsets, section_candidates=boundaries,
        cut_candidates=detect_cut_candidates(duration, beat_times, downbeats, drum_hits, energy_curve, sections),
        metadata={'algorithm_version': ANALYZER_VERSION, 'sample_rate': sr, 'hop_length': hop,
                  'percussion_source': percussion_source, 'downbeats_method': 'estimated_4_4_energy_phase',
                  'downbeats_confidence': .35 if downbeats else 0, 'drum_hits_method': 'spectral_onset_heuristic',
                  'section_candidates_method': 'energy_change_not_semantic_sections',
                  'normalization': 'per_track_per_channel_99th_percentile', 'silent': silent,
                  'beat_interval_regularity': round(float(np.clip(1 - np.std(np.diff(beat_times)) / np.mean(np.diff(beat_times)), 0, 1)), 3) if len(beat_times) > 2 else 0,
                  'confidence_note': 'Heuristic scores, not calibrated probabilities'})


def cached_audio_analysis(audio_path, cache_path, sections=None, feature_rate_hz=100, force=False):
    """Content/version/settings keyed cache; lyric edits only refresh cut hints."""
    import hashlib
    import tempfile
    audio_path, cache_path = Path(audio_path), Path(cache_path)
    digest = hashlib.sha256()
    with audio_path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
    key = {'audio_sha256': digest.hexdigest(), 'algorithm_version': ANALYZER_VERSION,
           'feature_rate_hz': feature_rate_hz, 'sample_rate': 22050, 'librosa_version': librosa.__version__}
    result = None
    if cache_path.is_file() and not force:
        try:
            candidate = SongAnalysis.model_validate_json(cache_path.read_text(encoding='utf-8'))
            if all(candidate.metadata.get(k) == v for k,v in key.items()): result = candidate
        except (ValueError, OSError): pass
    hit = result is not None
    if result is None: result = analyze_audio_for_director(audio_path, feature_rate_hz=feature_rate_hz)
    result.sections = sections or []
    result.cut_candidates = detect_cut_candidates(result.duration, result.beats, result.downbeats, result.drum_hits, result.energy_curve, result.sections)
    result.metadata.update(key)
    result.metadata['audio_path'] = str(audio_path.resolve())
    result.metadata['cache_hit'] = hit
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=cache_path.parent, suffix='.tmp', delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(result.model_dump_json(indent=2))
    try: tmp.replace(cache_path)
    finally: tmp.unlink(missing_ok=True)
    return result


# ----------------------------------------------------------------------------
# 兼容 CLI 命令行与 3D 游戏轨道生成
# ----------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Suno2MV 视听特征与节奏分析器")
    parser.add_argument("--audio", required=True, help="输入音频路径 (WAV/MP3)")
    parser.add_argument("--output", required=True, help="分析 JSON 输出路径")
    parser.add_argument("--fps", type=int, default=100, help="动效特征采样率 (默认: 100Hz)")
    return parser.parse_args()


def main():
    args = parse_args()
    if not os.path.exists(args.audio):
        print(f"Error: Audio file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing: {args.audio}")
    analysis = cached_audio_analysis(args.audio, args.output, feature_rate_hz=args.fps)

    # Cache writer already persisted the complete analysis atomically.
    print(f"✅ Successfully wrote director analysis to: {args.output}")


if __name__ == "__main__":
    main()
