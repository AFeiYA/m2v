"""
阿里通义万相 WanX 2.1 提示词编译器 (WanPromptCompiler)
----------------------------------------------------
专为 Alibaba WanX 2.1 物理写实视频模型定制：
1. 强化传统中国美学、写实光线透射与高动态范围质感。
2. 注入构图安全区规避指令。
"""
from __future__ import annotations

from typing import Optional
from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


class WanPromptCompiler(BasePromptCompiler):
    model_name: str = "wan"

    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        clean_visual = (shot.prompt_en or shot.action or "Cinematic scene").replace("Chinese text", "scene")
        scale = shot.shot_size or shot.scale or "MS"
        motion = shot.camera_motion or "static"

        prompt_str = (
            f"极致电影质感，大师运镜，{scale} 景别，{clean_visual}，"
            f"真实物理光照，高级胶片色调，4K 超清细节，{motion} 运镜，无杂质纯净画面。"
        )

        negative_str = (
            "文字，字幕，乱码，水印，畸变，粗糙低模，重影，低光噪点，过度曝光，非真实感"
        )

        return ModelPromptPayload(
            model_name="alibaba_wanx_2_1",
            prompt=prompt_str,
            negative_prompt=negative_str,
            aspect_ratio="16:9",
            duration_seconds=min(8.0, max(2.5, round(shot.duration, 1))),
            camera_motion=motion,
            camera_motion_scale=1.0,
            cfg_scale=6.5,
            extra_params={
                "hdr": True,
                "composition_guidance": shot.layout_contract.primary_subject_zone if shot.layout_contract else "center",
            },
        )
