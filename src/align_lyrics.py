"""
本地歌词对齐脚本
用法: python -m src.align_lyrics
      python -m src.align_lyrics audio.wav lyrics.txt -o ./output
      python -m src.align_lyrics audio.wav             # 无歌词 → 自动转写
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.config import AlignerConfig, PreprocessorConfig
from src.preprocessor import preprocess_lyrics
from src.aligner import align_lyrics, transcribe_audio
from src.subtitle import generate_ass
from src.config import SubtitleConfig

# ── 默认值，按需修改 ──────────────────────────────────────
DEFAULT_AUDIO   = r"E:\m2v\input\左手在右手的左边A05_vocals.wav"
# copy default to E:\m2v\input\

DEFAULT_LYRICS  = r"E:\m2v\input\左手在右手的左边A05_vocals.txt"              # 留空 = 无歌词时自动转写
DEFAULT_OUTPUT  = r"E:\m2v\output"
DEFAULT_MODEL   = "large-v3"     # 可选: medium / large-v2 / large-v3
DEFAULT_LANG    = None            # None = 自动检测语言；或填 "zh"/"en"/"ja"
DEFAULT_DEVICE  = "cuda"         # "cpu" 强制 CPU
DEFAULT_COMPUTE = "float16"      # "int8" 省显存
DEFAULT_BATCH   = 8
DEFAULT_LYRICS_START = 0.0       # 前奏跳过秒数，0 = 不跳过
# ─────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.align_lyrics",
        description="本地歌词对齐: 音频 + 歌词 → alignment.json + .ass",
    )
    parser.add_argument(
        "audio",
        nargs="?",
        default=DEFAULT_AUDIO,
        help=f"输入音频文件，默认: {DEFAULT_AUDIO}",
    )
    parser.add_argument(
        "lyrics",
        nargs="?",
        default=DEFAULT_LYRICS,
        help="歌词文件 (.txt/.lrc)；省略或文件不存在时自动转写",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"输出目录，默认: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Whisper 模型，默认: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--lang",
        default=DEFAULT_LANG,
        help="语言代码，默认 None=自动检测 (也可指定 zh/en/ja/ko 等)",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="强制 CPU 模式 (自动切换 int8)",
    )
    parser.add_argument(
        "--lyrics-start",
        type=float,
        default=DEFAULT_LYRICS_START,
        help=f"前奏跳过秒数，默认: {DEFAULT_LYRICS_START}",
    )
    parser.add_argument(
        "--ass-only",
        action="store_true",
        help="只生成 .ass，不保存 alignment.json",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="强制自动转写（即使提供了歌词文件也忽略）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    audio_path = Path(args.audio).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not audio_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    device  = "cpu" if args.cpu else DEFAULT_DEVICE
    compute = "int8" if args.cpu else DEFAULT_COMPUTE
    lang    = args.lang  # 可能为 None（自动检测）

    # ── 决定歌词来源 ──────────────────────────────────────
    lyrics_path = Path(args.lyrics).expanduser().resolve() if args.lyrics else None
    use_transcribe = (
        args.transcribe
        or not args.lyrics
        or not lyrics_path.exists()
    )

    stem = audio_path.stem

    if use_transcribe:
        if args.lyrics and lyrics_path and not lyrics_path.exists():
            print(f"[警告] 歌词文件不存在: {lyrics_path}，改为自动转写")
        elif not args.lyrics:
            print("未提供歌词文件，将使用 Whisper 自动转写")
        else:
            print("--transcribe 模式: 忽略歌词文件，使用 Whisper 自动转写")

        trans_config = AlignerConfig(
            whisper_model=args.model,
            device=device,
            compute_type=compute,
            language=lang,          # None → Whisper 自动检测
            batch_size=DEFAULT_BATCH,
            lyrics_start_time=args.lyrics_start,
        )
        lines, detected_lang = transcribe_audio(audio_path, trans_config)
        print(f"转写完成: {len(lines)} 行，检测语言: {detected_lang}")

        # 保存转写文本供复查/下次对齐使用
        txt_path = output_dir / f"{stem}_transcribed.txt"
        txt_path.write_text("\n".join(l.text for l in lines), encoding="utf-8")
        print(f"转写歌词 → {txt_path}")
        print("提示: 检查转写结果后，可将其作为歌词文件重新运行以进行对齐")
        return

    # ── 有歌词 → 预处理 + 对齐 ───────────────────────────
    lyrics = preprocess_lyrics(lyrics_path, PreprocessorConfig())
    print(f"歌词预处理完成: {len(lyrics)} 行")

    config = AlignerConfig(
        whisper_model=args.model,
        device=device,
        compute_type=compute,
        language=lang,
        batch_size=DEFAULT_BATCH,
        lyrics_start_time=args.lyrics_start,
    )
    result = align_lyrics(audio_path, lyrics, config)

    # ── 保存输出 ─────────────────────────────────────────
    if not args.ass_only:
        json_path = output_dir / f"{stem}_alignment.json"
        result.save_json(json_path)
        print(f"alignment.json → {json_path}")

    ass_path = output_dir / f"{stem}.ass"
    generate_ass(result, ass_path, SubtitleConfig(), audio_path=audio_path)
    print(f"ASS → {ass_path}")


if __name__ == "__main__":
    main()
