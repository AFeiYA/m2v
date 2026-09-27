"""
Pass C: 蒙太奇连续性与剪辑导演 (Continuity Director & Shot Graph)
-----------------------------------------------------------------
负责在拿到完整 Shot List 后进行全局二次扫描，建立真正的影视视听因果网：
1. 邻接镜头分析：计算相邻 Shot N 与 N-1 的视听语法 (Match Cut, Eyeline Match, Scale Contrast, Motion Vector)；
2. 规避“伪连续性”：基于全局真实生成的镜头属性计算真实转场，拒绝单镜头孤岛临场臆测；
3. 副歌复沓与母题进化 (Motif Callback & Visual Echo)：识别重复副歌与母题，赋予镜头回溯与意义演进；
4. 编译输出严密的 Shot Graph。
"""
from __future__ import annotations

from typing import List, Optional
from src.storyboard_schema import (
    AlignmentProject,
    GlobalBibles,
    SequencePlan,
    ShotPlan,
    TransitionSpec,
)
from src.utils import log


# 景别数值等级映射 (用于计算景别反差幅度)
SCALE_RANK = {
    "ECU": 1,
    "CU": 2,
    "MCU": 3,
    "MS": 4,
    "MLS": 5,
    "WS": 6,
    "EWS": 7,
}


class ContinuityDirector:
    """Pass C: 全局连续性审片与蒙太奇拓扑导演"""

    def __init__(self, project: AlignmentProject):
        self.project = project

    def weave_shot_graph(
        self,
        shots: list[ShotPlan],
        bibles: Optional[GlobalBibles] = None,
        sequences: Optional[list[SequencePlan]] = None,
    ) -> list[ShotPlan]:
        """
        对已生成的 Shot 列表进行全局连续性编织与转场蒙太奇构建。
        """
        if not shots:
            return shots

        bibles = bibles or self.project.bibles or GlobalBibles()
        sequences = sequences or self.project.sequences or []
        num_shots = len(shots)

        # 记录各乐段第一次出现时的起始镜头索引 (用于副歌视觉复沓)
        first_section_shot_map: dict[str, ShotPlan] = {}

        # --------------------------------------------------------------------
        # 1. 邻接镜头转场语法扫描 (Adjacency & Cut Analysis)
        # --------------------------------------------------------------------
        for i in range(num_shots):
            curr_shot = shots[i]

            # 记录首次出现的乐段代表镜头
            norm_sec = curr_shot.section_name.split()[0] if curr_shot.section_name else "Section"
            if norm_sec not in first_section_shot_map:
                first_section_shot_map[norm_sec] = curr_shot

            if i == 0:
                # 创世纪首镜：黑屏渐显入画
                curr_shot.incoming_transition = TransitionSpec(
                    target_shot_id="",
                    transition_type="cut",
                    description="全片开篇第一镜，黑屏淡入 (Fade in from black)",
                )
                curr_shot.previous_shot_id = None
                continue

            prev_shot = shots[i - 1]
            curr_shot.previous_shot_id = prev_shot.id
            prev_shot.next_shot_id = curr_shot.id

            # 计算景别跨度
            rank_curr = SCALE_RANK.get(curr_shot.shot_size, 4)
            rank_prev = SCALE_RANK.get(prev_shot.shot_size, 4)
            scale_diff = abs(rank_curr - rank_prev)

            # 跨幕次/乐段判断
            is_new_sequence = curr_shot.sequence_id != prev_shot.sequence_id
            is_new_section = curr_shot.section_name != prev_shot.section_name

            # 蒙太奇语法决策树 (Montage Decision Matrix)
            if scale_diff >= 3:
                # 景别大跨度反差 (例如 EWS -> ECU 或 WS -> CU)
                t_type = "scale_contrast"
                t_desc = f"景别大尺度反差推拉 ({prev_shot.shot_size} ➔ {curr_shot.shot_size})，产生呼吸感与视觉顿挫"
            elif curr_shot.camera_motion in ("pan_left", "pan_right", "tracking") and curr_shot.camera_motion == prev_shot.camera_motion:
                # 运镜动势矢量连贯匹配
                t_type = "motion_vector_match"
                t_desc = f"镜头运动矢量方向连贯 ({prev_shot.camera_motion})，镜头动势无缝顺接"
            elif (curr_shot.visual_metaphor and prev_shot.visual_metaphor and
                  curr_shot.visual_metaphor == prev_shot.visual_metaphor):
                # 共享视觉母题同构匹配
                t_type = "match_cut"
                t_desc = f"核心视觉母题同构匹配剪辑 (Match Cut: {curr_shot.visual_metaphor[:10]})"
            elif is_new_sequence or is_new_section:
                # 幕次转折
                if "Chorus" in curr_shot.section_name:
                    t_type = "match_cut"
                    t_desc = f"跨入高潮乐段 ({curr_shot.section_name})，重拍声画交汇，同心圆动势匹配"
                else:
                    t_type = "cut"
                    t_desc = f"幕次更替硬切 ({prev_shot.sequence_id} ➔ {curr_shot.sequence_id})，时空自然转换"
            else:
                t_type = "cut"
                t_desc = "利落硬切 (Standard Cut)，保持自然叙事节奏"

            spec = TransitionSpec(
                target_shot_id=prev_shot.id,
                transition_type=t_type,
                description=t_desc,
            )
            curr_shot.incoming_transition = spec
            prev_shot.outgoing_transition = TransitionSpec(
                target_shot_id=curr_shot.id,
                transition_type=t_type,
                description=t_desc,
            )

        # 最后一镜出点
        shots[-1].outgoing_transition = TransitionSpec(
            target_shot_id="",
            transition_type="dissolve",
            description="全片落幕终镜，画面缓缓融入黑场 (Fade to black)",
        )

        # --------------------------------------------------------------------
        # 2. 副歌复沓与母题进化扫描 (Motif Callback & Progression)
        # --------------------------------------------------------------------
        for i, shot in enumerate(shots):
            sec_name = shot.section_name
            # 识别是否为第 2 次及以后的副歌 (Chorus 2, Chorus 3)
            if "Chorus" in sec_name and ("2" in sec_name or "3" in sec_name or "Final" in sec_name):
                # 寻找在 Chorus 1 中的对应代表镜头
                chorus_1_shot = first_section_shot_map.get("Chorus")
                if chorus_1_shot and chorus_1_shot.id != shot.id:
                    shot.callback_to_shot = chorus_1_shot.id
                    shot.callback_type = "progression"
                    callback_note = (
                        f" [副歌视觉复沓与进阶：回溯呼应 {chorus_1_shot.id}，但此处画面不再简单重复，"
                        f"而是将母题从微观工艺升华为宏大叙事，形成意义递进]"
                    )
                    if callback_note not in shot.director_note:
                        shot.director_note += callback_note

            # 识别同一母题在不同镜头间的视听回响 (Visual Echo)
            elif shot.visual_intensity > 0.8 and i > 4:
                # 高张力镜头寻找前序共享母题的镜头
                earlier_match = next((
                    s for s in shots[:i-2]
                    if s.visual_metaphor and s.visual_metaphor == shot.visual_metaphor
                ), None)
                if earlier_match:
                    shot.callback_to_shot = earlier_match.id
                    shot.callback_type = "visual_echo"
                    echo_note = f" [母题回响 (Visual Echo)：与 {earlier_match.id} 的 '{shot.visual_metaphor[:8]}' 产生视听同构]"
                    if echo_note not in shot.director_note:
                        shot.director_note += echo_note

        log.info("✅ [Pass C] 连续性蒙太奇编织完成: 为 %d 个 Shot 构建了 Shot Graph 与副歌复沓链", num_shots)
        return shots
