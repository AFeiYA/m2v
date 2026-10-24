"""
Unit tests for Cast Studio Schema & Prompt Engine
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.cast_schema import CharacterProfile
from src.cast_prompts import (
    build_character_design_prompt,
    parse_character_profile_json,
    get_reference_golden_ratio_character,
)


def test_reference_character_validates_and_serializes(tmp_path: Path):
    char = get_reference_golden_ratio_character()
    assert char.identity.name == "零点六一八"
    assert char.visual_dna.gender == "male"
    assert char.visual_dna.hair.color.startswith("#E6EAEF")
    assert "mole under right eye" in char.prompt_engine.positive_character_anchor

    # Test JSON round-trip
    serialized = char.to_json()
    reloaded = CharacterProfile.from_json(serialized)
    assert reloaded.id == char.id
    assert reloaded.identity.alias == char.identity.alias

    # Test file persistence
    save_path = tmp_path / "0618_profile.json"
    char.save_file(save_path)
    assert save_path.exists()
    from_disk = CharacterProfile.load_file(save_path)
    assert from_disk.identity.name == "零点六一八"


def test_build_prompt_structure():
    messages = build_character_design_prompt(
        user_idea="一个爱穿复古大衣的赛博歌姬",
        style_preference="Cyberpunk Noir"
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "七大黄金法则" in messages[0]["content"]
    assert "赛博歌姬" in messages[1]["content"]


def test_parse_character_profile_from_markdown_block():
    char = get_reference_golden_ratio_character()
    raw_markdown = f"Here is the character:\n```json\n{char.to_json()}\n```\nEnjoy!"
    parsed = parse_character_profile_json(raw_markdown)
    assert parsed.id == char.id
    assert parsed.visual_dna.signature_prop == char.visual_dna.signature_prop
