"""
FLUX.1 电影首帧与尾帧提示词编译器 (FluxPromptCompiler)
-----------------------------------------------------
专为 Black Forest Labs FLUX.1 (Schnell / Dev 12B) 定制：
1. 聚焦纯静态材质微观、光学质感 (Depth of field, bokeh, lens mm)、自然布光与构图。
2. 严苛剔除任何运镜动词 (dolly, pan, tracking, tilt, zoom, motion)，消除运动模糊与重影。
3. 支持编译尾帧 (compile_endframe)，为一镜到底和首尾帧插值提供高质量终态画面。
"""
from __future__ import annotations

import re
from typing import Optional
from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


class FluxPromptCompiler(BasePromptCompiler):
    model_name: str = "flux"

    # 严禁在静态首帧出现的运镜与动态词汇
    MOTION_TERMS_PATTERN = re.compile(
        r"\b(slow\s+)?(dolly\s+in|dolly\s+out|dolly\s+inward|dolly\s+outward|pan\s+left|pan\s+right|tilt\s+up|tilt\s+down|"
        r"crane\s+up|crane\s+down|camera\s+tracking|camera\s+movement|tracking\s+shot|zoom\s+in|zoom\s+out|"
        r"push\s+in|pull\s+back|handheld\s+shake|moving\s+camera|orbit|fps)\b",
        re.IGNORECASE,
    )

    def _clean_static_prompt(self, text: str) -> str:
        """从提示词中剔除运动词汇并整理标点"""
        cleaned = self.MOTION_TERMS_PATTERN.sub("", text)
        cleaned = re.sub(r",\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" ,.")

    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        return self.compile_keyframe(shot, bibles=bibles, sequence=sequence)

    def compile_keyframe(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        # 1. 优先使用专属首帧提示词，若无则使用 prompt_en 并剔除运镜词
        raw_en = shot.keyframe_prompt or shot.prompt_en or shot.action or "Cinematic shot"
        clean_visual = self._clean_static_prompt(raw_en)

        scale = shot.shot_size or shot.scale or "MS"
        angle = shot.camera_angle or "eye_level"
        lens = shot.lens_mm or (85 if scale in ("ECU", "CU") else (35 if scale in ("WS", "EWS") else 50))
        lighting = shot.lighting or "natural cinematic soft grazing light"

        # 摄影光学描述
        optics_tokens = f"{lens}mm prime lens, f/1.8 shallow depth of field, sharp crisp focus, master photograph"

        scale_map = {
            "ECU": "extreme close-up macro photograph",
            "CU": "close-up photograph",
            "MCU": "medium close-up cinematic portrait",
            "MS": "medium cinematic shot",
            "MLS": "medium wide cinematic frame",
            "WS": "wide cinematic view",
            "EWS": "sweeping extreme wide landscape",
        }
        scale_phrase = scale_map.get(scale.upper(), f"{scale} shot")

        # 组装高保真静态 Prompt
        prompt_parts = [
            f"{scale_phrase} of {clean_visual}",
            f"{angle} perspective",
            optics_tokens,
            lighting,
            "photorealistic, 8k resolution, museum quality, tactile physical material texture, cinematic color grading, master cinematography",
        ]
        positive_prompt = ", ".join(p for p in prompt_parts if p)

        # 严苛去字、去畸变负向提示词
        negative_prompt = (
            "text, watermark, subtitles, captions, typography, logos, blur, motion blur, out of focus, "
            "overexposed, underexposed, deformed, distorted, extra limbs, bad anatomy, cartoon, 3d cgi render, "
            "plastic, flat lighting, amateur"
        )

        return ModelPromptPayload(
            model_name="flux-schnell",
            prompt=positive_prompt,
            negative_prompt=negative_prompt,
            aspect_ratio="16:9",
            duration_seconds=0.0,
            camera_motion="static",
            cfg_scale=1.0,
            extra_params={"steps": 4},
        )

    def compile_endframe(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> Optional[ModelPromptPayload]:
        if not shot.endframe_prompt:
            return None
        clean_visual = self._clean_static_prompt(shot.endframe_prompt)
        prompt = (
            f"Cinematic ending frame photograph, {clean_visual}, "
            f"master cinematography, photorealistic, 8k resolution, crisp texture, no text or watermark"
        )
        return ModelPromptPayload(
            model_name="flux-schnell",
            prompt=prompt,
            negative_prompt="text, watermark, subtitles, cartoon, 3d render, blurry, distorted",
            aspect_ratio="16:9",
            cfg_scale=1.0,
            extra_params={"steps": 4},
        )
