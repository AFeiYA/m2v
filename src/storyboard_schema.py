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
# 3. 动态控制与时域演进曲线 (Temporal Direction & Dynamic Curves)
# ============================================================================

class CurvePoint(BaseModel):
    """时间曲线控制点"""
    time: float = Field(..., ge=0, description="时间点(秒)")
    value: float = Field(..., ge=0.0, le=1.0, description="强度/能量值 (0.0~1.0)")
    label: str = Field(default="", description="关键事件或段落标注")


class TemporalDirection(BaseModel):
    """
    随时间演进的动态视听控制曲线 (解耦于静态 Bible)
    Music Energy ≠ Visual Intensity (支持对位蒙太奇与视听呼吸感)
    """
    music_energy: list[CurvePoint] = Field(default_factory=list, description="音频物理能量曲线")
    emotion_curve: list[CurvePoint] = Field(default_factory=list, description="戏剧剧情情绪起伏曲线")
    visual_intensity: list[CurvePoint] = Field(default_factory=list, description="导演视听张力曲线 (0.1 极简静止 ~ 1.0 史诗高潮)")


# ============================================================================
# 4. 全局美学与资产圣经 (Global Bibles & Prefabs)
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


class PropPrefab(BaseModel):
    """核心道具预制体 (保证关键道具与意象跨镜头一致)"""
    id: str = Field(..., description="道具唯一标识，如 'prop_porcelain_cup', 'prop_ancient_ship'")
    name: str = Field(..., description="道具名称")
    visual_features: str = Field(default="", description="材质、色调、时代痕迹与光影质感")
    symbolic_meaning: str = Field(default="", description="道具象征意象与戏剧功能")
    master_references: list[str] = Field(default_factory=list, description="道具概念图/实物参考图路径")


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

    # Prefab 资产库
    characters: list[CharacterPrefab] = Field(default_factory=list, description="角色资产库")
    locations: list[LocationPrefab] = Field(default_factory=list, description="场景资产库")
    props: list[PropPrefab] = Field(default_factory=list, description="关键道具资产库")
    style: StylePrefab | None = Field(default=None, description="影调摄影规范")
    forbidden_elements: list[str] = Field(default_factory=list, description="全局严禁出现的元素 (如现代汽车、文字、失真等)")


class MotifPrefab(BaseModel):
    """
    视觉母题预制体 (Motif Prefab)
    贯穿全片的视觉意象与图形隐喻，如：裂纹、同心圆、水波、飞鸟。
    支撑副歌视觉复沓 (Visual Callback) 与形态进化。
    """
    id: str = Field(..., description="母题标识，如 'motif_crack', 'motif_ripple'")
    name: str = Field(..., description="母题名称")
    core_concept: str = Field(..., description="核心隐喻概念 (如 '时间被封存在材质中')")
    manifestations: list[str] = Field(
        default_factory=list,
        description="在不同 Sequence/Shot 中的具象化形式 (如 '瓷器冰裂纹 -> 街巷石板裂痕 -> 巨轮钢板接缝')"
    )


class MotifBible(BaseModel):
    """母题圣经 (保证全片视觉深度与结构感)"""
    motifs: list[MotifPrefab] = Field(default_factory=list, description="全片视觉母题列表")


class TypographyBible(BaseModel):
    """排版与字体动效圣经 (解耦于画面 VisualBible)"""
    font_family: str = Field(default="Microsoft YaHei", description="主选字体名称或风格")
    primary_color: str = Field(default="#FFFFFF", description="主要文字颜色 (#RRGGBB)")
    secondary_color: str = Field(default="#888888", description="描边/副色 (#RRGGBB)")
    preferred_placement: str = Field(default="bottom_center", description="推荐排版位置: bottom_center, bottom_left, top_center, vertical_left")
    motion_personality: str = Field(default="calm_fade", description="排版动画性格: calm_fade, ink_bloom, kinetic_bold, typewriter")


class AssetBible(BaseModel):
    """统一资产连续性圣经 (角色、场景、核心道具)"""
    characters: list[CharacterPrefab] = Field(default_factory=list, description="角色资产库")
    locations: list[LocationPrefab] = Field(default_factory=list, description="场景资产库")
    props: list[PropPrefab] = Field(default_factory=list, description="关键道具资产库")


class GlobalBibles(BaseModel):
    """全局静态美学与资产圣经总集 (空间与风格不变量)"""
    visual: VisualBible | None = Field(default=None, description="视觉美学与摄影圣经")
    typography: TypographyBible | None = Field(default=None, description="排版动效圣经")
    assets: AssetBible | None = Field(default=None, description="角色/场景/道具资产圣经")
    motifs: MotifBible | None = Field(default=None, description="视觉母题圣经")

    @model_validator(mode="before")
    @classmethod
    def _alias_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "visual_bible" in data and "visual" not in data:
                data["visual"] = data.pop("visual_bible")
            if "typography_bible" in data and "typography" not in data:
                data["typography"] = data.pop("typography_bible")
            if "asset_bible" in data and "assets" not in data:
                data["assets"] = data.pop("asset_bible")
            if "motif_bible" in data and "motifs" not in data:
                data["motifs"] = data.pop("motif_bible")
        return data

    @property
    def visual_bible(self) -> VisualBible | None:
        return self.visual

    @property
    def typography_bible(self) -> TypographyBible | None:
        return self.typography

    @property
    def asset_bible(self) -> AssetBible | None:
        return self.assets

    @property
    def motif_bible(self) -> MotifBible | None:
        return self.motifs


# ============================================================================
# 5. 叙事序列宏观层 (Sequence Planning)
# ============================================================================

class SequencePlan(BaseModel):
    """
    叙事序列 / 乐段大幕 (Sequence / Narrative Movement)
    介于宏观 Treatment 与微观 Shot 之间的核心组织层。
    破除'一句歌词一个镜头'，以乐段叙事动作统领多个镜头。
    """
    id: str = Field(..., description="序列标识，如 'SEQ_01', 'SEQ_INTRO'")
    sequence_number: int = Field(default=1, description="序列序号 (1, 2, 3...)")
    title: str = Field(default="", description="本序列标题，如 '序章：微观瓷器与封存的时间'")
    start: float = Field(default=0.0, ge=0, description="序列起始时间(秒)")
    end: float = Field(default=0.0, ge=0, description="序列结束时间(秒)")
    dramatic_function: str = Field(default="", description="戏剧功能与核心动作推进 (如 '建立世界观', '情绪蓄势', '冲突爆发')")
    section_name: str = Field(default="", description="对应音乐乐段标识，如 'Intro', 'Verse 1', 'Chorus'")
    lyric_indices: list[int] = Field(default_factory=list, description="归属于该序列的歌词行索引")
    shot_ids: list[str] = Field(default_factory=list, description="包含的分镜 Shot ID 列表")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def time_range(self) -> tuple[float, float]:
        return (self.start, self.end)


# ============================================================================
# 6. 构图安全区契约与转场规格 (Layout Contract & Transitions)
# ============================================================================

class CompositionSafeZones(BaseModel):
    """
    构图安全区协议 (Layout Contract)
    协调视频画面主轨与字幕排版轨，防止字幕遮挡重要主体或人脸。
    """
    primary_subject_x: float = Field(default=0.5, ge=0.0, le=1.0, description="被摄主体归一化 X 坐标 (0.0 左 ~ 1.0 右)")
    primary_subject_y: float = Field(default=0.5, ge=0.0, le=1.0, description="被摄主体归一化 Y 坐标 (0.0 上 ~ 1.0 下)")
    protected_regions: list[str] = Field(
        default_factory=list,
        description="受保护禁止遮挡区域: center, center_left, center_right, bottom_center, bottom_left, etc."
    )
    preferred_text_regions: list[str] = Field(
        default_factory=lambda: ["bottom_center"],
        description="建议文字排版候选区域: bottom_center, bottom_left, top_center, vertical_left, etc."
    )

    @property
    def primary_subject_zone(self) -> str:
        h = "center"
        if self.primary_subject_x < 0.38:
            h = "left"
        elif self.primary_subject_x > 0.62:
            h = "right"

        v = "center"
        if self.primary_subject_y < 0.38:
            v = "top"
        elif self.primary_subject_y > 0.62:
            v = "bottom"

        if h == "center" and v == "center":
            return "center"
        if h == "center":
            return f"{v}_center"
        if v == "center":
            return f"center_{h}"
        return f"{v}_{h}"


class TransitionSpec(BaseModel):
    """镜头转场与蒙太奇关系描述"""
    target_shot_id: str = Field(default="", description="连接的镜头 ID")
    transition_type: Literal[
        "cut",
        "match_cut",
        "eyeline_match",
        "motion_vector_match",
        "scale_contrast",
        "color_match",
        "sound_bridge",
        "dissolve"
    ] = Field(default="cut", description="蒙太奇转场语法类型")
    description: str = Field(default="", description="具体视听连接动势说明")


# ============================================================================
# 7. 导演分镜、镜头与多 Take 架构 (Shot & Take System)
# ============================================================================

class Take(BaseModel):
    """单镜头的单次生成候选 (Take)"""
    id: str = Field(..., description="Take 唯一标识，如 'take_001'")
    shot_id: str = Field(..., description="关联的分镜 Shot ID")
    provider: str = Field(default="storyboard_mock", description="生成服务商: storyboard_mock, flux, veo, seedance, wan")
    media_type: Literal["image", "video"] = Field(default="image", description="素材形态: 'image' 或 'video'")
    media_path: str = Field(default="", description="生成产物文件路径或 URL")
    video_path: str = Field(default="", description="视频素材路径 (若为视频素材)")
    prompt: str = Field(default="", description="实际发送给模型的完整 Prompt")
    seed: int | None = Field(default=None, description="随机种子")
    cost: float = Field(default=0.0, ge=0, description="本次生成估算成本 (美元)")
    selected: bool = Field(default=False, description="是否被选定为最终正片素材")
    score: float = Field(default=0.0, ge=0, le=5.0, description="导演打分/评分 (0~5 星)")

    @model_validator(mode="before")
    @classmethod
    def _sync_paths(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("video_path") and not data.get("media_path"):
                data["media_path"] = data["video_path"]
                data["media_type"] = "video"
            elif data.get("media_path") and not data.get("video_path") and data.get("media_type") == "video":
                data["video_path"] = data["media_path"]
        return data


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
    prompt_en: str = Field(default="", description="英文生成提示词 (兼容回退用)")

    # 动静解耦双流提示词 (Two-Stream Decoupled Prompts)
    keyframe_prompt: str = Field(
        default="",
        description="首帧画面提示词 (专供 FLUX 12B T2I: 聚焦材质、光学参数、布光、景深与构图，严禁运镜动词)",
    )
    motion_prompt: str = Field(
        default="",
        description="时空运镜与物理演进提示词 (专供 LTX/Wan I2V: 聚焦摄影机轨迹、速度、刚体保真、微动与光斑位移)",
    )

    # 一镜到底与首尾帧无缝切换扩展 (One-Take & Seamless Continuity)
    endframe_prompt: str = Field(
        default="",
        description="尾帧画面描述 (可选: 用于首尾帧插值、终态定格，或作为一镜到底传递给下一镜首帧)",
    )
    endframe_image: str = Field(
        default="",
        description="尾帧图片路径 (可选: output/{project}/keyframes/shot_{id}_endframe_{time}.png)",
    )
    continuity_mode: Literal["cut", "match_cut", "one_take_continuous"] = Field(
        default="cut",
        description="镜头连续性模式: cut (普通硬切), match_cut (视听元素匹配), one_take_continuous (一镜到底首尾帧物理无缝继承)",
    )
    section_name: str = Field(default="", description="归属乐段名称")
    line_indices: list[int] = Field(default_factory=list, description="关联的歌词行序号")

    # 新版影视级分镜与因果链 (Story Graph & Machine Parameters)
    sequence_id: str = Field(default="", description="所属叙事序列 ID，如 'SEQ_01'")
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
    lens_mm: int | None = Field(default=None, description="摄影机焦段数值 (mm)，如 24, 35, 50, 85")
    lighting: str = Field(default="", description="机器布光参数 (如 'soft_side_backlight, low_contrast')")
    action: str = Field(default="", description="被摄主体的核心动作与微表情")
    emotion: str = Field(default="", description="情感张力 (如 loneliness, surge of hope, hesitation)")
    visual_intensity: float = Field(default=0.5, ge=0.0, le=1.0, description="视听张力强度 (0.1 极简静止 ~ 1.0 史诗高潮)")
    visual_metaphor: str = Field(default="", description="画面视觉隐喻与象征元素")
    layout_contract: CompositionSafeZones = Field(default_factory=CompositionSafeZones, description="构图安全区契约 (防字幕遮挡)")

    # 蒙太奇连续性与转场因果链 (Shot Adjacency & Continuity)
    incoming_transition: TransitionSpec | None = Field(default=None, description="入镜转场规格")
    outgoing_transition: TransitionSpec | None = Field(default=None, description="出镜转场规格")
    match_cut_element: str | None = Field(default=None, description="匹配剪辑/转场关联元素")
    previous_shot_id: str | None = Field(default=None, description="前序镜头依赖 ID (保证因果与视线不跳轴)")
    next_shot_id: str | None = Field(default=None, description="后序镜头依赖 ID")
    callback_to_shot: str | None = Field(default=None, description="副歌视觉复沓回溯的镜头 ID (Motif Callback)")
    callback_type: str = Field(default="", description="复沓类型: visual_echo, thematic_contrast, progression")

    # 导演审核笔记与设计构思 (Human Explanation)
    director_note: str = Field(default="", description="导演审核笔记 (Human Explanation)")
    dramatic_intent: str = Field(default="", description="戏剧意图与情感内核")
    design_rationale: str = Field(default="", description="导演设计构思与理念说明（为什么这样设计）")
    transition_rationale: str = Field(default="", description="镜头连接逻辑与转场蒙太奇语言（与前后镜头的视听衔接）")

    # 动态故事板 (Animatic) 与多候选 Take 管理
    preview_image: str = Field(default="", description="动态故事板 (Animatic) 静态预览卡片图路径")
    takes: list[Take] = Field(default_factory=list, description="候选生成素材列表 (Takes)")
    selected_take_id: str | None = Field(default=None, description="选中的 Take ID")

    @property
    def duration(self) -> float:
        """镜头持续秒数"""
        return max(0.0, self.end - self.start)

    @property
    def effective_keyframe_prompt(self) -> str:
        """获取生效的首帧提示词 (优先 keyframe_prompt，回退 prompt_en)"""
        return self.keyframe_prompt or self.prompt_en

    @property
    def effective_motion_prompt(self) -> str:
        """获取生效的运镜提示词 (优先 motion_prompt，回退 action 或 camera_motion)"""
        return self.motion_prompt or self.action or self.camera_motion

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

        # 兼容性同步：保证 director_note 与 design_rationale 互通
        if not self.director_note and self.design_rationale:
            self.director_note = self.design_rationale
        elif not self.design_rationale and self.director_note:
            self.design_rationale = self.director_note

        # 兼容性同步：保证 dramatic_intent 与 narrative_goal 互通
        if not self.dramatic_intent and self.narrative_goal:
            self.dramatic_intent = self.narrative_goal
        elif not self.narrative_goal and self.dramatic_intent:
            self.narrative_goal = self.dramatic_intent

        # 兼容性同步：保证 incoming_transition 与 transition_rationale 互通
        if self.transition_rationale and not self.incoming_transition:
            t_type = "match_cut" if "match cut" in self.transition_rationale.lower() else "cut"
            self.incoming_transition = TransitionSpec(transition_type=t_type, description=self.transition_rationale)
        elif self.incoming_transition and not self.transition_rationale:
            self.transition_rationale = f"[{self.incoming_transition.transition_type}] {self.incoming_transition.description}"

        return self


# 保持对旧代码导入名称的兼容别名
Shot = ShotPlan
StoryboardEvent = ShotPlan


# ============================================================================
# 8. 非线性剪辑时间轴与导演阐述 (NLE Timeline & Treatment)
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


class AudioClip(BaseModel):
    """音频轨剪辑片段 (主音频、人声、伴奏、音效)"""
    id: str = Field(..., description="AudioClip 标识")
    track_type: str = Field(default="master", description="音频角色: master, vocals, instrumental, sfx")
    file_path: str = Field(default="", description="物理音频文件路径")
    timeline_in: float = Field(default=0.0, ge=0)
    timeline_out: float = Field(default=0.0, ge=0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    mute: bool = Field(default=False)

    @property
    def duration(self) -> float:
        return max(0.0, self.timeline_out - self.timeline_in)


class TypographyClip(BaseModel):
    """字幕动效轨剪辑片段 (NLE 动效排版层)"""
    id: str = Field(..., description="TypographyClip 标识")
    line_index: int = Field(default=0)
    text: str = Field(default="")
    timeline_in: float = Field(default=0.0, ge=0)
    timeline_out: float = Field(default=0.0, ge=0)
    style_override: dict[str, Any] = Field(default_factory=dict)
    semantic_groups: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.timeline_out - self.timeline_in)


class MultiTrackTimeline(BaseModel):
    """
    工业级多轨非线性剪辑时间轴容器 (MultiTrack Timeline Engine)
    自 Animatic 阶段即确立，并在视频生成后平滑切换素材源，结构恒定。
    """
    duration: float = Field(default=0.0, ge=0)
    fps: float = Field(default=30.0, gt=0)
    audio_tracks: list[AudioClip] = Field(default_factory=list, description="音频轨道集")
    video_track: list[NLEClip] = Field(default_factory=list, description="视频主画面轨道")
    typography_track: list[TypographyClip] = Field(default_factory=list, description="歌词动效轨道")

    def __len__(self) -> int:
        return len(self.video_track)

    def __iter__(self):
        return iter(self.video_track)

    def __getitem__(self, idx: Any) -> Any:
        return self.video_track[idx]

    def get_video_clip_for_shot(self, shot_id: str) -> Optional[NLEClip]:
        for clip in self.video_track:
            if clip.shot_id == shot_id:
                return clip
        return None


class DirectorTreatment(BaseModel):
    """1 页纸导演阐述方案 (AI Director Treatment)"""
    title: str = Field(default="", description="MV 标题")
    logline: str = Field(default="", description="一句话核心剧情/意境摘要")
    visual_theme: str = Field(default="", description="核心视觉隐喻与主题词")
    director_statement: str = Field(default="", description="导演视听设计构想与艺术阐述")
    visual_metaphors: list[str] = Field(default_factory=list, description="关键视觉意象列表")
    acts: list[dict[str, Any]] = Field(default_factory=list, description="三幕式/乐段叙事拆解大纲")


# ============================================================================
# 9. 核心工程对象 (Project / AlignmentProject)
# ============================================================================

class AlignmentProject(BaseModel):
    """
    Suno2MV 核心工程模型 (对应 *_alignment.json 与 *_project.json)
    整合歌词时间轴、乐段、音乐智能、导演方案、视觉圣经、叙事序列、分镜镜头与时间线。
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

    # 宏观序列与时域曲线 (Suno2MV 工业流水线新增)
    sequences: list[SequencePlan] = Field(default_factory=list, description="叙事序列列表 (Sequences)")
    temporal_direction: TemporalDirection | None = Field(default=None, description="时域动态控制曲线 (张力/情绪/能量)")
    bibles: GlobalBibles | None = Field(default=None, description="全局美学与资产圣经总集")

    # 分镜与视觉圣经 (向下兼容)
    storyboard: list[ShotPlan] = Field(default_factory=list, description="分镜镜头列表 (Shot 序列)")
    background: str | None = Field(default=None, description="全局默认背景图路径")
    visual_bible: VisualBible | None = Field(default=None, description="视觉圣经设定")

    # 新版模块化引擎产物
    analysis: SongAnalysis | None = Field(default=None, description="音乐智能与切点分析")
    treatment: DirectorTreatment | None = Field(default=None, description="AI 导演方案")
    timeline: list[NLEClip] | MultiTrackTimeline = Field(default_factory=list, description="非线性剪辑时间线序列")

    @property
    def timeline_clips(self) -> list[NLEClip]:
        """统一获取视频轨 Clip 列表"""
        if isinstance(self.timeline, MultiTrackTimeline):
            return self.timeline.video_track
        elif isinstance(self.timeline, list):
            return self.timeline
        return []

    @property
    def shots(self) -> list[ShotPlan]:
        """别名访问 storyboard 镜头列表"""
        return self.storyboard

    @shots.setter
    def shots(self, value: list[ShotPlan]) -> None:
        self.storyboard = value

    @model_validator(mode="after")
    def sync_bibles(self) -> "AlignmentProject":
        # 兼容性同步：保证 visual_bible 与 bibles.visual 互通
        if self.visual_bible and not self.bibles:
            self.bibles = GlobalBibles(visual=self.visual_bible)
        elif self.bibles and self.bibles.visual and not self.visual_bible:
            self.visual_bible = self.bibles.visual
        return self

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
