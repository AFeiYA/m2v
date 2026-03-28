"""全局配置 — 模型参数 / 默认样式 / 输出规格"""

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

# ---------------------------------------------------------------------------
# ASS 字幕生成
# ---------------------------------------------------------------------------
@dataclass
class SubtitleConfig:
    template_path: Path = TEMPLATES_DIR / "default_style.ass"
    style_name: str = "Karaoke"
    # 颜色 (ASS &HAABBGGRR 格式)
    primary_colour: str = "&H00FFFFFF"    # 白 (未唱)
    secondary_colour: str = "&H0000FFFF"  # 黄 (已唱)
    outline_colour: str = "&H00000000"    # 黑描边
    font_name: str = "思源黑体"
    font_size: int = 56
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
