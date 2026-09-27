"""
PromptCompiler 基类与生成载荷定义
---------------------------------
将 Shot Specification 翻译为特定视频生成模型 (Veo / Kling / Seedance / Wan) 的专用输入。
Shot 本身是中立的导演事实，Prompt 则是模型特化的瞬时实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.storyboard_schema import GlobalBibles, SequencePlan, ShotPlan


@dataclass
class ModelPromptPayload:
    """
    针对具体视频生成模型的编译输出载荷 (Model-Agnostic Compilation Payload)
    """
    model_name: str
    prompt: str
    negative_prompt: str = ""
    aspect_ratio: str = "16:9"
    duration_seconds: float = 4.0
    camera_motion: str = "static"
    camera_motion_scale: float = 1.0
    cfg_scale: float = 7.0
    first_frame_path: Optional[str] = None
    last_frame_path: Optional[str] = None
    reference_images: List[str] = field(default_factory=list)
    seed: Optional[int] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "aspect_ratio": self.aspect_ratio,
            "duration_seconds": self.duration_seconds,
            "camera_motion": self.camera_motion,
            "camera_motion_scale": self.camera_motion_scale,
            "cfg_scale": self.cfg_scale,
            "first_frame_path": self.first_frame_path,
            "last_frame_path": self.last_frame_path,
            "reference_images": self.reference_images,
            "seed": self.seed,
            "extra_params": self.extra_params,
        }


class BasePromptCompiler(ABC):
    """
    视频提示词编译器抽象基类
    """
    model_name: str = "base"

    @abstractmethod
    def compile(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        """根据 Shot Specification 与全局圣经编译模型 Prompt"""
        pass

    def compile_keyframe(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        """编译首帧生图提示词载荷 (纯静态视觉与材质)"""
        return self.compile(shot, bibles=bibles, sequence=sequence)

    def compile_motion(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> ModelPromptPayload:
        """编译图生视频运镜与时空动势载荷 (去静态赘述，聚焦运镜轨迹与物理保真)"""
        return self.compile(shot, bibles=bibles, sequence=sequence)

    def compile_endframe(
        self,
        shot: ShotPlan,
        bibles: Optional[GlobalBibles] = None,
        sequence: Optional[SequencePlan] = None,
    ) -> Optional[ModelPromptPayload]:
        """编译尾帧生图提示词载荷 (可选，用于一镜到底或首尾帧插值)"""
        if not shot.endframe_prompt:
            return None
        return ModelPromptPayload(
            model_name="flux",
            prompt=shot.endframe_prompt,
            negative_prompt=self._build_forbidden_negative(bibles),
            aspect_ratio="16:9",
        )

    def _build_camera_tokens(self, shot: ShotPlan, bibles: Optional[GlobalBibles] = None) -> str:
        """构建机位与镜头参数提示词片段"""
        scale = shot.shot_size or shot.scale or "MS"
        motion = shot.camera_motion or shot.camera_movement or "static"
        lens = shot.lens_mm or 35
        return f"{scale} shot, {lens}mm anamorphic lens, {motion} camera movement"

    def _build_lighting_tokens(self, shot: ShotPlan, bibles: Optional[GlobalBibles] = None) -> str:
        """构建光影与色彩词"""
        lighting = shot.lighting or "natural cinematic lighting"
        palette_tokens = ""
        if bibles and bibles.visual_bible and bibles.visual_bible.color_palette:
            palette_tokens = f", color grading in {', '.join(bibles.visual_bible.color_palette[:2])}"
        return f"{lighting}{palette_tokens}"

    def _build_forbidden_negative(self, bibles: Optional[GlobalBibles] = None) -> str:
        """提取全局与默认负向提示词 (特别严禁在画面中直接绘制文字)"""
        base_negative = [
            "text", "subtitles", "watermark", "letters", "words", "captions",
            "Chinese characters", "distorted faces", "deformed limbs", "low quality",
            "blurry", "oversaturated", "amateurish", "cartoon", "3D CGI render look"
        ]
        if bibles and bibles.visual_bible and bibles.visual_bible.forbidden_elements:
            base_negative.extend(bibles.visual_bible.forbidden_elements)
        return ", ".join(list(dict.fromkeys(base_negative)))
