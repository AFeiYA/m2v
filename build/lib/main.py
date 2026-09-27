"""
Auto-Karaoke MV Generator — CLI 入口 & 管线调度

用法:
    python -m src.main --input ./input --output ./output
    python -m src.main --input ./input/song.mp3 --lyrics ./input/song.txt --output ./output
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import tomllib

from src.config import PipelineConfig
from src.utils import log, discover_pairs


def _run_edit_subcommand() -> None:
    """处理 `m2v edit` 子命令 — 启动统一 API 服务并自动打开编辑器页面。"""
    parser = argparse.ArgumentParser(
        prog="m2v edit",
        description="启动时间轴编辑器 (通过统一 API 服务)",
    )
    parser.add_argument("--port", "-p", type=int, default=8000, help="端口号")
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址")
    args = parser.parse_args(sys.argv[2:])

    import threading
    import webbrowser
    url = f"http://{args.host}:{args.port}/editor"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    from src.api_server import run_server
    run_server(host=args.host, port=args.port)


def _run_serve_subcommand() -> None:
    """处理 `m2v serve` 子命令，启动 API 服务。"""
    parser = argparse.ArgumentParser(
        prog="m2v serve",
        description="启动 M2V API 服务 (面向用户的 Web 服务)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--port", "-p", type=int, default=8000, help="端口号")
    args = parser.parse_args(sys.argv[2:])

    from src.api_server import run_server
    run_server(host=args.host, port=args.port)


def main() -> None:
    # 如果第一个参数是 edit，启动编辑器
    if len(sys.argv) > 1 and sys.argv[1] == "edit":
        _run_edit_subcommand()
        return

    # 如果第一个参数是 serve，启动 API 服务
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _run_serve_subcommand()
        return

    args = parse_args()

    config = PipelineConfig()

    # 可选: 从配置文件加载步骤控制参数
    if args.config_file:
        _apply_config_file(config, Path(args.config_file))

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

    # 步骤控制 (CLI 覆盖配置文件)
    if args.skip_separation:
        config.skip_separation = True
    if args.ass_only:
        config.ass_only = True
    if args.alignment_json:
        config.alignment_json = Path(args.alignment_json)
    if args.video_only:
        config.video_only = True
    if args.ass_file:
        config.ass_file = Path(args.ass_file)
    if args.lyrics_start is not None:
        config.aligner.lyrics_start_time = args.lyrics_start

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

# 进度回调类型: (step: str, progress: int, message: str) -> None
ProgressCallback = type(None) | type(lambda: None)  # 兼容类型提示


def process_one(
    mp3_path: Path,
    lyrics_path: Path,
    output_dir: Path,
    background: Path | None,
    config: PipelineConfig,
    on_progress: callable | None = None,
) -> Path:
    """
    处理单个 (MP3 + 歌词) 文件对 → 输出卡拉OK MP4。

    Args:
        on_progress: 可选进度回调 (step, progress, message)
                     用于 Web 服务 / Worker 向前端推送进度
    """
    def _progress(step: str, progress: int, message: str = ""):
        if on_progress:
            on_progress(step, progress, message)
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
        # 快捷路径: video_only — 直接从已有 ASS 合成视频
        # ---------------------------------------------------------------
        if config.video_only:
            ass_path = _resolve_ass_path(config.ass_file, mp3_path, output_dir)
            if not ass_path.exists():
                raise FileNotFoundError(f"ASS 文件不存在: {ass_path}")
            log.info("[1-4/5] 跳过 (video_only)，使用已有 ASS: %s", ass_path.name)
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

        # ---------------------------------------------------------------
        # Step 1: 歌词预处理
        # ---------------------------------------------------------------
        _progress("preprocessing", 5, "歌词预处理中…")
        log.info("[1/5] 歌词预处理…")
        from src.preprocessor import preprocess_lyrics
        lyrics = preprocess_lyrics(lyrics_path, config.preprocessor)
        _progress("preprocessing", 10, "歌词预处理完成")

        # ---------------------------------------------------------------
        # Step 2: 人声分离 (可跳过)
        # ---------------------------------------------------------------
        instrumental_path: Path | None = None
        if config.skip_separation:
            log.info("[2/5] 跳过人声分离，直接使用原音频进行对齐…")
            vocals_path = mp3_path
            _progress("separating", 30, "跳过人声分离")
        else:
            _progress("separating", 15, "人声分离中 (Demucs)…")
            log.info("[2/5] 人声分离 (Demucs)…")
            from src.separator import separate_vocals
            vocals_path, instrumental_path = separate_vocals(
                mp3_path, temp_dir, config.separator
            )
            _progress("separating", 30, "人声分离完成")

        # ---------------------------------------------------------------
        # Step 3: 词级对齐 (可复用 JSON)
        # ---------------------------------------------------------------
        from src.aligner import AlignmentResult

        if config.alignment_json:
            alignment_json = _resolve_alignment_json_path(config.alignment_json, mp3_path)
            if not alignment_json.exists():
                raise FileNotFoundError(f"指定的对齐 JSON 不存在: {alignment_json}")
            log.info("[3/5] 复用已有对齐 JSON: %s", alignment_json.name)
            alignment = AlignmentResult.load_json(alignment_json)
            _progress("aligning", 60, "复用已有对齐结果")

            # 复制一份到输出目录，保持产物一致
            output_json = output_dir / f"{stem}_alignment.json"
            shutil.copy2(alignment_json, output_json)
        else:
            _progress("aligning", 35, "词级对齐中 (WhisperX)…")
            log.info("[3/5] 词级对齐 (WhisperX)…")
            from src.aligner import align_lyrics
            alignment = align_lyrics(vocals_path, lyrics, config.aligner)
            _progress("aligning", 60, "词级对齐完成")

            # 保存对齐 JSON (方便调试/复用)
            json_path = temp_dir / f"{stem}_alignment.json"
            alignment.save_json(json_path)

            # 同时复制一份到输出目录
            output_json = output_dir / f"{stem}_alignment.json"
            shutil.copy2(json_path, output_json)

        # ---------------------------------------------------------------
        # Step 4: ASS 字幕生成
        # ---------------------------------------------------------------
        _progress("subtitle", 65, "生成 ASS 字幕…")
        log.info("[4/5] 生成 ASS 字幕…")
        from src.subtitle import generate_ass
        ass_path = temp_dir / f"{stem}.ass"
        generate_ass(alignment, ass_path, config.subtitle, audio_path=mp3_path)
        _progress("subtitle", 75, "ASS 字幕生成完成")

        # 复制 ASS 到输出目录
        output_ass = output_dir / f"{stem}.ass"
        shutil.copy2(ass_path, output_ass)

        if config.ass_only:
            log.info("[5/5] 已按配置跳过视频合成 (ASS-only)")
            log.info("✅ 完成: %s", output_ass)
            return output_ass

        # ---------------------------------------------------------------
        # Step 5: 视频合成
        # ---------------------------------------------------------------
        _progress("compositing", 80, "视频合成中 (FFmpeg)…")
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

        _progress("compositing", 100, "✅ 处理完成！")
        log.info("✅ 完成: %s", output_mp4)
        return output_mp4

    finally:
        if cleanup_temp and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.debug("已清理临时目录: %s", temp_dir)


def _apply_config_file(config: PipelineConfig, config_path: Path) -> None:
    """从 JSON / TOML 配置文件加载运行参数。"""
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    elif suffix == ".json":
        data = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        raise ValueError("配置文件仅支持 .toml 或 .json")

    pipeline = data.get("pipeline", data)

    config.skip_separation = bool(pipeline.get("skip_separation", config.skip_separation))
    config.ass_only = bool(pipeline.get("ass_only", config.ass_only))
    config.video_only = bool(pipeline.get("video_only", config.video_only))

    alignment_json = pipeline.get("alignment_json")
    if alignment_json:
        config.alignment_json = Path(alignment_json)

    ass_file = pipeline.get("ass_file")
    if ass_file:
        config.ass_file = Path(ass_file)

    # [aligner] 节
    aligner_cfg = data.get("aligner", {})
    if aligner_cfg.get("whisper_model"):
        config.aligner.whisper_model = aligner_cfg["whisper_model"]
    if aligner_cfg.get("device"):
        config.aligner.device = aligner_cfg["device"]
    if aligner_cfg.get("compute_type"):
        config.aligner.compute_type = aligner_cfg["compute_type"]
    if aligner_cfg.get("batch_size") is not None:
        config.aligner.batch_size = int(aligner_cfg["batch_size"])
    if aligner_cfg.get("language"):
        config.aligner.language = aligner_cfg["language"]
    if "use_pinyin" in aligner_cfg:
        config.aligner.use_pinyin = bool(aligner_cfg["use_pinyin"])
    if aligner_cfg.get("min_char_duration") is not None:
        config.aligner.min_char_duration = float(aligner_cfg["min_char_duration"])
    if aligner_cfg.get("max_char_duration") is not None:
        config.aligner.max_char_duration = float(aligner_cfg["max_char_duration"])
    if aligner_cfg.get("lyrics_start_time") is not None:
        config.aligner.lyrics_start_time = float(aligner_cfg["lyrics_start_time"])


def _resolve_alignment_json_path(template_path: Path, mp3_path: Path) -> Path:
    """支持在 alignment_json 中使用 {stem} 占位符。"""
    rendered = str(template_path).replace("{stem}", mp3_path.stem)
    return Path(rendered)


def _resolve_ass_path(
    ass_file: Path | None, mp3_path: Path, output_dir: Path
) -> Path:
    """解析 ASS 文件路径，支持 {stem} 占位符；未指定时取 output_dir/{stem}.ass"""
    if ass_file:
        rendered = str(ass_file).replace("{stem}", mp3_path.stem)
        return Path(rendered)
    return output_dir / f"{mp3_path.stem}.ass"


# ---------------------------------------------------------------------------
# CLI 参数
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="m2v",
        description="Auto-Karaoke MV Generator — Suno MP3 + 歌词 → 卡拉OK变色视频",
    )

    parser.add_argument(
        "--config-file",
        default=None,
        help="可选配置文件 (.toml/.json)，可配置步骤跳过策略",
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
    parser.add_argument(
        "--skip-separation",
        action="store_true",
        help="跳过人声分离，直接用原音频进行对齐",
    )
    parser.add_argument(
        "--alignment-json",
        default=None,
        help="复用已有对齐 JSON 文件路径 (支持 {stem} 占位符)，可跳过对齐",
    )
    parser.add_argument(
        "--ass-only",
        action="store_true",
        help="只输出 ASS + alignment.json，不合成 MP4",
    )
    parser.add_argument(
        "--video-only",
        action="store_true",
        help="直接从已有 ASS 合成视频，跳过步骤 1-4",
    )
    parser.add_argument(
        "--ass-file",
        default=None,
        help="video-only 模式: 指定 ASS 文件路径 (支持 {stem})，默认 output/{stem}.ass",
    )
    parser.add_argument(
        "--lyrics-start",
        type=float,
        default=None,
        help="歌词实际开唱时间(秒)，前奏/拟声词的 segment 会被过滤",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
