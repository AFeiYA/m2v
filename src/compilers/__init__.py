"""
PromptCompilers 模型提示词编译器统一入口与路由
---------------------------------------------
支持将中立的 ShotPlan 翻译为 Veo, Kling, Seedance, Wan 等异构大模型的专用输入载荷。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.compilers.veo_compiler import VeoPromptCompiler
from src.compilers.kling_compiler import KlingPromptCompiler
from src.compilers.seedance_compiler import SeedancePromptCompiler
from src.compilers.wan_compiler import WanPromptCompiler
from src.compilers.ltx_compiler import LTXPromptCompiler
from src.compilers.flux_compiler import FluxPromptCompiler
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan

_REGISTRY: Dict[str, Type[BasePromptCompiler]] = {
    "veo": VeoPromptCompiler,
    "google_veo": VeoPromptCompiler,
    "kling": KlingPromptCompiler,
    "kling_v2": KlingPromptCompiler,
    "seedance": SeedancePromptCompiler,
    "doubao": SeedancePromptCompiler,
    "wan": WanPromptCompiler,
    "wanx": WanPromptCompiler,
    "ltx": LTXPromptCompiler,
    "ltx_video": LTXPromptCompiler,
    "ltxv": LTXPromptCompiler,
    "flux": FluxPromptCompiler,
    "flux_schnell": FluxPromptCompiler,
    "flux_dev": FluxPromptCompiler,
}


def list_supported_compilers() -> List[str]:
    """返回支持的视频生成模型编译器列表"""
    return ["veo", "kling", "seedance", "wan", "ltx", "flux"]


def get_compiler(model_name: str) -> BasePromptCompiler:
    """根据模型名称获取对应的提示词编译器实例"""
    clean_name = model_name.lower().strip()
    cls = _REGISTRY.get(clean_name)
    if not cls:
        # 默认使用 Veo 编译器作为通用保真输出
        cls = VeoPromptCompiler
    return cls()


def compile_shot_for_model(
    shot: ShotPlan,
    model_name: str,
    bibles: Optional[GlobalBibles] = None,
    sequence: Optional[SequencePlan] = None,
) -> ModelPromptPayload:
    """一键为指定视频模型编译分镜提示词载荷"""
    compiler = get_compiler(model_name)
    return compiler.compile(shot, bibles=bibles, sequence=sequence)
