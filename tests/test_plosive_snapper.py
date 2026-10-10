"""
Unit tests for plosive consonant snapping and English syllable decomposition.
"""
import numpy as np
import pytest
from src.storyboard_schema import WordTimestamp, SyllableTimestamp
from src.align.plosive_snapper import (
    split_english_syllable_texts,
    decompose_word_syllables,
    refine_plosives_and_melisma,
)


def test_split_english_syllable_texts():
    assert split_english_syllable_texts("never") == ["ne", "ver"]
    assert split_english_syllable_texts("circus") == ["cir", "cus"]
    assert split_english_syllable_texts("could") == ["could"]
    assert split_english_syllable_texts("take") == ["take"]
    assert split_english_syllable_texts("running") == ["run", "ning"]
    assert split_english_syllable_texts("momentum") == ["mo", "men", "tum"]


def test_decompose_word_syllables_melisma():
    w = WordTimestamp(word="never", start=10.0, end=11.5)
    syls = decompose_word_syllables(w)
    assert syls is not None
    assert len(syls) == 2
    assert syls[0].text == "ne"
    assert syls[1].text == "ver"
    assert syls[0].start == 10.0
    assert syls[0].end <= 10.35
    assert syls[1].start == syls[0].end
    assert syls[1].end == 11.5


def test_decompose_single_syllable_word():
    w = WordTimestamp(word="could", start=10.0, end=10.5)
    syls = decompose_word_syllables(w)
    assert syls is None  # Single syllable word does not need sub-syllable decomposition


def test_plosive_snap_and_melisma_extension():
    sr = 16000
    # Create 3s synthetic audio
    # 0.0 ~ 1.0s: voice (tone) for word 1 (never)
    # 1.0 ~ 1.8s: continuing voice melisma (0.05 amp)
    # 1.80 ~ 1.90s: closure silence (0.00 amp)
    # 1.90s: sharp burst spike + tone for word 2 (could)
    t = np.linspace(0, 3.0, 3 * sr, endpoint=False)
    wav = np.zeros_like(t, dtype=np.float32)
    # Word 1 + melisma
    wav[int(0.2 * sr) : int(1.80 * sr)] = 0.08 * np.sin(2 * np.pi * 220 * t[int(0.2 * sr) : int(1.80 * sr)])
    # 1.80 ~ 1.90s is zero (closure)
    # Burst at 1.90s
    burst_idx = int(1.90 * sr)
    wav[burst_idx : burst_idx + int(0.01 * sr)] = 0.5 * np.random.randn(int(0.01 * sr))
    wav[burst_idx + int(0.01 * sr) : int(2.4 * sr)] = 0.08 * np.sin(2 * np.pi * 260 * t[burst_idx + int(0.01 * sr) : int(2.4 * sr)])

    words = [
        WordTimestamp(word="never", start=0.2, end=1.0),
        WordTimestamp(word="could", start=1.95, end=2.4),
    ]

    refined = refine_plosives_and_melisma(words, wav, sr=sr)
    assert len(refined) == 2
    # 'could' onset snapped near burst (around 1.90s)
    assert abs(refined[1].start - 1.90) <= 0.03
    # 'never' end extended through melisma up to closure dip (around 1.80s ~ 1.88s)
    assert refined[0].end >= 1.75
    assert refined[0].end <= refined[1].start
    # 'never' syllables created
    assert refined[0].syllables is not None
    assert len(refined[0].syllables) == 2


def test_elongated_plosive_snap_and_melisma_bridging():
    sr = 16000
    # Synthetic audio where singer sings 'never' continuously from 0.2s to 1.80s
    # Closure silence at 1.80 ~ 1.90s
    # Plosive burst at 1.90s, followed by 'could' tone to 2.4s
    t = np.linspace(0, 3.0, 3 * sr, endpoint=False)
    wav = np.zeros_like(t, dtype=np.float32)
    # Melisma unbroken tone
    wav[int(0.2 * sr) : int(1.80 * sr)] = 0.08 * np.sin(2 * np.pi * 220 * t[int(0.2 * sr) : int(1.80 * sr)])
    # Closure dip at 1.80 ~ 1.90s (silence)
    # Burst at 1.90s
    burst_idx = int(1.90 * sr)
    wav[burst_idx : burst_idx + int(0.01 * sr)] = 0.5 * np.random.randn(int(0.01 * sr))
    wav[burst_idx + int(0.01 * sr) : int(2.4 * sr)] = 0.08 * np.sin(2 * np.pi * 260 * t[burst_idx + int(0.01 * sr) : int(2.4 * sr)])

    # Whisper erroneously split 'could' at 1.0s (dur=1.4s) instead of 1.90s
    words = [
        WordTimestamp(word="never", start=0.2, end=1.0),
        WordTimestamp(word="could", start=1.0, end=2.4),
    ]

    refined = refine_plosives_and_melisma(words, wav, sr=sr)
    assert len(refined) == 2
    # 'could' onset must be snapped to the true burst (~1.90s), NOT left at 1.0s
    assert abs(refined[1].start - 1.90) <= 0.03
    # 'never' must be bridged to the closure dip (~1.80s ~ 1.88s)
    assert refined[0].end >= 1.75
    assert refined[0].end <= refined[1].start
    # 'never' syllables must be re-decomposed
    assert refined[0].syllables is not None
    assert len(refined[0].syllables) == 2
    assert refined[0].syllables[1].end == refined[0].end

