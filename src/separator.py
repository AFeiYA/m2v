"""
Module 2: 人声分离器
- Demucs v4 (htdemucs_ft) 封装
- GPU / CPU 自动回退
- 输出 vocals.wav + instrumental.wav
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from src.config import SeparatorConfig
from src.utils import log

try:
    import spaces
except ImportError:
    spaces = None


# 如果在 Hugging Face Spaces 环境，定义 ZeroGPU 动态执行函数
# 关键优化：duration 设为 35 秒（htdemucs 在 A100 上实际仅需 8~12s），
# 相比原本的 120s 节省 70% 额度，大幅提升排队成功率，并避免因剩余额度不足被拒！
if spaces and hasattr(spaces, "GPU"):
    @spaces.GPU(duration=35)
    def _run_demucs_zerogpu(opts: list[str]) -> None:
        import demucs.separate
        import torch
        dev_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "GPU"
        mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3) if torch.cuda.is_available() else 0
        log.info("🎯 [ZeroGPU] 成功借调 GPU 硬件: %s (显存: %.1f GB)，开始极速分离…", dev_name, mem_gb)
        demucs.separate.main(opts)
else:
    _run_demucs_zerogpu = None


def separate_vocals(
    mp3_path: Path,
    output_dir: Path,
    config: SeparatorConfig | None = None,
    status_callback: callable | None = None,
) -> tuple[Path, Path]:
    """
    使用 Demucs 分离人声和伴奏。

    Args:
        mp3_path:        输入 MP3 文件路径
        output_dir:      中间文件输出目录
        config:          分离器配置
        status_callback: 运行状态实时回调 (用于向前端反馈 GPU 借调详情)

    Returns:
        (vocals_path, instrumental_path) 两个 WAV/MP3 文件的路径
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

    is_zerogpu = _run_demucs_zerogpu is not None and device in ("cuda", "auto")

    if not is_zerogpu:
        if device in ("cuda", "auto") and not _is_cuda_ready():
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
                log.info("🎯 检测到 macOS Apple Silicon GPU，启用 Metal (MPS) 硬件加速分离")
            else:
                device = "cpu"
    else:
        # ZeroGPU 环境下，外层 torch.cuda 不可见，必须传给 demucs cuda 设备参数
        device = "cuda"

    log.info("开始人声分离: %s (model=%s, device=%s, is_zerogpu=%s)", mp3_path.name, config.model, device, is_zerogpu)

    # 构建 demucs 参数列表
    opts = [
        "--name", config.model,
        "--two-stems", config.two_stems,
        "--out", str(output_dir),
        "--device", device,
        "--shifts", str(config.shifts),
    ]

    # WAV 输出 (demucs 默认就是 wav)
    if config.output_format != "wav":
        opts.extend(["--mp3"])

    opts.append(str(mp3_path))

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

    # 执行，优先进程内执行，GPU 失败时回退 CPU
    _run_demucs_execution(opts, device, is_zerogpu=is_zerogpu, status_cb=status_callback)

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


def _run_demucs_execution(
    opts: list[str],
    device: str,
    is_zerogpu: bool = False,
    status_cb: callable | None = None,
) -> None:
    """
    执行 Demucs 分离任务:
    1. ZeroGPU 环境: 自动按需申请 A100，如额度不足或排队失败，自动无缝平滑切至 CPU，绝不崩溃中断
    2. 本地/物理卡环境: 优先使用 MPS 或 CUDA 高速运行，失败时回退 CPU
    """
    if is_zerogpu and _run_demucs_zerogpu is not None:
        log.info("⏳ [ZeroGPU] 正在向 Hugging Face 调度中心申请 GPU 算力 (申请额度: 35s)...")
        if status_cb:
            status_cb("⏳ 正在申请云端 GPU 算力 (预占 35s 额度)...")
        t0 = time.time()
        try:
            _run_demucs_zerogpu(opts)
            cost_sec = time.time() - t0
            log.info("⚡ [ZeroGPU] 伴奏分离完成 (GPU 实际计算耗时: %.1fs)，GPU 算力已释放归还集群", cost_sec)
            if status_cb:
                status_cb(f"⚡ GPU 分离完成 (耗时 {cost_sec:.1f}s)")
            return
        except Exception as exc:
            err_name = type(exc).__name__
            err_desc = str(exc)
            log.warning("⚠️ [ZeroGPU] 借调 GPU 未成功 (%s: %s)，已自动平滑降级至 CPU 模式继续完成！", err_name, err_desc)
            if status_cb:
                status_cb("🟡 云端 GPU 额度耗尽或排队，已平滑切换 CPU 运行 (预计需 1~2 分钟)...")
            device = "cpu"
            opts = [c if c != "cuda" else "cpu" for c in opts]

    # 非 ZeroGPU 或 ZeroGPU 降级后的常规执行通道
    try:
        import demucs.separate
        if device == "mps":
            log.info("执行进程内 Demucs (Apple Silicon MPS): %s", " ".join(opts))
            if status_cb:
                status_cb("🟢 正在使用 Apple Silicon GPU (MPS) 分离伴奏...")
        elif device == "cuda":
            log.info("执行进程内 Demucs (CUDA): %s", " ".join(opts))
            if status_cb:
                status_cb("🟢 正在使用物理 CUDA 显卡分离伴奏...")
        else:
            log.info("执行进程内 Demucs (CPU): %s", " ".join(opts))
            if status_cb:
                status_cb("⚙️ 正在使用 CPU 分离伴奏中...")

        t_start = time.time()
        demucs.separate.main(opts)
        log.info("Demucs 进程内执行完成，总耗时: %.1fs", time.time() - t_start)
        return
    except Exception as exc:
        log.warning("进程内 Demucs 执行遇到问题 (%s)，自动切换至子进程隔离模式…", exc)

    cmd = [sys.executable, "-m", "demucs"] + opts
    try:
        _run_demucs(cmd)
    except subprocess.CalledProcessError as exc:
        if device != "cpu":
            log.warning("GPU (%s) 分离失败，回退到 CPU 模式…", device)
            if status_cb:
                status_cb("🟡 GPU 分离失败，自动回退到 CPU 模式继续…")
            opts_cpu = [c if c != device else "cpu" for c in opts]
            cmd_cpu = [sys.executable, "-m", "demucs"] + opts_cpu
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
