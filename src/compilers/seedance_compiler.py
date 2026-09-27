"""
字节跳动 Seedance 2.5 提示词编译器 (SeedancePromptCompiler)
-------------------------------------------------------
专为 Seedance 2.5 (即梦 / 豆包视频) 定制：
1. 支持多模态参考锚点 (从 AssetBible 提取角色和场景参考图)。
2. 支持长片段生成与细粒度语义动作控制。
3. 严格遵循构图安全区。
"""
from __future__ import annotations

from typing import List, Optional
from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


class SeedancePromptCompiler(BasePromptCompiler):
    model_name: str = "seedance"

    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        clean_visual = (shot.prompt_en or shot.action or "Cinematic scene").replace("Chinese text", "subject")
        cam_tokens = self._build_camera_tokens(shot, bibles)

        # 收集参考图像
        ref_images: List[str] = []
        if bibles and bibles.asset_bible:
            # 关联角色参考图
            for cid in shot.character_ids:
                char = bibles.asset_bible.get_character(cid)
                if char and char.reference_image:
                    ref_images.append(char.reference_image)
            # 关联场景参考图
            if shot.location_id:
                loc = bibles.asset_bible.get_location(shot.location_id)
                if loc and loc.reference_image:
                    ref_images.append(loc.reference_image)

        prompt_str = (
            f"Masterpiece cinematic shot: {clean_visual}. "
            f"Cinematography: {cam_tokens}. Natural lighting, photorealistic textures, 8k resolution."
        )

        negative_str = self._build_forbidden_negative(bibles)

        return ModelPromptPayload(
            model_name="bytedance_seedance_2_5",
            prompt=prompt_str,
            negative_prompt=negative_str,
            aspect_ratio="16:9",
            duration_seconds=round(shot.duration, 2),
            camera_motion=shot.camera_motion or "static",
            camera_motion_scale=1.0,
            reference_images=ref_images,
            extra_params={
                "continuity_weight": 0.85,
                "motion_smoothness": 0.9,
                "allow_extended_generation": shot.duration > 5.0,
            },
        )
