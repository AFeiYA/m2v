"""
Google Veo 提示词编译器 (VeoPromptCompiler)
------------------------------------------
专为 Google DeepMind Veo 视频大模型量身定制：
1. 注重 8K 超高清胶片纹理描述与物理光照。
2. 支持首尾帧 Conditioning (first_frame_path, last_frame_path)。
3. 严格禁止视频画面中直接生成文字与字母。
"""
from __future__ import annotations

from typing import Optional
from src.compilers.base import BasePromptCompiler, ModelPromptPayload
from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


class VeoPromptCompiler(BasePromptCompiler):
    model_name: str = "veo"

    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        cam_tokens = self._build_camera_tokens(shot, bibles)
        lighting_tokens = self._build_lighting_tokens(shot, bibles)

        # 核心画面描述
        visual_core = shot.prompt_en or shot.action or "Cinematic scene"
        # 剥离任何可能误生成的文字描述
        clean_visual = visual_core.replace("Chinese text", "subject").replace("subtitles", "")

        # Veo 风格前缀与后缀
        style_prefix = "Photorealistic 8k cinematic master shot, 35mm film stock, Arri Alexa Mini LF"
        aesthetic_suffix = "high dynamic range, shallow depth of field, award-winning cinematography"

        full_prompt = (
            f"{style_prefix}. {clean_visual}. "
            f"Camera & Cinematography: {cam_tokens}. Lighting & Atmosphere: {lighting_tokens}. {aesthetic_suffix}."
        )

        negative_prompt = self._build_forbidden_negative(bibles)

        # 构图安全区提示 (注入 extra_params)
        safe_zone_hint = None
        if shot.layout_contract:
            safe_zone_hint = {
                "primary_subject_zone": shot.layout_contract.primary_subject_zone,
                "primary_subject_x": shot.layout_contract.primary_subject_x,
                "primary_subject_y": shot.layout_contract.primary_subject_y,
            }

        return ModelPromptPayload(
            model_name="google_veo",
            prompt=full_prompt,
            negative_prompt=negative_prompt,
            aspect_ratio="16:9",
            duration_seconds=round(shot.duration, 2),
            camera_motion=shot.camera_motion or "static",
            camera_motion_scale=1.0,
            cfg_scale=7.5,
            first_frame_path=shot.preview_image if shot.preview_image else None,
            extra_params={
                "safe_zone": safe_zone_hint,
                "dramatic_intent": shot.dramatic_intent or shot.director_note,
                "sequence_id": sequence.id if sequence else "",
            },
        )
