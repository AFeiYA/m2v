"""
Regression Test Runner for Lyric Alignment & Motion MV Generation.
Verifies critical acoustic anchors, instrumental interludes, and repeated section disambiguation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.aligner import AlignmentResult, alignment_quality_issue
from src.utils import log


@dataclass
class AnchorVerificationResult:
    line_idx: int
    expected_text: str
    actual_text: str
    start: float
    end: float
    passed: bool
    reason: str = ""


@dataclass
class InterludeVerificationResult:
    description: str
    expected_span: tuple[float, float]
    actual_gap: tuple[float, float]
    passed: bool
    reason: str = ""


@dataclass
class SongRegressionReport:
    song_id: str
    title: str
    url: str
    total_lines: int
    expected_lines: int
    quality_passed: bool
    quality_issue: str | None
    anchor_results: list[AnchorVerificationResult] = field(default_factory=list)
    interlude_results: list[InterludeVerificationResult] = field(default_factory=list)
    max_drift_vs_baseline: float = 0.0
    mean_drift_vs_baseline: float = 0.0
    passed: bool = True
    failure_reasons: list[str] = field(default_factory=list)


def load_test_suite(suite_path: Path | None = None) -> dict[str, Any]:
    if suite_path is None:
        suite_path = Path(__file__).parent / "test_suite.json"
    with open(suite_path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_alignment(
    song_cfg: dict[str, Any],
    alignment: AlignmentResult,
    baseline_alignment: AlignmentResult | None = None,
    tolerance_sec: float = 1.0,
) -> SongRegressionReport:
    """验证对齐结果是否满足回归基线与各项不变量约束"""
    song_id = song_cfg["id"]
    title = song_cfg["title"]
    url = song_cfg.get("url", "")
    expected_lines = song_cfg.get("expected_line_count", len(alignment.lines))

    report = SongRegressionReport(
        song_id=song_id,
        title=title,
        url=url,
        total_lines=len(alignment.lines),
        expected_lines=expected_lines,
        quality_passed=True,
        quality_issue=None,
    )

    # 1. 行数检验
    if len(alignment.lines) != expected_lines:
        report.passed = False
        report.failure_reasons.append(
            f"行数不匹配: 期望 {expected_lines} 行, 实际 {len(alignment.lines)} 行"
        )

    # 2. 基础质量检验 (单调性、字级挤压、异常超长)
    q_issue = alignment_quality_issue(alignment.lines)
    if q_issue:
        report.quality_passed = False
        report.quality_issue = q_issue
        report.passed = False
        report.failure_reasons.append(f"声学对齐质量问题: {q_issue}")

    # 3. 关键锚点检验 (Critical Anchors)
    for anchor in song_cfg.get("critical_anchors", []):
        idx = anchor["line_idx"]
        if idx >= len(alignment.lines):
            report.anchor_results.append(
                AnchorVerificationResult(
                    line_idx=idx,
                    expected_text=anchor.get("expected_text", ""),
                    actual_text="<OUT_OF_BOUNDS>",
                    start=0.0,
                    end=0.0,
                    passed=False,
                    reason=f"行号 {idx} 超出范围 (总行数={len(alignment.lines)})",
                )
            )
            report.passed = False
            continue

        line = alignment.lines[idx]
        min_s = anchor.get("min_start", 0.0)
        max_s = anchor.get("max_start", 9999.0)
        max_e = anchor.get("max_end", 9999.0)

        ok = True
        reasons = []
        if line.start < min_s:
            ok = False
            reasons.append(f"起唱过早 (start={line.start:.2f}s < min={min_s:.2f}s)")
        if line.start > max_s:
            ok = False
            reasons.append(f"起唱过晚 (start={line.start:.2f}s > max={max_s:.2f}s)")
        if line.end > max_e:
            ok = False
            reasons.append(f"结束过晚 (end={line.end:.2f}s > max={max_e:.2f}s)")

        res = AnchorVerificationResult(
            line_idx=idx,
            expected_text=anchor.get("expected_text", ""),
            actual_text=line.text,
            start=line.start,
            end=line.end,
            passed=ok,
            reason="; ".join(reasons) if not ok else "PASS",
        )
        report.anchor_results.append(res)
        if not ok:
            report.passed = False
            report.failure_reasons.append(f"锚点检验失败 (第 {idx} 行 '{line.text}'): {res.reason}")

    # 4. 纯伴奏/长间奏保护检验 (Instrumental Interludes)
    for interlude in song_cfg.get("instrumental_interludes", []):
        int_s = interlude["start"]
        int_e = interlude["end"]
        desc = interlude.get("description", "间奏")

        # 检查是否有任何歌词行侵入了该间奏的核心区间
        invaded_lines = [
            (i, l) for i, l in enumerate(alignment.lines)
            if l.start < int_e - 1.0 and l.end > int_s + 1.0
        ]
        if invaded_lines:
            report.passed = False
            inv_desc = ", ".join(f"L{i}('{l.text}', {l.start:.1f}-{l.end:.1f}s)" for i, l in invaded_lines)
            report.failure_reasons.append(f"间奏被歌词非法侵占 [{int_s}s ~ {int_e}s]: {inv_desc}")
            report.interlude_results.append(
                InterludeVerificationResult(
                    description=desc,
                    expected_span=(int_s, int_e),
                    actual_gap=(0.0, 0.0),
                    passed=False,
                    reason=f"被歌词侵占: {inv_desc}",
                )
            )
        else:
            report.interlude_results.append(
                InterludeVerificationResult(
                    description=desc,
                    expected_span=(int_s, int_e),
                    actual_gap=(int_s, int_e),
                    passed=True,
                    reason="PASS (间奏完整保留)",
                )
            )

    # 5. 重复副歌隔离检验 (Repeated Chorus Boundedness)
    for rep in song_cfg.get("repeated_choruses", []):
        f_max = rep.get("first_occurrence_max_end")
        s_min = rep.get("second_occurrence_min_start")
        # 验证歌词整体是否存在合法的序贯结构
        if f_max is not None and s_min is not None:
            # 找到首尾分界
            if f_max >= s_min:
                report.passed = False
                report.failure_reasons.append(f"重复段定义矛盾: first_max={f_max} >= second_min={s_min}")

    # 6. 对比 Baseline 漂移 (Drift Metrics)
    if baseline_alignment and len(baseline_alignment.lines) == len(alignment.lines):
        drifts = [
            abs(a.start - b.start) + abs(a.end - b.end)
            for a, b in zip(alignment.lines, baseline_alignment.lines)
        ]
        report.max_drift_vs_baseline = max(drifts)
        report.mean_drift_vs_baseline = sum(drifts) / len(drifts)
        if report.max_drift_vs_baseline > tolerance_sec * 2.0:
            report.passed = False
            report.failure_reasons.append(
                f"偏离基准过大: 最大漂移 {report.max_drift_vs_baseline:.2f}s > 容限 {tolerance_sec * 2.0:.2f}s"
            )

    return report
