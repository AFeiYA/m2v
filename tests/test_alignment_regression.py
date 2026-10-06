"""
Regression Test Suite for Alignment Engine.
Validates baseline integrity, ground-truth anchors, and solo interlude preservation.
Marked with @pytest.mark.local_only to conserve GitHub Actions CI quota.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from src.aligner import AlignmentResult, align_lyrics
from src.preprocessor import preprocess_lyrics
from tests.regression.runner import load_test_suite, verify_alignment

ROOT_DIR = Path(__file__).resolve().parent.parent
SUITE_DATA = load_test_suite(ROOT_DIR / "tests/regression/test_suite.json")
SONGS = SUITE_DATA.get("songs", [])


def test_suite_manifest_structure():
    """验证回归测试集元数据结构与规范 (超轻量，CI 默认执行)"""
    assert len(SONGS) >= 2, "回归测试集合至少应包含当前两首基线歌曲"
    for song in SONGS:
        assert "id" in song and "title" in song and "url" in song
        assert song["url"].startswith("https://suno.com/s/")
        assert "critical_anchors" in song
        assert "instrumental_interludes" in song


@pytest.mark.regression
@pytest.mark.parametrize("song_cfg", SONGS, ids=[s["id"] for s in SONGS])
def test_song_baseline_invariants(song_cfg: dict):
    """
    基线快照不变量验证 (秒级执行):
    确保本地已保存的基线 JSON 严格满足关键锚点、间奏保护、行数完整性与无挤压约束。
    在 GitHub CI 环境中若缺少媒体文件则自动跳过。
    """
    baseline_p = ROOT_DIR / song_cfg["baseline_alignment_path"]
    if not baseline_p.exists():
        pytest.skip(f"本地基线文件不存在 (CI 无媒体资产环境): {baseline_p}")

    baseline = AlignmentResult.load_json(baseline_p)

    report = verify_alignment(song_cfg, baseline, baseline_alignment=baseline, tolerance_sec=0.1)
    assert report.passed, f"基线未通过不变量验证 ({song_cfg['title']}): {report.failure_reasons}"
    assert report.quality_passed, f"基线存在声学对齐异常: {report.quality_issue}"
    assert report.total_lines == song_cfg["expected_line_count"]


@pytest.mark.regression
@pytest.mark.local_only
@pytest.mark.parametrize("song_cfg", SONGS, ids=[s["id"] for s in SONGS])
def test_live_alignment_matches_baseline(song_cfg: dict):
    """
    实时对齐现场模型推理验证 (高开销，本地专属):
    运行完整 Wav2Vec2 + CTC 对齐，校验与基线的漂移度。
    默认在 GitHub Actions CI 中跳过，节约云端免费计算配额并避免下载 1.2GB 模型。
    """
    # 明确检测 CI 环境并跳过，除非用户在 CI 中显式声明环境变量 RUN_ALIGNMENT_REGRESSION=1
    is_ci = os.getenv("CI", "false").lower() in ("true", "1") or os.getenv("GITHUB_ACTIONS", "false").lower() == "true"
    if is_ci and os.getenv("RUN_ALIGNMENT_REGRESSION") != "1":
        pytest.skip("GitHub CI 环境自动跳过高开销音频模型回归，节约免费配额。请在本地运行: python scripts/run_regression.py --live")

    vocals_p = ROOT_DIR / song_cfg["vocals_path"]
    lyrics_p = ROOT_DIR / song_cfg["lyrics_path"]
    baseline_p = ROOT_DIR / song_cfg["baseline_alignment_path"]

    if not vocals_p.exists() or not lyrics_p.exists() or not baseline_p.exists():
        pytest.skip(f"本地测试资产不全 ({song_cfg['title']})，跳过实时回归")

    lyrics = preprocess_lyrics(lyrics_p)
    live_result = align_lyrics(vocals_p, lyrics)
    baseline = AlignmentResult.load_json(baseline_p)

    report = verify_alignment(
        song_cfg,
        alignment=live_result,
        baseline_alignment=baseline,
        tolerance_sec=0.8,
    )

    assert report.passed, (
        f"实时对齐回归失败 [{song_cfg['title']}]:\n" + "\n".join(report.failure_reasons)
    )
