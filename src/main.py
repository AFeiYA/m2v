"""
Auto-Karaoke MV Generator — CLI 入口 & 管线调度

用法:
    python -m src.main --input ./input --output ./output
    python -m src.main --input ./input/song.mp3 --lyrics ./input/song.txt --output ./output
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from src.config import PipelineConfig
from src.utils import log, discover_pairs


def main() -> None:
    args = parse_args()

    config = PipelineConfig()

    # 覆盖语言设置
    if args.language:
        config.aligner.language = args.language

    # 覆盖设备
    if args.cpu:
        config.separator.device = "cpu"
        config.aligner.device = "cpu"
        config.aligner.compute_type = "int8"

    # 启用节奏动画
    if args.beat_effects:
        config.subtitle.enable_beat_effects = True

    # 保留中间文件
    config.keep_temp = args.keep_temp

    # 背景素材
    background = Path(args.background) if args.background else None

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 确定输入文件对
    if args.lyrics:
        # 单文件模式
        mp3_path = Path(args.input)
        lyrics_path = Path(args.lyrics)
        if not mp3_path.exists():
            log.error("MP3 文件不存在: %s", mp3_path)
            sys.exit(1)
        if not lyrics_path.exists():
            log.error("歌词文件不存在: %s", lyrics_path)
            sys.exit(1)
        pairs = [(mp3_path, lyrics_path)]
    else:
        # 批量模式: 扫描目录
        input_dir = Path(args.input)
        if not input_dir.is_dir():
            log.error("输入路径不是目录: %s (若处理单文件请同时指定 --lyrics)", input_dir)
            sys.exit(1)
        pairs = discover_pairs(input_dir)
        if not pairs:
            log.error("未在 %s 中发现任何 MP3+歌词 文件对", input_dir)
            sys.exit(1)

    # 处理每对文件
    success = 0
    failed = 0
    for mp3_path, lyrics_path in pairs:
        try:
            process_one(mp3_path, lyrics_path, output_dir, background, config)
            success += 1
        except Exception as e:
            log.error("处理失败 [%s]: %s", mp3_path.name, e, exc_info=True)
            failed += 1

    log.info("=" * 50)
    log.info("全部完成: 成功 %d, 失败 %d", success, failed)


# ---------------------------------------------------------------------------
# 单文件处理管线
# ---------------------------------------------------------------------------

def process_one(
    mp3_path: Path,
    lyrics_path: Path,
    output_dir: Path,
    background: Path | None,
    config: PipelineConfig,
) -> Path:
    """
    处理单个 (MP3 + 歌词) 文件对 → 输出卡拉OK MP4。
    """
    stem = mp3_path.stem
    log.info("=" * 50)
    log.info("开始处理: %s", stem)

    # 创建临时工作目录
    if config.temp_dir:
        temp_dir = config.temp_dir / stem
        temp_dir.mkdir(parents=True, exist_ok=True)
        cleanup_temp = False
    else:
        temp_obj = tempfile.mkdtemp(prefix=f"m2v_{stem}_")
        temp_dir = Path(temp_obj)
        cleanup_temp = not config.keep_temp

    try:
        # ---------------------------------------------------------------
        # Step 1: 歌词预处理
        # ---------------------------------------------------------------
        log.info("[1/5] 歌词预处理…")
        from src.preprocessor import preprocess_lyrics
        lyrics = preprocess_lyrics(lyrics_path, config.preprocessor)

        # ---------------------------------------------------------------
        # Step 2: 人声分离
        # ---------------------------------------------------------------
        log.info("[2/5] 人声分离 (Demucs)…")
        from src.separator import separate_vocals
        vocals_path, instrumental_path = separate_vocals(
            mp3_path, temp_dir, config.separator
        )

        # ---------------------------------------------------------------
        # Step 3: 词级对齐
        # ---------------------------------------------------------------
        log.info("[3/5] 词级对齐 (WhisperX)…")
        from src.aligner import align_lyrics
        alignment = align_lyrics(vocals_path, lyrics, config.aligner)

        # 保存对齐 JSON (方便调试/复用)
        json_path = temp_dir / f"{stem}_alignment.json"
        alignment.save_json(json_path)

        # 同时复制一份到输出目录
        output_json = output_dir / f"{stem}_alignment.json"
        shutil.copy2(json_path, output_json)

        # ---------------------------------------------------------------
        # Step 4: ASS 字幕生成
        # ---------------------------------------------------------------
        log.info("[4/5] 生成 ASS 字幕…")
        from src.subtitle import generate_ass
        ass_path = temp_dir / f"{stem}.ass"
        generate_ass(alignment, ass_path, config.subtitle, audio_path=mp3_path)

        # 复制 ASS 到输出目录
        output_ass = output_dir / f"{stem}.ass"
        shutil.copy2(ass_path, output_ass)

        # ---------------------------------------------------------------
        # Step 5: 视频合成
        # ---------------------------------------------------------------
        log.info("[5/5] 视频合成 (FFmpeg)…")
        from src.compositor import compose_video
        output_mp4 = output_dir / f"{stem}.mp4"
        compose_video(
            audio_path=mp3_path,
            subtitle_path=ass_path,
            output_path=output_mp4,
            background=background,
            config=config.compositor,
        )

        log.info("✅ 完成: %s", output_mp4)
        return output_mp4

    finally:
        if cleanup_temp and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.debug("已清理临时目录: %s", temp_dir)


# ---------------------------------------------------------------------------
# CLI 参数
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="m2v",
        description="Auto-Karaoke MV Generator — Suno MP3 + 歌词 → 卡拉OK变色视频",
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="输入目录 (批量模式) 或单个 MP3 文件路径",
    )
    parser.add_argument(
        "--lyrics", "-l",
        default=None,
        help="单文件模式: 指定歌词文件路径 (.txt/.lrc)",
    )
    parser.add_argument(
        "--output", "-o",
        default="./output",
        help="输出目录 (默认: ./output)",
    )
    parser.add_argument(
        "--background", "-bg",
        default=None,
        help="背景素材: 图片 (.jpg/.png) 或视频 (.mp4)，不指定则纯黑背景",
    )
    parser.add_argument(
        "--language", "--lang",
        default="zh",
        help="歌曲语言代码 (默认: zh)",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="强制使用 CPU (不使用 GPU)",
    )
    parser.add_argument(
        "--beat-effects",
        action="store_true",
        help="启用节奏同步字幕动画 (需要 librosa)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="保留中间文件 (用于调试)",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
