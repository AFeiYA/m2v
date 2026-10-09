#!/usr/bin/env python3
"""
Side-by-side Benchmark: Current Alignment Engine vs stable-ts.

Runs identical vocals and lyrics through both engines and compares:
1. 04tuZiDongV1 (兔子洞) - Chinese pop
2. Tailwind - Bilingual with guitar solo
3. Road Closed, Door Open - Code-switching with interlude
4. Circus in my head - English fast-tempo with melisma & tight boundaries
5. Missing Lyric Test (故意缺行/缺词测试) - Deleting Line 4 in Circus

Usage:
    python scripts/benchmark_stablets.py
    python scripts/benchmark_stablets.py --song circus
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.align.stablets_adapter import align_lyrics_stablets
from src.aligner import align_lyrics
from src.preprocessor import preprocess_lyrics
from tests.regression.runner import load_test_suite, verify_alignment

BENCHMARK_CASES = [
    {
        "id": "tuzidong",
        "title": "兔子洞 (04tuZiDongV1)",
        "vocals_path": "output/04tuZiDongV1/04tuZiDongV1_vocals.mp3",
        "lyrics_path": "input/04tuZiDongV1/04tuZiDongV1.txt",
        "language": "zh",
        "critical_anchors": [
            {"line_idx": 0, "expected_text": "天花板在脚下", "min_start": 26.0, "max_start": 29.5, "max_end": 33.0},
            {"line_idx": 15, "expected_text": "别试图呼救", "min_start": 96.0, "max_start": 99.5, "max_end": 105.0},
            {"line_idx": 28, "expected_text": "只有...更深...更美的...空。", "min_start": 175.0, "max_start": 179.0, "max_end": 183.0},
        ],
        "instrumental_interludes": [
            {"description": "Intro beat", "start": 0.0, "end": 26.0, "min_duration": 25.0, "forbidden_lyric_overlap": True}
        ],
        "repeated_choruses": [],
        "expected_line_count": 29,
    },
    {
        "id": "tailwind",
        "title": "Tailwind",
        "vocals_path": "output/Tailwind/Tailwind_vocals.mp3",
        "lyrics_path": "input/Tailwind/Tailwind.txt",
        "language": "mixed",
        "from_suite": True,
    },
    {
        "id": "road_closed",
        "title": "Road Closed, Door Open",
        "vocals_path": "output/Road Closed, Door Open/Road Closed, Door Open_vocals.mp3",
        "lyrics_path": "input/Road Closed, Door Open/Road Closed, Door Open.txt",
        "language": "mixed",
        "from_suite": True,
    },
    {
        "id": "circus",
        "title": "Circus in my head",
        "vocals_path": "output/Circus in my head/Circus in my head_vocals.mp3",
        "lyrics_path": "input/Circus in my head/Circus in my head.txt",
        "language": "en",
        "from_suite": True,
    },
]


def run_benchmark_for_song(case_cfg: dict, suite_cfg_map: dict):
    song_id = case_cfg["id"]
    cfg = suite_cfg_map.get(song_id, case_cfg)

    vocals_p = ROOT_DIR / cfg["vocals_path"]
    lyrics_p = ROOT_DIR / cfg["lyrics_path"]

    if not vocals_p.exists() or not lyrics_p.exists():
        print(f"⚠️ 跳过 {cfg['title']}: 资产文件不存在 ({vocals_p})")
        return None

    lyrics = preprocess_lyrics(lyrics_p)
    print(f"\n{'='*75}")
    print(f"🎵 测试歌曲: {cfg['title']} ({len(lyrics)} 行歌词)")
    print(f"{'='*75}")

    # 1. 运行 Current Engine
    print("\n⏳ 正在运行 [Current Engine: Wav2Vec2 + CTC + 任务规划] ...")
    t0 = time.time()
    res_current = align_lyrics(vocals_p, lyrics)
    t_current = time.time() - t0
    report_current = verify_alignment(cfg, res_current, baseline_alignment=res_current, tolerance_sec=0.8)

    # 2. 运行 stable-ts
    print("\n⏳ 正在运行 [stable-ts: Whisper base + Attention Alignment] ...")
    t0 = time.time()
    res_stablets = align_lyrics_stablets(vocals_p, lyrics, language=cfg.get("language"))
    t_stablets = time.time() - t0
    report_stablets = verify_alignment(cfg, res_stablets, baseline_alignment=res_current, tolerance_sec=0.8)

    # 打印对比分析
    print(f"\n📊 【{cfg['title']} 对比结果】")
    print("  指标                     | Current Engine          | stable-ts")
    print("  -------------------------+-------------------------+-------------------------")
    print(f"  耗时                     | {t_current:6.2f}s                 | {t_stablets:6.2f}s")
    
    cur_anchors_pass = "✅ 通过" if report_current.passed else "❌ 失败"
    st_anchors_pass = "✅ 通过" if report_stablets.passed else "❌ 失败"
    print(f"  关键锚点约束             | {cur_anchors_pass:23s} | {st_anchors_pass:23s}")
    
    cur_qual = "✅ 优良" if report_current.quality_passed else "❌ 异常"
    st_qual = "✅ 优良" if report_stablets.quality_passed else "❌ 异常"
    print(f"  声学挤压/重叠检查        | {cur_qual:23s} | {st_qual:23s}")

    if not report_current.passed:
        print(f"    Current 失败原因: {report_current.failure_reasons}")
    if not report_stablets.passed:
        print(f"    stable-ts 失败原因: {report_stablets.failure_reasons}")

    # 特殊观测点 (Circus never could)
    if song_id == "circus":
        print("\n  🔍 细粒度观测 [Circus 'never could']:")
        for name, res in [("Current Engine", res_current), ("stable-ts", res_stablets)]:
            l15 = res.lines[14] if len(res.lines) > 14 else None
            l31 = res.lines[30] if len(res.lines) > 30 else None
            w15_nc = [(w.word.strip(), round(w.start, 2), round(w.end, 2)) for w in l15.words if w.word.strip() in ("never", "could")] if l15 else []
            w31_nc = [(w.word.strip(), round(w.start, 2), round(w.end, 2)) for w in l31.words if w.word.strip() in ("never", "could")] if l31 else []
            print(f"    [{name}]")
            print(f"      第 15 行: line=[{l15.start:.2f}, {l15.end:.2f}] words={w15_nc}")
            print(f"      第 31 行: line=[{l31.start:.2f}, {l31.end:.2f}] words={w31_nc}")

    return {
        "title": cfg["title"],
        "t_current": t_current,
        "t_stablets": t_stablets,
        "pass_current": report_current.passed,
        "pass_stablets": report_stablets.passed,
    }


def run_missing_lyric_experiment():
    """故意漏词/漏句对抗测试：删除 Circus 第 4 行，检验两个引擎在缺词时的抗漂移能力。"""
    print(f"\n{'='*75}")
    print("🧪 【故意缺词/缺句鲁棒性对抗实验】")
    print("测试用例: Circus in my head 故意删除第 4 行 ('Got a million moving parts on a Tuesday night')")
    print("观察目标: 第 5 行是否会提前 3 秒抢跑、后续段落是否会发生雪崩式位移")
    print(f"{'='*75}")

    vocals_p = ROOT_DIR / "output/Circus in my head/Circus in my head_vocals.mp3"
    lyrics_p = ROOT_DIR / "input/Circus in my head/Circus in my head.txt"

    raw_lyrics = preprocess_lyrics(lyrics_p)
    # 删除第 4 行
    mutated_lyrics = [ly for i, ly in enumerate(raw_lyrics) if i != 4]
    deleted_text = raw_lyrics[4].text

    print(f"已删除歌词: '{deleted_text}' (原声学位置约 32.8s ~ 36.2s)")
    print(f"原第 5 行: '{raw_lyrics[5].text}' (原声学起唱约 36.68s)")

    # 1. Current Engine
    t0 = time.time()
    res_cur = align_lyrics(vocals_p, mutated_lyrics)
    t_cur = time.time() - t0

    # 2. stable-ts
    t0 = time.time()
    res_st = align_lyrics_stablets(vocals_p, mutated_lyrics, language="en")
    t_st = time.time() - t0

    # 检验突变后第 4 行 (即原第 5 行) 的起始时间
    cur_line_after_delete = res_cur.lines[4]
    st_line_after_delete = res_st.lines[4]

    print("\n📊 对抗实验结果:")
    print("  原第 5 行标准真值区间: [36.68s ~ 40.29s]")
    print(f"  Current Engine 对齐区间: [{cur_line_after_delete.start:.2f}s ~ {cur_line_after_delete.end:.2f}s] (耗时 {t_cur:.2f}s)")
    print(f"  stable-ts      对齐区间: [{st_line_after_delete.start:.2f}s ~ {st_line_after_delete.end:.2f}s] (耗时 {t_st:.2f}s)")

    cur_drift = abs(cur_line_after_delete.start - 36.68)
    st_drift = abs(st_line_after_delete.start - 36.68)
    print(f"  -> Current Engine 起始偏差: {cur_drift:.2f}s")
    print(f"  -> stable-ts      起始偏差: {st_drift:.2f}s")


def main():
    parser = argparse.ArgumentParser(description="Side-by-side benchmark: Current vs stable-ts")
    parser.add_argument("--song", type=str, default="", help="Filter song (tuzidong, tailwind, road_closed, circus)")
    parser.add_argument("--skip-missing", action="store_true", help="Skip missing lyrics experiment")
    args = parser.parse_args()

    suite_data = load_test_suite(ROOT_DIR / "tests/regression/test_suite.json")
    suite_map = {s["id"]: s for s in suite_data.get("songs", [])}

    cases = BENCHMARK_CASES
    if args.song:
        cases = [c for c in cases if c["id"].lower() == args.song.lower()]

    results = []
    for c in cases:
        r = run_benchmark_for_song(c, suite_map)
        if r:
            results.append(r)

    if not args.song and not args.skip_missing:
        run_missing_lyric_experiment()

    print(f"\n{'='*75}")
    print("🏁 全部基准对比测试执行完毕！")
    print(f"{'='*75}")


if __name__ == "__main__":
    main()
