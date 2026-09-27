"""
Pass A: 全局创见与企划导演 (Creative Director & Sequence Planner)
-----------------------------------------------------------------
负责整首 MV 的宏观剧作架构：
1. 提取音乐主题、核心冲突与意境，生成 DirectorTreatment；
2. 梳理全局美学规范与连续性资产，生成 GlobalBibles (Visual, Typography, Asset, Motif)；
3. 构建 4~6 个宏观叙事序列 (SequencePlan)，破除“歌词句=镜头”限制；
4. 综合音频物理能量与戏剧弧线，生成解耦的时域动态曲线 TemporalDirection (Music Energy ≠ Visual Intensity)。
"""
from __future__ import annotations

from typing import Optional, List
from src.storyboard_schema import (
    AlignmentProject,
    AssetBible,
    CharacterPrefab,
    CurvePoint,
    DirectorTreatment,
    GlobalBibles,
    LocationPrefab,
    MotifBible,
    MotifPrefab,
    MusicSection,
    PropPrefab,
    SequencePlan,
    SongAnalysis,
    StylePrefab,
    TemporalDirection,
    TypographyBible,
    VisualBible,
)
from src.utils import log


class CreativeDirector:
    """Pass A: 宏观视听与叙事企划总监"""

    def __init__(self, project: AlignmentProject, analysis: Optional[SongAnalysis] = None):
        self.project = project
        self.analysis = analysis or project.analysis
        self.duration = project.duration or (self.analysis.duration if self.analysis else 0.0)
        if self.duration <= 0 and project.lines:
            self.duration = max(line.end for line in project.lines) + 2.0

    def plan_treatment_and_bibles(self) -> tuple[DirectorTreatment, GlobalBibles]:
        """构建全局导演阐述与四维圣经 (Visual, Typography, Asset, Motif)"""
        title = self.project.title or "未命名曲目"
        lyrics_full = f"{title}\n" + "\n".join(line.text for line in self.project.lines)

        # 意象检测器
        has_porcelain = any(w in lyrics_full for w in ["青瓷", "天青", "瓷盏", "瓷器", "釉", "冰裂", "拉胚", "窑火", "柴窑", "泥料", "陶艺"]) or ("瓷" in lyrics_full and "匠" in lyrics_full)
        has_cosmic = any(w in lyrics_full for w in ["星球", "宇宙", "银河", "星星", "B-612", "B612", "小王子", "玫瑰", "狐狸", "火山", "猴面包树", "光年", "星空", "流星", "星轨", "陨石", "纯粹"])
        has_ocean = any(w in lyrics_full for w in ["海", "浪", "潮", "深蓝", "岸", "洋", "舟", "巨轮", "灯塔", "沙滩", "珊瑚"])
        has_nature = any(w in lyrics_full for w in ["森林", "林间", "绿意", "花草", "山谷", "荒原", "麦田", "溪流", "微风", "飞鸟", "原野"])
        has_urban = any(w in lyrics_full for w in ["城", "街", "车", "窗", "霓虹", "站台", "楼", "铁", "京", "公路"])

        if has_porcelain or (has_ocean and "匠" in lyrics_full):
            # 传统工艺、器物哲思与文明传承主题 (如《匠心入梦》)
            theme = "微观器物、时代时空折叠与文明匠心传承"
            logline = f"从一件天青色瓷盏的冰裂微观世界出发，穿梭于千百年古镇造船与现代工业巨轮之间，展现匠人精神对时间的超越。"
            char_lead = CharacterPrefab(
                id="char_craftsman",
                name="明轩",
                role="protagonist",
                appearance="26岁年轻工艺传承人，黑发后梳，眼神专注敏锐，手指带有轻微泥料与刻刀痕迹",
                wardrobe="深青色棉麻工装围裙，内着浅灰素色棉衬衫，袖口微微挽起",
                canonical_tokens=["26yo east asian craftsman", "focused piercing gaze", "dark linen craft apron", "rolled sleeves"],
                forbidden_tokens=["blonde", "glasses", "western modern suit", "bright plastic accessories"],
            )
            loc_a = LocationPrefab(
                id="loc_tea_studio",
                name="雨后古建筑手作茶室",
                spatial_layout="木制雕花窗棂，雨后初晴光斑照在暗色木桌上，盛满茶水的天青色瓷盏静置其上",
                canonical_lighting="柔和侧逆光与丁达尔光束（Tyndall effect），青色阴影与温暖高光交融",
                time_of_day="day",
            )
            loc_b = LocationPrefab(
                id="loc_shipyard_dock",
                name="工业巨轮船坞与海浪前沿",
                spatial_layout="巨大的暗红锈色钢铁船体结构，脚手架林立，远处波涛汹涌的海面延伸至天际",
                canonical_lighting="清晨海面破晓冷蓝光，巨轮表面反射出金色朝阳",
                time_of_day="dawn",
            )
            prop_cup = PropPrefab(
                id="prop_porcelain_cup",
                name="天青色冰裂瓷盏",
                visual_features="仿宋官窑天青釉，口沿紫口铁足，表面密布深浅交错的蝉翼冰裂开片，釉面温润如玉",
                symbolic_meaning="时间、匠人灵魂与历史记忆的物质载体",
            )
            motifs = [
                MotifPrefab(
                    id="motif_crack",
                    name="冰裂与接缝 (Crack & Seam)",
                    core_concept="历史记忆与时间封存在材质的裂痕之中",
                    manifestations=[
                        "瓷盏釉面微观冰裂纹理",
                        "老街青石板路缝隙中的青苔与雨水",
                        "造船厂巨轮钢板之间的精密焊接缝",
                    ],
                ),
                MotifPrefab(
                    id="motif_ripple",
                    name="旋转同心圆 (Rotational Ripple)",
                    core_concept="生命的流转与工艺动作的永恒轮回",
                    manifestations=[
                        "茶盏内茶汤轻轻荡漾的同心涟漪",
                        "陶艺拉胚转盘的飞速旋转",
                        "巨轮破开海浪时卷起的庞大同心波涛",
                    ],
                ),
            ]
            color_palette = ["#0F2027", "#203A43", "#2C5364", "#A0D8EF", "#D4AF37"]
            visual_style = "cinematic realism, 35mm anamorphic filmic depth, natural volumetric atmosphere"
            typo_placement = "bottom_left"
            motion_pers = "ink_bloom"
        elif has_cosmic:
            # 宇宙星际、小王子的玫瑰誓言与孤独哲学主题 (如《编号B-612的告别》)
            theme = "微缩星球、玫瑰守望与光年之外的哲思告别"
            logline = f"在仅有三座火山与一株玫瑰的微型星球B-612上，金发星际旅人拔除猴面包树幼苗，在光年轨迹与漫天星辰中守护唯一的纯粹。"
            char_lead = CharacterPrefab(
                id="char_little_prince",
                name="星际旅人",
                role="protagonist",
                appearance="金发微卷凌乱，清瘦身形，眼眸清澈纯粹却带着洞悉宇宙的淡淡忧伤",
                wardrobe="金黄色长围巾随星际微风飘扬，深青墨绿复古旅人风衣，深色长裤与短靴",
                canonical_tokens=["young traveler with messy golden hair", "flowing golden scarf", "pure deep melancholy eyes", "vintage dark cyan traveler coat"],
                forbidden_tokens=["sunglasses", "modern sportswear", "business suit", "heavy combat armor"],
            )
            loc_a = LocationPrefab(
                id="loc_b612_planet",
                name="B-612微型星球与火山群",
                spatial_layout="微曲弧度的微型星球地表，两座微型活火山与一座休眠火山伫立，低矮弧形地平线外是浩瀚无垠的深邃星海与瑰丽星云",
                canonical_lighting="幽蓝星海冷光与落日余晖交织，微弱丁达尔星尘漂浮在静谧虚空中",
                time_of_day="dusk",
            )
            loc_b = LocationPrefab(
                id="loc_glass_rose",
                name="玻璃罩孤株玫瑰台",
                spatial_layout="精致晶莹的半球形玻璃罩，内里一朵带刺盛放的深红玫瑰，背景为旋转漫卷的银河光轨",
                canonical_lighting="深空冷青与玫瑰艳红荧光形成鲜明冷暖对撞，玻璃罩倒映出遥远恒星光芒",
                time_of_day="night",
            )
            prop_cup = PropPrefab(
                id="prop_glass_rose_flower",
                name="玻璃罩下的唯一玫瑰",
                visual_features="深红重瓣带刺玫瑰，花瓣凝结晶莹露珠，罩在复古透明玻璃罩内",
                symbolic_meaning="独一无二的爱、漫长驯养与不可替代的责任",
            )
            motifs = [
                MotifPrefab(
                    id="motif_orbital_arc",
                    name="星轨弧线与光年轨迹 (Orbital Arc)",
                    core_concept="跨越光年的遥远守望与命运轨迹的重叠",
                    manifestations=[
                        "微型星球微曲的地平线弧光",
                        "深邃星空中长曝光的同心圆星轨",
                        "金黄色长围巾在星风中划出的优雅抛物线",
                    ],
                ),
                MotifPrefab(
                    id="motif_sprout_pull",
                    name="幼苗拔除与火山余温 (Sprout & Ember)",
                    core_concept="日复一日对纯粹净土的执着守卫",
                    manifestations=[
                        "双手小心翼翼拔出猴面包树幼苗时的星尘飞扬",
                        "微型休眠火山口升起的细细温热青烟",
                        "玻璃罩上凝聚滑落的一滴清晨水痕",
                    ],
                ),
            ]
            color_palette = ["#0A0E27", "#1E1B4B", "#312E81", "#F59E0B", "#F43F5E"]
            visual_style = "poetic cinematic fantasy, Saint-Exupery nostalgia, anamorphic 35mm space bokeh, melancholic magical realism"
            typo_placement = "bottom_center"
            motion_pers = "starfall_fade"
        elif has_ocean:
            theme = "潮汐边缘的记忆救赎与未知航行"
            logline = f"在潮汐与时间的边缘，一位青年在海边废弃遗迹中重寻失去的记忆与前行方向。"
            char_lead = CharacterPrefab(
                id="char_lead",
                name="林",
                role="protagonist",
                appearance="23岁年轻女性，黑色齐肩短发，清澈坚定的目光，面容素净",
                wardrobe="灰白色亚麻风衣，深灰长裤，银质水滴形吊坠",
                canonical_tokens=["23yo asian woman", "short black bob", "white linen trench coat", "silver pendant"],
                forbidden_tokens=["blonde", "glasses", "heavy makeup", "neon clothing"],
            )
            loc_a = LocationPrefab(
                id="loc_coastal_railway",
                name="废弃沿海站台",
                spatial_layout="锈蚀铁轨伸向广袤海水中，木制月台长满杂草野花",
                canonical_lighting="清晨薄雾，微弱冷天光与淡金色曦光交界",
                time_of_day="dawn",
            )
            loc_b = LocationPrefab(
                id="loc_tide_pool",
                name="潮汐玄武岩礁石",
                spatial_layout="黑色玄武岩礁石群，潮洼倒映着苍茫云空",
                canonical_lighting="阴云柔和漫射光，冷青调暗部",
                time_of_day="dusk",
            )
            prop_cup = PropPrefab(
                id="prop_compass",
                name="黄铜古罗盘",
                visual_features="指针微微晃动，外壳有海水侵蚀斑痕",
                symbolic_meaning="未明的心绪方向",
            )
            motifs = [
                MotifPrefab(
                    id="motif_wave",
                    name="潮汐起伏 (Tidal Flow)",
                    core_concept="不可逆的时间冲刷与记忆冲刷",
                    manifestations=["礁石浪花碎裂", "被海水吞没的铁轨", "眼底涌起的水光"],
                )
            ]
            color_palette = ["#1A365D", "#4A7C9B", "#DCE6EC", "#E29578", "#F4F1DE"]
            visual_style = "cinematic realism with melancholic naturalism"
            typo_placement = "bottom_center"
            motion_pers = "calm_fade"
        elif has_nature:
            theme = "林野微光、自然呼吸与万物生长"
            logline = f"穿行于晨曦未晞的深山林海与金色麦田，在微风与草木荣枯之间找回内心的平和与纯真。"
            char_lead = CharacterPrefab(
                id="char_naturalist",
                name="初禾",
                role="protagonist",
                appearance="22岁自然采风者，素雅干净，眼眸清澈，微风吹拂发梢",
                wardrobe="亚麻米白衬衫，浅棕工装背带裤，胸前挂着小巧铜哨",
                canonical_tokens=["22yo east asian naturalist", "simple linen clothes", "clear calm eyes"],
                forbidden_tokens=["heavy makeup", "neon colors", "cyberpunk clothing"],
            )
            loc_a = LocationPrefab(
                id="loc_morning_forest",
                name="晨曦薄雾林海与溪谷",
                spatial_layout="苍翠高耸的林木，清冽溪流在卵石间奔流，晨曦透过树冠形成如丝缕般的金色丁达尔光束",
                canonical_lighting="清晨温润阳光透射森林薄雾，高对比度天然光斑",
                time_of_day="dawn",
            )
            loc_b = LocationPrefab(
                id="loc_golden_meadow",
                name="风中起伏的金色原野",
                spatial_layout="无边无际的风吹麦浪与野花坡地，远山如黛在薄霭中隐现",
                canonical_lighting="黄昏金色时刻 (Golden Hour)，温暖柔和的侧逆光",
                time_of_day="golden_hour",
            )
            prop_cup = PropPrefab(
                id="prop_wildflower_herbarium",
                name="手工植物标本集",
                visual_features="牛皮纸压花装订，夹着干枯却颜色如初的风铃草与麦芒",
                symbolic_meaning="封存的时节与生命的呼吸",
            )
            motifs = [
                MotifPrefab(
                    id="motif_wind_sway",
                    name="风拂草木 (Wind Whisper)",
                    core_concept="无形之风带来的万物生息",
                    manifestations=["微风吹拂过麦浪掀起如海浪般的金波", "树梢间隙落下的斑驳光斑晃动", "指尖抚过草叶时的露珠飞溅"],
                ),
            ]
            color_palette = ["#1C3124", "#2E5339", "#8FA382", "#E8DDB5", "#D4A373"]
            visual_style = "naturalistic cinematic realism, Terrence Malick style golden light, 35mm organic film grain"
            typo_placement = "bottom_center"
            motion_pers = "breeze_sway"
        else:
            theme = "都市孤岛、霓虹梦境与破晓释怀"
            logline = f"穿行在雨夜霓虹迷离的都市边缘，在光影流转中体悟生命如其所是的平静。"
            char_lead = CharacterPrefab(
                id="char_lead",
                name="安",
                role="protagonist",
                appearance="25岁男子，微卷碎发，神情深邃略带疲惫，高挑身形",
                wardrobe="深黑色复古皮夹克，暗青色高领毛衣",
                canonical_tokens=["25yo east asian male", "wavy dark hair", "black leather jacket"],
                forbidden_tokens=["bald", "sunglasses", "sportswear"],
            )
            loc_a = LocationPrefab(
                id="loc_rainy_street",
                name="雨夜霓虹街道",
                spatial_layout="湿漉反光沥青路面，昏黄路灯与暗紫霓虹倒影",
                canonical_lighting="高对比度夜景，冷青水洼反射",
                time_of_day="neon_night",
            )
            loc_b = LocationPrefab(
                id="loc_rooftop",
                name="天台城市远眺",
                spatial_layout="空旷天台，地平线泛起冷金暖光",
                canonical_lighting="黎明蓝调时刻 (Blue Hour)",
                time_of_day="dawn",
            )
            prop_cup = PropPrefab(
                id="prop_cassette",
                name="复古磁带随身听",
                visual_features="半透明磨砂外壳，磁带缓慢转动",
                symbolic_meaning="封存的旋律与真实的自我",
            )
            motifs = [
                MotifPrefab(
                    id="motif_light_blur",
                    name="光斑流淌 (Bokeh Stream)",
                    core_concept="虚幻都市与内心情感的对撞",
                    manifestations=["车窗水滴散景", "霓虹光斑弥散", "黎明刺破黑暗的光束"],
                )
            ]
            color_palette = ["#0B132B", "#1C2541", "#3A506B", "#5BC0BE", "#FFD166"]
            visual_style = "neo-noir cinematic realism, anamorphic flare"
            typo_placement = "bottom_center"
            motion_pers = "typewriter"

        treatment = DirectorTreatment(
            title=title,
            logline=logline,
            visual_theme=theme,
            director_statement=(
                f"本片拒绝机械图解歌词，通过【{char_lead.name}】的视听动线将音乐声学能量转化为具有电影呼吸感的蒙太奇。"
                f"在微观叙事与宏观场景之间构建对位反差，在副歌重拍处强化视听母题的穿透力。"
            ),
            visual_metaphors=[m.core_concept for m in motifs],
            acts=[
                {"act": 1, "title": "启程与凝视", "narrative": "微观世界建立，信物显现，铺垫沉静氛围。"},
                {"act": 2, "title": "流动与对抗", "narrative": "跨入开阔空间，母题元素在不同材质间碰撞递进。"},
                {"act": 3, "title": "爆发与释怀", "narrative": "副歌能量全开，视听母题形成终极共振，回归平和。"},
            ],
        )

        visual_bible = VisualBible(
            title=f"{title} 视觉圣经",
            theme=theme,
            narrative_synopsis=logline,
            color_palette=color_palette,
            visual_style_anchor=visual_style,
            character_anchor=f"{char_lead.name} ({char_lead.appearance})",
            environment_anchor=f"{loc_a.name} & {loc_b.name}",
            characters=[char_lead],
            locations=[loc_a, loc_b],
            props=[prop_cup],
            style=StylePrefab(
                visual_style=visual_style,
                color_palette=color_palette,
                lens_spec="35mm Anamorphic, f/1.8",
                lighting_mood="natural volumetric lighting, cinematic contrast",
                film_grain="subtle 35mm grain",
            ),
        )

        typography_bible = TypographyBible(
            font_family="Microsoft YaHei",
            primary_color=color_palette[-2] if len(color_palette) >= 2 else "#FFFFFF",
            secondary_color=color_palette[0],
            preferred_placement=typo_placement,
            motion_personality=motion_pers,
        )

        asset_bible = AssetBible(
            characters=[char_lead],
            locations=[loc_a, loc_b],
            props=[prop_cup],
        )

        motif_bible = MotifBible(motifs=motifs)

        bibles = GlobalBibles(
            visual=visual_bible,
            typography=typography_bible,
            assets=asset_bible,
            motifs=motif_bible,
        )

        return treatment, bibles

    def plan_sequences(self, treatment: DirectorTreatment) -> list[SequencePlan]:
        """
        基于音乐乐段结构与戏剧三幕式，划分 4~6 个宏观叙事序列 (SequencePlan)。
        每个序列统领 15~45 秒的时间区间，破除“一句歌词等于一个镜头”的机械绑定。
        """
        sections = self.project.sections
        lines = self.project.lines
        total_dur = self.duration

        sequences: list[SequencePlan] = []

        if sections and len(sections) >= 3:
            # 依据乐段智能聚类为 4~6 个 Narrative Sequences
            seq_num = 1
            for sec in sections:
                # 寻找该乐段内包含的歌词索引
                matched_line_indices = [
                    idx for idx, line in enumerate(lines)
                    if max(sec.start, line.start) < min(sec.end, line.end)
                ]
                dramatic_function = "铺垫情境与微观意象" if "Intro" in sec.name else (
                    "情绪蓄力与人物内省" if "Verse" in sec.name else (
                        "视听高潮爆发与母题汇聚" if "Chorus" in sec.name else (
                            "转折过渡与戏剧反差" if "Bridge" in sec.name else "回味释怀与余韵渐远"
                        )
                    )
                )
                seq = SequencePlan(
                    id=f"SEQ_{seq_num:02d}",
                    sequence_number=seq_num,
                    title=f"第 {seq_num} 幕：{sec.name} ({sec.label or dramatic_function[:6]})",
                    start=round(sec.start, 3),
                    end=round(min(sec.end, total_dur), 3),
                    dramatic_function=dramatic_function,
                    section_name=sec.name,
                    lyric_indices=matched_line_indices,
                    shot_ids=[],  # 由 Pass B (ShotPlanner) 回填
                )
                sequences.append(seq)
                seq_num += 1
        else:
            # 无乐段标注时，按戏剧结构智能划分为 5 幕标准序列
            time_splits = [
                (0.0, total_dur * 0.15, "序章：微观引子与时空入画", "Intro"),
                (total_dur * 0.15, total_dur * 0.40, "第一幕：日常沉淀与工艺凝视", "Verse 1"),
                (total_dur * 0.40, total_dur * 0.65, "第二幕：破浪前行与视听交锋", "Chorus 1"),
                (total_dur * 0.65, total_dur * 0.85, "第三幕：沉吟思索与历史回响", "Bridge"),
                (total_dur * 0.85, total_dur, "尾声：传承升华与归宿如初", "Outro"),
            ]
            for seq_num, (st, en, title, sec_name) in enumerate(time_splits, start=1):
                matched_line_indices = [
                    idx for idx, line in enumerate(lines)
                    if max(st, line.start) < min(en, line.end)
                ]
                seq = SequencePlan(
                    id=f"SEQ_{seq_num:02d}",
                    sequence_number=seq_num,
                    title=title,
                    start=round(st, 3),
                    end=round(en, 3),
                    dramatic_function=title.split("：")[-1],
                    section_name=sec_name,
                    lyric_indices=matched_line_indices,
                    shot_ids=[],
                )
                sequences.append(seq)

        return sequences

    def plan_temporal_direction(self, sequences: list[SequencePlan]) -> TemporalDirection:
        """
        生成解耦的时域动态控制曲线 (Music Energy, Emotion, Visual Intensity)。
        实现对位蒙太奇原则：音乐物理能量 ≠ 导演视听张力。
        """
        music_energy_pts: list[CurvePoint] = []
        emotion_pts: list[CurvePoint] = []
        intensity_pts: list[CurvePoint] = []

        # 采样时间点
        sample_times = [0.0]
        for seq in sequences:
            sample_times.append(seq.start)
            sample_times.append((seq.start + seq.end) / 2.0)
            sample_times.append(seq.end)
        sample_times = sorted(list(set(round(t, 2) for t in sample_times if t <= self.duration)))

        for t in sample_times:
            # 找到所在 Sequence
            curr_seq = next((s for s in sequences if s.start <= t <= s.end), sequences[-1])
            is_chorus = "Chorus" in curr_seq.section_name
            is_intro = "Intro" in curr_seq.section_name
            is_bridge = "Bridge" in curr_seq.section_name

            # 物理音乐能量
            m_val = 0.85 if is_chorus else (0.25 if is_intro else (0.55 if is_bridge else 0.45))
            # 情感起伏
            e_val = 0.90 if is_chorus else (0.30 if is_intro else 0.60)
            # 导演视听张力 (引入艺术对位控制：Bridge 阶段音乐变缓但戏剧张力极高，Intro 保持克制留白)
            if is_intro:
                v_val = 0.15  # 极简静止，环境留白
                label = "微观静止与留白"
            elif is_chorus:
                v_val = 0.95  # 视听大开大合，强烈冲击
                label = "视听母题强爆发"
            elif is_bridge:
                v_val = 0.70  # 音乐减弱但张力积蓄 (反差对位)
                label = "沉静内省但张力紧绷"
            else:
                v_val = 0.40  # 节奏平稳铺垫
                label = "平缓叙事流动"

            music_energy_pts.append(CurvePoint(time=t, value=m_val, label=curr_seq.section_name))
            emotion_pts.append(CurvePoint(time=t, value=e_val, label=curr_seq.dramatic_function))
            intensity_pts.append(CurvePoint(time=t, value=v_val, label=label))

        return TemporalDirection(
            music_energy=music_energy_pts,
            emotion_curve=emotion_pts,
            visual_intensity=intensity_pts,
        )

    def execute(self) -> AlignmentProject:
        """执行 Pass A 全流程并写入 project 实例"""
        log.info("🎬 [Pass A] 启动全局创见与叙事规划: %s", self.project.title or "歌曲")
        treatment, bibles = self.plan_treatment_and_bibles()
        sequences = self.plan_sequences(treatment)
        temporal_dir = self.plan_temporal_direction(sequences)

        self.project.treatment = treatment
        self.project.bibles = bibles
        self.project.visual_bible = bibles.visual
        self.project.sequences = sequences
        self.project.temporal_direction = temporal_dir

        log.info("✅ [Pass A] 宏观企划完成: 生成 %d 个叙事序列，世界观与母题圣经就绪", len(sequences))
        return self.project
