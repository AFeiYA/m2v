"""
M2V / Suno2MV 视听与 AI 导演领域模型规范 (Pydantic v2)
-------------------------------------------------------
定义音乐理解、AI 导演剧作、视觉圣经 (Visual Bible Prefabs)、
卡点分镜 (Shots/Takes) 与非线性时间轴 (NLE Timeline) 数据契约。
保证 100% 兼容历史工程文件并提供强大的序列化与校验能力。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================================
# 1. 歌词与字级时间戳契约
# ============================================================================

class WordTimestamp(BaseModel):
    """单个字/词的时间戳 (毫秒级精度)"""
    word: str = Field(..., description="单个字或词的文本")
    start: float = Field(..., ge=0, description="起始时间(秒)")
    end: float = Field(..., ge=0, description="结束时间(秒)")

    @model_validator(mode="after")
    def validate_duration(self) -> "WordTimestamp":
        if self.end < self.start - 0.01:
            raise ValueError(f"字 '{self.word}' 结束时间 ({self.end}) 小于起始时间 ({self.start})")
        return self


class AlignedLine(BaseModel):
    """一行对齐后的歌词"""
    text: str = Field(..., description="歌词整行文本")
    start: float = Field(..., ge=0, description="行起始时间(秒)")
    end: float = Field(..., ge=0, description="行结束时间(秒)")
    words: list[WordTimestamp] = Field(default_factory=list, description="字级时间戳列表")
    style_overrides: dict[str, Any] = Field(default_factory=dict, description="样式覆盖参数")
    section: str = Field(default="", description="归属乐段名称，如 'Verse 1', 'Chorus'")

    @model_validator(mode="after")
    def validate_line(self) -> "AlignedLine":
        if self.words:
            self.start = self.words[0].start
            self.end = self.words[-1].end
        if self.end < self.start:
            raise ValueError(f"行 '{self.text}' 结束时间 ({self.end}) 小于起始时间 ({self.start})")
        return self


# ============================================================================
# 2. 音乐智能与乐段骨架
# ============================================================================

class MusicSection(BaseModel):
    """音乐乐段划分 (Intro, Verse, Chorus, Bridge, Outro 等)"""
    name: str = Field(..., description="乐段英文标识，如 'Intro', 'Verse 1', 'Chorus 2'")
    label: str = Field(default="", description="中文标签，如 '前奏', '主歌 1', '副歌 2', '桥段', '尾奏'")
    style: str = Field(default="", description="乐器、演奏指导与情绪描述 (来自 Suno Prompt)")
    start: float = Field(default=0.0, ge=0, description="乐段绝对起始时间(秒)")
    end: float = Field(default=0.0, ge=0, description="乐段绝对结束时间(秒)")
    energy: float = Field(default=0.5, ge=0.0, le=1.0, description="乐段平均能量/情绪强度 (0.0~1.0)")
    line_indices: list[int] = Field(default_factory=list, description="归属于该乐段的歌词行索引列表")


class MusicCutPoint(BaseModel):
    """基于音频特征自动提取的推荐剪辑切刀点 (Cut Candidate)"""
    time: float = Field(..., ge=0, description="切点时间(秒)")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="置信度评分")
    source: Literal["drum_onset", "energy_jump", "downbeat", "vocal_silence", "section_boundary", "manual"] = Field(
        default="drum_onset", description="切点来源"
    )
    strength: float = Field(default=0.5, ge=0.0, le=1.0, description="冲击力/能量强度")
    suggested_shot_size: str | None = Field(default=None, description="推荐景别反差建议")


class SongAnalysis(BaseModel):
    """全曲音乐智能感知元数据"""
    bpm: float = Field(default=120.0, description="曲目估算 BPM")
    duration: float = Field(default=0.0, ge=0, description="音频总时长(秒)")
    beats: list[float] = Field(default_factory=list, description="节拍时间点列表(秒)")
    downbeats: list[float] = Field(default_factory=list, description="小节重拍点列表(秒)")
    energy_curve: list[dict[str, float]] = Field(default_factory=list, description="时域能量采样序列 [{time, energy}]")
    drum_hits: list[dict[str, Any]] = Field(default_factory=list, description="鼓点打击事件 (Kick, Snare, Hi-Hat)")
    cut_candidates: list[MusicCutPoint] = Field(default_factory=list, description="推荐硬切剪辑点序列")
    sections: list[MusicSection] = Field(default_factory=list, description="解析出的乐段骨架")


# ============================================================================
# 3. 视觉圣经资产预制体 (Visual Bible Prefabs)
# ============================================================================

class CharacterPrefab(BaseModel):
    """角色实体预制体 (保证 30 个镜头角色外貌一致性)"""
    id: str = Field(..., description="角色唯一标识，如 'char_01', 'lead_female'")
    name: str = Field(..., description="角色名称")
    role: str = Field(default="protagonist", description="剧作定位: protagonist, antagonist, supporting")
    appearance: str = Field(default="", description="长相、年龄、发型、体态等恒定特征")
    wardrobe: str = Field(default="", description="固定服装与饰品 (如 'white linen shirt, silver pendant')")
    canonical_tokens: list[str] = Field(default_factory=list, description="每次生成强制注入的角色正向提示词")
    forbidden_tokens: list[str] = Field(default_factory=list, description="严禁变动的负向特征 (如 'long hair', 'glasses')")
    keyframe_pack: list[str] = Field(default_factory=list, description="参考三视图或定妆照路径列表")


class LocationPrefab(BaseModel):
    """场景实体预制体 (保证空间与光影基调统一)"""
    id: str = Field(..., description="场景唯一标识，如 'loc_station', 'loc_apartment'")
    name: str = Field(..., description="场景名称")
    spatial_layout: str = Field(default="", description="空间结构、材质与环境陈设")
    canonical_lighting: str = Field(default="", description="核心光照与色彩特征 (如 'dusk overcast, cyan shadows')")
    time_of_day: str = Field(default="day", description="时间段: dawn, day, dusk, night, neon_night")
    master_references: list[str] = Field(default_factory=list, description="场景概念原画/主参考图路径")


class StylePrefab(BaseModel):
    """全局摄影与影调风格规范"""
    visual_style: str = Field(default="cinematic realism", description="画风基调: cinematic realism, anime, etc.")
    color_palette: list[str] = Field(default_factory=list, description="调色板 Hex 色值或名称")
    lens_spec: str = Field(default="35mm anamorphic, f/1.8", description="摄影镜头规格")
    lighting_mood: str = Field(default="naturalistic volumetric light", description="光影情绪")
    film_grain: str = Field(default="subtle 35mm grain", description="胶片颗粒度")
    negative_prompt: str = Field(default="blurry, distorted, low quality, cartoon, watermark", description="通用负向词")


class VisualBible(BaseModel):
    """视觉圣经与世界观概念设定 (兼顾旧版扁平字段与新版 Prefab 资产体系)"""
    title: str = Field(default="", description="MV 企划名称")
    theme: str = Field(default="", description="核心主题与意境")
    narrative_synopsis: str = Field(default="", description="视觉叙事梗概/故事情节")
    color_palette: list[str] = Field(default_factory=list, description="主辅色调色盘")
    visual_style_anchor: str = Field(default="", description="全局摄影与画风基准词")
    character_anchor: str = Field(default="", description="主角/核心主体特征描述")
    environment_anchor: str = Field(default="", description="主要场景与光影基调")

    # 新版 Prefab 资产库
    characters: list[CharacterPrefab] = Field(default_factory=list, description="角色资产库")
    locations: list[LocationPrefab] = Field(default_factory=list, description="场景资产库")
    style: StylePrefab | None = Field(default=None, description="影调摄影规范")


# ============================================================================
# 4. 导演分镜、镜头与多 Take 架构 (Shot & Take System)
# ============================================================================

class Take(BaseModel):
    """单镜头的单次生成候选 (Take)"""
    id: str = Field(..., description="Take 唯一标识，如 'take_001'")
    shot_id: str = Field(..., description="关联的分镜 Shot ID")
    provider: str = Field(default="storyboard_mock", description="生成服务商: storyboard_mock, flux, veo, seedance, wan")
    media_type: Literal["image", "video"] = Field(default="image", description="素材形态: 'image' 或 'video'")
    media_path: str = Field(default="", description="生成产物文件路径或 URL")
    prompt: str = Field(default="", description="实际发送给模型的完整 Prompt")
    seed: int | None = Field(default=None, description="随机种子")
    cost: float = Field(default=0.0, ge=0, description="本次生成估算成本 (美元)")
    selected: bool = Field(default=False, description="是否被选定为最终正片素材")
    score: float = Field(default=0.0, ge=0, le=5.0, description="导演打分/评分 (0~5 星)")


class ShotPlan(BaseModel):
    """
    分镜镜头模型 (Shot Specification)
    同时兼容老版合成器字段与新版 AI 导演 Story Graph 约束。
    """
    # 基础物理时间与序号
    shot_id: int = Field(default=1, description="分镜序号 (数字)")
    id: str = Field(default="", description="分镜字符串标识，如 'shot_001'")
    type: str = Field(default="image", description="素材类型: 'image' 或 'video'")
    path: str = Field(default="", description="最终选定素材路径 (合成器与旧版兼容)")
    start: float = Field(default=0.0, ge=0, description="镜头起始时间(秒)")
    end: float = Field(default=0.0, ge=0, description="镜头结束时间(秒)")
    speed_align: bool = Field(default=True, description="是否自动变速对齐时间区间")

    # 影视视听与 AI 提示词字段 (兼容旧版)
    scale: str = Field(default="Medium", description="景别: ExtremeWide/Wide/Medium/CloseUp/Macro")
    camera_movement: str = Field(default="Static", description="运镜动作: Pan/Tilt/ZoomIn/ZoomOut/Tracking/Static")
    prompt_zh: str = Field(default="", description="中文构图、光影与动作描述")
    prompt_en: str = Field(default="", description="英文生成提示词")
    section_name: str = Field(default="", description="归属乐段名称")
    line_indices: list[int] = Field(default_factory=list, description="关联的歌词行序号")

    # 新版影视级分镜与因果链 (Story Graph)
    narrative_goal: str = Field(default="", description="本镜头的叙事目的与戏剧动作")
    lyric_reference: str = Field(default="", description="本镜头对应的歌词原句或意象")
    character_ids: list[str] = Field(default_factory=list, description="出场角色 Prefab ID 列表")
    location_id: str = Field(default="", description="所属场景 Prefab ID")
    shot_size: str = Field(default="MS", description="专业景别: ECU, CU, MCU, MS, MLS, WS, EWS")
    camera_motion: str = Field(
        default="static",
        description="专业运镜: static, slow_dolly_in, dolly_out, pan_left, pan_right, tilt_up, tilt_down, tracking, crane_up, handheld"
    )
    camera_angle: str = Field(default="eye_level", description="拍摄机位: eye_level, low_angle, high_angle, overhead, dutch_angle")
    action: str = Field(default="", description="被摄主体的核心动作与微表情")
    emotion: str = Field(default="", description="情感张力 (如 loneliness, surge of hope, hesitation)")
    match_cut_element: str | None = Field(default=None, description="匹配剪辑/转场关联元素")
    previous_shot_id: str | None = Field(default=None, description="前序镜头依赖 ID (保证因果与视线不跳轴)")
    next_shot_id: str | None = Field(default=None, description="后序镜头依赖 ID")

    # 动态故事板 (Animatic) 与多候选 Take 管理
    preview_image: str = Field(default="", description="动态故事板 (Animatic) 静态预览卡片图路径")
    takes: list[Take] = Field(default_factory=list, description="候选生成素材列表 (Takes)")
    selected_take_id: str | None = Field(default=None, description="选中的 Take ID")

    @property
    def duration(self) -> float:
        """镜头持续秒数"""
        return max(0.0, self.end - self.start)

    @model_validator(mode="after")
    def validate_shot(self) -> "ShotPlan":
        if not self.id:
            self.id = f"shot_{self.shot_id:03d}"
        if self.end > 0 and self.end < self.start:
            raise ValueError(f"镜头 {self.shot_id} 结束时间 ({self.end}) 不能小于起始时间 ({self.start})")
        # 兼容性同步：保证 scale 和 shot_size、camera_movement 和 camera_motion 互通
        if self.scale != "Medium" and self.shot_size == "MS":
            self.shot_size = self.scale
        elif self.shot_size != "MS" and self.scale == "Medium":
            self.scale = self.shot_size

        if self.camera_movement != "Static" and self.camera_motion == "static":
            self.camera_motion = self.camera_movement.lower()
        elif self.camera_motion != "static" and self.camera_movement == "Static":
            self.camera_movement = self.camera_motion

        if not self.preview_image and self.path:
            self.preview_image = self.path
        elif not self.path and self.preview_image:
            self.path = self.preview_image
        return self


# 保持对旧代码导入名称的兼容别名
Shot = ShotPlan
StoryboardEvent = ShotPlan


# ============================================================================
# 5. 非线性剪辑时间轴与片段 (NLE Timeline)
# ============================================================================

class NLEClip(BaseModel):
    """
    非线性编辑剪辑片段 (NLE Clip)
    解耦物理生成视频与时间线位置，支持非破坏性出入点裁剪、平滑变速。
    """
    id: str = Field(..., description="Clip 唯一标识")
    shot_id: str = Field(..., description="关联的 Shot ID")
    take_id: str = Field(default="", description="关联的 Take ID")
    source_media_path: str = Field(default="", description="物理源视频/图片路径")
    source_in: float = Field(default=0.0, ge=0, description="素材入点(秒)")
    source_out: float = Field(default=0.0, ge=0, description="素材出点(秒)")
    timeline_in: float = Field(default=0.0, ge=0, description="时间线入点(秒)")
    timeline_out: float = Field(default=0.0, ge=0, description="时间线出点(秒)")
    speed: float = Field(default=1.0, gt=0, description="播放速度倍率 (用于时间差微调)")
    transition_in: str = Field(default="cut", description="入点转场: cut, crossfade, dip_to_black")
    transition_out: str = Field(default="cut", description="出点转场: cut, crossfade, dip_to_black")

    @property
    def timeline_duration(self) -> float:
        return max(0.0, self.timeline_out - self.timeline_in)


class DirectorTreatment(BaseModel):
    """1 页纸导演阐述方案 (AI Director Treatment)"""
    title: str = Field(default="", description="MV 标题")
    logline: str = Field(default="", description="一句话核心剧情/意境摘要")
    visual_theme: str = Field(default="", description="核心视觉隐喻与主题词")
    director_statement: str = Field(default="", description="导演视听设计构想与艺术阐述")
    visual_metaphors: list[str] = Field(default_factory=list, description="关键视觉意象列表")
    acts: list[dict[str, Any]] = Field(default_factory=list, description="三幕式/乐段叙事拆解大纲")


# ============================================================================
# 6. 核心工程对象 (Project / AlignmentProject)
# ============================================================================

class AlignmentProject(BaseModel):
    """
    Suno2MV 核心工程模型 (对应 *_alignment.json 与 *_project.json)
    整合歌词时间轴、乐段、音乐智能、导演方案、视觉圣经、分镜镜头与时间线。
    全面向下兼容原有 AlignmentProject 接口。
    """
    title: str = Field(default="", description="歌曲名称")
    audio_path: str = Field(default="", description="原始全曲音频路径")
    vocals_path: str = Field(default="", description="人声干音路径")
    instrumental_path: str = Field(default="", description="伴奏音频路径")
    duration: float = Field(default=0.0, ge=0, description="歌曲总时长(秒)")

    # 歌词与乐段骨架
    lines: list[AlignedLine] = Field(default_factory=list, description="歌词行列表")
    sections: list[MusicSection] = Field(default_factory=list, description="乐段骨架列表")

    # 分镜与视觉圣经
    storyboard: list[ShotPlan] = Field(default_factory=list, description="分镜镜头列表 (Shot 序列)")
    background: str | None = Field(default=None, description="全局默认背景图路径")
    visual_bible: VisualBible | None = Field(default=None, description="视觉圣经设定")

    # 新版模块化引擎产物
    analysis: SongAnalysis | None = Field(default=None, description="音乐智能与切点分析")
    treatment: DirectorTreatment | None = Field(default=None, description="AI 导演方案")
    timeline: list[NLEClip] = Field(default_factory=list, description="非线性剪辑时间线序列")

    @property
    def shots(self) -> list[ShotPlan]:
        """别名访问 storyboard 镜头列表"""
        return self.storyboard

    @shots.setter
    def shots(self, value: list[ShotPlan]) -> None:
        self.storyboard = value

    def to_dict(self) -> dict[str, Any]:
        """序列化为标准字典格式"""
        return self.model_dump(exclude_none=True)

    def save_json(self, path: Path | str) -> None:
        """保存为 JSON 文件"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @classmethod
    def load_json(cls, path: Path | str) -> "AlignmentProject":
        """从 JSON 文件加载并严格校验 (支持老版本平滑升级)"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"工程文件不存在: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.model_validate(data)


# 保持对旧代码导入名称的兼容别名
Project = AlignmentProject
AlignmentResult = AlignmentProject
