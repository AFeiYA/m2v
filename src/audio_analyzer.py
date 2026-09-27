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

        while gap > max_shot_duration:
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


def analyze_audio_for_director(
    audio_path: str | Path,
    drums_path: Optional[str | Path] = None,
    bass_path: Optional[str | Path] = None,
    sections: Optional[list[MusicSection]] = None,
    sr: int = 22050,
) -> SongAnalysis:
    """
    针对 AI 导演与视听剪辑的音频高阶特征分析
    """
    audio_path = str(audio_path)
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    # 1. 加载音频并提取时长
    y, sr = librosa.load(audio_path, sr=sr)
    duration = float(librosa.get_duration(y=y, sr=sr))

    # 2. 和声与打击乐分离 (HPSS)
    y_harm, y_perc = librosa.effects.hpss(y)

    # 如果提供了专门的 Demucs 提取的 drums 音频，优先使用其作为打击乐源
    if drums_path and os.path.exists(str(drums_path)):
        try:
            y_drums, _ = librosa.load(str(drums_path), sr=sr)
            y_perc = y_drums
        except Exception:
            pass

    # 3. 节拍与 BPM 估计
    tempo, beat_frames = librosa.beat.beat_track(y=y_perc, sr=sr)
    bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
    beat_times = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]

    # 4. 计算小节重拍 (4/4 拍，每 4 拍一个小节头)
    downbeats = [beat_times[i] for i in range(0, len(beat_times), 4)] if beat_times else []

    # 5. 频段滤波提取 Kick, Snare, Hi-hat 鼓点打击事件
    hop_length = 512
    stft = np.abs(librosa.stft(y_perc, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr)
    times = librosa.frames_to_time(np.arange(stft.shape[1]), sr=sr, hop_length=hop_length)

    kick_mask = freqs < 120
    kick_env = np.sum(stft[kick_mask, :], axis=0) if np.any(kick_mask) else np.zeros(stft.shape[1])

    snare_mask = (freqs >= 200) & (freqs < 1000)
    snare_env = np.sum(stft[snare_mask, :], axis=0) if np.any(snare_mask) else np.zeros(stft.shape[1])

    hat_mask = (freqs >= 4000) & (freqs < 8000)
    hat_env = np.sum(stft[hat_mask, :], axis=0) if np.any(hat_mask) else np.zeros(stft.shape[1])

    kick_peaks = find_peaks(kick_env, times, sr, hop_length, min_dist_sec=0.22, threshold_factor=1.2)
    snare_peaks = find_peaks(snare_env, times, sr, hop_length, min_dist_sec=0.25, threshold_factor=1.3)
    hat_peaks = find_peaks(hat_env, times, sr, hop_length, min_dist_sec=0.15, threshold_factor=1.0)

    drum_hits: list[dict[str, Any]] = []
    for t in kick_peaks:
        drum_hits.append({"time": float(t), "type": "kick"})
    for t in snare_peaks:
        drum_hits.append({"time": float(t), "type": "snare"})
    for t in hat_peaks:
        drum_hits.append({"time": float(t), "type": "hat"})
    drum_hits.sort(key=lambda x: x["time"])

    # 6. 计算连续 RMS 能量采样曲线 (采样率约 10Hz)
    rms_raw = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    max_rms = float(np.max(rms_raw)) if len(rms_raw) > 0 and np.max(rms_raw) > 0 else 1.0
    rms_norm = rms_raw / max_rms

    times_raw = librosa.frames_to_time(np.arange(len(rms_raw)), sr=sr, hop_length=hop_length)
    target_fps = 10
    hop_sec = hop_length / sr
    step = max(1, int(round(1.0 / (target_fps * hop_sec))))

    energy_curve: list[dict[str, float]] = []
    for idx in range(0, len(rms_norm), step):
        energy_curve.append({
            "time": round(float(times_raw[idx]), 2),
            "energy": round(float(rms_norm[idx]), 3),
        })

    # 7. 综合生成推荐切刀点序列
    cut_candidates = detect_cut_candidates(
        duration=duration,
        beat_times=beat_times,
        downbeats=downbeats,
        drum_hits=drum_hits,
        energy_curve=energy_curve,
        sections=sections,
    )

    return SongAnalysis(
        bpm=round(bpm, 2),
        duration=round(duration, 2),
        beats=[round(b, 3) for b in beat_times],
        downbeats=[round(db, 3) for db in downbeats],
        energy_curve=energy_curve,
        drum_hits=drum_hits,
        cut_candidates=cut_candidates,
        sections=sections or [],
    )


# ----------------------------------------------------------------------------
# 兼容 CLI 命令行与 3D 游戏轨道生成
# ----------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Suno2MV 视听特征与节奏分析器")
    parser.add_argument("--audio", required=True, help="输入音频路径 (WAV/MP3)")
    parser.add_argument("--output", required=True, help="分析 JSON 输出路径")
    parser.add_argument("--fps", type=int, default=20, help="采样率 (默认: 20Hz)")
    return parser.parse_args()


def main():
    args = parse_args()
    if not os.path.exists(args.audio):
        print(f"Error: Audio file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing: {args.audio}")
    analysis = analyze_audio_for_director(args.audio)

    # 导出兼容旧版 3D 轨迹格式及完整分析
    out_dict = analysis.model_dump()
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out_dict, f, ensure_ascii=False, indent=2)

    print(f"✅ Successfully wrote director analysis to: {args.output}")


if __name__ == "__main__":
    main()
