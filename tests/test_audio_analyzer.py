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


def test_silence_does_not_invent_rhythm(tmp_path):
    path = tmp_path / 'silence.wav'
    sf.write(path, np.zeros(22050 * 8), 22050)
    analysis = analyze_audio_for_director(path)
    assert analysis.bpm == 0
    assert not analysis.beats and not analysis.downbeats
    assert not analysis.onsets and not analysis.drum_hits
    assert len(analysis.envelopes) == 800
    assert analysis.envelopes[-1]['time'] == 7.99
    assert all(value == 0 for row in analysis.envelopes for key, value in row.items() if key != 'time')
    assert all(point.source == 'section_boundary' for point in analysis.cut_candidates)


def test_features_and_onset_timing(tmp_path):
    sr = 22050
    signal = np.zeros(sr * 12)
    rng = np.random.default_rng(42)
    pulse = rng.normal(size=int(.03 * sr)) * np.exp(-np.linspace(0, 8, int(.03 * sr)))
    expected = np.arange(.5, 11.5, .5)
    for time in expected:
        index = round(time * sr)
        signal[index:index + len(pulse)] = pulse
    path = tmp_path / 'clicks.wav'
    sf.write(path, signal, sr)
    analysis = analyze_audio_for_director(path)
    assert analysis.bpm == pytest.approx(120, abs=4)
    assert len(analysis.envelopes) == 1200
    assert all(0 <= value <= 1 and np.isfinite(value) for row in analysis.envelopes for key, value in row.items() if key != 'time')
    assert all(min(abs(event['time'] - time) for event in analysis.onsets) < .08 for time in expected)
    assert 'estimated_4_4' in analysis.metadata['downbeats_method']


def test_cache_reuse_invalidation_and_section_refresh(tmp_path, monkeypatch):
    import src.audio_analyzer as analyzer
    from src.storyboard_schema import SongAnalysis
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'original')
    cache = tmp_path / 'analysis.json'
    calls = []
    def compute(*args, **kwargs):
        calls.append(kwargs)
        return SongAnalysis(duration=12, bpm=120, beats=[1, 3, 5, 7, 9], downbeats=[1, 5, 9])
    monkeypatch.setattr(analyzer, 'analyze_audio_for_director', compute)
    first = analyzer.cached_audio_analysis(audio, cache)
    assert not first.metadata['cache_hit']
    section = MusicSection(name='Chorus', start=4, end=12)
    second = analyzer.cached_audio_analysis(audio, cache, sections=[section])
    assert second.metadata['cache_hit'] and len(calls) == 1
    assert any(cut.time == 4 and cut.source == 'section_boundary' for cut in second.cut_candidates)
    audio.write_bytes(b'changed')
    assert not analyzer.cached_audio_analysis(audio, cache).metadata['cache_hit']
    analyzer.cached_audio_analysis(audio, cache, feature_rate_hz=50)
    analyzer.cached_audio_analysis(audio, cache, feature_rate_hz=50, force=True)
    assert len(calls) == 4
    cache.write_text('{broken')
    analyzer.cached_audio_analysis(audio, cache)
    assert len(calls) == 5
