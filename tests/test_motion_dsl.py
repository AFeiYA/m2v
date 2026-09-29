"""
Unit tests for m2v Motion Timeline DSL models and conversion
"""
import pytest
from src.storyboard_schema import (
    AlignmentProject,
    AlignedLine,
    WordTimestamp,
    ShotPlan,
    MotionTimelineDSL,
    MotionScene,
    MotionLayer,
    MotionCue,
)


def test_motion_timeline_dsl_basic():
    dsl = MotionTimelineDSL(
        meta={
            "title": "Test Song",
            "bpm": 128.0,
            "duration": 30.0,
            "aspect_ratio": "16:9",
            "fps": 30,
        },
        scenes=[
            MotionScene(
                scene_id="shot_001",
                start=0.0,
                end=4.0,
                layers=[
                    MotionLayer(
                        layer_id="shot_001:kinetic",
                        type="kinetic_typography",
                        preset="swiss_minimal",
                        seed="shot_001:seed_1",
                        cues=[
                            MotionCue(
                                cue_id="cue_01",
                                text="Hello World",
                                start=0.5,
                                end=2.0,
                                emphasis=0.9,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    assert dsl.version == "1.0.0"
    assert len(dsl.scenes) == 1
    assert dsl.scenes[0].layers[0].preset == "swiss_minimal"
    assert dsl.scenes[0].layers[0].cues[0].text == "Hello World"

    # Test JSON round-trip
    json_str = dsl.to_json()
    reconstructed = MotionTimelineDSL.from_json(json_str)
    assert reconstructed.meta["title"] == "Test Song"
    assert len(reconstructed.scenes) == 1
    assert reconstructed.scenes[0].scene_id == "shot_001"


def test_alignment_project_to_motion_dsl():
    project = AlignmentProject(
        title="Demo Project",
        duration=10.0,
        lines=[
            AlignedLine(
                text="海浪无声将夜幕深深淹没",
                start=1.0,
                end=5.0,
                words=[
                    WordTimestamp(word="海", start=1.0, end=1.3),
                    WordTimestamp(word="浪", start=1.3, end=1.6),
                    WordTimestamp(word="无", start=1.6, end=1.9),
                    WordTimestamp(word="声", start=1.9, end=2.2),
                    WordTimestamp(word="将", start=2.2, end=2.6),
                    WordTimestamp(word="夜", start=2.6, end=3.0),
                    WordTimestamp(word="幕", start=3.0, end=3.4),
                    WordTimestamp(word="深", start=3.4, end=3.8),
                    WordTimestamp(word="深", start=3.8, end=4.2),
                    WordTimestamp(word="淹", start=4.2, end=4.6),
                    WordTimestamp(word="没", start=4.6, end=5.0),
                ],
            )
        ],
        storyboard=[
            ShotPlan(
                shot_id=1,
                id="shot_001",
                start=0.0,
                end=5.5,
                camera_motion="slow_dolly_in",
                preview_image="keyframes/shot_001.png",
                semantic_groups=[
                    {"phrase": "海浪无声", "start": 1.0, "end": 2.2, "emphasis": 0.8},
                    {"phrase": "将夜幕", "start": 2.2, "end": 3.4, "emphasis": 0.6},
                    {"phrase": "深深淹没", "start": 3.4, "end": 5.0, "emphasis": 0.95},
                ],
            )
        ],
    )

    dsl = project.to_motion_dsl(default_preset="street_pop")
    assert dsl.meta["title"] == "Demo Project"
    assert len(dsl.scenes) == 1
    scene = dsl.scenes[0]
    assert scene.scene_id == "shot_001"
    assert scene.background.type == "image"
    assert scene.background.motion["camera_motion"] == "slow_dolly_in"

    kinetic_layer = next(l for l in scene.layers if l.type == "kinetic_typography")
    assert kinetic_layer.preset == "street_pop"
    assert len(kinetic_layer.cues) == 3
    assert kinetic_layer.cues[0].text == "海浪无声"
    assert kinetic_layer.cues[2].text == "深深淹没"
    assert kinetic_layer.cues[2].emphasis == 0.95
