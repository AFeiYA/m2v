"""
Cast Studio Domain Models (Pydantic v2)
---------------------------------------
Formal specification for Virtual Character Identity, Consistent Visual DNA,
Vocal Profile, Stage Aesthetics, and Prompt Generation Protocols.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class CharacterIdentity(BaseModel):
    """Core character conceptual identity and dramatic tension."""
    name: str = Field(..., description="Character primary name")
    alias: str = Field(..., description="Stage name, alias, or codename")
    tagline: str = Field(..., description="One-line defining concept")
    archetype: str = Field(..., description="Character archetype (e.g. 'Genius Perfectionist Rebel')")
    core_contradiction: str = Field(..., description="Internal contradiction / dramatic tension")
    personality_traits: list[str] = Field(default_factory=list, description="Key personality keywords")


class VisualHair(BaseModel):
    style: str = Field(..., description="Hairstyle and cut")
    color: str = Field(..., description="Base hair color with exact shade")
    highlights: str = Field("", description="Optional highlights or tint accents")
    texture: str = Field("", description="Hair texture (e.g. silky, messy, sharp spikes)")


class VisualEyes(BaseModel):
    shape: str = Field(..., description="Eye shape (e.g. sharp almond, gentle droop, intense cat-eye)")
    iris_color: str = Field(..., description="Iris color and specific luminosity")
    pupil_feature: str = Field("", description="Unique pupil pattern or glint")
    gaze_expression: str = Field("", description="Habitual gaze mood (e.g. piercing, melancholic)")


class VisualWardrobe(BaseModel):
    genre_style: str = Field(..., description="Fashion category (e.g. Techwear Streetwear, Cyber Goth)")
    signature_outerwear: str = Field(..., description="Dominant jacket, coat, or cape")
    innerwear: str = Field(..., description="Shirt, top, or base layer")
    accessories: list[str] = Field(default_factory=list, description="Distinctive accessories")
    materials: list[str] = Field(default_factory=list, description="Fabrics and textures")


class VisualColorPalette(BaseModel):
    dominant_hex: str = Field(..., description="Dominant color hex code (#RRGGBB)")
    dominant_name: str = Field(..., description="Descriptive name")
    secondary_hex: str = Field(..., description="Secondary color hex code")
    secondary_name: str = Field(..., description="Descriptive name")
    accent_hex: str = Field(..., description="Accent / pop color hex code")
    accent_name: str = Field(..., description="Descriptive name")
    glow_accent: str = Field("", description="Optional neon or emissive glow hue")


class VisualDNA(BaseModel):
    """Invariants and visual anchors ensuring cross-scene AI consistency."""
    gender: str = Field(..., description="Gender presentation")
    age_appearance: str = Field(..., description="Visual perceived age")
    silhouette: str = Field(..., description="Body build and signature silhouette shape")
    hair: VisualHair
    eyes: VisualEyes
    facial_marks: list[str] = Field(default_factory=list, description="Face anchors: mole, piercing, scar")
    wardrobe: VisualWardrobe
    color_palette: VisualColorPalette
    signature_prop: str = Field("", description="Iconic handheld prop, totem, or symbolic tool")


class ExpressionSheet(BaseModel):
    """Key emotional micro-expressions for character performance."""
    neutral: str = Field(..., description="Resting expression with personal mood")
    performance_focus: str = Field(..., description="Intensity during singing or intense action")
    vulnerable_climax: str = Field(..., description="Raw emotional vulnerability or climax")
    smug_ironic: str = Field(..., description="Playful, mocking, or confident smirk")


class VocalProfile(BaseModel):
    """Acoustic identity and vocal characteristics."""
    timbre_description: str = Field(..., description="Voice texture and resonance")
    pitch_range: str = Field(..., description="Vocal range (e.g. High Tenor, Breathy Alto)")
    delivery_style: str = Field(..., description="Singing style and phrasing habits")
    signature_audio_tag: str = Field("", description="Intro tag, catchphrase, or signature laugh")


class StageAesthetic(BaseModel):
    """World environment, lighting, and camera direction."""
    primary_environment: str = Field(..., description="Iconic stage or personal habitat")
    lighting_atmosphere: str = Field(..., description="Signature lighting setup (e.g. strong rim light)")
    camera_feel: str = Field(..., description="Cinematic framing and lens perspective")


class PromptEngine(BaseModel):
    """Compiled generation parameters for diffusion models (Midjourney, Flux, ComfyUI)."""
    positive_character_anchor: str = Field(..., description="Front-loaded positive prompt keywords")
    negative_prompt_anchor: str = Field(..., description="Negative prompt keywords to avoid drift")
    recommended_aspect_ratios: list[str] = Field(default_factory=lambda: ["9:16", "16:9", "1:1"])


class CharacterProfile(BaseModel):
    """Complete root model for a Cast Studio character."""
    id: str = Field(..., description="Unique slug ID (e.g. char_golden_0618)")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    identity: CharacterIdentity
    visual_dna: VisualDNA
    expression_sheet: ExpressionSheet
    vocal_profile: VocalProfile
    stage_aesthetic: StageAesthetic
    prompt_engine: PromptEngine

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, data: str | dict[str, Any]) -> CharacterProfile:
        if isinstance(data, str):
            return cls.model_validate_json(data)
        return cls.model_validate(data)

    def save_file(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(indent=2), encoding="utf-8")

    @classmethod
    def load_file(cls, path: str | Path) -> CharacterProfile:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
