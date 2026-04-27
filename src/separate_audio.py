from __future__ import annotations

import argparse
from pathlib import Path

from src.config import SeparatorConfig
from src.separator import separate_vocals

# ── 默认值，按需修改 ──────────────────────────────────────
DEFAULT_INPUT  = r"C:\Users\Luca\Downloads\左手在右手的左边F.wav"
DEFAULT_OUTPUT = r"H:\AniMusic\audio\废不废"
DEFAULT_MODEL  = "htdemucs_ft"   # 可选: htdemucs / htdemucs_6s
DEFAULT_SHIFTS = 1               # 越大越慢但效果更好，建议 1-4
DEFAULT_CPU    = False           # True = 强制 CPU
# ─────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.separate_audio",
        description="仅执行 Demucs 人声/伴奏分离",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"输入音频文件路径 (.wav/.mp3 等)，默认: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT,
        help=f"输出目录，默认: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        default=DEFAULT_CPU,
        help="强制使用 CPU 运行 Demucs",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Demucs 模型名，默认: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--shifts",
        type=int,
        default=DEFAULT_SHIFTS,
        help=f"Demucs shifts 参数，默认: {DEFAULT_SHIFTS}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    output_dir = Path(args.output).expanduser().resolve()
    config = SeparatorConfig(
        model=args.model,
        device="cpu" if args.cpu else "cuda",
        shifts=args.shifts,
    )

    vocals_path, instrumental_path = separate_vocals(input_path, output_dir, config)
    print(f"vocals={vocals_path}")
    print(f"instrumental={instrumental_path}")


if __name__ == "__main__":
    main()