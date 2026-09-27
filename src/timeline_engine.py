"""
Suno2MV 多轨非线性剪辑时间轴引擎 (MultiTrack Timeline Engine)
-----------------------------------------------------------
自 Animatic 阶段即作为中央组织骨架存在：
1. 组织 AudioTrack (全曲、人声轨、伴奏轨)
2. 组织 VideoTrack (分镜卡片 -> 选定 Take 视频平滑替换)
3. 组织 TypographyTrack (字级时间轴与 ASS / 动效排版层)
4. 校验视听时长守恒性与切点连续性
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.storyboard_schema import (
    AlignmentProject,
    AudioClip,
    MultiTrackTimeline,
    NLEClip,
    TypographyClip,
)
from src.utils import log


class TimelineEngine:
    """多轨时间轴构建与校验引擎"""

    @classmethod
    def build_from_project(
        cls,
        project: AlignmentProject,
        fps: float = 30.0,
    ) -> MultiTrackTimeline:
        """从 AlignmentProject 生成结构化多轨时间轴"""
        dur = project.duration
        if dur <= 0 and project.storyboard:
            dur = max(s.end for s in project.storyboard)
        if dur <= 0 and project.lines:
            dur = max(l.end for l in project.lines) + 2.0

        timeline = MultiTrackTimeline(
            duration=round(dur, 3),
            fps=fps,
            audio_tracks=[],
            video_track=[],
            typography_track=[],
        )

        # 1. 编译音频轨道 (Audio Track)
        if project.audio_path:
            timeline.audio_tracks.append(
                AudioClip(
                    id="audio_master",
                    track_type="master",
                    file_path=str(project.audio_path),
                    timeline_in=0.0,
                    timeline_out=dur,
                    volume=1.0,
                    mute=False,
                )
            )
        if project.vocals_path:
            timeline.audio_tracks.append(
                AudioClip(
                    id="audio_vocals",
                    track_type="vocals",
                    file_path=str(project.vocals_path),
                    timeline_in=0.0,
                    timeline_out=dur,
                    volume=1.0,
                    mute=False,
                )
            )
        if project.instrumental_path:
            timeline.audio_tracks.append(
                AudioClip(
                    id="audio_instrumental",
                    track_type="instrumental",
                    file_path=str(project.instrumental_path),
                    timeline_in=0.0,
                    timeline_out=dur,
                    volume=1.0,
                    mute=False,
                )
            )

        # 2. 编译主视频轨道 (Video Track)
        for s in project.storyboard:
            # 优先判定是否有选中的 Take 视频，否则使用 Animatic 静态分镜帧
            source_media = s.preview_image or s.path or f"storyboard/{s.id}.png"
            selected_take = None
            if s.takes:
                for t in s.takes:
                    if t.id == s.selected_take_id or t.selected:
                        selected_take = t
                        break
            if selected_take and selected_take.video_path:
                source_media = selected_take.video_path

            trans_in = s.incoming_transition.transition_type if s.incoming_transition else "cut"
            trans_out = s.outgoing_transition.transition_type if s.outgoing_transition else "cut"

            clip = NLEClip(
                id=f"clip_{s.id}",
                shot_id=s.id,
                take_id=selected_take.id if selected_take else "",
                source_media_path=str(source_media),
                source_in=0.0,
                source_out=round(s.duration, 3),
                timeline_in=round(s.start, 3),
                timeline_out=round(s.end, 3),
                speed=1.0,
                transition_in=trans_in,
                transition_out=trans_out,
            )
            timeline.video_track.append(clip)

        # 3. 编译歌词动效轨道 (Typography Track)
        for i, line in enumerate(project.lines):
            if line.text.strip() in ("...", "", "♪"):
                continue
            overrides = line.style_overrides or {}
            sem_groups = overrides.get("semantic_groups") or []
            typo_clip = TypographyClip(
                id=f"typo_{i:03d}",
                line_index=i,
                text=line.text,
                timeline_in=round(line.start, 3),
                timeline_out=round(line.end, 3),
                style_override=overrides,
                semantic_groups=sem_groups,
            )
            timeline.typography_track.append(typo_clip)

        return timeline

    @classmethod
    def validate_integrity(cls, timeline: MultiTrackTimeline) -> List[str]:
        """校验时间轴时序连续性与漏洞"""
        issues: List[str] = []
        if not timeline.video_track:
            issues.append("视频轨道为空，尚无任何镜头 Clip")
            return issues

        prev_out = 0.0
        for i, clip in enumerate(timeline.video_track):
            if clip.timeline_in < prev_out - 0.05:
                issues.append(f"镜头 {clip.shot_id} 入点 ({clip.timeline_in:.3f}s) 与前一镜头产生严重交叉重叠")
            elif clip.timeline_in > prev_out + 0.1:
                gap = clip.timeline_in - prev_out
                issues.append(f"镜头 {clip.shot_id} 前方存在时长 {gap:.3f}s 的黑屏缝隙 (Gap)")
            if clip.timeline_out <= clip.timeline_in:
                issues.append(f"镜头 {clip.shot_id} 时长为非正数: {clip.timeline_duration:.3f}s")
            prev_out = clip.timeline_out

        return issues

    @classmethod
    def export_summary(cls, timeline: MultiTrackTimeline) -> Dict[str, Any]:
        """导出多轨时间轴概览指标"""
        return {
            "total_duration": timeline.duration,
            "fps": timeline.fps,
            "audio_tracks_count": len(timeline.audio_tracks),
            "video_shots_count": len(timeline.video_track),
            "typography_clips_count": len(timeline.typography_track),
            "transitions_count": sum(1 for c in timeline.video_track if c.transition_in != "cut"),
        }
