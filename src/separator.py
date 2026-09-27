"""
Module 2: 人声分离器
- Demucs v4 (htdemucs_ft) 封装
- GPU / CPU 自动回退
- 输出 vocals.wav + instrumental.wav
"""

from __future__ import annotations

import subprocess
import shutil
import sys
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

    import torch

    # 智能设备检测: CUDA -> Apple Silicon MPS -> CPU
    device = config.device

    def _is_cuda_ready() -> bool:
        if not torch.cuda.is_available():
            return False
        try:
            t = torch.zeros(1, device="cuda")
            del t
            return True
        except Exception:
            return False

    if device in ("cuda", "auto") and not _is_cuda_ready():
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
            log.info("检测到 macOS Apple Silicon GPU，启用 Metal (MPS) 硬件加速分离")
        else:
            device = "cpu"

    log.info("开始人声分离: %s (model=%s, device=%s)", mp3_path.name, config.model, device)

    # 构建 demucs 命令
    cmd = [
        sys.executable, "-m", "demucs",
        "--name", config.model,
        "--two-stems", config.two_stems,
        "--out", str(output_dir),
        "--device", device,
        "--shifts", str(config.shifts),
    ]

    # WAV 输出 (demucs 默认就是 wav)
    if config.output_format != "wav":
        cmd.extend(["--mp3"])

    cmd.append(str(mp3_path))

    # 1. 前置音频有效性探测 (防止因文件损坏或 moov atom 丢失导致底层崩溃)
    from src.utils import get_ffprobe_binary
    probe_cmd = [get_ffprobe_binary(), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(mp3_path)]
    try:
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        if probe_res.returncode != 0:
            err_msg = probe_res.stderr.strip() or "无法被 FFmpeg 解码"
            raise ValueError(
                f"音频文件损坏或格式无效 ({mp3_path.name})。\n"
                f"可能原因为网络下载不完整或受 Suno 防盗链保护（如缺少 moov atom）。\n"
                f"💡 建议：在 Suno 网页点击【Download】选择【Audio (MP3)】下载，重新运行即可自动接管！\n"
                f"底层探测错误: {err_msg}"
            )
    except FileNotFoundError:
        pass  # 系统无 ffprobe 则跳过前置检查

    # 执行，GPU 失败时回退 CPU
    try:
        _run_demucs(cmd)
    except subprocess.CalledProcessError as exc:
        if device != "cpu":
            log.warning("GPU (%s) 分离失败，回退到 CPU 模式…", device)
            if exc.stdout:
                for line in exc.stdout.strip().splitlines():
                    log.warning("[demucs-gpu stdout] %s", line)
            if exc.stderr:
                for line in exc.stderr.strip().splitlines():
                    log.warning("[demucs-gpu stderr] %s", line)
            cmd_cpu = [c if c != device else "cpu" for c in cmd]
            try:
                _run_demucs(cmd_cpu)
            except subprocess.CalledProcessError as exc_cpu:
                err_detail = exc_cpu.stderr.strip() if exc_cpu.stderr else str(exc_cpu)
                log.error("CPU 分离亦失败: %s", err_detail)
                raise RuntimeError(f"Demucs 人声分离失败: {err_detail}") from exc_cpu
        else:
            err_detail = exc.stderr.strip() if exc.stderr else str(exc)
            log.error("Demucs 分离失败: %s", err_detail)
            raise RuntimeError(f"Demucs 人声分离失败: {err_detail}") from exc

    # Demucs 输出路径: {output_dir}/{model}/{stem}/vocals.{ext}, no_vocals.{ext}
    demucs_out = output_dir / config.model / stem
    ext = f".{config.output_format.lstrip('.')}"
    vocals_src = demucs_out / f"vocals{ext}"
    instrumental_src = demucs_out / f"no_vocals{ext}"

    if not vocals_src.exists():
        # 兼容性搜寻：匹配实际生成的 vocals 文件
        found_vocals = list(demucs_out.glob("vocals.*"))
        if found_vocals:
            vocals_src = found_vocals[0]
            ext = vocals_src.suffix
            instrumental_src = demucs_out / f"no_vocals{ext}"
        else:
            raise FileNotFoundError(f"Demucs 输出未找到: {vocals_src}")

    # 移动到 output_dir 根目录，简化后续引用
    vocals_dst = output_dir / f"{stem}_vocals{ext}"
    instrumental_dst = output_dir / f"{stem}_instrumental{ext}"
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
