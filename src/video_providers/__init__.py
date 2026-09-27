"""
视频生成提供商与引擎集成模块
-----------------------------
提供对本地与云端视频/图像生成引擎的调度抽象。
"""
from __future__ import annotations

from src.video_providers.comfyui_client import ComfyUIClient, get_comfyui_client

__all__ = ["ComfyUIClient", "get_comfyui_client"]
