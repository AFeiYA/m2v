"""Shared handling of lyric headings and inline arrangement cues."""
from __future__ import annotations

import re

_SQUARE_CUE = re.compile(r"^(?:\[.+\]|【.+】)$")
_ROUND_CUE = re.compile(r"^(?:\(.+\)|（.+）)$")
_INLINE_CUE = re.compile(r"\[[^\[\]]+\]|【[^【】]+】|[（(][^（）()]*[）)]")


def is_square_cue(text: str) -> bool:
    return bool(_SQUARE_CUE.fullmatch(text.strip()))


def is_round_cue(text: str) -> bool:
    return bool(_ROUND_CUE.fullmatch(text.strip()))


def strip_inline_cues(text: str) -> str:
    return _INLINE_CUE.sub('', text).strip()
