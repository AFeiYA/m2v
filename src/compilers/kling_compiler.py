"""
快手可灵 Kling 提示词编译器 (KlingPromptCompiler)
----------------------------------------------
专为 Kling 1.5 / 2.0 视频生成模型定制：
1. 映射结构化运镜参数 (zoom, pan, tilt, horizontal)。
2. 支持构图主体锁定。
3. 负向提示词过滤字幕与残影。
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


class KlingPromptCompiler(BasePromptCompiler):
    model_name: str = "kling"

    def _map_kling_camera_motion(self, motion: str) -> Dict[str, float]:
        """将标准运镜标签映射为可灵参数标量"""
        motion_map = {
            "static": {"zoom": 0.0, "horizontal": 0.0, "vertical": 0.0, "pan": 0.0, "tilt": 0.0},
            "slow_dolly_in": {"zoom": 2.5, "horizontal": 0.0, "vertical": 0.0, "pan": 0.0, "tilt": 0.0},
            "dolly_out": {"zoom": -2.5, "horizontal": 0.0, "vertical": 0.0, "pan": 0.0, "tilt": 0.0},
            "pan_left": {"zoom": 0.0, "horizontal": -3.0, "vertical": 0.0, "pan": -2.0, "tilt": 0.0},
            "pan_right": {"zoom": 0.0, "horizontal": 3.0, "vertical": 0.0, "pan": 2.0, "tilt": 0.0},
            "tilt_up": {"zoom": 0.0, "horizontal": 0.0, "vertical": 2.5, "pan": 0.0, "tilt": 2.0},
            "tilt_down": {"zoom": 0.0, "horizontal": 0.0, "vertical": -2.5, "pan": 0.0, "tilt": -2.0},
            "tracking": {"zoom": 1.0, "horizontal": 2.0, "vertical": 0.0, "pan": 0.0, "tilt": 0.0},
            "crane_up": {"zoom": 0.5, "horizontal": 0.0, "vertical": 4.0, "pan": 0.0, "tilt": -1.5},
            "handheld": {"zoom": 0.2, "horizontal": 0.5, "vertical": 0.5, "pan": 0.2, "tilt": 0.2},
        }
        return motion_map.get(motion.lower(), {"zoom": 0.0, "horizontal": 0.0, "vertical": 0.0, "pan": 0.0, "tilt": 0.0})

    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        motion_name = shot.camera_motion or "static"
        motion_params = self._map_kling_camera_motion(motion_name)

        clean_visual = (shot.prompt_en or shot.action or "Cinematic shot").replace("Chinese text", "scene")
        scale = shot.shot_size or shot.scale or "MS"

        kling_prompt = (
            f"电影级画质，大师构图，{scale} 景别，{clean_visual}，"
            f"柔和胶片光影，4K，超高解析度，浅景深。"
        )

        kling_negative = (
            "字幕，文字，水印，变形，肢体畸变，低分辨率，噪点，粗糙质感，模糊，重影，卡通渲染"
        )

        return ModelPromptPayload(
            model_name="kling_v2",
            prompt=kling_prompt,
            negative_prompt=kling_negative,
            aspect_ratio="16:9",
            duration_seconds=min(10.0, max(3.0, round(shot.duration, 1))),
            camera_motion=motion_name,
            camera_motion_scale=1.0,
            cfg_scale=0.5,  # Kling 习惯 0~1 的引导强度
            extra_params={
                "camera_control": motion_params,
                "mode": "pro",
            },
        )
