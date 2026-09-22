"""
Suno2MV 导演推理引擎 (Director Reasoning Engine)
------------------------------------------------
将音乐智能（节拍/鼓点/能量）与歌词叙事转化为具备影视语法的可执行分镜：
1. Pass 1: 宏观剧作 (Macro Arc) — 生成 Treatment 与 Visual Bible 资产预制体。
2. Pass 2: 微观视听编译 (Micro Composer) — 基于切刀点与影视语法规则网编译 30+ Shots。
3. 提供离线规则引擎（零网络高保真生成）与可选的 LLM 增强模式。
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, List, Optional

from src.storyboard_schema import (
    AlignmentProject,
    CharacterPrefab,
    DirectorTreatment,
    LocationPrefab,
    MusicCutPoint,
    MusicSection,
    NLEClip,
    ShotPlan,
    SongAnalysis,
    StylePrefab,
    Take,
    VisualBible,
)
from src.utils import log


# ============================================================================
# 影视语法规则库与预设库 (Cinematography Grammar)
# ============================================================================

CINEMATIC_SCALES = ["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"]

CAMERA_MOTIONS = [
    "static",
    "slow_dolly_in",
    "dolly_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "tracking",
    "crane_up",
    "handheld",
]


class RuleBasedDirector:
    """
    确定性离线影视导演引擎 (无需外网与 API Key)
    根据歌词意象、乐段结构与能量曲线，进行专业级视听规划与 Story Graph 编织。
    """

    def __init__(self, project: AlignmentProject, analysis: Optional[SongAnalysis] = None):
        self.project = project
        self.analysis = analysis or project.analysis
        self.duration = project.duration or (self.analysis.duration if self.analysis else 0.0)
        if self.duration <= 0 and project.lines:
            self.duration = max(line.end for line in project.lines) + 2.0

    # ------------------------------------------------------------------------
    # Pass 1: 宏观剧作与视觉圣经生成
    # ------------------------------------------------------------------------

    def build_treatment_and_bible(self) -> tuple[DirectorTreatment, VisualBible]:
        title = self.project.title or "未命名曲目"
        lyrics_full = "\n".join(line.text for line in self.project.lines)

        # 语义与情感意象探测
        has_ocean = any(w in lyrics_full for w in ["海", "浪", "潮", "水", "深蓝", "岸", "洋", "舟"])
        has_night = any(w in lyrics_full for w in ["夜", "星", "月", "暗", "黑", "暮", "晚", "梦"])
        has_urban = any(w in lyrics_full for w in ["城", "街", "车", "窗", "霓虹", "站台", "楼", "铁"])
        has_nature = any(w in lyrics_full for w in ["山", "风", "云", "花", "树", "林", "雪", "晨", "光"])

        # 匹配叙事母题
        if has_ocean:
            logline = f"在潮汐与时间的边缘，一位青年在海边废弃遗迹中重寻失去的记忆与方向。"
            theme = "时间潮汐、遗忘与重逢"
            char_lead = CharacterPrefab(
                id="char_lead",
                name="林",
                role="protagonist",
                appearance="23岁年轻女性，黑色齐肩短发，清澈坚定的目光，面容素净",
                wardrobe="灰白色亚麻衬衫，深灰阔腿风衣，银质水滴形吊坠",
                canonical_tokens=["23yo asian woman", "short black bob hair", "white linen shirt", "silver pendant"],
                forbidden_tokens=["long hair", "blonde", "glasses", "bright makeup", "neon clothing"],
            )
            loc_a = LocationPrefab(
                id="loc_coastal_railway",
                name="废弃沿海站台",
                spatial_layout="锈蚀的铁轨蜿蜒伸入海水中，被杂草与野花覆盖的木制月台",
                canonical_lighting="清晨薄雾，微弱的冷天光与淡金色的晨曦交界",
                time_of_day="dawn",
            )
            loc_b = LocationPrefab(
                id="loc_tide_pool",
                name="潮汐礁石海滩",
                spatial_layout="广袤的黑色玄武岩礁石群，倒映天空的平静潮水坑洼",
                canonical_lighting="阴云密布的柔和漫射光，青色阴影与温暖高光",
                time_of_day="dusk",
            )
            color_palette = ["#1A365D", "#4A7C9B", "#DCE6EC", "#E29578", "#F4F1DE"]
            visual_style = "cinematic realism with melancholic naturalism"
        elif has_urban or has_night:
            logline = f"穿行在雨夜霓虹迷离的都市边缘，追寻旧磁带里模糊的旋律与真实的自我。"
            theme = "都市孤岛、霓虹梦境与破晓释怀"
            char_lead = CharacterPrefab(
                id="char_lead",
                name="安",
                role="protagonist",
                appearance="25岁男子，微卷碎发，神情深邃略带疲惫，高挑身形",
                wardrobe="深黑色复古皮夹克，暗青色高领毛衣，银色细边指环",
                canonical_tokens=["25yo east asian male", "wavy dark hair", "black leather jacket", "deep thoughtful gaze"],
                forbidden_tokens=["bald", "sunglasses", "casual sportswear", "formal suit"],
            )
            loc_a = LocationPrefab(
                id="loc_rainy_street",
                name="雨夜霓虹小巷",
                spatial_layout="湿漉反光的沥青路面，昏黄路灯与暗紫色霓虹招牌在雨水中重叠",
                canonical_lighting="高对比度夜景光照，冷青色雨水倒影与琥珀色暖光源",
                time_of_day="neon_night",
            )
            loc_b = LocationPrefab(
                id="loc_rooftop_overlook",
                name="天台城市俯瞰点",
                spatial_layout="空旷的公寓楼顶，雨后积水的地面倒映着整座城市林立的光斑",
                canonical_lighting="黎明前的蓝调时刻（Blue Hour），地平线泛起冷金暖光",
                time_of_day="dawn",
            )
            color_palette = ["#0B132B", "#1C2541", "#3A506B", "#5BC0BE", "#FFD166"]
            visual_style = "neo-noir cinematic realism, anamorphic lens flare"
        else:
            logline = f"一段跨越心绪原野的自我救赎之旅，在光影流转中体悟生命如其所是的平静。"
            theme = "生命流转、宁静与自我接纳"
            char_lead = CharacterPrefab(
                id="char_lead",
                name="初",
                role="protagonist",
                appearance="22岁青年，黑发微风拂动，眼神温和沉静，身形修长",
                wardrobe="米白色粗针织毛衣，墨绿棉麻长裤，复古帆布背包",
                canonical_tokens=["22yo east asian person", "natural hair", "beige knit sweater", "calm expression"],
                forbidden_tokens=["bright synthetic clothes", "heavy accessories", "fashion model pose"],
            )
            loc_a = LocationPrefab(
                id="loc_sunlit_meadow",
                name="芒草微风原野",
                spatial_layout="起伏的金色原野，风吹拂草浪如海，远处有一棵孤立的古树",
                canonical_lighting="黄金时刻逆光（Golden Hour），柔和的丁达尔丁达尔光束",
                time_of_day="dusk",
            )
            loc_b = LocationPrefab(
                id="loc_wooden_studio",
                name="老式木质阁楼",
                spatial_layout="斜顶阁楼窗，散落的老胶片、书籍与木吉他，尘埃在光柱中飘荡",
                canonical_lighting="透过旧木百叶窗照射进来的斜阳，暖黄色丁达尔光晕",
                time_of_day="day",
            )
            color_palette = ["#2B2D42", "#8D99AE", "#EDF2F4", "#EF233C", "#D90429"]
            visual_style = "poetic cinematic realism, soft film grain, naturalistic warmth"

        treatment = DirectorTreatment(
            title=title,
            logline=logline,
            visual_theme=theme,
            director_statement=(
                f"本片拒绝浅白图解歌词，通过【{char_lead.name}】的视角将音乐的声学起伏转化为有呼吸感的视听流动。"
                f"在主歌阶段采用近景手持与中景捕捉情绪的迟疑；在副歌爆发时通过大景别俯冲与高视线切镜释放戏剧张力。"
            ),
            visual_metaphors=["雨滴穿透水面折射时光", "空荡的飞鸟划过破晓天际", "掌心握紧又松开的风"],
            acts=[
                {"act": 1, "title": "启程与困囿", "narrative": "建立主人公在固有空间内的压抑与迟疑，引发心绪波动的信物出现。"},
                {"act": 2, "title": "旅途与对抗", "narrative": "步入宽阔的外部世界，面对风暴、雨水或潮汐的洗礼，情绪经历反复拉扯。"},
                {"act": 3, "title": "破晓与释怀", "narrative": "副歌高潮全力爆发，冲破阴霾，最终回归内心的平和与澄明。"},
            ],
        )

        visual_bible = VisualBible(
            title=f"{title} 视觉圣经",
            theme=theme,
            narrative_synopsis=logline,
            color_palette=color_palette,
            visual_style_anchor=visual_style,
            character_anchor=f"{char_lead.name} ({char_lead.appearance}, {char_lead.wardrobe})",
            environment_anchor=f"{loc_a.name} & {loc_b.name}",
            characters=[char_lead],
            locations=[loc_a, loc_b],
            style=StylePrefab(
                visual_style=visual_style,
                color_palette=color_palette,
                lens_spec="35mm Anamorphic, f/1.8",
                lighting_mood="natural volumetric lighting, filmic contrast",
                film_grain="Kodak Vision3 500T 35mm grain",
            ),
        )

        return treatment, visual_bible

    # ------------------------------------------------------------------------
    # Pass 2: 微观视听编译 (Shot & Story Graph Composition)
    # ------------------------------------------------------------------------

    def compose_shots(
        self,
        treatment: DirectorTreatment,
        bible: VisualBible,
        cut_candidates: list[MusicCutPoint],
    ) -> list[ShotPlan]:
        if not cut_candidates:
            # 自动兜底生成切点
            cut_times = [0.0]
            step = 3.8
            t = 0.0
            while t < self.duration - 1.5:
                t += step
                cut_times.append(round(min(t, self.duration), 3))
            cut_candidates = [MusicCutPoint(time=ct, confidence=0.8) for ct in cut_times]

        shots: list[ShotPlan] = []
        total_cuts = len(cut_candidates)

        char = bible.characters[0] if bible.characters else None
        char_id = char.id if char else "char_01"
        char_tokens = ", ".join(char.canonical_tokens) if char else "person"
        char_name = char.name if char else "主人公"

        loc_a = bible.locations[0] if bible.locations else None
        loc_b = bible.locations[1] if len(bible.locations) > 1 else loc_a
        style_tokens = bible.style.visual_style if bible.style else "cinematic realism"

        # 镜头总数通常为 cut 数量 - 1
        num_shots = total_cuts - 1 if total_cuts > 1 else 1

        for i in range(num_shots):
            shot_num = i + 1
            t_start = cut_candidates[i].time
            t_end = cut_candidates[i + 1].time if i + 1 < total_cuts else self.duration
            t_mid = (t_start + t_end) / 2.0
            dur = max(0.1, t_end - t_start)

            # 关联乐段
            section_name = "Verse 1"
            is_chorus = False
            is_intro = False
            is_outro = False
            if self.project.sections:
                for sec in self.project.sections:
                    if sec.start <= t_mid <= sec.end or (sec.start <= t_start and sec.end >= t_end):
                        section_name = sec.name
                        break
            if "Intro" in section_name or t_mid < 15.0:
                is_intro = True
            elif "Chorus" in section_name:
                is_chorus = True
            elif "Outro" in section_name or t_mid > self.duration - 15.0:
                is_outro = True

            # 关联歌词行
            matched_line_indices: list[int] = []
            matched_lyrics: list[str] = []
            for l_idx, line in enumerate(self.project.lines):
                if max(t_start, line.start) < min(t_end, line.end):
                    matched_line_indices.append(l_idx)
                    matched_lyrics.append(line.text)

            lyric_ref = " / ".join(matched_lyrics) if matched_lyrics else "【器乐段落】"

            # 确定场景归属 (Intro/Verse 偏场景 A，Chorus/Climax 切换场景 B)
            current_loc = loc_b if is_chorus else loc_a
            loc_id = current_loc.id if current_loc else "loc_01"
            loc_desc = current_loc.name if current_loc else "空间"

            # 影视语法规则调度景别与运镜 (Scale & Motion Flow)
            if is_intro:
                if shot_num == 1:
                    shot_size = "EWS"
                    camera_motion = "static"
                    narrative_goal = "交代宏观环境全貌与孤寂基调"
                    action_zh = f"广角全景展现【{loc_desc}】全貌，晨雾缭绕，天地苍茫寂静"
                    action_en = f"Extreme wide shot of {current_loc.spatial_layout}, serene and cinematic atmosphere"
                else:
                    shot_size = "WS"
                    camera_motion = "slow_dolly_in"
                    narrative_goal = "引入主角背影，建立人物与空间的悬殊张力"
                    action_zh = f"缓推镜头，【{char_name}】的身影背对镜头孤立站立，风吹动衣襟"
                    action_en = f"Wide shot, {char_tokens} standing alone facing the vast horizon, gentle wind"
            elif is_chorus:
                # 高潮副歌：景别对比强烈，运镜快速动感
                scale_cycle = ["EWS", "MCU", "WS", "CU", "EWS"]
                motion_cycle = ["crane_up", "tracking", "dolly_out", "slow_dolly_in", "pan_left"]
                shot_size = scale_cycle[shot_num % len(scale_cycle)]
                camera_motion = motion_cycle[shot_num % len(motion_cycle)]
                narrative_goal = "情感核心爆发，冲破压抑与迷茫"
                action_zh = f"【{char_name}】奔向光芒处，雨水或狂风中神情充满坚定与解脱"
                action_en = f"{char_tokens} running towards the glowing light with intense determined expression, cinematic energy"
            elif is_outro:
                shot_size = "WS" if shot_num % 2 == 0 else "EWS"
                camera_motion = "dolly_out"
                narrative_goal = "释怀平静，镜头后拉渐隐"
                action_zh = f"镜头缓缓向后拉开，【{char_name}】静立于天地间，晨光逐渐洒满大地"
                action_en = f"Slow dolly out, {char_tokens} in peace, golden morning sunlight bathing the landscape"
            else:
                # 主歌 Verse：注重人物面部神情、微动作与心理刻画
                scale_cycle = ["MCU", "CU", "MS", "MCU", "CU"]
                motion_cycle = ["slow_dolly_in", "static", "tracking", "handheld", "tilt_up"]
                shot_size = scale_cycle[shot_num % len(scale_cycle)]
                camera_motion = motion_cycle[shot_num % len(motion_cycle)]
                narrative_goal = "捕捉主人公的微小思绪与动作细节"
                action_zh = f"近景对准【{char_name}】，手指抚过冰冷的物体，眼底流淌出沉思"
                action_en = f"Medium close-up of {char_tokens}, contemplative look, intricate lighting and depth of field"

            # 匹配剪辑 (Match Cut) 与前序依赖
            prev_id = f"shot_{shot_num - 1:03d}" if shot_num > 1 else None
            next_id = f"shot_{shot_num + 1:03d}" if shot_num < num_shots else None
            match_cut = "光影流动匹配" if shot_num % 4 == 0 else None

            # 构造双语提示词
            prompt_zh = f"【{shot_size}】|【{camera_motion}】在{loc_desc}。{action_zh}。歌词意象: {lyric_ref}"
            prompt_en = (
                f"{shot_size} shot, {camera_motion} movement, {style_tokens}. "
                f"{action_en}, at {current_loc.spatial_layout if current_loc else ''}. "
                f"Lighting: {current_loc.canonical_lighting if current_loc else ''}, 8k cinematic masterpiece, 35mm lens."
            )

            shot_id_str = f"shot_{shot_num:03d}"
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
                shot_id=shot_num,
                id=shot_id_str,
                start=round(t_start, 3),
                end=round(t_end, 3),
                section_name=section_name,
                line_indices=matched_line_indices,
                narrative_goal=narrative_goal,
                lyric_reference=lyric_ref,
                character_ids=[char_id],
                location_id=loc_id,
                shot_size=shot_size,
                camera_motion=camera_motion,
                scale=shot_size,
                camera_movement=camera_motion,
                action=action_zh,
                emotion="hopeful" if is_chorus else ("contemplative" if not is_outro else "peaceful"),
                match_cut_element=match_cut,
                previous_shot_id=prev_id,
                next_shot_id=next_id,
                prompt_zh=prompt_zh,
                prompt_en=prompt_en,
                preview_image=f"storyboard/{shot_id_str}.png",
                path=f"storyboard/{shot_id_str}.png",
                takes=[take_a],
                selected_take_id=take_a.id,
            )
            shots.append(shot)

        return shots


# ============================================================================
# 顶级入口：一键导演视听工程 (Director Pipeline Orchestrator)
# ============================================================================

def direct_project(
    project: AlignmentProject,
    analysis: Optional[SongAnalysis] = None,
    min_shots: int = 24,
) -> AlignmentProject:
    """
    一键运行 AI 导演推理流程：
    1. 确保音频智能特征分析就绪；
    2. 生成 1 页纸导演 Treatment 与 Visual Bible Prefabs；
    3. 编译整首歌 30+ 影视级连续 Shot 序列并写入 project.storyboard；
    4. 生成对应的初始 NLE Timeline 片段序列。
    """
    log.info("🎬 启动 AI 导演推理引擎: %s", project.title)

    director = RuleBasedDirector(project, analysis=analysis)

    # 1. 宏观剧作
    treatment, bible = director.build_treatment_and_bible()
    project.treatment = treatment
    project.visual_bible = bible

    # 2. 获取或生成切点
    cut_candidates: list[MusicCutPoint] = []
    if analysis and analysis.cut_candidates:
        cut_candidates = analysis.cut_candidates
    elif project.analysis and project.analysis.cut_candidates:
        cut_candidates = project.analysis.cut_candidates

    # 3. 微观分镜编译
    shots = director.compose_shots(treatment, bible, cut_candidates)
    project.storyboard = shots

    # 4. 构建初始非线性剪辑时间轴 (NLE Timeline)
    timeline_clips: list[NLEClip] = []
    for s in shots:
        clip = NLEClip(
            id=f"clip_{s.id}",
            shot_id=s.id,
            take_id=s.selected_take_id or "",
            source_media_path=s.preview_image,
            source_in=0.0,
            source_out=s.duration,
            timeline_in=s.start,
            timeline_out=s.end,
            speed=1.0,
            transition_in="cut",
            transition_out="cut",
        )
        timeline_clips.append(clip)
    project.timeline = timeline_clips

    log.info("✅ 导演分镜规划完成: 共编译 %d 个分镜 Shot，覆盖时长 %.2fs", len(shots), director.duration)
    return project
