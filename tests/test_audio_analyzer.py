"""
单元测试：音乐智能与音频特征分析器 (audio_analyzer)
测试节拍分析、能量跃迁与硬切候选点 (Cut Candidates) 合成逻辑。
"""
import pytest
import numpy as np
from pathlib import Path
import soundfile as sf

from src.audio_analyzer import (
    find_peaks,
    detect_cut_candidates,
    analyze_audio_for_director,
)
from src.storyboard_schema import MusicSection


def test_find_peaks_basic():
    # 模拟合成能量包络与时间
    envelope = np.array([0.1, 0.2, 0.8, 0.1, 0.1, 0.9, 0.2, 0.1])
    times = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    peaks = find_peaks(envelope, times, sr=22050, hop_length=512, min_dist_sec=0.05, threshold_factor=0.5)
    assert len(peaks) > 0
    assert any(abs(p - 0.2) < 0.05 for p in peaks)


def test_detect_cut_candidates():
    duration = 30.0
    beat_times = [float(b * 0.5) for b in range(60)] # 120 BPM, 每 0.5s 一拍
    downbeats = [float(db * 2.0) for db in range(15)] # 每 4 拍一个小节
    drum_hits = [
        {"time": 2.0, "type": "kick"},
        {"time": 4.0, "type": "snare"},
        {"time": 10.0, "type": "kick"},
    ]
    energy_curve = [
        {"time": t * 0.5, "energy": 0.3 if t < 20 else 0.85}
        for t in range(60)
    ]
    sections = [
        MusicSection(name="Intro", start=0.0, end=10.0, energy=0.3),
        MusicSection(name="Chorus 1", start=10.0, end=30.0, energy=0.9),
    ]

    cuts = detect_cut_candidates(
        duration=duration,
        beat_times=beat_times,
        downbeats=downbeats,
        drum_hits=drum_hits,
        energy_curve=energy_curve,
        sections=sections,
        min_shot_duration=1.5,
        max_shot_duration=6.0,
    )

    assert len(cuts) >= 5
    # 0.0 起始点
    assert cuts[0].time == 0.0
    # 乐段起始点应该被包含
    assert any(abs(c.time - 10.0) < 0.1 and c.source == "section_boundary" for c in cuts)
    # 所有切点时间单调递增
    for i in range(len(cuts) - 1):
        assert cuts[i + 1].time > cuts[i].time


def test_analyze_audio_for_director_synthetic(tmp_path):
    # 生成 4 秒合成立体声测试音频
    sr = 22050
    duration = 4.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # 模拟 120 BPM 的低频底鼓脉冲 + 高频白噪声
    sig = 0.5 * np.sin(2 * np.pi * 60 * t) # 60Hz 贝斯
    # 规律脉冲
    for beat in range(8):
        idx = int(beat * 0.5 * sr)
        if idx < len(sig):
            sig[idx : min(len(sig), idx + 1000)] += 0.8

    wav_file = tmp_path / "synthetic_test.wav"
    sf.write(str(wav_file), sig, sr)

    analysis = analyze_audio_for_director(wav_file)
    assert analysis.duration == pytest.approx(4.0, abs=0.2)
    assert analysis.bpm > 0
    assert len(analysis.energy_curve) > 0
    assert len(analysis.cut_candidates) >= 1
