"""
Lyric Alignment Engine Subsystem.
Modular architecture:
- task: Immutable AlignmentTask specification
- evidence: Phonetic tokenization, sequence matching, silence snapping
- planner: Pure-function Task Planning & Validation
- executor: Pure Task Execution via Wav2Vec2 CTC / Whisper
- quality: Quality auditing, over-compression detection, self-healing
"""

from src.align.evidence import (
    _fallback_even_split,
    _mixed_run_split_bounds,
    _unique_phrase_anchors,
    detect_line_lang,
    detect_song_primary_language,
    find_silence_snap,
    tokenize_lyric_line,
    tokenize_lyric_phonetic,
)
from src.align.executor import execute_all_tasks, execute_task
from src.align.planner import build_alignment_tasks
from src.align.quality import (
    _audit_alignment,
    _self_heal_alignment,
    _trim_word_over_silence,
    alignment_quality_issue,
)
from src.align.task import AlignmentTask

__all__ = [
    "AlignmentTask",
    "tokenize_lyric_line",
    "tokenize_lyric_phonetic",
    "_fallback_even_split",
    "_mixed_run_split_bounds",
    "find_silence_snap",
    "_unique_phrase_anchors",
    "detect_line_lang",
    "detect_song_primary_language",
    "build_alignment_tasks",
    "execute_task",
    "execute_all_tasks",
    "alignment_quality_issue",
    "_trim_word_over_silence",
    "_audit_alignment",
    "_self_heal_alignment",
]
