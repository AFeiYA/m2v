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
        design_rationale="通过中近景刻画人物眼神的游离与告别的不舍",
        transition_rationale="与前序镜头通过车窗反光实现 Match Cut 动势匹配",
    )
    assert shot2.duration == pytest.approx(3.7)
    assert shot2.previous_shot_id == "shot_001"
    assert shot2.character_ids == ["char_mei"]
    assert "眼神的游离" in shot2.design_rationale
    assert "Match Cut" in shot2.transition_rationale

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
    assert loaded.bibles is not None
    assert loaded.bibles.visual.characters[0].name == "林"


def test_temporal_direction_and_intensity():
    from src.storyboard_schema import CurvePoint, TemporalDirection

    td = TemporalDirection(
        music_energy=[
            CurvePoint(time=0.0, value=0.2, label="Intro Start"),
            CurvePoint(time=45.0, value=0.9, label="Chorus Climax"),
        ],
        emotion_curve=[
            CurvePoint(time=0.0, value=0.3, label="Quiet contemplation"),
            CurvePoint(time=45.0, value=0.95, label="Ecstatic release"),
        ],
        visual_intensity=[
            CurvePoint(time=0.0, value=0.15, label="Minimalism / static"),
            # 音乐高潮处导演选择反差静止特写 (对位蒙太奇)
            CurvePoint(time=45.0, value=0.25, label="Deliberate stillness under heavy beat"),
        ],
    )
    assert len(td.music_energy) == 2
    assert td.music_energy[1].value == 0.9
    assert td.visual_intensity[1].value == 0.25
    assert "stillness" in td.visual_intensity[1].label


def test_motif_and_asset_bibles():
    from src.storyboard_schema import (
        AssetBible,
        GlobalBibles,
        MotifBible,
        MotifPrefab,
        PropPrefab,
        TypographyBible,
    )

    motif = MotifPrefab(
        id="motif_crack",
        name="冰裂纹理",
        core_concept="时间与记忆被封存在材质裂隙中",
        manifestations=[
            "瓷器冰裂开片",
            "老街青石板裂痕",
            "造船厂钢板焊缝",
        ],
    )
    prop = PropPrefab(
        id="prop_azure_cup",
        name="天青色茶盏",
        visual_features="仿宋官窑天青釉，口沿微泛紫褐，釉面开片细密",
        symbolic_meaning="传统文脉与匠心精神的凝结器物",
    )
    bibles = GlobalBibles(
        motifs=MotifBible(motifs=[motif]),
        assets=AssetBible(props=[prop]),
        typography=TypographyBible(
            font_family="PingFang SC",
            primary_color="#E6FFFF",
            preferred_placement="bottom_left",
        ),
    )
    assert len(bibles.motifs.motifs) == 1
    assert bibles.motifs.motifs[0].manifestations[1] == "老街青石板裂痕"
    assert bibles.assets.props[0].id == "prop_azure_cup"
    assert bibles.typography.preferred_placement == "bottom_left"


def test_sequence_plan_and_safe_zones():
    from src.storyboard_schema import CompositionSafeZones, SequencePlan, ShotPlan, TransitionSpec

    seq = SequencePlan(
        id="SEQ_01",
        sequence_number=1,
        title="序章：微观瓷影与封存记忆",
        start=0.0,
        end=15.0,
        dramatic_function="建立微观世界观，烘托古镇与雨后氛围",
        section_name="Intro",
        lyric_indices=[0, 1],
        shot_ids=["shot_001", "shot_002", "shot_003"],
    )
    assert seq.duration == 15.0
    assert len(seq.shot_ids) == 3

    safe_zones = CompositionSafeZones(
        primary_subject_x=0.75,
        primary_subject_y=0.45,
        protected_regions=["center_right"],
        preferred_text_regions=["bottom_left", "vertical_left"],
    )

    shot = ShotPlan(
        shot_id=1,
        start=0.0,
        end=4.5,
        sequence_id="SEQ_01",
        shot_size="ECU",
        lens_mm=85,
        lighting="soft_side_backlight, low_contrast",
        camera_motion="slow_dolly_in",
        visual_intensity=0.2,
        visual_metaphor="雨滴折射出古镇倒影",
        layout_contract=safe_zones,
        director_note="微距聚焦于茶盏开片纹理，建立微观器物感",
        incoming_transition=TransitionSpec(transition_type="cut", description="黑色渐显入画"),
        outgoing_transition=TransitionSpec(transition_type="match_cut", description="与下一镜茶汤涟漪同心圆动势匹配"),
        callback_to_shot="shot_012",
        callback_type="visual_echo",
    )

    # 验证双向同步与字段有效性
    assert shot.sequence_id == "SEQ_01"
    assert shot.lens_mm == 85
    assert shot.visual_intensity == 0.2
    assert shot.layout_contract.primary_subject_x == 0.75
    assert shot.director_note == "微距聚焦于茶盏开片纹理，建立微观器物感"
    # 验证旧字段与新字段自动同步
    assert shot.design_rationale == shot.director_note
    assert "cut" in shot.transition_rationale
    assert shot.outgoing_transition.transition_type == "match_cut"
    assert shot.callback_to_shot == "shot_012"

