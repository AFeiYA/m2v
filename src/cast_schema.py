"""
Cast Studio Domain Models (Pydantic v2)
---------------------------------------
Decoupled multi-layer specification for Virtual Character Identity,
Consistent Visual DNA, Outfits, Assets, Versioning, and Song Bindings.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from src.storyboard_schema import CharacterPrefab


class CharacterIdentity(BaseModel):
    """Core character conceptual identity and invariants."""
    name: str = Field(..., description="Character primary name")
    alias: str = Field(..., description="Stage name, alias, or codename")
    age: int = Field(16, ge=1, le=1000, description="Canonical character age")
    age_locked: bool = Field(True, description="Locks age from accidental prompt drift")
    gender: str = Field(..., description="Gender presentation")
    tagline: str = Field(..., description="One-line defining concept")
    archetype: str = Field(..., description="Character archetype")
    core_contradiction: str = Field(..., description="Internal contradiction / dramatic tension")
    personality_traits: list[str] = Field(default_factory=list, description="Key personality keywords")


class VisualHair(BaseModel):
    style: str = Field(..., description="Hairstyle and base cut")
    color: str = Field(..., description="Base hair color with exact shade")
    highlights: str = Field("", description="Optional highlights or tint accents")
    texture: str = Field("", description="Hair texture (e.g. silky, messy, sharp spikes)")


class VisualEyes(BaseModel):
    shape: str = Field(..., description="Eye shape (e.g. sharp elongated almond, gentle round)")
    iris_color: str = Field(..., description="Iris color and specific luminosity")
    pupil_feature: str = Field("", description="Unique pupil pattern or glint")
    gaze_expression: str = Field("", description="Habitual gaze mood (e.g. piercing, calculating)")


class CharacterFaceInvariants(BaseModel):
    """Facial geometry that remains unchanged across different outfits and scenes."""
    silhouette: str = Field(..., description="Body build and signature silhouette shape")
    hair: VisualHair
    eyes: VisualEyes
    facial_marks: list[str] = Field(default_factory=list, description="Permanent face anchors: mole, piercing, scar")


class CharacterColorPalette(BaseModel):
    dominant_hex: str = Field(..., description="Dominant color hex code (#RRGGBB)")
    dominant_name: str = Field(..., description="Descriptive name")
    secondary_hex: str = Field(..., description="Secondary color hex code")
    secondary_name: str = Field(..., description="Descriptive name")
    accent_hex: str = Field(..., description="Accent / pop color hex code")
    accent_name: str = Field(..., description="Descriptive name")
    glow_accent: str = Field("", description="Optional neon or emissive glow hue")


class CharacterOutfit(BaseModel):
    """A specific wardrobe/costume setup. Characters can have multiple outfits across tracks."""
    id: str = Field(default="outfit_default", description="Outfit identifier (e.g. 'debut_techwear', 'acoustic_casual')")
    name: str = Field(default="Default Outfit", description="Readable outfit label")
    genre_style: str = Field(..., description="Fashion category (e.g. Avant-garde Techwear, Casual Vintage)")
    signature_outerwear: str = Field(..., description="Dominant jacket, coat, or cape")
    innerwear: str = Field(..., description="Shirt, top, or base layer")
    accessories: list[str] = Field(default_factory=list, description="Distinctive accessories")
    materials: list[str] = Field(default_factory=list, description="Fabrics and textures")
    color_palette: CharacterColorPalette
    signature_prop: str = Field("", description="Held prop or item associated with this outfit")


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


class PerformanceContext(BaseModel):
    """Track-specific stage setting and visual atmosphere (decoupled from the character)."""
    primary_environment: str = Field(..., description="Iconic stage or personal habitat for this song")
    lighting_atmosphere: str = Field(..., description="Signature lighting setup (e.g. strong rim light)")
    camera_feel: str = Field(..., description="Cinematic framing and lens perspective")


class PromptEngine(BaseModel):
    """Compiled generation parameters for diffusion models (Midjourney, Flux, ComfyUI)."""
    positive_character_anchor: str = Field(..., description="Front-loaded positive prompt keywords")
    negative_prompt_anchor: str = Field(..., description="Negative prompt keywords to avoid drift")
    recommended_aspect_ratios: list[str] = Field(default_factory=lambda: ["9:16", "16:9", "1:1"])


class CharacterAssets(BaseModel):
    """Reference image assets and thumbnails."""
    primary_image_url: str = Field("", description="Main confirmed portrait or half-body reference image")
    secondary_images: list[str] = Field(default_factory=list, description="Supplementary reference images or sheets")
    thumbnail_url: str = Field("", description="Compact avatar thumbnail for UI badges")


class CharacterVersioning(BaseModel):
    """Explicit version control preventing prompt overwrite or unconfirmed drift."""
    version: int = Field(1, ge=1, description="Sequential version counter (e.g. 1 for v1)")
    is_locked: bool = Field(False, description="Whether the baseline is confirmed and protected against overwrite")
    confirmed_at: str | None = Field(None, description="ISO timestamp of baseline confirmation")


class CharacterProfile(BaseModel):
    """Complete root model for a Cast Studio character."""
    id: str = Field(..., description="Unique slug ID (e.g. char_golden_0618)")
    user_id: str = Field(default="default_local", description="Owner user ID or 'system' for official characters")
    visibility: Literal["private", "public"] = Field(default="private", description="Visibility scope ('private' or 'public')")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    identity: CharacterIdentity
    face_invariants: CharacterFaceInvariants
    active_outfit_id: str = Field(default="outfit_default")
    outfits: list[CharacterOutfit] = Field(default_factory=list)
    expression_sheet: ExpressionSheet
    vocal_profile: VocalProfile
    performance_context: PerformanceContext
    prompt_engine: PromptEngine
    assets: CharacterAssets = Field(default_factory=CharacterAssets)
    versioning: CharacterVersioning = Field(default_factory=CharacterVersioning)
    bound_songs: list[str] = Field(default_factory=list, description="Song IDs currently bound to this character")

    @property
    def is_official(self) -> bool:
        return self.user_id == "system" or self.visibility == "public"

    @property
    def active_outfit(self) -> CharacterOutfit:
        for outfit in self.outfits:
            if outfit.id == self.active_outfit_id:
                return outfit
        if self.outfits:
            return self.outfits[0]
        raise ValueError(f"No outfits available for character {self.id}")

    def to_character_prefab(self, role: str = "protagonist") -> CharacterPrefab:
        """
        Converts this rich profile into the existing director/storyboard CharacterPrefab.
        Ensures 100% interoperability with Director Engine and multi-pass storyboard generation.
        """
        outfit = self.active_outfit
        marks_str = ", ".join(self.face_invariants.facial_marks)
        appearance_desc = (
            f"{self.identity.name}, age {self.identity.age}, {self.identity.gender}, "
            f"{self.face_invariants.silhouette}, hair: {self.face_invariants.hair.color} {self.face_invariants.hair.style}, "
            f"eyes: {self.face_invariants.eyes.iris_color} {self.face_invariants.eyes.shape}"
            + (f", marks: {marks_str}" if marks_str else "")
        )
        wardrobe_desc = f"{outfit.signature_outerwear}, {outfit.innerwear}, style: {outfit.genre_style}"
        canonical_tokens = [tok.strip() for tok in self.prompt_engine.positive_character_anchor.split(",") if tok.strip()]
        forbidden_tokens = [tok.strip() for tok in self.prompt_engine.negative_prompt_anchor.split(",") if tok.strip()]
        keyframes = [self.assets.primary_image_url] if self.assets.primary_image_url else []
        keyframes.extend(self.assets.secondary_images)

        return CharacterPrefab(
            id=self.id,
            name=self.identity.name,
            role=role,
            appearance=appearance_desc,
            wardrobe=wardrobe_desc,
            canonical_tokens=canonical_tokens,
            forbidden_tokens=forbidden_tokens,
            keyframe_pack=keyframes,
        )

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
