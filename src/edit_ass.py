"""
本地 alignment.json 编辑 + 重新生成 ASS
用法:
  python -m src.edit_ass                          # 用默认路径
  python -m src.edit_ass alignment.json -o ./out  # 指定路径

操作说明:
  - 运行后列出所有歌词行，输入行号进入编辑
  - 可修改: 行文本 / 行起止时间 / 单字时间戳
  - 保存后自动重新生成 .ass
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.aligner import AlignmentResult, AlignedLine, WordTimestamp
from src.subtitle import generate_ass
from src.config import SubtitleConfig

# ── 默认值，按需修改 ──────────────────────────────────────
DEFAULT_ALIGNMENT = r"H:\AniMusic\output\左手在右手的左边01A_alignment.json"
DEFAULT_OUTPUT    = r"H:\AniMusic\output"
DEFAULT_AUDIO     = ""   # 可选，填入后节奏动画才生效；留空跳过
# ─────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.edit_ass",
        description="交互式编辑 alignment.json 并重新生成 .ass",
    )
    parser.add_argument(
        "alignment",
        nargs="?",
        default=DEFAULT_ALIGNMENT,
        help=f"alignment.json 路径，默认: {DEFAULT_ALIGNMENT}",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"输出目录，默认: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--audio",
        default=DEFAULT_AUDIO,
        help="原始音频路径（可选，用于节奏动画）",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="跳过交互编辑，直接从 alignment.json 重新生成 .ass",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 交互式编辑
# ---------------------------------------------------------------------------

def _fmt_time(s: float) -> str:
    m, sec = divmod(s, 60)
    return f"{int(m):02d}:{sec:05.2f}"


def _parse_time(s: str) -> float:
    """接受 mm:ss.xx 或纯秒数"""
    s = s.strip()
    if ":" in s:
        parts = s.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    return float(s)


def _list_lines(result: AlignmentResult) -> None:
    print("\n── 当前歌词行 ──────────────────────────────")
    for i, line in enumerate(result.lines):
        print(f"  [{i:3d}] {_fmt_time(line.start)} ~ {_fmt_time(line.end)}  {line.text}")
    print()


def _edit_line(line: AlignedLine) -> None:
    """交互式编辑单行"""
    print(f"\n  文本   : {line.text}")
    print(f"  起始   : {_fmt_time(line.start)}")
    print(f"  结束   : {_fmt_time(line.end)}")
    print(f"  字数   : {len(line.words)}")

    while True:
        cmd = input("  编辑 [t=文本 s=起始 e=结束 w=逐字 q=返回]: ").strip().lower()
        if cmd == "q":
            break
        elif cmd == "t":
            v = input(f"  新文本 [{line.text}]: ").strip()
            if v:
                line.text = v
        elif cmd == "s":
            v = input(f"  新起始时间 (mm:ss.xx 或秒) [{_fmt_time(line.start)}]: ").strip()
            if v:
                line.start = _parse_time(v)
        elif cmd == "e":
            v = input(f"  新结束时间 (mm:ss.xx 或秒) [{_fmt_time(line.end)}]: ").strip()
            if v:
                line.end = _parse_time(v)
        elif cmd == "w":
            _edit_words(line)
        else:
            print("  未知命令，请输入 t/s/e/w/q")


def _edit_words(line: AlignedLine) -> None:
    """交互式编辑逐字时间戳"""
    for i, w in enumerate(line.words):
        print(f"    [{i}] '{w.word}'  {_fmt_time(w.start)} ~ {_fmt_time(w.end)}")
    idx = input("  输入字的序号（回车跳过）: ").strip()
    if not idx:
        return
    try:
        i = int(idx)
        w = line.words[i]
    except (ValueError, IndexError):
        print("  无效序号")
        return
    s = input(f"  新起始 [{_fmt_time(w.start)}]: ").strip()
    if s:
        w.start = _parse_time(s)
    e = input(f"  新结束 [{_fmt_time(w.end)}]: ").strip()
    if e:
        w.end = _parse_time(e)


def _interactive_edit(result: AlignmentResult) -> bool:
    """返回 True 表示用户选择了保存"""
    print("\n输入行号编辑，输入 s 保存并生成 ASS，输入 q 放弃退出。")
    while True:
        _list_lines(result)
        cmd = input("行号 / s / q: ").strip().lower()
        if cmd == "q":
            return False
        if cmd == "s":
            return True
        try:
            idx = int(cmd)
            if 0 <= idx < len(result.lines):
                _edit_line(result.lines[idx])
            else:
                print(f"  行号超出范围 (0 ~ {len(result.lines)-1})")
        except ValueError:
            print("  请输入行号、s 或 q")


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    align_path = Path(args.alignment).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not align_path.exists():
        raise FileNotFoundError(f"alignment.json 不存在: {align_path}")

    result = AlignmentResult.load_json(align_path)
    print(f"已加载 {align_path.name}: {len(result.lines)} 行歌词")

    if not args.no_interactive:
        saved = _interactive_edit(result)
        if not saved:
            print("放弃，未保存。")
            sys.exit(0)

        # 保存修改后的 alignment.json（同名覆盖）
        result.save_json(align_path)
        print(f"已保存 alignment.json → {align_path}")

    # 重新生成 .ass
    stem = align_path.stem.replace("_alignment", "")
    ass_path = output_dir / f"{stem}.ass"
    audio_path = Path(args.audio).expanduser().resolve() if args.audio else None
    generate_ass(result, ass_path, SubtitleConfig(), audio_path=audio_path)
    print(f"ASS 已生成 → {ass_path}")


if __name__ == "__main__":
    main()
