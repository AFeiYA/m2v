"""
Suno2MV 工业级双导演架构与多阶段流水线核心包
---------------------------------------------
Pass A: CreativeDirector (宏观剧作、Sequences 幕次、四维 Bibles 与 Temporal 曲线)
Pass B: ShotPlanner (微观分镜、机器参数、构图安全区、纯画面 Prompt)
Pass C: ContinuityDirector (Shot Graph、蒙太奇转场、副歌复沓与母题进化)
"""
from src.directors.creative_director import CreativeDirector
from src.directors.shot_planner import ShotPlanner
from src.directors.continuity_director import ContinuityDirector

__all__ = [
    "CreativeDirector",
    "ShotPlanner",
    "ContinuityDirector",
]
