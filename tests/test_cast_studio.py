"""
Unit tests for Cast Studio Schema, Decoupling & Prompt Engine
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
    assert char.identity.age == 16
    assert char.identity.age_locked is True
    assert char.identity.gender == "male"
    assert char.face_invariants.hair.color.startswith("#E6EAEF")
    assert "mole under right eye" in char.prompt_engine.positive_character_anchor
    assert char.versioning.version == 1
    assert char.versioning.is_locked is True

    # Test outfit decoupling
    assert len(char.outfits) >= 1
    assert char.active_outfit.id == "outfit_debut_blackgold"
    assert char.active_outfit.color_palette.dominant_hex == "#0D0F12"

    # Test conversion to CharacterPrefab (Director Engine compatibility)
    prefab = char.to_character_prefab(role="lead")
    assert prefab.id == char.id
    assert prefab.name == "零点六一八"
    assert prefab.role == "lead"
    assert "age 16" in prefab.appearance
    assert len(prefab.canonical_tokens) > 0
    assert prefab.keyframe_pack == ["/assets/characters/zero_soe/primary.png"]

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
    assert from_disk.identity.age == 16


def test_build_prompt_structure_includes_schema_and_id():
    messages = build_character_design_prompt(
        user_idea="一个爱穿复古大衣的赛博歌姬",
        character_id="char_test_123",
        style_key="indie_retro",
        forced_age=19,
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "五大核心原则" in messages[0]["content"]

    user_prompt = messages[1]["content"]
    assert "char_test_123" in user_prompt
    assert "19 岁" in user_prompt
    assert "Lo-Fi Indie Musician" in user_prompt
    # Ensures full JSON Schema is embedded in prompt
    assert '"FoveaCharacterProfile"' not in user_prompt  # Schema title is CharacterProfile
    assert '"face_invariants"' in user_prompt
    assert '"outfits"' in user_prompt


def test_parse_character_profile_from_markdown_block():
    char = get_reference_golden_ratio_character()
    raw_markdown = f"Here is the character:\n```json\n{char.to_json()}\n```\nEnjoy!"
    parsed = parse_character_profile_json(raw_markdown)
    assert parsed.id == char.id
    assert parsed.identity.age == 16
    assert parsed.active_outfit.signature_prop == char.active_outfit.signature_prop


def test_cast_storage_full_lifecycle(tmp_path: Path):
    from src.cast_storage import (
        create_character,
        list_characters,
        get_character,
        upload_reference_image,
        confirm_character_version,
        bind_character_to_song,
        unbind_character_from_song,
        delete_character,
    )

    storage_dir = tmp_path / "characters"
    scan_dir = tmp_path / "songs"
    scan_dir.mkdir(parents=True)

    # 1. Create Character
    char = create_character(
        name="测试歌手",
        alias="Singer X",
        age=16,
        gender="female",
        tagline="虚拟新星",
        storage_dir=storage_dir,
    )
    assert char.identity.name == "测试歌手"
    assert char.identity.age == 16
    assert char.versioning.version == 1
    assert char.versioning.is_locked is False

    # Check listing
    char_list = list_characters(storage_dir)
    assert len(char_list) == 1
    assert char_list[0]["id"] == char.id

    # 2. Upload Reference Image
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    char, rel_url = upload_reference_image(
        char_id=char.id,
        image_bytes=fake_png,
        filename="face_portrait.png",
        is_primary=True,
        storage_dir=storage_dir,
    )
    assert char.assets.primary_image_url == rel_url
    assert rel_url.startswith(f"/api/characters/{char.id}/assets/")

    # 3. Confirm Baseline Version
    confirmed = confirm_character_version(char_id=char.id, storage_dir=storage_dir)
    assert confirmed.versioning.is_locked is True
    assert confirmed.versioning.version == 1
    assert confirmed.versioning.confirmed_at is not None

    # 4. Bind Character to Song
    song_folder = "song_cyber_01"
    song_dir = scan_dir / song_folder
    song_dir.mkdir(parents=True)
    align_file = song_dir / "cyber_alignment.json"
    align_file.write_text(json.dumps({"title": "Cyber Song", "lines": []}), encoding="utf-8")

    bound = bind_character_to_song(
        char_id=char.id,
        song_folder_name=song_folder,
        scan_dir=scan_dir,
        storage_dir=storage_dir,
    )
    assert song_folder in bound.bound_songs
    # Check song file was updated
    updated_align = json.loads(align_file.read_text(encoding="utf-8"))
    assert updated_align["character_id"] == char.id
    assert updated_align["character_version"] == 1

    # 5. Unbind
    unbound = unbind_character_from_song(
        char_id=char.id,
        song_folder_name=song_folder,
        scan_dir=scan_dir,
        storage_dir=storage_dir,
    )
    assert song_folder not in unbound.bound_songs
    cleared_align = json.loads(align_file.read_text(encoding="utf-8"))
    assert "character_id" not in cleared_align

    # 6. Delete
    deleted = delete_character(char_id=char.id, storage_dir=storage_dir)
    assert deleted is True
    assert get_character(char.id, storage_dir=storage_dir) is None
    assert len(list_characters(storage_dir)) == 0

