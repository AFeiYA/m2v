"""
Stable-ts Alignment Engine Adapter.
Independent, side-by-side adapter that integrates stable-ts (stable_whisper)
into the suno2MV architecture, outputting native AlignmentResult objects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import stable_whisper

from src.storyboard_schema import AlignedLine, AlignmentResult, WordTimestamp

if TYPE_CHECKING:
    from src.preprocessor import LyricLine

log = logging.getLogger("m2v.stablets")

_CACHED_MODELS: dict[tuple[str, str], any] = {}


def get_stablets_model(model_name: str = "base", device: str = "cpu"):
    from src.aligner import is_safe_cuda_available

    if device == "cuda" and not is_safe_cuda_available():
        log.info("当前环境无物理 CUDA 或位于云端容器，stable-ts 自动采用 CPU 运行")
        device = "cpu"

    key = (model_name, device)
    if key not in _CACHED_MODELS:
        log.info("加载 stable-ts Whisper 模型: %s (device=%s)", model_name, device)
        try:
            _CACHED_MODELS[key] = stable_whisper.load_model(model_name, device=device)
        except Exception as err:
            if device != "cpu":
                log.warning("使用设备 %s 加载 Whisper 失败 (%s)，自动降级至 CPU 重试...", device, err)
                device = "cpu"
                key = (model_name, "cpu")
                if key not in _CACHED_MODELS:
                    _CACHED_MODELS[key] = stable_whisper.load_model(model_name, device="cpu")
            else:
                raise
    return _CACHED_MODELS[key]


def align_lyrics_stablets(
    vocals_path: Path | str,
    lyrics: list[LyricLine],
    language: str | None = None,
    model_name: str = "base",
    device: str = "cpu",
    refine: bool = False,
    nonspeech_skip: float | None = None,
    guard_interludes: bool = True,
) -> AlignmentResult:
    """使用 stable-ts 对整曲歌词执行直接声学对齐。

    Args:
        vocals_path: 人声音频文件路径
        lyrics: 预处理后的歌词列表
        language: 语言代码 ('en', 'zh', 或 None 自动检测)
        model_name: Whisper 模型名称 ('base', 'small', 'medium', 'large-v3')
        device: 推理设备 ('cpu' 或 'cuda')
        refine: 是否在对齐后运行 model.refine()
        nonspeech_skip: 非语音跳过阈值 (秒，默认 None 保持整块连续对齐，避免分块回滚时张量尺寸不一致)
        guard_interludes: 是否启用宏观间奏硬保护屏障 (默认 True)
    """
    if language in ("mixed", "auto", None):
        language = None

    try:
        model = get_stablets_model(model_name=model_name, device=device)

        if guard_interludes:
            from src.align.interlude_guard import align_with_interlude_guard

            return align_with_interlude_guard(
                vocals_path=vocals_path,
                lyrics=lyrics,
                model=model,
                language=language,
                nonspeech_skip=nonspeech_skip,
            )
    except Exception as exc:
        err_str = str(exc).lower()
        if device != "cpu" and any(k in err_str for k in ("cuda", "cublas", "cudnn", "zerogpu", "torch._c._cuda_init", "init")):
            log.warning("⚠️ stable-ts 在 %s 设备运行失败 (%s)，自动回退到 CPU 模式重试...", device, exc)
            return align_lyrics_stablets(
                vocals_path=vocals_path,
                lyrics=lyrics,
                language=language,
                model_name=model_name,
                device="cpu",
                refine=refine,
                nonspeech_skip=nonspeech_skip,
                guard_interludes=guard_interludes,
            )
        raise

    from src.align.cjk_disambiguation import prepare_line_for_alignment, reconcile_aligned_words

    lyrics_text = "\n".join(prepare_line_for_alignment(ly.text) for ly in lyrics)

    import re
    has_zh = bool(re.search(r"[\u4e00-\u9fff]", lyrics_text))
    if language in ("en", "zh", "ja", "ko"):
        lang_code = language
    elif has_zh:
        lang_code = "zh"
    else:
        lang_code = "en"

    align_opts = {
        "language": lang_code,
        "original_split": True,
    }
    if nonspeech_skip is not None:
        align_opts["nonspeech_skip"] = nonspeech_skip

    log.info("【stable-ts】启动歌词对齐: %s (%d 行, lang=%s)", Path(vocals_path).name, len(lyrics), lang_code)
    whisper_res = model.align(str(vocals_path), lyrics_text, **align_opts)

    if refine and whisper_res is not None:
        log.info("【stable-ts】运行注意力和声学边界 refine…")
        whisper_res = model.refine(str(vocals_path), whisper_res)

    segments = whisper_res.segments if whisper_res is not None else []

    aligned_lines: list[AlignedLine] = []
    for idx, ly in enumerate(lyrics):
        sec = getattr(ly, "section", "")
        if not sec and getattr(ly, "paragraph", 0):
            sec = f"Paragraph {ly.paragraph}"

        if idx < len(segments):
            seg = segments[idx]
            raw_words: list[WordTimestamp] = []
            if seg.words:
                for w in seg.words:
                    w_s = max(0.0, round(float(w.start), 3))
                    w_e = max(w_s, round(float(w.end), 3))
                    raw_words.append(WordTimestamp(word=str(w.word), start=w_s, end=w_e))
            if not raw_words:
                s_s = max(0.0, round(float(seg.start), 3))
                s_e = max(s_s, round(float(seg.end), 3))
                raw_words = [WordTimestamp(word=ly.text, start=s_s, end=s_e)]

            words = reconcile_aligned_words(target_text=ly.text, whisper_words=raw_words)
            l_start = words[0].start if words else max(0.0, round(float(seg.start), 3))
            l_end = max(l_start, words[-1].end if words else round(float(seg.end), 3))
            aligned_lines.append(
                AlignedLine(
                    text=ly.text,
                    start=l_start,
                    end=l_end,
                    words=words,
                    section=sec,
                )
            )
        else:
            # 兜底缺行
            prev_end = aligned_lines[-1].end if aligned_lines else 0.0
            aligned_lines.append(
                AlignedLine(
                    text=ly.text,
                    start=prev_end,
                    end=prev_end + 1.0,
                    words=[WordTimestamp(word=ly.text, start=prev_end, end=prev_end + 1.0)],
                    section=sec,
                )
            )

    return AlignmentResult(lines=aligned_lines)
