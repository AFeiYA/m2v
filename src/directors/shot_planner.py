"""
Pass B: 微观分镜规划导演 (Shot Planner)
---------------------------------------
负责将叙事序列 (SequencePlan) 编译为具备电影级视听规格的 Shot 列表：
1. 破除“歌词句=镜头”：根据音乐节拍、能量、长句裂变与器乐间奏，生成 2.5~6s 的精细镜头；
2. 明确拆分机器参数 (shot_size, camera_motion, lens_mm, lighting) 与人类说明 (director_note)；
3. 输出构图安全区协议 (layout_contract / CompositionSafeZones)，为字幕动效轨提供避让指引；
4. 编译纯画面 Prompt（坚决剔除任何中文字幕指示，画面保持 Clean Feed）；
5. 回填 Sequence.shot_ids 形成严密的父子层级。
"""
from __future__ import annotations

from typing import Optional, List
from src.storyboard_schema import (
    AlignmentProject,
    CompositionSafeZones,
    GlobalBibles,
    MusicCutPoint,
    SequencePlan,
    ShotPlan,
    Take,
    TemporalDirection,
)
from src.utils import log


class ShotPlanner:
    """Pass B: 影视分镜与微观视听架构师"""

    def __init__(self, project: AlignmentProject):
        self.project = project
        self.duration = project.duration or (
            max((line.end for line in project.lines), default=60.0) + 2.0
        )

    def _get_intensity_at(self, time_sec: float, td: Optional[TemporalDirection]) -> float:
        """获取指定时间点的视听张力强度"""
        if not td or not td.visual_intensity:
            return 0.5
        pts = td.visual_intensity
        # 寻找最近的时间点
        closest = min(pts, key=lambda p: abs(p.time - time_sec))
        return closest.value

    def compose_shots(
        self,
        cut_candidates: Optional[list[MusicCutPoint]] = None,
        target_shot_duration: float = 3.8,
    ) -> list[ShotPlan]:
        """
        基于 Sequences、Bibles 与音频切点，编织完整的 Shot 序列。
        """
        sequences = self.project.sequences
        bibles = self.project.bibles or GlobalBibles()
        visual_bible = bibles.visual or self.project.visual_bible
        temporal_dir = self.project.temporal_direction
        lines = self.project.lines

        if not sequences:
            log.warning("未检测到 Sequences，将执行紧急兜底单序列规划")
            from src.directors.creative_director import CreativeDirector
            cd = CreativeDirector(self.project)
            cd.execute()
            sequences = self.project.sequences
            bibles = self.project.bibles
            visual_bible = bibles.visual

        char = visual_bible.characters[0] if (visual_bible and visual_bible.characters) else None
        char_tokens = ", ".join(char.canonical_tokens) if char else "protagonist"
        char_name = char.name if char else "主角"

        loc_a = visual_bible.locations[0] if (visual_bible and visual_bible.locations) else None
        loc_b = visual_bible.locations[1] if (visual_bible and len(visual_bible.locations) > 1) else loc_a
        style_tokens = visual_bible.style.visual_style if (visual_bible and visual_bible.style) else "cinematic realism"

        motif_list = bibles.motifs.motifs if (bibles.motifs and bibles.motifs.motifs) else []

        # 整理全局切点候选
        all_cuts: list[float] = [0.0]
        if cut_candidates:
            all_cuts.extend([c.time for c in cut_candidates if 0 < c.time < self.duration])
        all_cuts = sorted(list(set(round(t, 3) for t in all_cuts)))

        all_shots: list[ShotPlan] = []
        global_shot_id = 1

        for seq_idx, seq in enumerate(sequences):
            seq_shots: list[ShotPlan] = []
            seq_dur = seq.duration
            t_curr = seq.start

            # 计算本 Sequence 需要安排的镜头数量 (通常 3~6 秒一个镜头)
            # 长间奏或长歌词自动切分
            expected_shot_count = max(2, round(seq_dur / target_shot_duration))
            step_duration = seq_dur / expected_shot_count

            is_intro = "Intro" in seq.section_name or seq_idx == 0
            is_chorus = "Chorus" in seq.section_name
            is_bridge = "Bridge" in seq.section_name
            is_outro = "Outro" in seq.section_name or (seq_idx == len(sequences) - 1)

            curr_loc = loc_b if is_chorus else loc_a
            loc_desc = curr_loc.name if curr_loc else "空间"
            loc_lighting = curr_loc.canonical_lighting if curr_loc else "cinematic lighting"

            for s_in_seq in range(expected_shot_count):
                t_start = round(t_curr, 3)
                if s_in_seq == expected_shot_count - 1:
                    t_end = round(seq.end, 3)
                else:
                    t_end = round(min(t_curr + step_duration, seq.end), 3)

                t_mid = (t_start + t_end) / 2.0
                intensity = self._get_intensity_at(t_mid, temporal_dir)
                t_curr = t_end

                shot_id_str = f"shot_{global_shot_id:03d}"

                # 匹配本镜头时间区间内的歌词
                matched_line_indices = [
                    idx for idx, line in enumerate(lines)
                    if max(t_start, line.start) < min(t_end, line.end)
                ]
                matched_lyrics = [lines[idx].text for idx in matched_line_indices]
                lyric_ref = " / ".join(matched_lyrics) if matched_lyrics else "【器乐流动 / 空镜情绪】"

                # 提取视觉母题隐喻
                chosen_motif = motif_list[global_shot_id % len(motif_list)] if motif_list else None
                metaphor_str = chosen_motif.core_concept if chosen_motif else "时光流淌与微观凝视"
                motif_name = chosen_motif.name if chosen_motif else "环境光影"

                # 确定专业景别 (Scale) 与镜头焦段 (Lens)
                if is_intro:
                    if s_in_seq == 0:
                        shot_size = "EWS"
                        lens_mm = 24
                        camera_motion = "static"
                        dramatic_intent = "建立宏观空间冷寂感，交代世界观边缘"
                        action_zh = f"大远景俯瞰【{loc_desc}】全貌，晨雾与环境光影在空间中缭绕流动"
                        action_en = f"Extreme wide shot of {curr_loc.spatial_layout if curr_loc else 'vast space'}, tranquil and atmospheric lighting"
                        safe_zones = CompositionSafeZones(
                            primary_subject_x=0.5,
                            primary_subject_y=0.6,
                            protected_regions=["center"],
                            preferred_text_regions=["bottom_center"],
                        )
                    else:
                        shot_size = "ECU" if s_in_seq % 2 == 1 else "WS"
                        lens_mm = 85 if shot_size == "ECU" else 35
                        camera_motion = "slow_dolly_in"
                        dramatic_intent = "从宏观瞬间拉入微观材质与实体，产生尺度对冲"
                        action_zh = f"微距慢速推进，镜头聚焦于【{motif_name}】，微光折射倒映出【{loc_desc}】的静谧氛围"
                        action_en = f"Macro extreme close-up slowly dollying in on {motif_name}, shallow depth of field, poetic atmospheric lighting"
                        safe_zones = CompositionSafeZones(
                            primary_subject_x=0.4,
                            primary_subject_y=0.5,
                            protected_regions=["center_left"],
                            preferred_text_regions=["bottom_right", "vertical_left"],
                        )
                elif is_chorus:
                    # 高潮副歌：景别剧烈对比，运镜富有冲击力
                    scales = ["EWS", "MCU", "WS", "CU", "EWS"]
                    motions = ["crane_up", "tracking", "dolly_out", "slow_dolly_in", "pan_left"]
                    lenses = [24, 50, 28, 85, 24]
                    idx_cycle = (global_shot_id) % len(scales)
                    shot_size = scales[idx_cycle]
                    camera_motion = motions[idx_cycle]
                    lens_mm = lenses[idx_cycle]
                    dramatic_intent = "情绪能量全面爆发，冲破压抑，展现生命韧性"
                    action_zh = f"【{char_name}】在【{loc_desc}】迎风奔跑或驻足回眸，眼神充满坚定与解脱，周围【{motif_name}】漫卷飞扬"
                    action_en = f"{char_tokens} moving dynamically through {loc_desc}, resolute gaze, dynamic lighting and particles freezing in air"
                    safe_zones = CompositionSafeZones(
                        primary_subject_x=0.65,
                        primary_subject_y=0.45,
                        protected_regions=["center_right"],
                        preferred_text_regions=["bottom_left", "vertical_left"],
                    )
                elif is_bridge:
                    # 桥段：对位反差，极度内省
                    shot_size = "CU" if s_in_seq % 2 == 0 else "MCU"
                    lens_mm = 85
                    camera_motion = "static" if s_in_seq % 2 == 0 else "slow_dolly_in"
                    dramatic_intent = "音乐声势骤降，镜头以长特写凝视人物微表情，积蓄最终力量"
                    action_zh = f"特写定格在【{char_name}】的深邃眼神或微动指尖，【{loc_desc}】的明暗光影在面部产生强烈反差"
                    action_en = f"Intimate close-up of {char_tokens} at {loc_desc}, micro-expressions of introspection, dramatic chiaroscuro lighting"
                    safe_zones = CompositionSafeZones(
                        primary_subject_x=0.5,
                        primary_subject_y=0.4,
                        protected_regions=["center"],
                        preferred_text_regions=["bottom_left", "bottom_right"],
                    )
                elif is_outro:
                    # 尾奏：镜头拉远释放
                    shot_size = "WS" if s_in_seq == 0 else "EWS"
                    lens_mm = 28 if shot_size == "WS" else 24
                    camera_motion = "dolly_out"
                    dramatic_intent = "回归平和与生命本体，镜头缓缓抽离"
                    action_zh = f"镜头缓慢后拉，【{char_name}】静立于【{loc_desc}】天地之间，柔和微光洒落，余韵悠长"
                    action_en = f"Slow cinematic dolly out, {char_tokens} standing peaceful in {loc_desc}, golden or celestial light"
                    safe_zones = CompositionSafeZones(
                        primary_subject_x=0.5,
                        primary_subject_y=0.55,
                        protected_regions=["center"],
                        preferred_text_regions=["bottom_center"],
                    )
                else:
                    # 主歌 Verse：注重人物与环境的互动
                    scales = ["MCU", "CU", "MS", "MCU", "MLS"]
                    motions = ["slow_dolly_in", "static", "tracking", "handheld", "tilt_up"]
                    lenses = [50, 85, 35, 50, 35]
                    idx_cycle = (global_shot_id) % len(scales)
                    shot_size = scales[idx_cycle]
                    camera_motion = motions[idx_cycle]
                    lens_mm = lenses[idx_cycle]
                    dramatic_intent = "细腻刻画动作过程与心境流淌"
                    action_zh = f"中近景展现【{char_name}】在【{loc_desc}】中，与【{motif_name}】相互呼应，举手投足间流露出内心的专注与沉思"
                    action_en = f"Medium close-up of {char_tokens} at {loc_desc}, resonant with {motif_name}, delicate focus, cinematic naturalism"
                    safe_zones = CompositionSafeZones(
                        primary_subject_x=0.6,
                        primary_subject_y=0.5,
                        protected_regions=["center_right"],
                        preferred_text_regions=["bottom_left"],
                    )

                director_note = (
                    f"【序列 {seq.id} | 视听张力 {intensity:.2f}】选用 {shot_size} 搭配 {lens_mm}mm 镜头与 {camera_motion} 运镜。"
                    f"{dramatic_intent}。画面隐喻：{metaphor_str}。"
                )

                # 构造纯画面 Prompt (严禁包含任何中文字幕指示！)
                prompt_en = (
                    f"{shot_size} shot, {lens_mm}mm anamorphic lens, {camera_motion} motion. "
                    f"{action_en}. Setting: {curr_loc.spatial_layout if curr_loc else 'cinematic environment'}. "
                    f"Lighting: {loc_lighting}. Aesthetic: {style_tokens}, filmic 8k quality, cinematic depth of field."
                )
                prompt_zh = f"【{shot_size} | {lens_mm}mm | {camera_motion}】在{loc_desc}。{action_zh}。母题: {metaphor_str}"

                # 构造默认候选 Take
                take_a = Take(
                    id=f"{shot_id_str}_take_A",
                    shot_id=shot_id_str,
                    provider="storyboard_mock",
                    media_type="image",
                    media_path=f"storyboard/{shot_id_str}.png",
                    prompt=prompt_en,
                    selected=True,
                    score=4.8,
                )

                shot = ShotPlan(
                    shot_id=global_shot_id,
                    id=shot_id_str,
                    start=t_start,
                    end=t_end,
                    sequence_id=seq.id,
                    section_name=seq.section_name,
                    line_indices=matched_line_indices,
                    narrative_goal=dramatic_intent,
                    dramatic_intent=dramatic_intent,
                    lyric_reference=lyric_ref,
                    character_ids=[char.id] if char else [],
                    location_id=curr_loc.id if curr_loc else "loc_01",
                    shot_size=shot_size,
                    camera_motion=camera_motion,
                    camera_angle="eye_level",
                    lens_mm=lens_mm,
                    lighting=loc_lighting,
                    visual_intensity=intensity,
                    visual_metaphor=metaphor_str,
                    layout_contract=safe_zones,
                    director_note=director_note,
                    action=action_zh,
                    emotion="hopeful" if is_chorus else ("contemplative" if not is_outro else "peaceful"),
                    prompt_zh=prompt_zh,
                    prompt_en=prompt_en,
                    preview_image=f"storyboard/{shot_id_str}.png",
                    path=f"storyboard/{shot_id_str}.png",
                    takes=[take_a],
                    selected_take_id=take_a.id,
                )

                seq_shots.append(shot)
                all_shots.append(shot)
                global_shot_id += 1

            # 回填 Sequence 包含的 shot_ids
            seq.shot_ids = [s.id for s in seq_shots]

        log.info("✅ [Pass B] 微观分镜规划完成: 共编织 %d 个影视分镜 Shot (平均时长 %.2fs)", len(all_shots), self.duration / max(1, len(all_shots)))
        return all_shots
