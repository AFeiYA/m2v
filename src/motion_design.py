"""Authoring document: shared theme and independently editable visual modes."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from src.motion_director import MotionPlan


class DesignModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Theme(DesignModel):
    palette: str = Field(default='impact', min_length=1, max_length=64)
    background: Literal['auto', 'dark', 'light'] = 'auto'


class ModeSettings(DesignModel):
    aspect: Literal['16:9', '9:16'] = '16:9'
    theme: Theme | None = None
    post: bool = True
    bloom: float = Field(default=.7, ge=0, le=1.4, allow_inf_nan=False)
    shake: float = Field(default=.65, ge=0, le=1.5, allow_inf_nan=False)


class KineticDesign(ModeSettings):
    layout: Literal['smart', 'random', 'single', 'two-stack', 'three-stack', 'word-by-word'] = 'smart'
    highlight: Literal['none', 'word', 'sweep'] = 'none'
    plan: MotionPlan | None = None


class AppleDesign(ModeSettings):
    aspect: Literal['16:9', '9:16'] = '9:16'
    font_scale: float = Field(default=1, ge=.7, le=1.4, allow_inf_nan=False)
    focus_y: float = Field(default=.42, ge=.3, le=.6, allow_inf_nan=False)


class KaraokeDesign(ModeSettings):
    font_scale: float = Field(default=1, ge=.7, le=1.4, allow_inf_nan=False)
    preview_seconds: float = Field(default=2.5, ge=0, le=8, allow_inf_nan=False)


class Modes(DesignModel):
    kinetic: KineticDesign = Field(default_factory=KineticDesign)
    apple: AppleDesign = Field(default_factory=AppleDesign)
    tv: KaraokeDesign = Field(default_factory=KaraokeDesign)


class MotionDesign(DesignModel):
    version: Literal['motion-design-v1'] = 'motion-design-v1'
    active_mode: Literal['kinetic', 'apple', 'tv'] = 'kinetic'
    theme: Theme = Field(default_factory=Theme)
    height: Literal[360, 720] = 720
    modes: Modes = Field(default_factory=Modes)
