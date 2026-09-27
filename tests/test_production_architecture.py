"""
单元测试：AI-Native MV 工业流水线核心架构组件
测试范围：
1. SongSource 统一输入源适配器 (Suno / 本地音频)
2. PromptCompiler 异构大模型编译器 (Veo / Kling / Seedance / Wan)
3. MultiTrack TimelineEngine (Audio / Video / Typography)
"""
from pathlib import Path
import pytest

from src.song_source import (
    SongSource,
    SunoDirectoryAdapter,
    LocalAudioFileAdapter,
    detect_and_load_song_source,
)
from src.compilers import (
    list_supported_compilers,
    get_compiler,
    compile_shot_for_model,
)
from src.compilers.veo_compiler import VeoPromptCompiler
from src.compilers.kling_compiler import KlingPromptCompiler
from src.compilers.seedance_compiler import SeedancePromptCompiler
from src.compilers.wan_compiler import WanPromptCompiler
from src.timeline_engine import TimelineEngine
from src.storyboard_schema import (
    AlignedLine,
    AlignmentProject,
    CompositionSafeZones,
    GlobalBibles,
    MultiTrackTimeline,
    SequencePlan,
    ShotPlan,
    Take,
    VisualBible,
)


def test_song_source_local_adapter(tmp_path):
    """测试本地单音频文件适配器"""
    audio = tmp_path / "my_track.mp3"
    audio.write_bytes(b"MOCK_MP3_DATA")
    lrc = tmp_path / "my_track.lrc"
    lrc.write_text("[00:01.00]测试歌词第一句\n[00:05.00]测试歌词第二句", encoding="utf-8")

    source = detect_and_load_song_source(audio)
    assert isinstance(source, SongSource)
    assert source.title == "my_track"
    assert source.audio_path == audio
    assert "测试歌词第一句" in source.lyrics_raw
    assert source.validate() is True


def test_song_source_suno_adapter(tmp_path):
    """测试 Suno 导出工程目录适配器"""
    suno_dir = tmp_path / "suno_song_01"
    suno_dir.mkdir()
    (suno_dir / "suno_song_01.wav").write_bytes(b"MOCK_WAV")
    (suno_dir / "suno_song_01_vocals.wav").write_bytes(b"MOCK_VOCALS")
    (suno_dir / "suno_song_01_instrumental.wav").write_bytes(b"MOCK_INSTRUMENTAL")

    stems_dir = suno_dir / "stems"
    stems_dir.mkdir()
    (stems_dir / "drums.wav").write_bytes(b"MOCK_DRUMS")

    source = detect_and_load_song_source(suno_dir)
    assert source.title == "suno_song_01"
    assert source.has_isolated_audio is True
    assert source.has_stems is True
    assert "drums" in source.stems


def test_prompt_compilers():
    """测试各大视频模型提示词编译器输出规格与负向词隔离"""
    shot = ShotPlan(
        shot_id=1,
        id="shot_001",
        start=0.0,
        end=4.5,
        shot_size="MCU",
        camera_motion="slow_dolly_in",
        prompt_en="Master craftsman shaping azure porcelain on spinning wheel.",
        action="手指轻按旋转瓷土，青色釉泥飞溅",
        layout_contract=CompositionSafeZones(primary_subject_x=0.65, primary_subject_y=0.5),
    )
    bibles = GlobalBibles(
        visual=VisualBible(forbidden_elements=["cartoon", "modern cars"])
    )
    seq = SequencePlan(id="SEQ_01", title="序章：匠人起胚", start=0.0, end=10.0)

    # 1. 检验编译器列表
    compilers = list_supported_compilers()
    assert "veo" in compilers
    assert "kling" in compilers
    assert "seedance" in compilers
    assert "wan" in compilers

    # 2. Veo 编译测试
    veo_res = compile_shot_for_model(shot, "veo", bibles=bibles, sequence=seq)
    assert veo_res.model_name == "google_veo"
    assert "MCU shot" in veo_res.prompt
    assert "35mm anamorphic" in veo_res.prompt
    assert "subtitles" in veo_res.negative_prompt
    assert "modern cars" in veo_res.negative_prompt
    assert veo_res.extra_params["safe_zone"]["primary_subject_zone"] == "center_right"

    # 3. Kling 编译测试
    kling_res = compile_shot_for_model(shot, "kling", bibles=bibles)
    assert kling_res.model_name == "kling_v2"
    assert kling_res.extra_params["camera_control"]["zoom"] > 0

    # 4. Seedance 编译测试
    seedance_res = compile_shot_for_model(shot, "seedance", bibles=bibles)
    assert seedance_res.model_name == "bytedance_seedance_2_5"
    assert seedance_res.duration_seconds == 4.5

    # 5. Wan 编译测试
    wan_res = compile_shot_for_model(shot, "wan", bibles=bibles)
    assert wan_res.model_name == "alibaba_wanx_2_1"
    assert "MCU 景别" in wan_res.prompt


def test_timeline_engine():
    """测试多轨非线性剪辑时间轴编译与校验"""
    proj = AlignmentProject(
        title="test_track",
        duration=12.0,
        audio_path="test_audio.wav",
        vocals_path="test_vocals.wav",
        lines=[
            AlignedLine(text="晨光洒在古镇檐角", start=0.0, end=5.0),
            AlignedLine(text="炉火点燃千年匠心", start=5.0, end=12.0),
        ],
        storyboard=[
            ShotPlan(shot_id=1, id="shot_001", start=0.0, end=5.0, preview_image="shot_001.png"),
            ShotPlan(
                shot_id=2,
                id="shot_002",
                start=5.0,
                end=12.0,
                preview_image="shot_002.png",
                takes=[Take(id="take_002_a", shot_id="shot_002", video_path="clip_002.mp4", selected=True)],
                selected_take_id="take_002_a",
            ),
        ],
    )

    timeline = TimelineEngine.build_from_project(proj)
    assert isinstance(timeline, MultiTrackTimeline)
    assert timeline.duration == 12.0

    # 检验多轨分配
    assert len(timeline.audio_tracks) == 2
    assert len(timeline.video_track) == 2
    assert len(timeline.typography_track) == 2

    # 检验素材平滑切换 (Shot 1 使用 preview_image，Shot 2 选定 Take 使用视频 clip_002.mp4)
    assert timeline.video_track[0].source_media_path == "shot_001.png"
    assert timeline.video_track[1].source_media_path == "clip_002.mp4"

    # 检验时间轴完整性
    issues = TimelineEngine.validate_integrity(timeline)
    assert len(issues) == 0

    # 检验概览指标
    summary = TimelineEngine.export_summary(timeline)
    assert summary["video_shots_count"] == 2
    assert summary["audio_tracks_count"] == 2
