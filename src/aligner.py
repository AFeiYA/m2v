"""
Module 3: 词级对齐引擎
- WhisperX forced alignment 封装
- 支持 Forced Alignment（传入原歌词约束，避免自由转写）
- Fallback: 对齐失败的行按时长均分给每个字符
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from src.config import AlignerConfig
from src.preprocessor import LyricLine
from src.utils import log


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class WordTimestamp:
    """单个字/词的时间戳"""
    word: str
    start: float   # 秒
    end: float      # 秒


@dataclass
class AlignedLine:
    """一行对齐后的歌词"""
    text: str
    start: float
    end: float
    words: list[WordTimestamp]


@dataclass
class AlignmentResult:
    """完整对齐结果"""
    lines: list[AlignedLine]

    def to_dict(self) -> dict:
        return {"lines": [asdict(line) for line in self.lines]}

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        log.info("对齐结果已保存: %s", path.name)

    @classmethod
    def load_json(cls, path: Path) -> "AlignmentResult":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        lines = []
        for line_data in data["lines"]:
            words = [WordTimestamp(**w) for w in line_data["words"]]
            lines.append(AlignedLine(
                text=line_data["text"],
                start=line_data["start"],
                end=line_data["end"],
                words=words,
            ))
        return cls(lines=lines)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def align_lyrics(
    vocals_path: Path,
    lyrics: list[LyricLine],
    config: AlignerConfig | None = None,
) -> AlignmentResult:
    """
    音频驱动的歌词对齐:
    1. Whisper 自由转写 → WhisperX forced alignment → 每字真实时间戳
    2. 把歌词文本模糊匹配到这些带时间戳的字上
    时间戳完全由音频决定，歌词只负责显示。
    """
    if config is None:
        config = AlignerConfig()

    log.info("开始词级对齐: %s (%d 行歌词)", vocals_path.name, len(lyrics))

    try:
        import whisperx
        import torch
    except ImportError as e:
        raise ImportError(
            "WhisperX 未安装。请运行: pip install whisperx\n"
            "或使用 Docker 环境运行本项目。"
        ) from e

    device = config.device
    fell_back_to_cpu = False
    if device == "cuda" and not torch.cuda.is_available():
        log.warning("CUDA 不可用，回退到 CPU 模式")
        device = "cpu"
        fell_back_to_cpu = True

    compute_type = "int8" if fell_back_to_cpu else config.compute_type

    _CPU_HEAVY_MODELS = {"large", "large-v1", "large-v2", "large-v3", "large-v3-turbo"}
    whisper_model = config.whisper_model
    if device == "cpu" and whisper_model in _CPU_HEAVY_MODELS:
        whisper_model = "medium"
        log.warning(
            "CPU 模式下 %s 会极慢，已自动降级为 medium。"
            " 如需指定模型请在 pipeline.toml [aligner] whisper_model 中设置。",
            config.whisper_model,
        )

    # -----------------------------------------------------------------------
    # Step 1: Whisper 自由转写
    # -----------------------------------------------------------------------
    log.info("加载 Whisper 模型: %s (device=%s, compute=%s)",
             whisper_model, device, compute_type)
    model = whisperx.load_model(
        whisper_model,
        device=device,
        compute_type=compute_type,
        language=config.language,
    )

    audio = whisperx.load_audio(str(vocals_path))
    log.info("Whisper 转写中…")
    transcribe_result = model.transcribe(
        audio,
        batch_size=config.batch_size,
        language=config.language,
    )

    # 过滤前奏
    if config.lyrics_start_time > 0:
        orig_count = len(transcribe_result.get("segments", []))
        transcribe_result["segments"] = [
            seg for seg in transcribe_result.get("segments", [])
            if seg.get("end", 0) > config.lyrics_start_time
        ]
        filtered = orig_count - len(transcribe_result["segments"])
        if filtered:
            log.info("已过滤 %d 个前奏 segment (lyrics_start_time=%.1fs)",
                     filtered, config.lyrics_start_time)

    segments = transcribe_result.get("segments", [])

    # 保存调试信息
    _debug_path = vocals_path.parent / (vocals_path.stem + "_whisper_segments.json")
    try:
        import json as _json
        with open(_debug_path, "w", encoding="utf-8") as _f:
            _json.dump(segments, _f, ensure_ascii=False, indent=2)
        log.info("Whisper segments 已保存: %s (%d 条)", _debug_path.name, len(segments))
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Step 2: WhisperX 对齐 — 用 Whisper 自己的文本做 forced alignment
    # -----------------------------------------------------------------------
    log.info("加载对齐模型 (language=%s)…", config.language)
    align_model, align_metadata = whisperx.load_align_model(
        language_code=config.language,
        device=device,
        model_name=config.align_model,
    )

    log.info("执行字符级对齐…")
    align_result = whisperx.align(
        transcribe_result["segments"],
        align_model,
        align_metadata,
        audio,
        device=device,
        return_char_alignments=True,
    )

    # -----------------------------------------------------------------------
    # Step 3: 收集所有带时间戳的字符 → 时间轴
    # -----------------------------------------------------------------------
    timeline = _build_char_timeline(align_result)
    log.info("音频时间轴: %d 个带时间戳的字符 (%.1fs ~ %.1fs)",
             len(timeline),
             timeline[0][1] if timeline else 0,
             timeline[-1][2] if timeline else 0)

    # 保存时间轴用于调试
    _tl_path = vocals_path.parent / (vocals_path.stem + "_timeline.json")
    try:
        with open(_tl_path, "w", encoding="utf-8") as _f:
            _json.dump(
                [{"char": c, "start": s, "end": e} for c, s, e in timeline],
                _f, ensure_ascii=False, indent=2,
            )
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Step 4: 把歌词行模糊匹配到时间轴上
    # -----------------------------------------------------------------------
    aligned_lines = _match_lyrics_to_timeline(lyrics, timeline)

    result = AlignmentResult(lines=aligned_lines)
    log.info("对齐完成: %d 行, %d 个词",
             len(result.lines),
             sum(len(line.words) for line in result.lines))
    return result


# ---------------------------------------------------------------------------
# 音频驱动: 从 WhisperX 对齐结果构建字符时间轴
# ---------------------------------------------------------------------------

def _build_char_timeline(
    align_result: dict,
) -> list[tuple[str, float, float]]:
    """
    从 WhisperX align() 的输出中收集所有带时间戳的字符。

    返回: [(char, start, end), ...] 按时间排序
    优先用 char_segments，其次用 word_segments 拆字。
    """
    timeline: list[tuple[str, float, float]] = []

    for seg in align_result.get("segments", []):
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start + 1.0)

        # 优先: chars 级别的时间戳
        char_segs = seg.get("chars", [])
        if char_segs:
            for cs in char_segs:
                c = cs.get("char", "").strip()
                s = cs.get("start")
                e = cs.get("end")
                if c and s is not None and e is not None:
                    timeline.append((c, s, e))
            continue

        # 次选: words 级别 → 拆成单字
        word_segs = seg.get("words", [])
        if word_segs:
            for ws in word_segs:
                w = ws.get("word", "").strip()
                s = ws.get("start")
                e = ws.get("end")
                if not w or s is None or e is None:
                    continue
                # 中文词一般就是1-2字，拆成单字均分
                chars = [c for c in w if not c.isspace()]
                if not chars:
                    continue
                dur = (e - s) / len(chars)
                for ci, ch in enumerate(chars):
                    timeline.append((
                        ch,
                        round(s + ci * dur, 3),
                        round(s + (ci + 1) * dur, 3),
                    ))
            continue

        # 兜底: segment 文本均分
        text = seg.get("text", "").strip()
        chars = [c for c in text if not c.isspace()]
        if chars:
            dur = (seg_end - seg_start) / len(chars)
            for ci, ch in enumerate(chars):
                timeline.append((
                    ch,
                    round(seg_start + ci * dur, 3),
                    round(seg_start + (ci + 1) * dur, 3),
                ))

    # 按时间排序
    timeline.sort(key=lambda x: x[1])
    return timeline


# ---------------------------------------------------------------------------
# 歌词 → 时间轴模糊匹配 (SequenceMatcher)
# ---------------------------------------------------------------------------

def _match_lyrics_to_timeline(
    lyrics: list["LyricLine"],
    timeline: list[tuple[str, float, float]],
) -> list[AlignedLine]:
    """
    用 SequenceMatcher 将歌词文本匹配到音频时间轴上。

    策略:
    1. 拼接所有歌词行的纯字符（去空格标点）得到 lyrics_seq
    2. 拼接时间轴的字符得到 audio_seq
    3. 用 SequenceMatcher 找到最佳对齐块
    4. 对齐的字直接用音频时间戳；未对齐的字用插值
    5. 按行边界切分，标点零时长继承前字
    """
    from difflib import SequenceMatcher

    if not timeline or not lyrics:
        return []

    # --- 构建歌词字符序列 (只保留有声字符用于匹配) ---
    lyrics_chars: list[tuple[int, int, str]] = []  # (line_idx, char_idx_in_line, char)
    for li, ly in enumerate(lyrics):
        chars_in_line = [c for c in ly.text if not c.isspace()]
        for ci, ch in enumerate(chars_in_line):
            if _CHINESE_CHAR_RE.match(ch) or ch.isalnum():
                lyrics_chars.append((li, ci, ch))

    # --- 时间轴字符序列 ---
    audio_chars = [c for c, _, _ in timeline]

    lyrics_seq = "".join(c for _, _, c in lyrics_chars)
    audio_seq = "".join(audio_chars)

    log.info("模糊匹配: 歌词 %d 字 vs 音频 %d 字", len(lyrics_seq), len(audio_seq))

    # --- SequenceMatcher 对齐 ---
    sm = SequenceMatcher(None, lyrics_seq, audio_seq, autojunk=False)
    matching_blocks = sm.get_matching_blocks()

    # 构建 lyrics_char_idx → timeline_idx 的映射
    lyric_to_tl: dict[int, int] = {}
    for a, b, size in matching_blocks:
        for k in range(size):
            lyric_to_tl[a + k] = b + k

    matched = len(lyric_to_tl)
    log.info("匹配结果: %d/%d 字命中 (%.0f%%)",
             matched, len(lyrics_seq),
             100 * matched / len(lyrics_seq) if lyrics_seq else 0)

    # --- 为每个歌词字符分配时间戳 ---
    # 对于匹配到的字: 直接用时间轴的时间
    # 对于未匹配的字: 用前后锚点线性插值
    char_times: list[tuple[float, float] | None] = [None] * len(lyrics_chars)
    for lci, tli in lyric_to_tl.items():
        _, s, e = timeline[tli]
        char_times[lci] = (s, e)

    # 插值填充未匹配的字符
    _interpolate_char_times(char_times, timeline)

    # --- 按行切分，生成 AlignedLine ---
    aligned_lines: list[AlignedLine] = []
    # 重新遍历每行，包含所有字符（含标点）
    lci = 0  # lyrics_chars 的游标
    for li, ly in enumerate(lyrics):
        chars_in_line = [c for c in ly.text if not c.isspace()]
        if not chars_in_line:
            continue

        words: list[WordTimestamp] = []
        for ci, ch in enumerate(chars_in_line):
            is_voiced = bool(_CHINESE_CHAR_RE.match(ch)) or ch.isalnum()
            if is_voiced and lci < len(char_times):
                t = char_times[lci]
                lci += 1
                if t is not None:
                    words.append(WordTimestamp(word=ch, start=t[0], end=t[1]))
                else:
                    # 仍然没有时间 → 继承前字
                    prev_end = words[-1].end if words else 0.0
                    words.append(WordTimestamp(word=ch, start=prev_end, end=prev_end + 0.3))
            else:
                # 标点: 零时长
                prev_end = words[-1].end if words else 0.0
                words.append(WordTimestamp(word=ch, start=prev_end, end=prev_end))

        if words and any(w.end > w.start for w in words):
            aligned_lines.append(AlignedLine(
                text=ly.text,
                start=words[0].start,
                end=words[-1].end,
                words=words,
            ))

    return aligned_lines


def _interpolate_char_times(
    char_times: list[tuple[float, float] | None],
    timeline: list[tuple[str, float, float]],
) -> None:
    """
    用前后锚点线性插值填充 char_times 中的 None 位置。
    """
    n = len(char_times)
    if n == 0:
        return

    # 找所有锚点 (有时间戳的位置)
    anchors: list[int] = [i for i in range(n) if char_times[i] is not None]

    if not anchors:
        # 完全没有锚点 → 用时间轴首尾均分
        if timeline:
            t_start = timeline[0][1]
            t_end = timeline[-1][2]
        else:
            t_start, t_end = 0.0, float(n) * 0.5
        dur = (t_end - t_start) / n
        for i in range(n):
            char_times[i] = (
                round(t_start + i * dur, 3),
                round(t_start + (i + 1) * dur, 3),
            )
        return

    # 填充第一个锚点之前
    first = anchors[0]
    if first > 0:
        anchor_s = char_times[first][0]
        # 每个字 ~0.4s，往前推
        for i in range(first - 1, -1, -1):
            anchor_s = max(anchor_s - 0.4, 0.0)
            char_times[i] = (round(anchor_s, 3), round(anchor_s + 0.4, 3))

    # 填充最后一个锚点之后
    last = anchors[-1]
    if last < n - 1:
        anchor_e = char_times[last][1]
        for i in range(last + 1, n):
            char_times[i] = (round(anchor_e, 3), round(anchor_e + 0.4, 3))
            anchor_e += 0.4

    # 填充锚点之间的空隙
    for ai in range(len(anchors) - 1):
        left = anchors[ai]
        right = anchors[ai + 1]
        if right - left <= 1:
            continue
        left_end = char_times[left][1]
        right_start = char_times[right][0]
        gap_count = right - left - 1
        dur = (right_start - left_end) / gap_count if gap_count > 0 else 0.3
        for j in range(gap_count):
            idx = left + 1 + j
            s = left_end + j * dur
            char_times[idx] = (round(s, 3), round(s + dur, 3))


# ---------------------------------------------------------------------------
# 旧策略 (保留): Whisper 行级时间范围 + 行内按字符等比分配
# ---------------------------------------------------------------------------

def _match_segments_to_lyrics(
    segments: list[dict],
    lyrics: list["LyricLine"],
) -> list[tuple[float, float] | None]:
    """
    将 Whisper segment 时间范围映射到每行歌词。

    三级匹配: 段落 → 句子 → 字符
    1. 按空行将歌词分段落
    2. 用 DP 最优匹配将 Whisper segments 分配到各段落
       (使时长比例与字符数比例最接近)
    3. 段落内用 segment 边界锚定句子
    4. 句子内按字符等比分配

    Returns:
        长度 = len(lyrics) 的列表，每个元素是 (start, end) 或 None
    """
    n_lines = len(lyrics)
    if not segments or not lyrics:
        return [None] * n_lines

    # --- 1. 按 paragraph 字段将歌词分组 ---
    paragraphs: list[list[int]] = []
    cur_para_id = lyrics[0].paragraph
    cur_group: list[int] = []
    for i, ly in enumerate(lyrics):
        if ly.paragraph != cur_para_id:
            if cur_group:
                paragraphs.append(cur_group)
            cur_group = []
            cur_para_id = ly.paragraph
        cur_group.append(i)
    if cur_group:
        paragraphs.append(cur_group)

    n_paras = len(paragraphs)
    n_segs = len(segments)

    def _voiced_count(text: str) -> int:
        return max(
            sum(1 for c in text if _CHINESE_CHAR_RE.match(c) or c.isalnum()),
            1,
        )

    line_chars = [_voiced_count(ly.text) for ly in lyrics]
    para_chars = [sum(line_chars[li] for li in p) for p in paragraphs]
    total_chars = sum(para_chars) or 1

    log.info("歌词分为 %d 个段落: %s (字符数: %s)",
             n_paras, [len(p) for p in paragraphs], para_chars)

    # --- 2. DP 最优匹配: segments → paragraphs ---
    # dp[i][j] = 将 segments[0:i] 分配给 paragraphs[0:j] 的最小代价
    # 代价 = sum of (实际时长比例 - 期望字符比例)²  - gap_bonus
    seg_starts = [s.get("start", 0.0) for s in segments]
    seg_ends = [s.get("end", 0.0) for s in segments]
    total_dur = seg_ends[-1] - seg_starts[0] if n_segs > 0 else 1.0

    INF = float("inf")
    dp = [[INF] * (n_paras + 1) for _ in range(n_segs + 1)]
    parent = [[0] * (n_paras + 1) for _ in range(n_segs + 1)]
    dp[0][0] = 0.0

    for j in range(1, n_paras + 1):
        expected = para_chars[j - 1] / total_chars
        for i in range(j, n_segs - (n_paras - j) + 1):
            # segments[k:i] → paragraph j-1
            for k in range(j - 1, i):
                grp_dur = seg_ends[i - 1] - seg_starts[k]
                actual = grp_dur / total_dur if total_dur > 0 else 0
                cost = (actual - expected) ** 2

                # 加分: 在大间隙处分割 (鼓励在静音处断开)
                gap_bonus = 0.0
                if k > 0:
                    gap = seg_starts[k] - seg_ends[k - 1]
                    gap_bonus = -gap * 0.01  # 间隙越大越好

                total_cost = dp[k][j - 1] + cost + gap_bonus
                if total_cost < dp[i][j]:
                    dp[i][j] = total_cost
                    parent[i][j] = k

    # --- 3. 回溯: 得到每个段落对应哪些 segments ---
    assignments: list[tuple[int, int]] = []  # [(seg_from, seg_to), ...]
    i, j = n_segs, n_paras
    while j > 0:
        k = parent[i][j]
        assignments.append((k, i))  # segments[k:i]
        i, j = k, j - 1
    assignments.reverse()

    log.info("DP 段落↔segments 匹配: %s",
             [(f"P{pi+1}({len(paragraphs[pi])}行)",
               f"S{a[0]+1}~S{a[1]}",
               f"{seg_starts[a[0]]:.1f}~{seg_ends[a[1]-1]:.1f}")
              for pi, a in enumerate(assignments)])

    # --- 4. 段落内用 segment 边界锚定句子 ---
    result: list[tuple[float, float] | None] = [None] * n_lines

    for pi, (sf, st) in enumerate(assignments):
        seg_group = segments[sf:st]
        if not seg_group:
            continue
        _distribute_lines_with_segments(
            result, paragraphs[pi], line_chars, lyrics, seg_group)

    # 兜底: 未分配的行
    for i in range(n_lines):
        if result[i] is None:
            if i > 0 and result[i - 1] is not None:
                prev_end = result[i - 1][1]
                result[i] = (prev_end, prev_end + 3.0)
            else:
                result[i] = (0.0, 3.0)

    return result


def _distribute_lines_with_segments(
    result: list[tuple[float, float] | None],
    line_indices: list[int],
    line_chars: list[int],
    lyrics: list["LyricLine"],
    seg_group: list[dict],
) -> None:
    """
    在一个段落内，用 Whisper segments 锚定每行歌词的时间。

    策略:
    1. 如果 segment 数 == 行数 → 1:1 直接用 segment 的 start/end
    2. 如果 segment 数 > 行数  → 合并相邻 segments 给同一行
    3. 如果 segment 数 < 行数  → 按字符比例拆分 segment 给多行
    4. 最后确保相邻行首尾衔接 (end_i == start_{i+1})
    """
    n_lines = len(line_indices)
    if n_lines == 0 or not seg_group:
        return

    n_segs = len(seg_group)
    grp_start = seg_group[0].get("start", 0.0)
    grp_end = seg_group[-1].get("end", grp_start + 1.0)

    if n_segs == n_lines:
        # --- 完美匹配: 1:1 ---
        for li, seg in zip(line_indices, seg_group):
            s = seg.get("start", grp_start)
            e = seg.get("end", s + 1.0)
            result[li] = (round(s, 3), round(e, 3))

    elif n_segs > n_lines:
        # --- segments 多于行: 合并 ---
        # 按比例把 n_segs 个 segment 分给 n_lines 行
        # 用浮点均分确定每行分得多少个 segment
        assignments: list[tuple[int, int]] = []  # (seg_from, seg_to) inclusive
        for i in range(n_lines):
            seg_from = round(i * n_segs / n_lines)
            seg_to = round((i + 1) * n_segs / n_lines) - 1
            seg_to = max(seg_to, seg_from)
            assignments.append((seg_from, seg_to))

        for i, li in enumerate(line_indices):
            sf, st = assignments[i]
            s = seg_group[sf].get("start", grp_start)
            e = seg_group[st].get("end", s + 1.0)
            result[li] = (round(s, 3), round(e, 3))

    else:
        # --- segments 少于行: 拆分 ---
        # 先将 segments 映射到行，每个 segment 可覆盖多行
        # 按字符数比例决定每个 segment 覆盖哪些行
        seg_durations = [
            seg.get("end", 0) - seg.get("start", 0)
            for seg in seg_group
        ]
        total_seg_dur = sum(seg_durations) or 1.0

        # 按时长比例给每个 segment 分配字符预算
        total_chars = sum(line_chars[li] for li in line_indices) or 1
        li_cursor = 0
        chars_used = 0

        for si, seg in enumerate(seg_group):
            s = seg.get("start", grp_start)
            e = seg.get("end", s + 1.0)
            seg_dur = e - s

            if si < n_segs - 1:
                budget = round(total_chars * seg_dur / total_seg_dur)
            else:
                budget = total_chars - chars_used

            # 贪心分行到这个 segment
            sub_lines: list[int] = []
            sub_chars_sum = 0
            while li_cursor < n_lines:
                li = line_indices[li_cursor]
                lc = line_chars[li]
                sub_lines.append(li)
                sub_chars_sum += lc
                li_cursor += 1
                if sub_chars_sum >= budget and li_cursor < n_lines:
                    break

            chars_used += sub_chars_sum

            # segment 内按字符均分
            if sub_lines:
                _distribute_lines_in_range(
                    result, sub_lines, line_chars, s, e)

    # --- 消除行间间隙: 让相邻行首尾衔接 ---
    _close_line_gaps(result, line_indices)


def _distribute_lines_in_range(
    result: list[tuple[float, float] | None],
    line_indices: list[int],
    line_chars: list[int],
    start: float,
    end: float,
) -> None:
    """将一个时间范围按字符数比例分配给多行"""
    total = sum(line_chars[i] for i in line_indices) or 1
    dur = end - start
    cursor = start
    for li in line_indices:
        line_dur = dur * line_chars[li] / total
        result[li] = (round(cursor, 3), round(cursor + line_dur, 3))
        cursor += line_dur


def _close_line_gaps(
    result: list[tuple[float, float] | None],
    line_indices: list[int],
) -> None:
    """
    消除段落内相邻行之间的小间隙。
    将间隙时间平均分给前后两行（后行提前，前行延后各一半）。
    """
    for i in range(len(line_indices) - 1):
        curr_li = line_indices[i]
        next_li = line_indices[i + 1]
        if result[curr_li] is None or result[next_li] is None:
            continue
        curr_end = result[curr_li][1]
        next_start = result[next_li][0]
        gap = next_start - curr_end
        if gap > 0.01:
            mid = curr_end + gap / 2
            result[curr_li] = (result[curr_li][0], round(mid, 3))
            result[next_li] = (round(mid, 3), result[next_li][1])


def _split_line_to_words(
    text: str,
    start: float,
    end: float,
) -> list[WordTimestamp]:
    """
    将一行歌词按字符等比分配时间戳。

    - 有发音的字符 (中文/字母/数字) 均分整行时长
    - 标点符号零时长，继承前一个发音字符的 end
    """
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return []

    voiced_chars = [c for c in chars if _CHINESE_CHAR_RE.match(c) or c.isalnum()]
    n_voiced = len(voiced_chars)

    if n_voiced == 0:
        # 全标点行: 均分
        duration = end - start
        char_dur = duration / len(chars)
        return [
            WordTimestamp(
                word=c,
                start=round(start + i * char_dur, 3),
                end=round(start + (i + 1) * char_dur, 3),
            )
            for i, c in enumerate(chars)
        ]

    duration = end - start
    voiced_dur = duration / n_voiced

    words: list[WordTimestamp] = []
    voiced_idx = 0

    for c in chars:
        is_voiced = bool(_CHINESE_CHAR_RE.match(c)) or c.isalnum()
        if is_voiced:
            c_start = start + voiced_idx * voiced_dur
            c_end = c_start + voiced_dur
            words.append(WordTimestamp(
                word=c,
                start=round(c_start, 3),
                end=round(c_end, 3),
            ))
            voiced_idx += 1
        else:
            # 标点: 零时长
            t = words[-1].end if words else start
            words.append(WordTimestamp(word=c, start=t, end=t))

    return words


# ---------------------------------------------------------------------------
# 辅助: 将原始歌词注入 Whisper 转写结果 (旧策略, 保留供参考)
# ---------------------------------------------------------------------------

def _inject_lyrics_into_segments(
    transcribe_result: dict,
    lyrics: list[LyricLine],
) -> dict:
    """
    用原始歌词文本替换 Whisper 的自由转写文本，
    保留 Whisper 给出的 segment 时间范围。
    这样 align() 就会按正确的歌词做 forced alignment。
    """
    segments = transcribe_result.get("segments", [])

    if len(segments) == 0:
        # 如果 Whisper 没有输出 segment，手动构造
        log.warning("Whisper 未返回 segment，使用歌词手动构造")
        new_segments = []
        for i, lyric in enumerate(lyrics):
            new_segments.append({
                "text": lyric.text,
                "start": lyric.timestamp if lyric.timestamp is not None else i * 5.0,
                "end": (lyric.timestamp + 5.0) if lyric.timestamp is not None else (i + 1) * 5.0,
            })
        transcribe_result["segments"] = new_segments
        return transcribe_result

    # 将歌词按顺序分配给 segments
    # 策略: 如果 segment 数 != 歌词行数，尝试最佳匹配
    if len(segments) >= len(lyrics):
        # segments 多于歌词行 → 合并多余 segments
        for i, lyric in enumerate(lyrics):
            if i < len(segments):
                segments[i]["text"] = lyric.text
        transcribe_result["segments"] = segments[:len(lyrics)]
    else:
        # segments 少于歌词行 → 基于时间均分
        new_segments = []
        if segments:
            total_start = segments[0].get("start", 0.0)
            total_end = segments[-1].get("end", total_start + len(lyrics) * 5.0)
        else:
            total_start = 0.0
            total_end = len(lyrics) * 5.0

        duration_per_line = (total_end - total_start) / len(lyrics)
        for i, lyric in enumerate(lyrics):
            new_segments.append({
                "text": lyric.text,
                "start": total_start + i * duration_per_line,
                "end": total_start + (i + 1) * duration_per_line,
            })
        transcribe_result["segments"] = new_segments

    return transcribe_result


# ---------------------------------------------------------------------------
# 辅助: 解析 WhisperX 对齐输出
# ---------------------------------------------------------------------------

def _parse_alignment_result(
    align_result: dict,
    lyrics: list[LyricLine],
) -> list[AlignedLine]:
    """将 WhisperX align() 的输出转为 AlignedLine 列表"""
    segments = align_result.get("segments", [])
    aligned_lines: list[AlignedLine] = []

    for i, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start + 1.0)

        # 获取词级时间戳
        word_segments = seg.get("words", [])

        if word_segments:
            words = []
            for ws in word_segments:
                w = ws.get("word", "").strip()
                if not w:
                    continue
                w_start = ws.get("start")
                w_end = ws.get("end")
                # 某些词可能缺少时间戳
                if w_start is None or w_end is None:
                    continue
                words.append(WordTimestamp(word=w, start=w_start, end=w_end))

            if words:
                aligned_lines.append(AlignedLine(
                    text=text,
                    start=words[0].start,
                    end=words[-1].end,
                    words=words,
                ))
                continue

        # Fallback: 对齐失败 → 均分时长给每个字符
        log.warning("第 %d 行对齐失败，使用均分 fallback: '%s'", i + 1, text[:20])
        fallback_words = _fallback_even_split(text, seg_start, seg_end)
        if fallback_words:
            aligned_lines.append(AlignedLine(
                text=text,
                start=seg_start,
                end=seg_end,
                words=fallback_words,
            ))

    return aligned_lines


def _fallback_even_split(
    text: str,
    start: float,
    end: float,
) -> list[WordTimestamp]:
    """将一行文本按字符均分时长（fallback 策略）"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return []

    duration = end - start
    char_duration = duration / len(chars)
    words = []
    for i, char in enumerate(chars):
        words.append(WordTimestamp(
            word=char,
            start=round(start + i * char_duration, 3),
            end=round(start + (i + 1) * char_duration, 3),
        ))
    return words


# ---------------------------------------------------------------------------
# 中文 → 拼音双向映射管线
# ---------------------------------------------------------------------------

_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_PUNCT_RE = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9]")


@dataclass
class CharToken:
    """歌词中的单个字符 token，标记其类型和拼音"""
    char: str
    pinyin: str          # VOICED: 拼音音节; PUNCT: ""
    voiced: bool         # True=有发音的字, False=标点/符号
    index: int           # 在原始行（去空格后）中的位置


def _tokenize_line(text: str) -> list[CharToken]:
    """
    将一行中文歌词拆分为 CharToken 序列。

    - 中文字 → VOICED, 词语级拼音消歧 (Style.NORMAL, 无声调)
    - 字母/数字 → VOICED, pinyin = 自身小写
    - 标点符号 → PUNCT, pinyin = ""
    - 空格跳过

    注意: pypinyin 对连续标点（如 "..."）会合并为一个 token，
    所以必须先分离标点，只把中文/字母序列传给 pypinyin。
    """
    from pypinyin import pinyin, Style

    chars = [c for c in text if not c.isspace()]
    if not chars:
        return []

    tokens: list[CharToken] = []

    # 先收集连续的中文字符段，批量转拼音（保留词语级消歧）
    # 然后逐字符组装 token
    # 策略: 先识别每个字符的类型，中文段批量转拼音
    segments: list[tuple[str, list[int]]] = []  # (type, char_indices)
    current_type = ""
    current_indices: list[int] = []

    for idx, ch in enumerate(chars):
        if _CHINESE_CHAR_RE.match(ch):
            ch_type = "zh"
        elif ch.isalnum():
            ch_type = "alnum"
        else:
            ch_type = "punct"

        if ch_type != current_type and current_indices:
            segments.append((current_type, list(current_indices)))
            current_indices = []
        current_type = ch_type
        current_indices.append(idx)

    if current_indices:
        segments.append((current_type, list(current_indices)))

    # 为中文段批量获取拼音
    pinyin_cache: dict[int, str] = {}
    for seg_type, indices in segments:
        if seg_type == "zh":
            zh_chars = [chars[i] for i in indices]
            # 词语级批量转拼音，保留上下文消歧
            py_results = pinyin(zh_chars, style=Style.NORMAL, heteronym=False)
            for i, py_list in zip(indices, py_results):
                pinyin_cache[i] = py_list[0]

    # 逐字符组装 token
    for idx, ch in enumerate(chars):
        if _CHINESE_CHAR_RE.match(ch):
            tokens.append(CharToken(
                char=ch, pinyin=pinyin_cache.get(idx, ch),
                voiced=True, index=idx,
            ))
        elif ch.isalnum():
            tokens.append(CharToken(
                char=ch, pinyin=ch.lower(),
                voiced=True, index=idx,
            ))
        else:
            tokens.append(CharToken(
                char=ch, pinyin="",
                voiced=False, index=idx,
            ))

    return tokens


def _inject_lyrics_pinyin(
    transcribe_result: dict,
    lyrics: list[LyricLine],
) -> tuple[dict, list[list[CharToken]]]:
    """
    拼音模式注入:
    1. 将每行歌词 tokenize 为 CharToken 序列
    2. 只取 VOICED tokens 的拼音组成空格分隔的文本注入 segment
    3. 返回完整 token 序列（含 PUNCT），用于后续映射回汉字
    """
    segments = transcribe_result.get("segments", [])
    token_map: list[list[CharToken]] = []

    def _make_pinyin_text(tokens: list[CharToken]) -> str:
        return " ".join(t.pinyin for t in tokens if t.voiced)

    if len(segments) == 0:
        log.warning("Whisper 未返回 segment，使用歌词手动构造")
        new_segments = []
        for i, lyric in enumerate(lyrics):
            tokens = _tokenize_line(lyric.text)
            token_map.append(tokens)
            new_segments.append({
                "text": _make_pinyin_text(tokens),
                "start": lyric.timestamp if lyric.timestamp is not None else i * 5.0,
                "end": (lyric.timestamp + 5.0) if lyric.timestamp is not None else (i + 1) * 5.0,
            })
        transcribe_result["segments"] = new_segments
        return transcribe_result, token_map

    if len(segments) >= len(lyrics):
        for i, lyric in enumerate(lyrics):
            tokens = _tokenize_line(lyric.text)
            token_map.append(tokens)
            if i < len(segments):
                segments[i]["text"] = _make_pinyin_text(tokens)
        transcribe_result["segments"] = segments[:len(lyrics)]
    else:
        new_segments = []
        total_start = segments[0].get("start", 0.0) if segments else 0.0
        total_end = segments[-1].get("end", total_start + len(lyrics) * 5.0) if segments else len(lyrics) * 5.0
        dur_per_line = (total_end - total_start) / len(lyrics)
        for i, lyric in enumerate(lyrics):
            tokens = _tokenize_line(lyric.text)
            token_map.append(tokens)
            new_segments.append({
                "text": _make_pinyin_text(tokens),
                "start": total_start + i * dur_per_line,
                "end": total_start + (i + 1) * dur_per_line,
            })
        transcribe_result["segments"] = new_segments

    return transcribe_result, token_map


# ---------------------------------------------------------------------------
# 拼音对齐结果 → 汉字时间戳 (带标点位点保留)
# ---------------------------------------------------------------------------

def _parse_pinyin_alignment(
    align_result: dict,
    lyrics: list[LyricLine],
    token_map: list[list[CharToken]],
) -> list[AlignedLine]:
    """
    核心映射逻辑:
    1. WhisperX 返回的 words 是拼音音节的时间戳
    2. 按顺序将拼音时间戳分配给 VOICED tokens
    3. PUNCT tokens 继承前一个 VOICED token 的 end 时间（零时长）
    4. 缺少时间戳的拼音用线性插值补全
    """
    segments = align_result.get("segments", [])
    aligned_lines: list[AlignedLine] = []

    for i, seg in enumerate(segments):
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start + 1.0)

        tokens = token_map[i] if i < len(token_map) else []
        original_text = lyrics[i].text if i < len(lyrics) else ""
        word_segments = seg.get("words", [])

        voiced_tokens = [t for t in tokens if t.voiced]
        n_voiced = len(voiced_tokens)

        if not voiced_tokens:
            continue

        # --- 收集 WhisperX 返回的拼音时间戳 ---
        # 分为有时间戳和缺时间戳两类
        raw_timestamps: list[tuple[str, float | None, float | None]] = []
        for ws in word_segments:
            w = ws.get("word", "").strip()
            if w:
                raw_timestamps.append((w, ws.get("start"), ws.get("end")))

        # --- 构建 VOICED token 的时间戳 ---
        voiced_times = _assign_pinyin_timestamps(
            raw_timestamps, n_voiced, seg_start, seg_end
        )

        if not voiced_times:
            log.warning("第 %d 行拼音时间戳为空，使用均分 fallback: '%s'",
                        i + 1, original_text[:20])
            fallback = _fallback_even_split(original_text, seg_start, seg_end)
            if fallback:
                aligned_lines.append(AlignedLine(
                    text=original_text, start=seg_start,
                    end=seg_end, words=fallback,
                ))
            continue

        # --- 将时间戳分配给全部 tokens (含 PUNCT) ---
        words = _merge_tokens_with_timestamps(tokens, voiced_times)

        if words:
            aligned_lines.append(AlignedLine(
                text=original_text,
                start=words[0].start,
                end=words[-1].end,
                words=words,
            ))
        else:
            fallback = _fallback_even_split(original_text, seg_start, seg_end)
            if fallback:
                aligned_lines.append(AlignedLine(
                    text=original_text, start=seg_start,
                    end=seg_end, words=fallback,
                ))

    return aligned_lines


def _assign_pinyin_timestamps(
    raw_timestamps: list[tuple[str, float | None, float | None]],
    n_voiced: int,
    seg_start: float,
    seg_end: float,
) -> list[tuple[float, float]]:
    """
    将 WhisperX 返回的（可能不完整的）拼音时间戳
    分配给 n_voiced 个发音字符。

    策略:
    - 有时间戳的拼音直接用
    - 缺时间戳的拼音用相邻锚点线性插值
    - 数量不匹配时，多余的截断，不足的用均分补全
    """
    # 提取有效锚点 (index_in_sequence, start, end)
    anchors: list[tuple[int, float, float]] = []
    for idx, (_, s, e) in enumerate(raw_timestamps):
        if s is not None and e is not None:
            anchors.append((idx, s, e))

    if not anchors:
        # 全部缺时间戳 → 整段均分
        dur = (seg_end - seg_start) / n_voiced
        return [
            (round(seg_start + j * dur, 3), round(seg_start + (j + 1) * dur, 3))
            for j in range(n_voiced)
        ]

    # 先构建完整的 len(raw_timestamps) 个时间戳（用插值填充缺失的）
    n_raw = len(raw_timestamps)
    filled: list[tuple[float, float]] = [(-1.0, -1.0)] * n_raw

    for seq_idx, s, e in anchors:
        if seq_idx < n_raw:
            filled[seq_idx] = (s, e)

    # 前向/后向插值填充
    filled = _interpolate_gaps(filled, seg_start, seg_end)

    # 映射到 n_voiced 个字符
    if len(filled) >= n_voiced:
        return filled[:n_voiced]
    else:
        # 不足：补全
        result = list(filled)
        last_end = filled[-1][1] if filled else seg_start
        remaining = n_voiced - len(result)
        rem_dur = max(seg_end - last_end, remaining * 0.08)
        d = rem_dur / remaining
        for k in range(remaining):
            result.append((
                round(last_end + k * d, 3),
                round(last_end + (k + 1) * d, 3),
            ))
        return result


def _interpolate_gaps(
    filled: list[tuple[float, float]],
    seg_start: float,
    seg_end: float,
) -> list[tuple[float, float]]:
    """线性插值填充缺失的时间戳（-1.0 标记的位置）"""
    n = len(filled)
    if n == 0:
        return []

    # 找到所有锚点的索引
    anchor_indices = [i for i in range(n) if filled[i][0] >= 0]

    if not anchor_indices:
        dur = (seg_end - seg_start) / n
        return [
            (round(seg_start + j * dur, 3), round(seg_start + (j + 1) * dur, 3))
            for j in range(n)
        ]

    result = list(filled)

    # 填充第一个锚点之前的空隙
    first_anchor = anchor_indices[0]
    if first_anchor > 0:
        anchor_start = result[first_anchor][0]
        gap_dur = (anchor_start - seg_start) / first_anchor
        for j in range(first_anchor):
            s = round(seg_start + j * gap_dur, 3)
            e = round(seg_start + (j + 1) * gap_dur, 3)
            result[j] = (s, e)

    # 填充最后一个锚点之后的空隙
    last_anchor = anchor_indices[-1]
    if last_anchor < n - 1:
        anchor_end = result[last_anchor][1]
        remaining = n - last_anchor - 1
        gap_dur = (seg_end - anchor_end) / remaining
        for j in range(remaining):
            idx = last_anchor + 1 + j
            s = round(anchor_end + j * gap_dur, 3)
            e = round(anchor_end + (j + 1) * gap_dur, 3)
            result[idx] = (s, e)

    # 填充锚点之间的空隙
    for ai in range(len(anchor_indices) - 1):
        left = anchor_indices[ai]
        right = anchor_indices[ai + 1]
        if right - left <= 1:
            continue
        left_end = result[left][1]
        right_start = result[right][0]
        gap_count = right - left - 1
        gap_dur = (right_start - left_end) / gap_count
        for j in range(gap_count):
            idx = left + 1 + j
            s = round(left_end + j * gap_dur, 3)
            e = round(left_end + (j + 1) * gap_dur, 3)
            result[idx] = (s, e)

    return result


def _merge_tokens_with_timestamps(
    tokens: list[CharToken],
    voiced_times: list[tuple[float, float]],
) -> list[WordTimestamp]:
    """
    将 VOICED 时间戳和 PUNCT tokens 合并为最终的 WordTimestamp 序列。

    规则:
    - VOICED token: 获得对应的 (start, end) 时间戳
    - PUNCT token: 继承前一个 VOICED token 的 end（零时长），
      这样标点在 ASS 渲染时不会吃掉时间
    """
    words: list[WordTimestamp] = []
    voiced_idx = 0

    for token in tokens:
        if token.voiced:
            if voiced_idx < len(voiced_times):
                s, e = voiced_times[voiced_idx]
                words.append(WordTimestamp(word=token.char, start=s, end=e))
                voiced_idx += 1
            # 超出时间戳数量的 voiced token 不应该出现，但兜底
        else:
            # PUNCT: 零时长，继承前一个字的 end
            if words:
                t = words[-1].end
            elif voiced_idx < len(voiced_times):
                t = voiced_times[voiced_idx][0]
            else:
                t = 0.0
            words.append(WordTimestamp(word=token.char, start=t, end=t))

    return words


# ---------------------------------------------------------------------------
# 后处理: 权重重分配 (从长字借时间，而非暴力位移)
# ---------------------------------------------------------------------------

def _postprocess_timing(
    lines: list[AlignedLine],
    config: AlignerConfig,
) -> list[AlignedLine]:
    """
    歌唱场景优化的后处理:

    1. 跳过零时长 token（标点），只处理 VOICED
    2. 过短字（< min_dur）: 从相邻最长的字"借"时间补偿
    3. 过长字（> max_dur）: 截断多余时间，均分给同行其他字
    4. 行尾静音检测: 如果末字 end 远超倒数第二字，截断到合理值
    5. 确保连续性: end_i == start_{i+1}
    """
    min_dur = config.min_char_duration
    max_dur = config.max_char_duration

    for line in lines:
        # 分离 voiced 和 punct
        voiced_indices = [
            j for j, w in enumerate(line.words)
            if w.end - w.start > 0  # 有时长 = voiced
        ]

        if len(voiced_indices) < 2:
            continue

        # --- Pass 1: 连续性 (voiced 之间) ---
        for vi in range(1, len(voiced_indices)):
            curr = voiced_indices[vi]
            prev = voiced_indices[vi - 1]
            line.words[curr].start = line.words[prev].end

        # --- Pass 2: 从长字借时间给过短字 ---
        for vi, j in enumerate(voiced_indices):
            dur = line.words[j].end - line.words[j].start
            if dur < min_dur:
                deficit = min_dur - dur
                # 找同行最长的 voiced 字借时间
                donor_vi = max(
                    range(len(voiced_indices)),
                    key=lambda x: (
                        line.words[voiced_indices[x]].end
                        - line.words[voiced_indices[x]].start
                    ),
                )
                donor_j = voiced_indices[donor_vi]
                donor_dur = line.words[donor_j].end - line.words[donor_j].start

                if donor_dur > min_dur + deficit and donor_j != j:
                    # 从 donor 的尾部借出 deficit
                    line.words[donor_j].end = round(
                        line.words[donor_j].end - deficit, 3
                    )
                    line.words[j].end = round(
                        line.words[j].start + min_dur, 3
                    )

        # --- Pass 3: 截断过长字 ---
        for j in voiced_indices:
            dur = line.words[j].end - line.words[j].start
            if dur > max_dur:
                excess = dur - max_dur
                line.words[j].end = round(line.words[j].start + max_dur, 3)
                # 将多余时间均分给同行其他 voiced 字
                other_voiced = [
                    vi for vi in voiced_indices if vi != j
                ]
                if other_voiced:
                    bonus = excess / len(other_voiced)
                    for ov in other_voiced:
                        line.words[ov].end = round(
                            line.words[ov].end + bonus, 3
                        )

        # --- Pass 4: 重建连续性 ---
        for vi in range(1, len(voiced_indices)):
            curr = voiced_indices[vi]
            prev = voiced_indices[vi - 1]
            line.words[curr].start = line.words[prev].end

        # --- Pass 5: 更新 PUNCT tokens 的时间戳 ---
        for j, w in enumerate(line.words):
            if w.end == w.start:  # punct
                # 找最近的前一个 voiced
                for k in range(j - 1, -1, -1):
                    if line.words[k].end != line.words[k].start:
                        w.start = line.words[k].end
                        w.end = line.words[k].end
                        break

        # 更新行的 start/end
        if line.words:
            line.start = line.words[0].start
            line.end = line.words[-1].end

    return lines
