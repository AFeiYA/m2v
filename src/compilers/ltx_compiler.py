"""
Lightricks LTX-Video 提示词编译器 (LTXPromptCompiler)
----------------------------------------------------
专为 Lightricks LTX-Video (2B/0.9.x) 极速物理视频模型定制：
1. 强化英文物理动势、影视机位镜头与光影质感描述。
2. 注入严苛去文字 (No text/subtitles/watermarks) 负向提示词约束。
3. 适配 16:9 比例与高帧率时间轴节奏。
"""
from __future__ import annotations

from typing import Optional
from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


class LTXPromptCompiler(BasePromptCompiler):
    model_name: str = "ltx"

    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        return self.compile_motion(shot, bibles=bibles, sequence=sequence)

    def compile_motion(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        """
        专为 LTX-Video 图生视频 (I2V) 编译纯时空动势载荷：
        1. 优先使用专属 motion_prompt，杜绝重复描述静态材质引起的注意力稀释与形态沸腾。
        2. 注入刚体保真与抗形变约束 (Rigid body stability, anti-morphing)。
        3. 强化摄影机运动轨迹与平滑速率。
        """
        motion = shot.camera_motion or shot.camera_movement or "static"

        # LTX-Video 核心镜头运镜映射
        motion_map = {
            "static": "static camera, completely stable framing, subtle ambient micro-motion",
            "slow_dolly_in": "slow smooth dolly in, forward camera push, steady gliding speed",
            "dolly_out": "smooth steady dolly out, expanding spatial perspective",
            "pan_left": "cinematic smooth pan to the left, steady panning rate",
            "pan_right": "cinematic smooth pan to the right, steady panning rate",
            "crane_up": "crane up shot, smooth rising perspective",
            "tilt_up": "camera tilts up smoothly at constant speed",
            "tilt_down": "camera tilts down smoothly at constant speed",
            "tracking": "smooth tracking camera following motion vectors",
            "handheld": "subtle cinematic organic camera float, realistic handheld breathing",
        }
        motion_phrase = motion_map.get(motion.lower(), f"{motion} camera movement")

        if shot.motion_prompt:
            # 用户或导演给出了显式运镜物理描述
            clean_motion = shot.motion_prompt.strip()
            prompt_parts = [
                clean_motion,
                "steady continuous cinematic camera motion, smooth temporal dynamics, master cinematography",
            ]
        else:
            # 智能合成动静解耦的运镜描述（不重复描述画面物体外貌，只指示如何运动）
            action_desc = f", {shot.action}" if shot.action else ""
            prompt_parts = [
                motion_phrase,
                f"the primary subject remains a solid rigid structure without warping{action_desc}",
                "subtle light reflection shifts and ambient micro-dust drifting in air",
                "steady continuous speed, cinematic 16:9, master motion physics",
            ]

        positive_prompt = ", ".join(p for p in prompt_parts if p)

        # 视频专用负向提示词：严打形变、画面沸腾、闪烁与文字
        negative_prompt = (
            "morphing, warping, surface bubbling, boiling pixels, flickering, sudden jerky cuts, glitch, jitter, "
            "face distortion, deformed geometry, text, watermark, subtitles, captions, logos, low frame rate, "
            "cartoon, 3d cgi render, blurry"
        )

        return ModelPromptPayload(
            model_name="ltx-video-2b",
            prompt=positive_prompt,
            negative_prompt=negative_prompt,
            aspect_ratio="16:9",
            duration_seconds=min(5.0, max(1.5, round(shot.duration, 1))),
            camera_motion=motion,
            camera_motion_scale=1.0,
            cfg_scale=3.0,
            extra_params={
                "steps": 20,
                "fps": 16,
                "width": 768,
                "height": 448,
            },
        )

    def compile_keyframe(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        """回退兼容：若以 LTX 编译器编译首帧，转交给 FLUX 逻辑"""
        from src.compilers.flux_compiler import FluxPromptCompiler
        return FluxPromptCompiler().compile_keyframe(shot, bibles=bibles, sequence=sequence)
