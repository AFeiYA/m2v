"""
Module 3: 词级对齐引擎
- WhisperX forced alignment 封装
- 支持 Forced Alignment（传入原歌词约束，避免自由转写）
- Fallback: 对齐失败的行按时长均分给每个字符
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, asdict, field
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
class StoryboardEvent:
    """背景素材/图片事件"""
    type: str          # "image" or "video"
    path: str          # 文件相对路径或绝对路径
    start: float       # 开始时间
    end: float         # 结束时间
    speed_align: bool = True


@dataclass
class AlignedLine:
    """一行对齐后的歌词"""
    text: str
    start: float
    end: float
    words: list[WordTimestamp]
    style_overrides: dict = field(default_factory=dict)


@dataclass
class AlignmentResult:
    """完整对齐结果"""
    lines: list[AlignedLine]
    storyboard: list[StoryboardEvent] = field(default_factory=list)
    background: str | None = None  # 默认背景图路径

    def to_dict(self) -> dict:
        d = {
            "lines": [asdict(line) for line in self.lines],
            "storyboard": [asdict(e) for e in self.storyboard]
        }
        if self.background:
            d["background"] = self.background
        return d

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
                style_overrides=line_data.get("style_overrides", {}),
            ))
        
        storyboard = []
        for e_data in data.get("storyboard", []):
            storyboard.append(StoryboardEvent(
                type=e_data["type"],
                path=e_data["path"],
                start=e_data["start"],
                end=e_data["end"],
                speed_align=e_data.get("speed_align", True)
            ))
        
        background = data.get("background", None)
            
        return cls(lines=lines, storyboard=storyboard, background=background)


# ---------------------------------------------------------------------------
# Whisper 初始化（共用逻辑）
# ---------------------------------------------------------------------------

_CPU_HEAVY_MODELS = {"large", "large-v1", "large-v2", "large-v3", "large-v3-turbo"}


def ensure_local_model(model_name: str) -> str:
    """
    如果是在国内网络环境，使用 requests 从镜像源手动下载模型文件到本地，
    以避免 huggingface_hub 各种 HEAD/metadata 握手故障。
    """
    import os
    import time
    from pathlib import Path
    
    # 仅针对特定的常用模型进行本地托管下载
    supported_models = {
        "tiny": {
            "repo": "Systran/faster-whisper-tiny",
            "files": ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
        },
        "base": {
            "repo": "Systran/faster-whisper-base",
            "files": ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
        },
        "small": {
            "repo": "Systran/faster-whisper-small",
            "files": ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
        },
        "medium": {
            "repo": "Systran/faster-whisper-medium",
            "files": ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
        },
        "large-v3": {
            "repo": "Systran/faster-whisper-large-v3",
            "files": ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
        },
        "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn": {
            "repo": "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
            "files": ["config.json", "vocab.json", "preprocessor_config.json", "special_tokens_map.json", "pytorch_model.bin"]
        }
    }
    
    if model_name not in supported_models:
        return model_name
        
    cache_dir = Path.home() / ".cache" / "m2v_local_models" / model_name.replace("/", "--")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    model_info = supported_models[model_name]
    repo = model_info["repo"]
    files = model_info["files"]
    
    log.info("检查本地模型缓存: %s...", model_name)
    
    # 检查是否所有文件都已完整下载
    all_exist = True
    for f in files:
        f_path = cache_dir / f
        if not f_path.exists() or f_path.stat().st_size == 0:
            all_exist = False
            break
            
    if all_exist:
        log.info("模型已本地缓存: %s", cache_dir)
        return str(cache_dir)
    # 执行手动极速下载
    try:
        import subprocess
        log.info("开始通过 curl 从 ModelScope 镜像源手动下载模型 %s 到本地缓存...", model_name)
        for f in files:
            dest_path = cache_dir / f
            if dest_path.exists() and dest_path.stat().st_size > 0:
                continue
                
            url = f"https://modelscope.cn/api/v1/models/{repo}/repo?Revision=master&FilePath={f}"
            log.info("下载中: %s -> %s", url, dest_path.name)
            
            temp_dest = dest_path.with_suffix(".tmp")
            
            # 使用 curl -L 进行下载。设置低速限制：如果速度低于 1000B/s 持续 10 秒则超时并重试。
            cmd = [
                "curl", "-L",
                "-y", "10", "-Y", "1000",
                "--connect-timeout", "30",
                "--retry", "5",
                "--retry-delay", "2",
                "-o", str(temp_dest),
                url
            ]
            
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            
            temp_dest.rename(dest_path)
            log.info("下载完成: %s", f)
            
        log.info("模型 %s 全部分流下载成功，已加载自: %s", model_name, cache_dir)
        return str(cache_dir)
    except Exception as e:
        log.warning("手动下载本地缓存模型失败，回退到 huggingface_hub 原生加载: %s", e)
        # 清理可能下载了一半的文件
        for f in files:
            f_path = cache_dir / f
            if f_path.exists():
                try:
                    f_path.unlink()
                except Exception:
                    pass
        return model_name


def _init_whisper(config: AlignerConfig, vocals_path: Path):
    """
    共用的 Whisper 初始化:
    - 导入 whisperx
    - 设备检测 + CPU 回退
    - 大模型自动降级
    - 模型加载（带缓存修复）
    - 音频加载 + 转写

    返回: (whisperx, audio, transcribe_result, device, compute_type, whisper_model)
    """
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

    compute_type = "int8" if device == "cpu" else config.compute_type

    whisper_model = config.whisper_model
    if device == "cpu" and whisper_model in _CPU_HEAVY_MODELS:
        whisper_model = "medium"
        log.warning(
            "CPU 模式下 %s 会极慢，已自动降级为 medium。"
            " 如需指定模型请在 pipeline.toml [aligner] whisper_model 中设置。",
            config.whisper_model,
        )

    whisper_model_path = ensure_local_model(whisper_model)
    log.info("加载 Whisper 模型: %s (path=%s, device=%s, compute=%s)",
             whisper_model, whisper_model_path, device, compute_type)
    model = _load_whisper_model_with_recovery(
        whisperx=whisperx,
        whisper_model=whisper_model_path,
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

    return whisperx, audio, transcribe_result, device, compute_type, whisper_model


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

    whisperx, audio, transcribe_result, device, compute_type, whisper_model = \
        _init_whisper(config, vocals_path)

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

    # 确定实际使用的语言（Whisper 自动检测后取回）
    detected_language: str = (
        transcribe_result.get("language")
        or config.language
        or "zh"
    )
    log.info("对齐语言: %s", detected_language)

    # 确定对齐模型使用的设备，在 Mac 上可使用 PyTorch mps 硬件加速
    align_device = device
    if device == "cpu":
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                align_device = "mps"
                log.info("检测到 Mac Apple Silicon GPU (MPS)，对齐模型 (Wav2Vec2) 将在 GPU (MPS) 上运行加速")
        except Exception:
            pass

    align_model = config.align_model
    if align_model is None and detected_language == "zh":
        align_model = "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"

    align_model_name = ensure_local_model(align_model) if align_model else None
    log.info("加载对齐模型 (language=%s, device=%s, path=%s)…", detected_language, align_device, align_model_name)
    align_model, align_metadata = whisperx.load_align_model(
        language_code=detected_language,
        device=align_device,
        model_name=align_model_name,
    )
    _debug_path = vocals_path.parent / (vocals_path.stem + "_whisper_segments.json")
    try:
        import json as _json
        with open(_debug_path, "w", encoding="utf-8") as _f:
            _json.dump(segments, _f, ensure_ascii=False, indent=2)
        log.info("Whisper segments 已保存: %s (%d 条)", _debug_path.name, len(segments))
    except Exception:
        pass

    log.info("执行字符级对齐…")
    align_result = whisperx.align(
        transcribe_result["segments"],
        align_model,
        align_metadata,
        audio,
        device=align_device,
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

    # 后处理: 修复连续极短字符 (wav2vec2 对长音后的字符压缩 bug)
    timeline = _fix_compressed_chars(timeline)
    log.info("后处理完成: %d 个字符", len(timeline))

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

    # -----------------------------------------------------------------------
    # Step 5: 审计时间戳单调性，检测并修正副歌重复导致的回退
    # -----------------------------------------------------------------------
    aligned_lines = _audit_alignment(aligned_lines)

    result = AlignmentResult(lines=aligned_lines)
    log.info("对齐完成: %d 行, %d 个词",
             len(result.lines),
             sum(len(line.words) for line in result.lines))
    return result


def transcribe_audio(
    vocals_path: Path,
    config: "AlignerConfig | None" = None,
) -> tuple[list["LyricLine"], str]:
    """
    用 Whisper 转写音频，自动检测语言，返回 (歌词行列表, 检测到的语言代码)。

    歌词行直接来自 Whisper 的 segment 文本，每个 segment 一行。
    可将结果直接传入 align_lyrics()，避免手动提供歌词文件。
    """
    from src.preprocessor import LyricLine

    if config is None:
        config = AlignerConfig()

    _, _, transcribe_result, _, _, _ = _init_whisper(config, vocals_path)

    detected_lang: str = (
        transcribe_result.get("language")
        or config.language
        or "zh"
    )
    log.info("检测到语言: %s", detected_lang)

    segments = transcribe_result.get("segments", [])
    if config.lyrics_start_time > 0:
        segments = [s for s in segments if s.get("end", 0) > config.lyrics_start_time]

    lines: list[LyricLine] = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if text:
            lines.append(LyricLine(text=text))

    log.info("转写完成: %d 行, 语言=%s", len(lines), detected_lang)
    return lines, detected_lang


def _load_whisper_model_with_recovery(
    whisperx,
    whisper_model: str,
    device: str,
    compute_type: str,
    language: str,
):
    """
    加载 Whisper 模型；若检测到损坏缓存（缺失 model.bin），
    清理对应快照目录后自动重试一次。
    """
    load_kwargs = {
        "device": device,
        "compute_type": compute_type,
        "language": language,
    }

    try:
        return whisperx.load_model(whisper_model, **load_kwargs)
    except RuntimeError as e:
        broken_model_dir = _extract_broken_model_dir(str(e))
        if not broken_model_dir:
            raise

        broken_path = Path(broken_model_dir)
        log.warning("检测到损坏模型缓存: %s", broken_path)
        if broken_path.exists():
            shutil.rmtree(broken_path, ignore_errors=True)
            log.warning("已清理损坏缓存，准备重新下载并重试…")

        return whisperx.load_model(whisper_model, **load_kwargs)


def _extract_broken_model_dir(error_text: str) -> str | None:
    match = re.search(r"Unable to open file 'model\.bin' in model '([^']+)'", error_text)
    if match:
        return match.group(1)
    return None


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
# 后处理: 修复 wav2vec2 字符压缩 bug
# ---------------------------------------------------------------------------

def _fix_compressed_chars(
    timeline: list[tuple[str, float, float]],
    min_char_ms: float = 50,   # 低于此毫秒视为异常短
    min_run: int = 3,          # 至少连续 N 个短字符才触发修复
) -> list[tuple[str, float, float]]:
    """
    检测并修复 wav2vec2 的"长音后压缩"bug。

    症状: 一个字拖很长音 (如 "人" 占 7s)，后面的字全挤在 <1s 内，
          每个字只有 20ms。

    修复策略:
    1. 扫描 timeline，找连续 duration < min_char_ms 的 run
    2. 找到该 run 的可用时间范围:
       - start = run 前一个正常字符的 end（如果前字过长则借时间）
       - end   = run 后第一个正常字符的 start (或下一个大间隙)
    3. 在这个范围内均匀重分配这些字符
    """
    if len(timeline) < 2:
        return timeline

    result = list(timeline)
    n = len(result)
    min_dur = min_char_ms / 1000.0

    i = 0
    fixes = 0
    while i < n:
        # 找连续短字符 run
        if (result[i][2] - result[i][1]) < min_dur:
            run_start = i
            while i < n and (result[i][2] - result[i][1]) < min_dur:
                i += 1
            run_end = i  # exclusive
            run_len = run_end - run_start

            if run_len >= min_run:
                # 确定可用时间范围
                # 向前: 从前一个字符借时间（截短它的尾巴）
                if run_start > 0:
                    prev_char = result[run_start - 1]
                    prev_dur = prev_char[2] - prev_char[1]
                    # 如果前一个字很长 (>2s)，从它借 40%
                    if prev_dur > 2.0:
                        borrow = prev_dur * 0.4
                        avail_start = prev_char[2] - borrow
                        result[run_start - 1] = (
                            prev_char[0], prev_char[1],
                            round(avail_start, 3),
                        )
                    else:
                        avail_start = prev_char[2]
                else:
                    avail_start = result[run_start][1]

                # 向后: 到下一个正常字符的 start，或利用大间隙
                if run_end < n:
                    next_start = result[run_end][1]
                    gap = next_start - result[run_end - 1][2]
                    if gap > 2.0:
                        # 有大间隙 → 用间隙的前半部分
                        avail_end = result[run_end - 1][2] + gap * 0.5
                    else:
                        avail_end = next_start
                else:
                    # 最后一批 → 给每个字至少 0.5s
                    avail_end = avail_start + run_len * 0.5

                # 重新均匀分配
                total_dur = avail_end - avail_start
                if total_dur > run_len * min_dur:  # 确保有足够空间
                    char_dur = total_dur / run_len
                    for j in range(run_len):
                        idx = run_start + j
                        s = avail_start + j * char_dur
                        e = s + char_dur
                        result[idx] = (result[idx][0], round(s, 3), round(e, 3))
                    fixes += 1
                    log.info("修复压缩序列: %d 字 @ %.1fs~%.1fs (每字 %.0fms → %.0fms)",
                             run_len, avail_start, avail_end,
                             min_dur * 1000,
                             char_dur * 1000)
        else:
            i += 1

    if fixes:
        log.info("共修复 %d 处压缩序列", fixes)

    return result


def _audit_alignment(aligned: list[AlignedLine]) -> list[AlignedLine]:
    """
    审计对齐结果的时间戳单调性。

    症状: 某行的 start 比前一行的 end 小 0.5s 以上，
            通常意味着该行被匹配到了音频的较早位置（副歌重复错位）。

    修正策略:
    - 找到回退块（连续时间戳 < 前行 end 的行组）
    - 整体向后平移，使其第一行 start 紧接在前一个正常行的 end 之后
    - 修正基于估算，建议在编辑器中人工复核
    """
    if len(aligned) < 2:
        return aligned

    # --- 检测回退点 ---
    regression_indices: list[int] = []
    for i in range(1, len(aligned)):
        if aligned[i].start < aligned[i - 1].end - 0.5:
            regression_indices.append(i)

    if not regression_indices:
        return aligned

    log.warning("对齐审计: 检测到 %d 处时间轴回退（可能是副歌重复导致的错位）", len(regression_indices))
    for i in regression_indices:
        log.warning(
            "  第%d行 '%s…': start=%.2fs < 前行 end=%.2fs (倒退 %.2fs)",
            i + 1, aligned[i].text[:12],
            aligned[i].start, aligned[i - 1].end,
            aligned[i - 1].end - aligned[i].start,
        )

    # --- 逐块修正 ---
    working = list(aligned)   # 副本
    corrected_count = 0

    # 将连续回退行合并为块
    blocks: list[tuple[int, int]] = []   # [(block_start_idx, block_end_idx), ...]
    i = 0
    while i < len(regression_indices):
        blk_start = regression_indices[i]
        # 找到这个回退块的结束位置: 第一个时间已经 >= 前一正常行 end 的行
        anchor_end = working[blk_start - 1].end
        blk_end = blk_start
        while blk_end < len(working) and working[blk_end].start < anchor_end - 0.1:
            blk_end += 1
        blocks.append((blk_start, blk_end))
        # 跳过已纳入块的所有回退点
        while i < len(regression_indices) and regression_indices[i] < blk_end:
            i += 1

    for blk_start, blk_end in blocks:
        anchor_end = working[blk_start - 1].end
        old_start = working[blk_start].start
        offset = anchor_end + 0.1 - old_start

        log.warning(
            "  修正第%d~%d行: 平移 +%.2fs（估算，建议在编辑器中复核）",
            blk_start + 1, blk_end, offset,
        )

        for j in range(blk_start, blk_end):
            ln = working[j]
            new_words = [
                WordTimestamp(w.word, round(w.start + offset, 3), round(w.end + offset, 3))
                for w in ln.words
            ]
            working[j] = AlignedLine(
                text=ln.text,
                start=round(ln.start + offset, 3),
                end=round(ln.end + offset, 3),
                words=new_words,
            )
        corrected_count += 1

    log.warning(
        "对齐审计: 已自动尝试修正 %d 处回退（修正均基于估算，延迟可能不准）",
        corrected_count,
    )
    return working


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
        if ly.is_annotation:
            continue
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
    lci = 0  # lyrics_chars 的游标游走于所有正常歌词字符

    for li, ly in enumerate(lyrics):
        if ly.is_annotation:
            # 编曲说明行：先占位，稍后回填时间
            aligned_lines.append(AlignedLine(
                text=ly.text,
                start=0.0,
                end=0.0,
                words=[WordTimestamp(word=ly.text, start=0.0, end=0.0)]
            ))
            continue

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
                    prev_end = words[-1].end if words else (aligned_lines[-1].end if aligned_lines else 0.0)
                    words.append(WordTimestamp(word=ch, start=prev_end, end=prev_end + 0.3))
            else:
                prev_end = words[-1].end if words else (aligned_lines[-1].end if aligned_lines else 0.0)
                words.append(WordTimestamp(word=ch, start=prev_end, end=prev_end))

        if words:
            aligned_lines.append(AlignedLine(
                text=ly.text,
                start=words[0].start,
                end=words[-1].end,
                words=words,
            ))

    # --- 为编曲说明分配空隙时间 (支持多行平分) ---
    i = 0
    while i < len(aligned_lines):
        al = aligned_lines[i]
        # 判断是否为待处理的编曲说明行
        if len(al.words) == 1 and al.words[0].word == al.text and al.start == 0 and al.end == 0:
            # 找到连续的编曲说明块
            block_start = i
            while i < len(aligned_lines):
                curr = aligned_lines[i]
                if not (len(curr.words) == 1 and curr.words[0].word == curr.text and curr.start == 0 and curr.end == 0):
                    break
                i += 1
            block_end = i  # 不包含
            block_count = block_end - block_start

            # 确定块的前后锚点
            anchor_start = aligned_lines[block_start - 1].end if block_start > 0 else 0.0
            anchor_end = aligned_lines[block_end].start if block_end < len(aligned_lines) else anchor_start + 5.0
            total_gap = anchor_end - anchor_start

            # 确定块的前后锚点 (绝对界限)
            anchor_start = aligned_lines[block_start - 1].end if block_start > 0 else 0.0
            anchor_end = aligned_lines[block_end].start if block_end < len(aligned_lines) else anchor_start + 5.0
            total_gap = max(0.0, anchor_end - anchor_start)

            # 设定理想参数
            PREF_DUR = 3.0  # 每行最大持续时间 3秒

            if block_start == 0:
                # 情况 A: 前奏块 -> 从 0 开始往后排，但不超过第一句歌词
                dur = min(total_gap / block_count, PREF_DUR)
                for j in range(block_count):
                    idx = block_start + j
                    target = aligned_lines[idx]
                    target.start = round(j * dur, 3)
                    target.end = round((j + 1) * dur, 3)
                    target.words[0].start, target.words[0].end = target.start, target.end
            else:
                # 情况 B: 中间或结尾块 -> 靠后对齐 (下一句开唱前)，绝不越界
                actual_dur = min(total_gap / block_count, PREF_DUR)
                # 整个块贴着 anchor_end 往前排
                block_real_start = anchor_end - (actual_dur * block_count)
                
                for j in range(block_count):
                    idx = block_start + j
                    target = aligned_lines[idx]
                    s = block_real_start + j * actual_dur
                    e = s + actual_dur
                    target.start, target.end = round(s, 3), round(e, 3)
                    target.words[0].start, target.words[0].end = target.start, target.end
        else:
            i += 1

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


# _fix_punct_durations 已移除: 标点符号始终保持零时长 (start == end)


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


# ---------------------------------------------------------------------------
# 局部重对齐
# ---------------------------------------------------------------------------

def realign_lines(
    vocals_path: Path,
    texts: list[str],
    rough_start: float,
    rough_end: float,
    config: AlignerConfig | None = None,
    buffer: float = 2.0,
) -> list[AlignedLine]:
    """
    对指定时间段内的几行歌词进行局部重对齐。

    流程:
    1. 从 vocals_path 裁剪 [rough_start-buffer, rough_end+buffer] 的音频片段
    2. 对该片段跑 WhisperX（转写 + 强制对齐）
    3. 所有时间戳加回 clip_start 偏移量
    4. 返回新的 AlignedLine 列表（长度 == len(texts)）

    Args:
        vocals_path:  人声 WAV 文件路径
        texts:        要重对齐的歌词行文本列表（纯显示文本）
        rough_start:  大致起始时间（秒），用于裁剪音频
        rough_end:    大致结束时间（秒）
        config:       对齐配置，None 则使用默认值
        buffer:       音频片段前后各加多少秒的缓冲
    Returns:
        list[AlignedLine]，时间戳已换算回原始音频坐标系
    """
    import tempfile
    import soundfile as sf
    import numpy as np

    if config is None:
        config = AlignerConfig()

    # --- 裁剪音频 ---
    clip_start = max(0.0, rough_start - buffer)
    clip_end = rough_end + buffer

    log.info("局部重对齐: %.2fs ~ %.2fs (片段 %.2fs ~ %.2fs, buffer=%.1fs)",
             rough_start, rough_end, clip_start, clip_end, buffer)

    audio_data, sample_rate = sf.read(str(vocals_path), dtype="float32", always_2d=False)
    start_sample = int(clip_start * sample_rate)
    end_sample = int(clip_end * sample_rate)
    end_sample = min(end_sample, len(audio_data))
    clip = audio_data[start_sample:end_sample]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    sf.write(str(tmp_path), clip, sample_rate)

    try:
        # 局部重对齐时不需要过滤前奏
        local_config = AlignerConfig(
            whisper_model=config.whisper_model,
            device=config.device,
            compute_type=config.compute_type,
            batch_size=config.batch_size,
            language=config.language,
            use_pinyin=config.use_pinyin,
            lyrics_start_time=0.0,  # 片段从 0 开始，不过滤
            min_char_duration=config.min_char_duration,
            max_char_duration=config.max_char_duration,
        )
        lyrics = [LyricLine(text=t) for t in texts]
        local_result = align_lyrics(tmp_path, lyrics, local_config)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass

    # --- 时间戳加回 clip_start 偏移 ---
    shifted: list[AlignedLine] = []
    for line in local_result.lines:
        new_words = [
            WordTimestamp(
                word=w.word,
                start=round(w.start + clip_start, 3),
                end=round(w.end + clip_start, 3),
            )
            for w in line.words
        ]
        shifted.append(AlignedLine(
            text=line.text,
            start=round(line.start + clip_start, 3),
            end=round(line.end + clip_start, 3),
            words=new_words,
        ))

    log.info("局部重对齐完成: %d 行", len(shifted))
    return shifted
