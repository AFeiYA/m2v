"""
单元测试：动态故事板分镜卡片渲染器 (storyboard_renderer)
测试 16:9 电影卡片绘制、文字排版、构图辅助线与批量生成。
"""
from pathlib import Path
from PIL import Image

from src.storyboard_renderer import render_shot_frame, render_all_storyboard_frames
from src.storyboard_schema import AlignmentProject, ShotPlan


def test_render_single_shot_frame(tmp_path):
    shot = ShotPlan(
        shot_id=4,
        id="shot_004",
        start=12.5,
        end=16.8,
        section_name="Chorus 1",
        shot_size="MCU",
        camera_motion="slow_dolly_in",
        camera_angle="eye_level",
        action="主角在光芒中缓缓抬头，目光坚定",
        narrative_goal="高潮爆发",
        lyric_reference="奔向那片炽热的破晓",
        character_ids=["林"],
        location_id="沿海站台",
        match_cut_element="水滴折射光芒",
    )

    out_file = tmp_path / "test_shot_004.png"
    result_path = render_shot_frame(shot, out_file, width=640, height=360)

    assert result_path.exists()
    img = Image.open(str(result_path))
    assert img.size == (640, 360)
    assert img.format == "PNG"


def test_render_all_storyboard_frames(tmp_path):
    shots = [
        ShotPlan(shot_id=1, id="shot_001", start=0.0, end=3.0, section_name="Intro", shot_size="EWS", action="全景介绍"),
        ShotPlan(shot_id=2, id="shot_002", start=3.0, end=7.0, section_name="Verse 1", shot_size="MCU", action="主角出场"),
    ]
    proj = AlignmentProject(title="测试全片", storyboard=shots)

    out_dir = tmp_path / "storyboard_out"
    paths = render_all_storyboard_frames(proj, out_dir)

    assert len(paths) == 2
    assert (out_dir / "shot_001.png").exists()
    assert (out_dir / "shot_002.png").exists()
    assert proj.storyboard[0].preview_image == "storyboard/shot_001.png"
