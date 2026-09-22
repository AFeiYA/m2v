"""
单元测试：Suno2MV 导演领域模型规范 (Pydantic v2)
测试 Prefab 资产、Shot/Take 体系、Story Graph 约束及向下兼容性。
"""
import pytest
from src.storyboard_schema import (
    AlignedLine,
    AlignmentProject,
    CharacterPrefab,
    DirectorTreatment,
    LocationPrefab,
    MusicCutPoint,
    MusicSection,
    NLEClip,
    Project,
    Shot,
    ShotPlan,
    SongAnalysis,
    StylePrefab,
    Take,
    VisualBible,
    WordTimestamp,
)


def test_character_prefab_validation():
    char = CharacterPrefab(
        id="char_mei",
        name="林",
        appearance="23岁女性，齐肩短发",
        canonical_tokens=["short black bob", "white shirt"],
        forbidden_tokens=["long hair", "glasses"],
    )
    assert char.id == "char_mei"
    assert char.role == "protagonist"
    assert "short black bob" in char.canonical_tokens
    assert "glasses" in char.forbidden_tokens


def test_location_and_style_prefabs():
    loc = LocationPrefab(
        id="loc_station",
        name="沿海站台",
        spatial_layout="锈蚀铁轨伸向海面",
        time_of_day="dawn",
    )
    assert loc.id == "loc_station"
    assert loc.time_of_day == "dawn"

    style = StylePrefab(
        visual_style="cinematic realism",
        lens_spec="35mm anamorphic",
    )
    assert "35mm" in style.lens_spec


def test_shot_validation_and_backward_compatibility():
    # 兼容老版字段传参
    shot = ShotPlan(
        shot_id=1,
        start=0.0,
        end=3.5,
        scale="Wide",
        camera_movement="Pan",
        path="assets/bg.jpg",
    )
    assert shot.duration == 3.5
    assert shot.id == "shot_001"
    assert shot.preview_image == "assets/bg.jpg"
    assert shot.shot_size == "Wide"

    # 新版字段传参
    shot2 = Shot(
        shot_id=2,
        id="shot_002",
        start=3.5,
        end=7.2,
        shot_size="MCU",
        camera_motion="slow_dolly_in",
        narrative_goal="展示人物迟疑的神情",
        action="手指轻抚车窗",
        character_ids=["char_mei"],
        location_id="loc_station",
        previous_shot_id="shot_001",
    )
    assert shot2.duration == pytest.approx(3.7)
    assert shot2.previous_shot_id == "shot_001"
    assert shot2.character_ids == ["char_mei"]

    # 错误时间倒挂校验
    with pytest.raises(ValueError):
        ShotPlan(shot_id=3, start=5.0, end=3.0)


def test_take_and_nle_clip():
    take = Take(
        id="take_001_A",
        shot_id="shot_001",
        provider="storyboard_mock",
        media_type="image",
        media_path="storyboard/shot_001.png",
        selected=True,
    )
    assert take.selected is True
    assert take.media_type == "image"

    clip = NLEClip(
        id="clip_001",
        shot_id="shot_001",
        source_in=0.5,
        source_out=4.0,
        timeline_in=0.0,
        timeline_out=3.5,
        speed=1.0,
    )
    assert clip.timeline_duration == 3.5


def test_project_serialization_roundtrip(tmp_path):
    proj = Project(
        title="如其所是",
        duration=180.0,
        lines=[
            AlignedLine(
                text="海浪淹没我的名字",
                start=1.2,
                end=4.5,
                words=[
                    WordTimestamp(word="海", start=1.2, end=1.8),
                    WordTimestamp(word="浪", start=1.8, end=2.4),
                    WordTimestamp(word="淹没", start=2.4, end=3.5),
                    WordTimestamp(word="我的名字", start=3.5, end=4.5),
                ],
            )
        ],
        sections=[
            MusicSection(name="Intro", start=0.0, end=15.0),
            MusicSection(name="Chorus 1", start=15.0, end=45.0, energy=0.9),
        ],
        storyboard=[
            ShotPlan(
                shot_id=1,
                start=0.0,
                end=3.5,
                shot_size="EWS",
                camera_motion="static",
                action="清晨沿海全貌",
            )
        ],
        treatment=DirectorTreatment(
            title="如其所是",
            logline="在潮汐边缘寻找记忆",
            visual_theme="海浪与时间",
        ),
        visual_bible=VisualBible(
            title="如其所是视觉圣经",
            characters=[CharacterPrefab(id="char_01", name="林")],
        ),
    )

    save_path = tmp_path / "test_project.json"
    proj.save_json(save_path)
    assert save_path.exists()

    loaded = Project.load_json(save_path)
    assert loaded.title == "如其所是"
    assert len(loaded.lines) == 1
    assert len(loaded.sections) == 2
    assert len(loaded.storyboard) == 1
    assert loaded.storyboard[0].shot_size == "EWS"
    assert loaded.treatment.logline == "在潮汐边缘寻找记忆"
    assert loaded.visual_bible.characters[0].name == "林"
