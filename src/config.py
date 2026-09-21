"""全局配置 — 模型参数 / 默认样式 / 输出规格"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 项目根目录
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
ASSETS_DIR = PROJECT_ROOT / "assets"

# ---------------------------------------------------------------------------
# Demucs 人声分离
# ---------------------------------------------------------------------------
@dataclass
class SeparatorConfig:
    model: str = "htdemucs_ft"        # fine-tuned, 质量最高
    two_stems: str = "vocals"         # 只输出 vocals + no_vocals
    device: str = "cuda"              # 自动回退 CPU
    shifts: int = 1                   # overlap shifts (越高越慢越好)
    output_format: str = "wav"

# ---------------------------------------------------------------------------
# WhisperX 词级对齐
# ---------------------------------------------------------------------------
@dataclass
class AlignerConfig:
    whisper_model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "int8"        # int8 省显存，适合 8GB VRAM
    language: str = "zh"
    batch_size: int = 8               # 8GB VRAM 建议 ≤8
    # 中文 wav2vec2 对齐模型（WhisperX 默认会自动选）
    align_model: str | None = None
    # 拼音对齐：将中文转拼音后做 wav2vec2 对齐，然后映射回汉字
    use_pinyin: bool = True
    # 歌词起始时间(秒): 前奏/拟声词之后的实际开唱时间点
    # 此时间之前的 Whisper segment 会被丢弃
    lyrics_start_time: float = 0.0
    # 后处理时间阈值
    min_char_duration: float = 0.08   # 单字最短时长(秒)，低于此值从长字借时间
    max_char_duration: float = 3.0    # 单字最长时长(秒)，超过会截断

# ---------------------------------------------------------------------------
# ASS 字幕生成
# ---------------------------------------------------------------------------
@dataclass
class SubtitleConfig:
    template_path: Path = TEMPLATES_DIR / "default_style.ass"
    style_name: str = "Karaoke"
    # 颜色 (Apple Style: 纯白变焦与透明度)
    primary_colour: str = "&H00FFFFFF"    # 纯白 (已唱)
    secondary_colour: str = "&H66FFFFFF"  # 半透明白 (未唱)
    outline_colour: str = "&H99000000"    # 暗色半透明描边
    font_name: str = "思源黑体"
    font_path: str = "C:/Windows/Fonts/msyh.ttc"  # 默认路径，Pillow 需要真实文件
    font_size: int = 72
    # 渲染模式: "classic" (传统) / "apple" (滚动聚焦)
    render_mode: str = "apple"
    apple_pulse: bool = True              # 是否启用字级缩放呼吸感
    use_karaoke_gradient: bool = True     # 开启时使用平滑过光渐变(\kf)，关闭时使用逐字跳跃(\k)
    # 节奏动画
    enable_beat_effects: bool = False
    beat_scale: float = 1.15              # 鼓点处放大倍数

# ---------------------------------------------------------------------------
# FFmpeg 视频合成
# ---------------------------------------------------------------------------
@dataclass
class CompositorConfig:
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 30
    video_codec: str = "libx264"
    crf: int = 18
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    pixel_format: str = "yuv420p"
    default_bg: Path = ASSETS_DIR / "default_bg.jpg"
    enable_subtitles: bool = True

# ---------------------------------------------------------------------------
# 歌词预处理
# ---------------------------------------------------------------------------
@dataclass
class PreprocessorConfig:
    convert_numbers: bool = True          # 数字转中文
    convert_traditional: bool = False     # 繁→简
    opencc_config: str = "t2s"            # OpenCC 转换方案

# ---------------------------------------------------------------------------
# 主管线配置
# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    separator: SeparatorConfig = field(default_factory=SeparatorConfig)
    aligner: AlignerConfig = field(default_factory=AlignerConfig)
    subtitle: SubtitleConfig = field(default_factory=SubtitleConfig)
    compositor: CompositorConfig = field(default_factory=CompositorConfig)
    preprocessor: PreprocessorConfig = field(default_factory=PreprocessorConfig)
    # 工作目录
    temp_dir: Path | None = None          # None = 自动创建临时目录
    keep_temp: bool = False               # 调试用: 保留中间文件
    # 步骤控制
    skip_separation: bool = False         # 跳过 Demucs，直接用原音频对齐
    ass_only: bool = False                # 只生成 ASS，不合成 MP4
    alignment_json: Path | None = None    # 复用已有对齐结果，跳过对齐
    video_only: bool = False              # 直接从已有 ASS 合成视频，跳过 1-4 步
    ass_file: Path | None = None          # video_only 时指定 ASS 路径 (支持 {stem})

    @classmethod
    def from_file(cls, path: Path | str) -> "PipelineConfig":
        """从 .toml 或 .json 文件统一加载主管线与子模块配置"""
        import json
        try:
            import tomllib
        except ModuleNotFoundError:
            tomllib = None

        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"配置文件不存在: {p}")

        suffix = p.suffix.lower()
        if suffix == ".toml":
            if tomllib is None:
                raise ValueError("当前 Python 环境缺少 tomllib，请升级到 Python 3.11+ 或使用 .json 配置文件")
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        elif suffix == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
        else:
            raise ValueError(f"不支持的配置文件格式: {suffix}，仅支持 .toml 或 .json")

        cfg = cls()
        pipeline_data = data.get("pipeline", data)
        if isinstance(pipeline_data, dict):
            cfg.skip_separation = bool(pipeline_data.get("skip_separation", cfg.skip_separation))
            cfg.ass_only = bool(pipeline_data.get("ass_only", cfg.ass_only))
            cfg.video_only = bool(pipeline_data.get("video_only", cfg.video_only))
            cfg.keep_temp = bool(pipeline_data.get("keep_temp", cfg.keep_temp))
            if pipeline_data.get("alignment_json"):
                cfg.alignment_json = Path(pipeline_data["alignment_json"])
            if pipeline_data.get("ass_file"):
                cfg.ass_file = Path(pipeline_data["ass_file"])

        aligner_data = data.get("aligner", {})
        if isinstance(aligner_data, dict):
            for k in ["whisper_model", "device", "compute_type", "language", "align_model"]:
                if k in aligner_data and aligner_data[k] is not None:
                    setattr(cfg.aligner, k, str(aligner_data[k]))
            if "batch_size" in aligner_data and aligner_data["batch_size"] is not None:
                cfg.aligner.batch_size = int(aligner_data["batch_size"])
            if "use_pinyin" in aligner_data:
                cfg.aligner.use_pinyin = bool(aligner_data["use_pinyin"])
            if "lyrics_start_time" in aligner_data and aligner_data["lyrics_start_time"] is not None:
                cfg.aligner.lyrics_start_time = float(aligner_data["lyrics_start_time"])
            if "min_char_duration" in aligner_data and aligner_data["min_char_duration"] is not None:
                cfg.aligner.min_char_duration = float(aligner_data["min_char_duration"])
            if "max_char_duration" in aligner_data and aligner_data["max_char_duration"] is not None:
                cfg.aligner.max_char_duration = float(aligner_data["max_char_duration"])

        subtitle_data = data.get("subtitle", {})
        if isinstance(subtitle_data, dict):
            if subtitle_data.get("template_path"):
                tpl = Path(subtitle_data["template_path"]).expanduser()
                cfg.subtitle.template_path = (p.parent / tpl).resolve() if not tpl.is_absolute() else tpl
            for k in ["style_name", "primary_colour", "secondary_colour", "outline_colour", "font_name"]:
                if k in subtitle_data and subtitle_data[k] is not None:
                    setattr(cfg.subtitle, k, str(subtitle_data[k]))
            if subtitle_data.get("font_size") is not None:
                cfg.subtitle.font_size = int(subtitle_data["font_size"])
            if "enable_beat_effects" in subtitle_data:
                cfg.subtitle.enable_beat_effects = bool(subtitle_data["enable_beat_effects"])
            if subtitle_data.get("beat_scale") is not None:
                cfg.subtitle.beat_scale = float(subtitle_data["beat_scale"])

        return cfg

