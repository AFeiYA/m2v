"""
Module 2: 人声分离器
- Demucs v4 (htdemucs_ft) 封装
- GPU / CPU 自动回退
- 输出 vocals.wav + instrumental.wav
"""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from src.config import SeparatorConfig
from src.utils import log


def separate_vocals(
    mp3_path: Path,
    output_dir: Path,
    config: SeparatorConfig | None = None,
) -> tuple[Path, Path]:
    """
    使用 Demucs 分离人声和伴奏。

    Args:
        mp3_path:   输入 MP3 文件路径
        output_dir: 中间文件输出目录
        config:     分离器配置

    Returns:
        (vocals_path, instrumental_path) 两个 WAV 文件的路径
    """
    if config is None:
        config = SeparatorConfig()

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = mp3_path.stem

    log.info("开始人声分离: %s (model=%s)", mp3_path.name, config.model)

    # 构建 demucs 命令
    cmd = [
        "python", "-m", "demucs",
        "--name", config.model,
        "--two-stems", config.two_stems,
        "--out", str(output_dir),
        "--device", config.device,
        "--shifts", str(config.shifts),
    ]

    # WAV 输出 (demucs 默认就是 wav)
    if config.output_format != "wav":
        cmd.extend(["--mp3"])

    cmd.append(str(mp3_path))

    # 执行，GPU 失败时回退 CPU
    try:
        _run_demucs(cmd)
    except subprocess.CalledProcessError:
        if config.device != "cpu":
            log.warning("GPU 分离失败，回退到 CPU 模式…")
            cmd_cpu = [c if c != config.device else "cpu" for c in cmd]
            _run_demucs(cmd_cpu)
        else:
            raise

    # Demucs 输出路径: {output_dir}/{model}/{stem}/vocals.wav, no_vocals.wav
    demucs_out = output_dir / config.model / stem
    vocals_src = demucs_out / "vocals.wav"
    instrumental_src = demucs_out / "no_vocals.wav"

    if not vocals_src.exists():
        raise FileNotFoundError(f"Demucs 输出未找到: {vocals_src}")

    # 移动到 output_dir 根目录，简化后续引用
    vocals_dst = output_dir / f"{stem}_vocals.wav"
    instrumental_dst = output_dir / f"{stem}_instrumental.wav"
    shutil.move(str(vocals_src), str(vocals_dst))
    shutil.move(str(instrumental_src), str(instrumental_dst))

    # 清理 demucs 子目录
    demucs_model_dir = output_dir / config.model
    if demucs_model_dir.exists():
        shutil.rmtree(demucs_model_dir, ignore_errors=True)

    log.info("人声分离完成: %s, %s", vocals_dst.name, instrumental_dst.name)
    return vocals_dst, instrumental_dst


def _run_demucs(cmd: list[str]) -> None:
    """执行 demucs 命令并打印实时日志"""
    log.debug("执行命令: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            log.debug("[demucs] %s", line)
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            log.debug("[demucs] %s", line)
