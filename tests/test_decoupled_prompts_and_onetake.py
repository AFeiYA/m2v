"""
动静解耦提示词体系与一镜到底契约单元测试
------------------------------------------
验证:
1. ShotPlan 新增的 keyframe_prompt, motion_prompt, endframe_prompt, continuity_mode 等契约有效性
2. FluxPromptCompiler 纯静态材质编译与运镜动词清洗能力
3. LTXPromptCompiler 动静解耦运镜与刚体防变形约束编译能力
4. 后端 /api/shots/link_one_take 一镜到底首尾帧继承 API
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.storyboard_schema import AlignmentProject, ShotPlan
from src.compilers import get_compiler
from src.compilers.flux_compiler import FluxPromptCompiler
from src.compilers.ltx_compiler import LTXPromptCompiler
from src.local_editor import app


def test_shotplan_decoupled_contract():
    """测试 ShotPlan 动静解耦与尾帧字段规范"""
    shot = ShotPlan(
        shot_id=1,
        id="shot_001",
        start=0.0,
        end=4.0,
        prompt_en="A macro shot of celadon porcelain with slow dolly in",
        keyframe_prompt="Macro photo of Song dynasty celadon porcelain, cracked glaze, soft lighting",
        motion_prompt="Slow continuous forward push, bowl remains rigid solid body without warping",
        endframe_prompt="Extreme macro view of porcelain rim glinting under sunlight",
        endframe_image="output/test/keyframes/shot_001_endframe_001.png",
        continuity_mode="one_take_continuous",
    )

    assert shot.keyframe_prompt.startswith("Macro photo")
    assert shot.motion_prompt.startswith("Slow continuous")
    assert shot.endframe_prompt.startswith("Extreme macro")
    assert shot.continuity_mode == "one_take_continuous"
    assert shot.effective_keyframe_prompt == shot.keyframe_prompt
    assert shot.effective_motion_prompt == shot.motion_prompt


def test_shotplan_effective_prompt_fallback():
    """测试当未指定 keyframe_prompt 和 motion_prompt 时的智能回退"""
    shot = ShotPlan(
        shot_id=2,
        id="shot_002",
        start=4.0,
        end=8.0,
        prompt_en="A sweeping landscape",
        camera_motion="slow_dolly_in",
        action="Clouds drift gently",
    )

    assert shot.keyframe_prompt == ""
    assert shot.effective_keyframe_prompt == "A sweeping landscape"
    assert shot.effective_motion_prompt == "Clouds drift gently"


def test_flux_prompt_compiler_cleans_motion():
    """测试 Flux 编译器过滤运镜动词，防止首帧运动模糊"""
    compiler = get_compiler("flux")
    assert isinstance(compiler, FluxPromptCompiler)

    shot = ShotPlan(
        shot_id=3,
        id="shot_003",
        prompt_en="Extreme macro of celadon porcelain, slow dolly in, tracking shot, pan right, beautiful texture",
        shot_size="ECU",
        lens_mm=85,
    )

    payload = compiler.compile_keyframe(shot)
    prompt = payload.prompt.lower()

    # 验证运镜词被成功剥离
    assert "dolly in" not in prompt
    assert "tracking shot" not in prompt
    assert "pan right" not in prompt
    # 验证材质与摄影参数被注入
    assert "macro" in prompt
    assert "85mm" in prompt
    assert "photorealistic" in prompt


def test_ltx_prompt_compiler_motion_decoupling():
    """测试 LTX 编译器编译纯运镜物理，注入刚体保真与抗形变约束"""
    compiler = get_compiler("ltx")
    assert isinstance(compiler, LTXPromptCompiler)

    # 1. 显式提供 motion_prompt
    shot_explicit = ShotPlan(
        shot_id=4,
        id="shot_004",
        motion_prompt="Smooth steady forward dolly push, porcelain remains rigid without morphing",
        camera_motion="slow_dolly_in",
    )
    payload_explicit = compiler.compile_motion(shot_explicit)
    assert "Smooth steady forward dolly push" in payload_explicit.prompt
    assert "morphing" in payload_explicit.negative_prompt

    # 2. 自动由 camera_motion 编译，注入刚体约束
    shot_implicit = ShotPlan(
        shot_id=5,
        id="shot_005",
        camera_motion="slow_dolly_in",
        action="ambient dust particles floating",
    )
    payload_implicit = compiler.compile_motion(shot_implicit)
    assert "slow smooth dolly in" in payload_implicit.prompt
    assert "rigid structure without warping" in payload_implicit.prompt


def test_link_one_take_api(tmp_path):
    """测试一镜到底首尾帧继承 API 接口"""
    client = TestClient(app)
    app.state.scan_dir = tmp_path

    project_file = tmp_path / "onetake_alignment.json"
    project = AlignmentProject(
        audio_file="test.mp3",
        song_name="测试歌曲",
        storyboard=[
            ShotPlan(
                shot_id=1,
                id="shot_001",
                start=0.0,
                end=4.0,
                preview_image="output/test/keyframes/shot_001_kf.png",
                endframe_image="output/test/keyframes/shot_001_endframe.png",
            ),
            ShotPlan(
                shot_id=2,
                id="shot_002",
                start=4.0,
                end=8.0,
                preview_image="",
            ),
        ],
    )
    project.save_json(project_file)

    req_body = {
        "json_path": str(project_file),
        "from_shot_id": "shot_001",
        "to_shot_id": "shot_002",
    }
    res = client.post("/api/shots/link_one_take", json=req_body)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["inherited_image"] == "output/test/keyframes/shot_001_endframe.png"

    # 验证工程落盘结果
    updated = AlignmentProject.load_json(project_file)
    s1 = updated.storyboard[0]
    s2 = updated.storyboard[1]
    assert s1.continuity_mode == "one_take_continuous"
    assert s2.preview_image == "output/test/keyframes/shot_001_endframe.png"
    assert s2.path == "output/test/keyframes/shot_001_endframe.png"


def test_llm_director_prompt_generation_and_merge(tmp_path):
    """测试 LLM 导演 System Prompt 生成与动静解耦响应回填合并"""
    from src.llm_director import generate_llm_prompt, merge_llm_response
    from src.storyboard_schema import AlignedLine

    project_file = tmp_path / "llm_alignment.json"
    project = AlignmentProject(
        audio_file="test.mp3",
        song_name="测试歌曲",
        lines=[
            AlignedLine(text="天青色等烟雨", start=1.0, end=4.0),
        ],
    )
    project.save_json(project_file)

    # 1. 验证生成的 LLM Prompt 包含两阶段动静解耦指令与尾帧规范
    prompt_text = generate_llm_prompt(project_file, mode="shot_director")
    assert "keyframe_prompt" in prompt_text
    assert "motion_prompt" in prompt_text
    assert "endframe_prompt" in prompt_text
    assert "continuity_mode" in prompt_text

    # 2. 模拟大模型返回结构并合并
    mock_llm_output = json.dumps([
        {
            "line_index": 0,
            "shot_id": "shot_001",
            "shot_size": "CU",
            "camera_motion": "slow_dolly_in",
            "keyframe_prompt": "Close-up macro of Song dynasty celadon bowl, delicate crackle fissures, f/1.8 lens",
            "motion_prompt": "Slow continuous dolly in, bowl remains rigid without morphing",
            "endframe_prompt": "Extreme macro of the rim glowing under soft light",
            "continuity_mode": "one_take_continuous",
            "video_prompt": "Cinematic close-up of celadon bowl with slow dolly in",
            "design_rationale": "【构思说明】特写器物开片",
        }
    ])

    merged_proj = merge_llm_response(project_file, mock_llm_output, render_frames=False)
    assert len(merged_proj.storyboard) == 1
    shot = merged_proj.storyboard[0]
    assert shot.keyframe_prompt.startswith("Close-up macro")
    assert shot.motion_prompt.startswith("Slow continuous")
    assert shot.endframe_prompt.startswith("Extreme macro")
    assert shot.continuity_mode == "one_take_continuous"

