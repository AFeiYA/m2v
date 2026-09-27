"""
Suno2MV 统一音乐输入源体系 (SongSource & Adapters)
--------------------------------------------------
将输入源从单一的 "Suno 爬取/下载" 升格为通用的 "音乐资产摄入规范 (SongSource)"。
支持：
1. Suno Studio 工程源 (全曲音频、分轨 Stems、MIDI、元数据)
2. 本地音频与歌词对 (WAV/MP3/FLAC + LRC/TXT)
3. 专业分轨源 (Vocals, Drums, Bass, Other)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.utils import log


@dataclass
class SongSource:
    """
    统一音乐源资产模型 (SongSource)
    作为整个 AI-Native MV 工业流水线的物理输入源抽象。
    """
    title: str = "未命名曲目"
    artist: str = "AI 创作者"
    audio_path: Optional[Path] = None
    vocals_path: Optional[Path] = None
    instrumental_path: Optional[Path] = None
    stems: Dict[str, Path] = field(default_factory=dict)
    midi_path: Optional[Path] = None
    lyrics_raw: str = ""
    lrc_path: Optional[Path] = None
    duration: float = 0.0
    bpm: Optional[float] = None
    musical_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_stems(self) -> bool:
        return bool(self.stems)

    @property
    def has_isolated_audio(self) -> bool:
        return bool(self.vocals_path and self.vocals_path.exists()) and bool(
            self.instrumental_path and self.instrumental_path.exists()
        )

    def validate(self) -> bool:
        """检验必要媒体源是否存在"""
        if not self.audio_path or not self.audio_path.exists():
            raise FileNotFoundError(f"主音频文件不存在: {self.audio_path}")
        return True


class BaseSongAdapter:
    """输入源适配器抽象基类"""
    @classmethod
    def can_handle(cls, source_path: Path) -> bool:
        raise NotImplementedError

    @classmethod
    def load(cls, source_path: Path, **kwargs) -> SongSource:
        raise NotImplementedError


class SunoDirectoryAdapter(BaseSongAdapter):
    """
    Suno 导出的工程文件夹适配器
    识别标准：文件夹内包含 <stem>.mp3 / <stem>.wav，或 _vocals.wav / _instrumental.wav / .lrc
    """
    @classmethod
    def can_handle(cls, source_path: Path) -> bool:
        if not source_path.is_dir():
            return False
        # 探测是否有音频文件
        audio_files = list(source_path.glob("*.mp3")) + list(source_path.glob("*.wav"))
        return len(audio_files) > 0

    @classmethod
    def load(cls, source_path: Path, **kwargs) -> SongSource:
        source_dir = source_path.resolve()
        stem_name = source_dir.name

        # 查找主音频 (排除 _vocals 和 _instrumental)
        main_audio: Optional[Path] = None
        candidates = list(source_dir.glob("*.wav")) + list(source_dir.glob("*.mp3"))
        for f in candidates:
            if not f.name.endswith(("_vocals.wav", "_instrumental.wav", "_vocals.mp3", "_instrumental.mp3")):
                main_audio = f
                break
        if not main_audio and candidates:
            main_audio = candidates[0]

        # 查找人声轨与伴奏轨
        vocals = source_dir / f"{stem_name}_vocals.wav"
        if not vocals.exists():
            v_alt = list(source_dir.glob("*vocals*.*"))
            vocals = v_alt[0] if v_alt else None
        else:
            vocals = vocals

        instrumental = source_dir / f"{stem_name}_instrumental.wav"
        if not instrumental.exists():
            i_alt = list(source_dir.glob("*instrumental*.*"))
            instrumental = i_alt[0] if i_alt else None
        else:
            instrumental = instrumental

        # 查找 MIDI
        midi_files = list(source_dir.glob("*.mid")) + list(source_dir.glob("*.midi"))
        midi_path = midi_files[0] if midi_files else None

        # 查找歌词文件
        lrc_files = list(source_dir.glob("*.lrc")) + list(source_dir.glob("*.ass"))
        lrc_path = lrc_files[0] if lrc_files else None
        lyrics_text = ""
        if lrc_path and lrc_path.suffix == ".lrc":
            lyrics_text = lrc_path.read_text(encoding="utf-8", errors="ignore")

        # 提取 Stems (如果存在独立 stems 文件夹)
        stems = {}
        stems_dir = source_dir / "stems"
        if stems_dir.exists() and stems_dir.is_dir():
            for sf in stems_dir.glob("*.*"):
                if sf.suffix.lower() in [".wav", ".mp3", ".flac"]:
                    stems[sf.stem.lower()] = sf

        # 尝试读取元数据 JSON
        meta_json = source_dir / "metadata.json"
        metadata = {}
        if meta_json.exists():
            try:
                metadata = json.loads(meta_json.read_text(encoding="utf-8"))
            except Exception:
                pass

        return SongSource(
            title=metadata.get("title") or stem_name,
            artist=metadata.get("artist") or "AI Creator",
            audio_path=main_audio,
            vocals_path=vocals if (vocals and vocals.exists()) else None,
            instrumental_path=instrumental if (instrumental and instrumental.exists()) else None,
            stems=stems,
            midi_path=midi_path,
            lyrics_raw=lyrics_text,
            lrc_path=lrc_path,
            metadata=metadata,
        )


class LocalAudioFileAdapter(BaseSongAdapter):
    """
    单个本地音频文件适配器 (WAV / MP3 / FLAC)
    自动嗅探同名 .lrc 或 .txt 歌词
    """
    @classmethod
    def can_handle(cls, source_path: Path) -> bool:
        return source_path.is_file() and source_path.suffix.lower() in [
            ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"
        ]

    @classmethod
    def load(cls, source_path: Path, **kwargs) -> SongSource:
        audio_file = source_path.resolve()
        parent_dir = audio_file.parent
        stem_name = audio_file.stem

        # 嗅探同名歌词
        lrc_path = parent_dir / f"{stem_name}.lrc"
        if not lrc_path.exists():
            txt_path = parent_dir / f"{stem_name}.txt"
            lrc_path = txt_path if txt_path.exists() else None

        lyrics_text = ""
        if lrc_path and lrc_path.exists():
            lyrics_text = lrc_path.read_text(encoding="utf-8", errors="ignore")

        # 嗅探伴奏和人声
        vocals = parent_dir / f"{stem_name}_vocals.wav"
        instrumental = parent_dir / f"{stem_name}_instrumental.wav"

        return SongSource(
            title=stem_name,
            artist="Unknown Artist",
            audio_path=audio_file,
            vocals_path=vocals if vocals.exists() else None,
            instrumental_path=instrumental if instrumental.exists() else None,
            lyrics_raw=lyrics_text,
            lrc_path=lrc_path if (lrc_path and lrc_path.exists()) else None,
        )


def detect_and_load_song_source(path: Path | str) -> SongSource:
    """
    智能嗅探并加载任意输入源，返回结构化 SongSource 对象
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"指定的歌曲源路径不存在: {p}")

    if p.is_dir() and SunoDirectoryAdapter.can_handle(p):
        log.info("🎵 识别为工程目录源: %s", p.name)
        source = SunoDirectoryAdapter.load(p)
    elif p.is_file() and LocalAudioFileAdapter.can_handle(p):
        log.info("🎵 识别为独立音频文件源: %s", p.name)
        source = LocalAudioFileAdapter.load(p)
    elif p.is_file() and p.suffix.lower() in [".json"]:
        # 支持从现有 alignment.json 推导
        from src.storyboard_schema import AlignmentProject
        proj = AlignmentProject.load_json(p)
        source_dir = p.parent
        source = SunoDirectoryAdapter.load(source_dir)
        source.title = proj.title or source.title
        source.duration = proj.duration
    else:
        raise ValueError(f"无法识别该路径下的音乐资产格式: {p}")

    source.validate()
    return source
