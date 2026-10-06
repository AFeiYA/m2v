#!/usr/bin/env python3
"""
CLI Tool for Running Alignment Regression Tests.
Usage:
    python scripts/run_regression.py
    python scripts/run_regression.py --live
    python scripts/run_regression.py --song tailwind
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.aligner import AlignmentResult, align_lyrics
from src.preprocessor import preprocess_lyrics
from tests.regression.runner import load_test_suite, verify_alignment


def main():
    parser = argparse.ArgumentParser(description="Run Lyric Alignment Regression Suite")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute real-time CTC alignment instead of validating cached baseline JSON",
    )
    parser.add_argument(
        "--song",
        type=str,
        default="",
        help="Filter by specific song ID (e.g. look_up or tailwind)",
    )
    args = parser.parse_args()

    suite_data = load_test_suite(ROOT_DIR / "tests/regression/test_suite.json")
    songs = suite_data.get("songs", [])

    if args.song:
        songs = [s for s in songs if s["id"].lower() == args.song.lower()]
        if not songs:
            print(f"❌ 未找到 ID 为 '{args.song}' 的测试歌曲")
            sys.exit(1)

    print("=" * 80)
    mode_str = "【实时 CTC 对齐回归】" if args.live else "【基线快照不变量审计】"
    print(f"🎵 M2V 歌词声学对齐回归测试集 {mode_str}")
    print(f"  版本: {suite_data.get('version')} | 包含歌曲: {len(songs)} 首")
    print("=" * 80)

    all_passed = True
    reports = []

    for song_cfg in songs:
        title = song_cfg["title"]
        song_id = song_cfg["id"]
        url = song_cfg.get("url", "")
        lyrics_p = ROOT_DIR / song_cfg["lyrics_path"]
        vocals_p = ROOT_DIR / song_cfg["vocals_path"]
        baseline_p = ROOT_DIR / song_cfg["baseline_alignment_path"]

        print(f"\n▶ 正在验证: 《{title}》 ({song_id})")
        print(f"  Suno 链接: {url}")

        baseline = AlignmentResult.load_json(baseline_p) if baseline_p.exists() else None

        if args.live:
            print("  [Live] 启动现场 CTC 强制对齐...")
            lyrics = preprocess_lyrics(lyrics_p)
            current_alignment = align_lyrics(vocals_p, lyrics)
        else:
            current_alignment = baseline

        if current_alignment is None:
            print("  ❌ 缺少对齐数据，无法验证")
            all_passed = False
            continue

        report = verify_alignment(
            song_cfg,
            alignment=current_alignment,
            baseline_alignment=baseline,
            tolerance_sec=0.8,
        )
        reports.append(report)

        # Print song results
        status_icon = "✅ PASS" if report.passed else "❌ FAIL"
        print(f"  测试结果: {status_icon}")
        print(f"  有效行数: {report.total_lines}/{report.expected_lines}")
        
        passed_anchors = sum(1 for a in report.anchor_results if a.passed)
        total_anchors = len(report.anchor_results)
        print(f"  关键锚点: {passed_anchors}/{total_anchors} 通过")

        for int_res in report.interlude_results:
            int_icon = "✓" if int_res.passed else "✗"
            print(f"  长间奏保护 [{int_res.expected_span[0]:.1f}s~{int_res.expected_span[1]:.1f}s]: {int_icon} {int_res.description}")

        if args.live and baseline:
            print(f"  基线漂移: 最大 {report.max_drift_vs_baseline:.2f}s | 平均 {report.mean_drift_vs_baseline:.2f}s")

        if not report.passed:
            all_passed = False
            print("  失败详情:")
            for fail in report.failure_reasons:
                print(f"    • {fail}")

    print("\n" + "=" * 80)
    if all_passed:
        print("🎉 全部回归基线测试通过！算法稳定性与声学锚点保持完整。")
        print("=" * 80)
        sys.exit(0)
    else:
        print("⚠️ 存在回归测试失败项，请检视上方失败详情与声学切分约束。")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
