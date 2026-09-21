"""
M2V 视听数据模型规范 (Pydantic v2)
定义歌词时间戳、音乐乐段、视觉圣经与分镜镜头的数据契约，
支持严格类型校验、自动序列化与反序列化，可直接作为大模型结构化输出 Schema。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class WordTimestamp(BaseModel):
    """单个字/词的时间戳"""
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


class MusicSection(BaseModel):
    """音乐乐段划分 (Intro, Verse, Chorus, Bridge, Outro 等)"""
    name: str = Field(..., description="乐段英文标识，如 'Intro', 'Verse 1', 'Chorus 2'")
    label: str = Field(default="", description="中文标签，如 '前奏', '主歌 1', '副歌 2', '桥段', '尾奏'")
    style: str = Field(default="", description="乐器、演奏指导与情绪描述 (来自 Suno Prompt)")
    start: float = Field(default=0.0, ge=0, description="乐段绝对起始时间(秒)")
    end: float = Field(default=0.0, ge=0, description="乐段绝对结束时间(秒)")
    line_indices: list[int] = Field(default_factory=list, description="归属于该乐段的歌词行索引列表")


class ShotPlan(BaseModel):
    """分镜镜头模型 (兼备视听设计与合成器兼容属性)"""
    shot_id: int = Field(default=1, description="分镜序号")
    type: str = Field(default="image", description="素材类型: 'image' 或 'video'")
    path: str = Field(default="", description="素材绝对或相对路径 (合成器使用)")
    start: float = Field(default=0.0, ge=0, description="镜头起始时间(秒)")
    end: float = Field(default=0.0, ge=0, description="镜头结束时间(秒)")
    speed_align: bool = Field(default=True, description="是否自动变速对齐时间区间")

    # 影视视听与 AI 提示词字段
    scale: str = Field(default="Medium", description="景别: ExtremeWide/Wide/Medium/CloseUp/Macro")
    camera_movement: str = Field(default="Static", description="运镜动作: Pan/Tilt/ZoomIn/ZoomOut/Tracking/Static")
    prompt_zh: str = Field(default="", description="中文构图、光影与动作描述")
    prompt_en: str = Field(default="", description="英文 Midjourney/Flux/Kling 提示词")
    section_name: str = Field(default="", description="归属乐段名称")
    line_indices: list[int] = Field(default_factory=list, description="关联的歌词行序号")

    @model_validator(mode="after")
    def validate_shot(self) -> "ShotPlan":
        if self.end > 0 and self.end < self.start:
            raise ValueError(f"镜头 {self.shot_id} 结束时间 ({self.end}) 不能小于起始时间 ({self.start})")
        return self


# 保持对旧代码导入名称的兼容别名
StoryboardEvent = ShotPlan


class VisualBible(BaseModel):
    """视觉圣经与世界观概念设定"""
    title: str = Field(default="", description="MV 企划名称")
    theme: str = Field(default="", description="核心主题与意境")
    narrative_synopsis: str = Field(default="", description="视觉叙事梗概/故事情节")
    color_palette: list[str] = Field(default_factory=list, description="主辅色调色盘 (十六进制色值或色彩词)")
    visual_style_anchor: str = Field(default="", description="全局摄影与画风基准词 (DNA Prompt)")
    character_anchor: str = Field(default="", description="主角/核心主体特征描述")
    environment_anchor: str = Field(default="", description="主要场景与光影基调")


class AlignmentProject(BaseModel):
    """
    M2V 核心对齐与分镜工程文件 (对应 *_alignment.json)
    整合歌词字级时间戳、乐段骨架、分镜镜头与概念设定。
    """
    title: str = Field(default="", description="歌曲名称")
    lines: list[AlignedLine] = Field(default_factory=list, description="歌词行列表")
    sections: list[MusicSection] = Field(default_factory=list, description="乐段骨架列表")
    storyboard: list[ShotPlan] = Field(default_factory=list, description="分镜镜头列表")
    background: str | None = Field(default=None, description="全局默认背景图路径")
    visual_bible: VisualBible | None = Field(default=None, description="视觉圣经设定")

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
        """从 JSON 文件加载并严格校验"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"工程文件不存在: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.model_validate(data)


# 保持对旧代码导入名称的兼容别名
AlignmentResult = AlignmentProject
