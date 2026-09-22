"""
单元测试：AI 导演推理引擎 (director_engine)
测试 Two-Pass 剧作与分镜规划、Visual Bible 资产继承与因果依赖链。
"""
import pytest
from src.director_engine import RuleBasedDirector, direct_project
from src.storyboard_schema import (
    AlignedLine,
    AlignmentProject,
    MusicCutPoint,
    MusicSection,
    SongAnalysis,
    WordTimestamp,
)


def _make_sample_project() -> AlignmentProject:
    lines = [
        AlignedLine(text="海浪淹没我的名字", start=2.0, end=5.0, section="Verse 1"),
        AlignedLine(text="我们在潮汐尽头告别", start=6.0, end=9.5, section="Verse 1"),
        AlignedLine(text="奔向那片炽热的破晓", start=12.0, end=16.0, section="Chorus"),
        AlignedLine(text="风暴终于停歇在晨光里", start=17.0, end=21.0, section="Chorus"),
    ]
    sections = [
        MusicSection(name="Intro", start=0.0, end=2.0, energy=0.2),
        MusicSection(name="Verse 1", start=2.0, end=10.0, energy=0.4),
        MusicSection(name="Pre-Chorus", start=10.0, end=12.0, energy=0.6),
        MusicSection(name="Chorus", start=12.0, end=22.0, energy=0.9),
    ]
    return AlignmentProject(
        title="潮汐信使",
        duration=24.0,
        lines=lines,
        sections=sections,
    )


def test_rule_based_director_treatment_and_bible():
    project = _make_sample_project()
    director = RuleBasedDirector(project)

    treatment, bible = director.build_treatment_and_bible()
    assert treatment.title == "潮汐信使"
    assert "海" in treatment.visual_theme or "潮" in treatment.visual_theme
    assert len(treatment.acts) == 3

    assert len(bible.characters) >= 1
    lead_char = bible.characters[0]
    assert lead_char.role == "protagonist"
    assert len(lead_char.canonical_tokens) > 0

    assert len(bible.locations) >= 1
    assert bible.style is not None


def test_rule_based_director_shot_composition():
    project = _make_sample_project()
    director = RuleBasedDirector(project)
    treatment, bible = director.build_treatment_and_bible()

    cuts = [
        MusicCutPoint(time=0.0, confidence=1.0),
        MusicCutPoint(time=2.0, confidence=1.0),
        MusicCutPoint(time=5.5, confidence=0.8),
        MusicCutPoint(time=9.5, confidence=0.85),
        MusicCutPoint(time=12.0, confidence=1.0), # Chorus start
        MusicCutPoint(time=16.0, confidence=0.9),
        MusicCutPoint(time=20.0, confidence=0.85),
        MusicCutPoint(time=24.0, confidence=1.0),
    ]

    shots = director.compose_shots(treatment, bible, cuts)
    assert len(shots) == len(cuts) - 1

    # 检查因果链与 Story Graph
    for i, s in enumerate(shots):
        assert s.shot_id == i + 1
        assert s.start < s.end
        assert s.character_ids == [bible.characters[0].id]
        if i > 0:
            assert s.previous_shot_id == shots[i - 1].id

    # 检查副歌镜头的景别与运镜
    chorus_shots = [s for s in shots if "Chorus" in s.section_name]
    assert len(chorus_shots) > 0
    assert any(s.camera_motion in ["crane_up", "tracking", "slow_dolly_in"] for s in chorus_shots)


def test_direct_project_orchestration():
    project = _make_sample_project()
    analysis = SongAnalysis(
        bpm=128.0,
        duration=24.0,
        cut_candidates=[
            MusicCutPoint(time=0.0),
            MusicCutPoint(time=3.0),
            MusicCutPoint(time=7.0),
            MusicCutPoint(time=12.0),
            MusicCutPoint(time=18.0),
            MusicCutPoint(time=24.0),
        ],
    )

    enriched = direct_project(project, analysis=analysis)
    assert enriched.treatment is not None
    assert enriched.visual_bible is not None
    assert len(enriched.storyboard) >= 5
    assert len(enriched.timeline) == len(enriched.storyboard)
    assert enriched.timeline[0].timeline_duration == pytest.approx(3.0)
