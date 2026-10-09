"""
Alignment Task Specification.
Immutable representation of an isolated acoustic alignment unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.preprocessor import LyricLine


@dataclass(frozen=True)
class AlignmentTask:
    """单个不可变的歌词对齐任务单元。

    在模型推理执行前完整规划生成，明确规定行索引、语言、音频窗口与定位依据。
    执行层仅负责在给定窗口内执行声学对齐，不得修改全局状态或随意越界。
    """
    task_id: str
    paragraph_idx: int
    line_indices: list[int]
    lyrics: list[tuple[int, LyricLine]] = field(repr=False)
    language: str
    window_start: float
    window_end: float
    anchor_source: str = "unknown"
    is_estimated: bool = False
    confidence: str = "normal"

    @property
    def duration(self) -> float:
        return max(0.0, self.window_end - self.window_start)

    @property
    def line_count(self) -> int:
        return len(self.line_indices)
