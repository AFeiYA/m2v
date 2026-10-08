"""Cloud runtime regressions without GPU, model downloads or private audio."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.aligner as aligner
from src.config import AlignerConfig


def test_cuda_constructor_failure_retries_cpu(monkeypatch):
    calls = []
    def model(name, device, compute_type):
        calls.append((device, compute_type))
        if device == 'cuda':
            raise RuntimeError('CUDA failed with error no CUDA-capable device is detected')
        return 'cpu-model'
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=model))
    monkeypatch.setattr(aligner.torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(aligner, '_whisper_cache', {})
    cfg = AlignerConfig(whisper_model='base', device='cuda')
    assert aligner._get_whisper(cfg) == 'cpu-model'
    assert calls == [('cuda', 'float16'), ('cpu', 'int8')]
    assert cfg.device == 'cuda'


def test_lazy_cuda_failure_restarts_full_transcription(monkeypatch):
    partial, complete = object(), object()
    def failing_segments():
        yield partial
        raise RuntimeError('CUDA runtime unavailable')
    gpu = Mock()
    gpu.transcribe.return_value = (failing_segments(), 'gpu-info')
    cpu = Mock()
    cpu.transcribe.return_value = (iter([complete]), 'cpu-info')
    monkeypatch.setattr(aligner, '_get_whisper', lambda cfg: gpu if cfg.device == 'cuda' else cpu)
    cfg = AlignerConfig(device='cuda')
    segments, info = aligner._transcribe_whisper('song.wav', cfg, language='en', vad_filter=False)
    assert segments == [complete]  # do not append partial CUDA results
    assert info == 'cpu-info'
    cpu.transcribe.assert_called_once_with('song.wav', language='en', vad_filter=False)
    assert cfg.device == 'cuda'


def test_non_cuda_errors_are_not_hidden(monkeypatch):
    model = Mock()
    model.transcribe.side_effect = FileNotFoundError('missing audio')
    get_model = Mock(return_value=model)
    monkeypatch.setattr(aligner, '_get_whisper', get_model)
    with pytest.raises(FileNotFoundError):
        aligner._transcribe_whisper('missing.wav', AlignerConfig())
    assert get_model.call_count == 1


def test_failed_asr_does_not_allow_unanchored_song_success():
    with pytest.raises(RuntimeError, match='未能提取句级 ASR 锚点'):
        aligner._validate_asr_evidence([], 26, [(17.4, 228.5)])
    with pytest.raises(RuntimeError, match='覆盖不足'):
        aligner._validate_asr_evidence([{'end': 133.5}], 26, [(17.4, 228.5)])
    aligner._validate_asr_evidence([{'end': 228.0}], 26, [(17.4, 228.5)])
    aligner._validate_asr_evidence([], 1, [(0, 2)])


def test_old_asr_cache_is_refreshed_with_correct_language(tmp_path, monkeypatch):
    audio = tmp_path / 'vocals.wav'
    audio.write_bytes(b'fake-audio')
    cache = tmp_path / '.vocals_asr_words.json'
    cache.write_text(json.dumps({'version': 2, 'meta': {'mtime': audio.stat().st_mtime,
        'size': audio.stat().st_size, 'language': 'en', 'model': 'base'},
        'words': [{'raw': 'stale', 'py': 'stale', 'start': 0, 'end': 1}]}))
    transcribe = Mock(return_value=([SimpleNamespace(words=[SimpleNamespace(word='Hello', start=2, end=3)])], None))
    monkeypatch.setattr(aligner, '_transcribe_whisper', transcribe)
    words = aligner.extract_asr_words(audio, config=AlignerConfig(whisper_model='base'), language='en')
    assert words[0]['raw'] == 'hello'
    assert transcribe.call_args.kwargs['language'] == 'en'
    assert json.loads(cache.read_text())['version'] == 3
    assert aligner.extract_asr_words(audio, config=AlignerConfig(whisper_model='base'), language='en') == words
    assert transcribe.call_count == 1
