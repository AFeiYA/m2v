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
    assert char.identity.gender == "male"
    assert char.face_invariants.hair.color.startswith("#E6EAEF")
    assert "mole under right eye" in char.prompt_engine.positive_character_anchor

    # Age is freely editable
    char.identity.age = 17
    assert char.identity.age == 17

    # Test outfit decoupling
    assert len(char.outfits) >= 1
    assert char.active_outfit.id == "outfit_debut_blackgold"
    assert char.active_outfit.color_palette.dominant_hex == "#0D0F12"

    # Test conversion to CharacterPrefab (Director Engine compatibility)
    prefab = char.to_character_prefab(role="lead")
    assert prefab.id == char.id
    assert prefab.name == "零点六一八"
    assert prefab.role == "lead"
    assert "age 17" in prefab.appearance
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
    assert from_disk.identity.age == 17


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
    from io import BytesIO
    from PIL import Image
    from src.cast_storage import (
        create_character,
        list_characters,
        get_character,
        save_character,
        upload_reference_image,
        confirm_character_version,
        bind_character_to_song,
        unbind_character_from_song,
        delete_character,
    )

    storage_dir = tmp_path / "characters"
    scan_dir = tmp_path / "songs"
    scan_dir.mkdir(parents=True)

    # 1. Create Character & verify editable age without versioning lock
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

    # Modify age anytime
    char.identity.age = 19
    save_character(char, storage_dir=storage_dir)
    reloaded = get_character(char.id, storage_dir=storage_dir)
    assert reloaded.identity.age == 19

    # Check listing: contains user's character + official Zero.SOE
    char_list = list_characters(storage_dir)
    assert len(char_list) == 2
    ids = [c["id"] for c in char_list]
    assert char.id in ids
    assert "char_zero_soe_0618" in ids

    # 2. Upload Reference Image with Pillow Validation
    # Test rejection of corrupt/non-image bytes
    with pytest.raises(ValueError, match="Corrupt or invalid image data"):
        upload_reference_image(
            char_id=char.id,
            image_bytes=b"not an image at all",
            filename="fake.png",
            storage_dir=storage_dir,
        )

    # Test rejection of tiny dimensions (< 32x32)
    tiny_buf = BytesIO()
    Image.new("RGB", (16, 16), color="red").save(tiny_buf, format="PNG")
    with pytest.raises(ValueError, match="Image dimensions too small"):
        upload_reference_image(
            char_id=char.id,
            image_bytes=tiny_buf.getvalue(),
            filename="tiny.png",
            storage_dir=storage_dir,
        )

    # Test valid image upload (64x64 PNG)
    valid_buf = BytesIO()
    Image.new("RGB", (64, 64), color="blue").save(valid_buf, format="PNG")
    char, rel_url = upload_reference_image(
        char_id=char.id,
        image_bytes=valid_buf.getvalue(),
        filename="face_portrait.png",
        is_primary=True,
        storage_dir=storage_dir,
    )
    assert char.assets.primary_image_url == rel_url
    assert rel_url.startswith(f"/api/characters/{char.id}/assets/")

    # 3. Confirm Baseline Version (touch updated_at)
    confirmed = confirm_character_version(char_id=char.id, storage_dir=storage_dir)
    assert confirmed.updated_at is not None

    # 4. Bind Character to Song
    # Non-existent song folder raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        bind_character_to_song(
            char_id=char.id,
            song_folder_name="non_existent_song",
            scan_dir=scan_dir,
            storage_dir=storage_dir,
        )

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
    # Check song file was updated without version lock field
    updated_align = json.loads(align_file.read_text(encoding="utf-8"))
    assert updated_align["character_id"] == char.id
    assert "character_version" not in updated_align

    # 5. Re-bind to a second character & test unbinding cascade
    char2 = create_character(
        name="歌手二号",
        storage_dir=storage_dir,
    )
    bind_character_to_song(
        char_id=char2.id,
        song_folder_name=song_folder,
        scan_dir=scan_dir,
        storage_dir=storage_dir,
    )
    # Check char1 no longer has the song in bound_songs
    char1_reloaded = get_character(char.id, storage_dir=storage_dir)
    assert song_folder not in char1_reloaded.bound_songs

    # 6. Delete Character Cascades Unbinding
    deleted = delete_character(char_id=char2.id, scan_dir=scan_dir, storage_dir=storage_dir)
    assert deleted is True
    assert get_character(char2.id, storage_dir=storage_dir) is None
    cleared_align = json.loads(align_file.read_text(encoding="utf-8"))
    assert "character_id" not in cleared_align

    # Delete char 1 as well
    delete_character(char_id=char.id, scan_dir=scan_dir, storage_dir=storage_dir)
    assert get_character(char.id, storage_dir=storage_dir) is None

    # Official Zero.SOE remains
    assert len(list_characters(storage_dir)) == 1
    assert list_characters(storage_dir)[0]["id"] == "char_zero_soe_0618"

    # 7. System character protection
    with pytest.raises(PermissionError):
        delete_character("char_zero_soe_0618", current_user_id="user_attacker", storage_dir=storage_dir)


def test_bound_character_flows_into_director_pipeline(tmp_path: Path):
    from src.cast_storage import create_character, save_character
    from src.directors.creative_director import CreativeDirector
    from src.storyboard_schema import AlignmentProject, AlignedLine, MusicSection

    storage_dir = tmp_path / "characters"
    scan_dir = tmp_path / "songs"
    scan_dir.mkdir(parents=True)

    # 1. Create Character with unique attributes
    char = create_character(
        name="星野未来",
        alias="Miku.Echo",
        age=16,
        gender="female",
        tagline="银河虚拟漫游者",
        storage_dir=storage_dir,
    )
    char.prompt_engine.positive_character_anchor = "cyber teal twin tails, futuristic silver jacket"
    char.assets.primary_image_url = f"/api/characters/{char.id}/assets/portrait.png"
    save_character(char, storage_dir=storage_dir)

    # 2. Setup project with character_id bound
    project = AlignmentProject(
        title="星轨之声",
        duration=25.0,
        character_id=char.id,
        lines=[AlignedLine(text="在光年之外歌唱", start=1.0, end=4.0)],
        sections=[MusicSection(name="Verse", start=0.0, end=10.0)],
    )

    # 3. CreativeDirector executes
    cd = CreativeDirector(project, characters_dir=storage_dir)
    treatment, bibles = cd.plan_treatment_and_bibles()

    lead = bibles.visual.characters[0]
    assert lead.id == char.id
    assert lead.name == "星野未来"
    assert "16岁" in lead.appearance
    assert "cyber teal twin tails" in lead.canonical_tokens
    assert lead.keyframe_pack == [char.assets.primary_image_url]

    # 4. Modify character's age to 18 and re-run (simulating: 新生成采用最新设定)
    char.identity.age = 18
    save_character(char, storage_dir=storage_dir)

    cd_updated = CreativeDirector(project, characters_dir=storage_dir)
    treatment2, bibles2 = cd_updated.plan_treatment_and_bibles()
    lead2 = bibles2.visual.characters[0]
    assert lead2.id == char.id
    assert "18岁" in lead2.appearance
    assert "18yo" in lead2.canonical_tokens

