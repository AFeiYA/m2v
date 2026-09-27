"""
单元测试：Suno2MV 工业级三阶段导演流水线 (Pass A, Pass B, Pass C)
-----------------------------------------------------------------
验证：
1. Pass A (CreativeDirector): Treatment, Sequences 幕次, GlobalBibles (四维圣经), TemporalDirection (时域张力对位)
2. Pass B (ShotPlanner): Sequence 分解为多 Shot (长句裂变, 间奏空镜), 机器参数, 构图安全区, 纯画面 Prompt
3. Pass C (ContinuityDirector): 全局 Shot Graph, 蒙太奇转场语法 (Scale Contrast, Match Cut), 副歌视觉复沓
"""
import pytest
from src.directors.creative_director import CreativeDirector
from src.directors.shot_planner import ShotPlanner
from src.directors.continuity_director import ContinuityDirector
from src.storyboard_schema import (
    AlignedLine,
    AlignmentProject,
    MusicCutPoint,
    MusicSection,
    SongAnalysis,
)


def _create_test_project() -> AlignmentProject:
    lines = [
        AlignedLine(text="看那 冰裂纹理 锁住了 哪朝的雨", start=2.0, end=7.6, section="Verse 1"),
        AlignedLine(text="万象 在方寸间 缓缓 揭开序曲", start=8.0, end=18.26, section="Verse 1"),  # 10.26s 长句
        AlignedLine(text="星火 坠入深渊 幻化作 满天繁星", start=20.0, end=25.0, section="Chorus 1"),
        AlignedLine(text="这一步 跨越千年 巨轮破开重重浪", start=25.0, end=32.0, section="Chorus 1"),
        AlignedLine(text="纯音乐延音与静默深思", start=33.0, end=48.0, section="Bridge"),  # 15s 长间奏
        AlignedLine(text="星火 再次照亮深渊 重生为万里长歌", start=50.0, end=56.0, section="Chorus 2"),  # 重复副歌复沓
    ]
    sections = [
        MusicSection(name="Intro", start=0.0, end=2.0, energy=0.2),
        MusicSection(name="Verse 1", start=2.0, end=19.0, energy=0.4),
        MusicSection(name="Chorus 1", start=19.0, end=33.0, energy=0.9),
        MusicSection(name="Bridge", start=33.0, end=49.0, energy=0.5),
        MusicSection(name="Chorus 2", start=49.0, end=58.0, energy=0.95),
        MusicSection(name="Outro", start=58.0, end=65.0, energy=0.3),
    ]
    return AlignmentProject(
        title="匠心瓷影",
        duration=65.0,
        lines=lines,
        sections=sections,
    )


def test_pass_a_creative_director():
    project = _create_test_project()
    cd = CreativeDirector(project)
    enriched = cd.execute()

    # 1. 验证 Treatment
    assert enriched.treatment is not None
    assert "瓷" in enriched.treatment.visual_theme or "匠" in enriched.treatment.visual_theme
    assert len(enriched.treatment.acts) == 3

    # 2. 验证 Global Bibles (四维圣经)
    assert enriched.bibles is not None
    assert enriched.bibles.visual is not None
    assert len(enriched.bibles.visual.characters) >= 1
    assert len(enriched.bibles.visual.locations) >= 2
    assert len(enriched.bibles.visual.props) >= 1
    assert enriched.bibles.typography is not None
    assert enriched.bibles.typography.font_family != ""
    assert enriched.bibles.motifs is not None
    assert len(enriched.bibles.motifs.motifs) >= 1
    # 验证母题存在跨场景具体化 (manifestations)
    assert len(enriched.bibles.motifs.motifs[0].manifestations) >= 2

    # 3. 验证 Sequences (宏观幕次)
    assert len(enriched.sequences) == 6
    assert enriched.sequences[0].section_name == "Intro"
    assert enriched.sequences[2].section_name == "Chorus 1"
    assert enriched.sequences[2].dramatic_function != ""

    # 4. 验证 Temporal Direction (时域张力对位)
    td = enriched.temporal_direction
    assert td is not None
    assert len(td.music_energy) > 0
    assert len(td.visual_intensity) > 0
    # 验证 Intro 阶段张力克制留白
    intro_intensity = next(p.value for p in td.visual_intensity if p.time == 0.0)
    assert intro_intensity <= 0.3


def test_pass_b_shot_planner():
    project = _create_test_project()
    cd = CreativeDirector(project)
    cd.execute()

    planner = ShotPlanner(project)
    shots = planner.compose_shots(target_shot_duration=3.5)

    assert len(shots) >= 12
    # 验证每个 Shot 均已归属某个 Sequence
    seq_ids = {s.id for s in project.sequences}
    for s in shots:
        assert s.sequence_id in seq_ids
        assert s.start < s.end
        assert s.duration >= 0.5
        # 机器执行参数齐全
        assert s.shot_size in ["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"]
        assert s.lens_mm in [24, 28, 35, 50, 85, 105]
        assert s.camera_motion != ""
        assert s.lighting != ""
        # 构图安全区
        assert s.layout_contract is not None
        assert 0.0 <= s.layout_contract.primary_subject_x <= 1.0
        assert len(s.layout_contract.preferred_text_regions) > 0
        # 纯画面 Prompt（坚决不能包含中文字幕生成指令）
        assert "Chinese text" not in s.prompt_en
        assert "render subtitle" not in s.prompt_en.lower()

    # 验证 Sequences 的 shot_ids 已经被正确回填
    for seq in project.sequences:
        assert len(seq.shot_ids) > 0


def test_pass_c_continuity_director():
    project = _create_test_project()
    cd = CreativeDirector(project)
    cd.execute()

    planner = ShotPlanner(project)
    raw_shots = planner.compose_shots(target_shot_duration=3.5)

    continuity = ContinuityDirector(project)
    shots = continuity.weave_shot_graph(
        raw_shots,
        bibles=project.bibles,
        sequences=project.sequences,
    )

    assert len(shots) == len(raw_shots)

    # 验证首尾镜头
    assert shots[0].previous_shot_id is None
    assert shots[0].incoming_transition.transition_type == "cut"
    assert shots[-1].outgoing_transition.transition_type == "dissolve"

    # 验证相邻镜头的转场因果链
    for i in range(1, len(shots)):
        curr_shot = shots[i]
        prev_shot = shots[i - 1]
        assert curr_shot.previous_shot_id == prev_shot.id
        assert prev_shot.next_shot_id == curr_shot.id
        assert curr_shot.incoming_transition is not None
        assert curr_shot.incoming_transition.transition_type in [
            "cut", "match_cut", "eyeline_match", "motion_vector_match",
            "scale_contrast", "color_match", "sound_bridge", "dissolve"
        ]

    # 验证副歌复沓与母题进阶 (Chorus 2 镜头应回溯 Chorus 1)
    chorus_2_shots = [s for s in shots if "Chorus 2" in s.section_name]
    assert len(chorus_2_shots) > 0
    # 至少有一个副歌进阶回溯标记
    assert any(s.callback_to_shot is not None and s.callback_type == "progression" for s in chorus_2_shots)
    assert any("副歌视觉复沓与进阶" in s.director_note for s in chorus_2_shots)
