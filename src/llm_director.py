"""
LLM Director — Semantic Video/Text Effect Automation for M2V

This script automates:
1. Parsing lyrics from `alignment.json`.
2. Formulating a structured prompt for LLMs (Gemini, Claude, GPT) to design:
   - Semantic text effects (standard Hex colors, translated to ASS BGR automatically).
   - High-fidelity video generation prompts for each line.
3. Merging the LLM response back into the alignment JSON:
   - Creating a storyboard mapped to video clips (e.g. clip_001.mp4).
   - Overriding ASS subtitle colors/effects per line.
"""

import os
import json
from typing import Any
import argparse
import subprocess
from pathlib import Path
from dataclasses import asdict

from src.storyboard_schema import (
    AlignmentProject as AlignmentResult,
    ShotPlan as StoryboardEvent,
    ShotPlan,
    Take,
    CompositionSafeZones,
    TransitionSpec,
    AlignedLine,
    WordTimestamp,
)
from src.utils import log

# ── Color Converter ────────────────────────────────────────────────────────

def hex_to_ass_color(hex_str: str, alpha: int = 0) -> str:
    """
    Converts standard Hex colors (#RRGGBB) to ASS BGR format (&H00BBGGRR&).
    E.g. #FF8833 -> &H003388FF&
    """
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 8:
        # RRGGBBAA
        r, g, b, a = hex_str[0:2], hex_str[2:4], hex_str[4:6], hex_str[6:8]
        # ASS Alpha is 255 - A (opacity), or we can use A directly as transparency
        # In ASS, 00 is opaque, FF is transparent.
        try:
            val_a = 255 - int(a, 16)
        except ValueError:
            val_a = 0
        alpha = min(255, max(0, val_a))
    elif len(hex_str) == 6:
        r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
    else:
        # Fallback to white
        r, g, b = "FF", "FF", "FF"
    
    return f"&H{alpha:02X}{b}{g}{r}&"

# ── Prompt Generator ────────────────────────────────────────────────────────

SYSTEM_PROMPT_DUAL_TRACK = """You are a visionary Music Video Director, Master Cinematographer, and Motion Designer.
You will direct a high-end music video with an AI-Native Dual-Track NLE Pipeline:
1. TRACK 1: VIDEO GENERATION (Pure Visual Cinematography — NO text/subtitles rendered inside the video!)
2. TRACK 2: TYPOGRAPHY & MOTION GRAPHICS (Kinetic typography rendered by ASS/Canvas, adhering to Safe Zones)
3. TRACK 3: DIRECTOR REVIEW & MONTAGE (In-depth directorial intent and connective grammar for director review)

CRITICAL MANDATES:
1. PURE CINEMATIC VISUALS & TWO-STAGE DECOUPLED PROMPTS (首帧静态材质与运镜时空解耦):
   - "keyframe_prompt": Pure Static Visual & Materials Spec for FLUX 12B T2I. Highly tactile description of materials, surfaces, lighting, depth of field, 35mm/85mm lens. STRICTLY NO CAMERA MOVEMENT WORDS (No dolly, pan, tracking, zoom, motion).
   - "motion_prompt": Spatiotemporal Camera Motion & Physics Spec for LTX/Wan I2V. Camera movement trajectory, panning/dolly speed, subject rigidity (e.g. 'subject remains a solid rigid body without warping'), light beam glints, micro dust floating.
   - "endframe_prompt" (Optional): Ending frame static description for one-take continuous transitions or match cuts.
   - "continuity_mode" (Optional): "cut", "match_cut", or "one_take_continuous" (seamless first/last frame inheritance).
   - "video_prompt": Combined cinematic prompt for Google Veo, Runway, Sora, and general compatibility. Follow the 5-element formula: [Shot Scale & Lens] + [Focal Subject & Tactile Textures] + [Environment & Volumetric Lighting] + [Explicit Camera Movement & Physics] + [Film Emulsion & Photorealistic Quality].
   - ZERO-TEXT MANDATE: NEVER include words like 'text', 'subtitles', 'lyrics', 'letters', or 'typography' inside video_prompt or keyframe_prompt! Video diffusion models will mistakenly paint corrupted letters on screen. Subtitles are dynamically rendered downstream by the NLE compositor.

2. BILINGUAL PROMPT ENGINEERING SPECIFICATIONS (中英文提示词特性与认知差异分工):
   - CHINESE FIELDS ("design_rationale", "transition_rationale", "storyboard_design"):
     * Focus on POETIC INTENT, DRAMATIC SUBTEXT, EMOTIONAL ATMOSPHERE, AND EDITING GRAMMAR.
     * Explain WHY this shot scale and lighting were chosen, and how the transition matches adjacent shots (Match Cut, Motion Vector Match).
     * Serves human directors, editors, and Chinese-native models (Kling, Jimeng) that excel at understanding Chinese poetic metaphors.
   - ENGLISH FIELDS ("video_prompt", "keyframe_prompt", "motion_prompt"):
     * DO NOT LITERALLY TRANSLATE CHINESE POETIC METAPHORS! English video models (Google Veo, Sora, LTX) fail on abstract metaphors like "sorrow fills the air" or "loneliness flows like water".
     * YOU MUST PERFORM PHYSICAL TRANSDUCTION: Convert abstract emotions into CONCRETE, PHYSICALLY RENDERABLE OPTICS, TEXTURES, AND GEOMETRY (e.g., "heavy overcast twilight, rain streaks weeping down a cold double-glazed window, cool desaturated slate-blue palette, soft volumetric rim lighting").
     * Strict physical plausibility: specify lighting sources, lens millimeter, depth of field, tactile surfaces (e.g. wet asphalt, aged oak, brushed titanium, porcelain glaze).

3. COMPOSITION SAFE ZONES (构图安全区协议):
   - Specify "composition_safe_zones":
     * "primary_subject_zone": e.g., "center_right", "center", "center_left", "top_center", "bottom_right" where the visual focal point / character is located.
     * "protected_regions": List of zones where typography MUST NOT intrude (e.g. ["center_right", "top_right"]).
     * "preferred_text_regions": Suggested safe anchor zones for typography (e.g. ["bottom_left", "vertical_left"]).

4. HUMAN-READABLE DIRECTORIAL INTENT (导演检视核心字段):
   - "design_rationale": In Chinese, explain WHY this shot size (ECU/CU/MCU/MS/MLS/WS/EWS), camera angle, lighting, and visual metaphor embody the musical mood and lyric subtext.
   - "transition_rationale": In Chinese, explain the visual and auditory connective grammar linking this shot with adjacent shots (Match Cut, Eyeline Match, Scale Contrast, Motion Vector Match).

5. TYPOGRAPHY & DYNAMIC MOTION (歌词动效排版):
   - "layout_design": Font family, primary color (#RRGGBB), secondary/shadow color (#RRGGBB), and alignment coordinated with the Safe Zone.
   - "reveal_animation_design": Character-by-character reveal style and highlights.
   - "semantic_groups": Synchronized phrase-level groupings with timestamps and kinetic visual effects.

Guidelines:
- Color Design: Colors should reflect the mood. Historical/Traditional themes use jade greens, ink blacks, gold, celadon. Cyber themes use neon, cyan, purple. Romantic themes use warm pastel, soft rose, gold.
- Output Format: You MUST output a JSON array of objects. Do not wrap in markdown except for standard JSON code blocks.

Example Output Format:
[
  {
    "line_index": 0,
    "shot_id": "shot_001",
    "shot_size": "MS",
    "camera_motion": "slow_dolly_in",
    "design_rationale": "【导演构思】选用中景（MS）与柔和侧逆光聚焦于茶盏，天青色釉面映射窗外古镇倒影，慢速推镜头营造专注凝视感，与主歌平缓渐进的情绪深度共振。",
    "transition_rationale": "【镜头衔接】承接上一镜头的雨后古镇全景（WS），采用景别反差（WS -> MS）；与下一镜头通过水波涟漪与拉胚转盘形成同心圆动势匹配（Match Cut）。",
    "composition_safe_zones": {
      "primary_subject_zone": "center_right",
      "protected_regions": ["center_right", "top_right"],
      "preferred_text_regions": ["bottom_left", "vertical_left"]
    },
    "keyframe_prompt": "Cinematic medium shot of an antique Chinese tea room, morning sunlight streaming through wooden lattice windows with delicate Tyndall haze, golden tea surface shimmering inside an azure celadon porcelain cup, 35mm prime lens, f/1.8 shallow depth of field, photorealistic 8k, tactile ceramic texture.",
    "motion_prompt": "Slow continuous forward dolly push, camera glides smoothly towards the tea cup. The porcelain cup remains a solid rigid body with zero warping. Ambient micro-dust motes drift gently across the warm light beam, subtle specular glint shifts.",
    "endframe_prompt": "Close-up of the azure celadon cup rim bathed in warm golden dawn light, glistening tea drop suspended, tactile porcelain crackle texture.",
    "continuity_mode": "cut",
    "video_prompt": "Cinematic medium shot (MS), 35mm anamorphic lens, soft warm side-backlighting. An antique Chinese tea room, morning sunlight streaming through wooden lattice windows with delicate Tyndall haze. Golden tea surface shimmers inside an azure celadon porcelain cup. Slow smooth dolly in, shallow depth of field, photorealistic 8k.",
    "storyboard_design": {
      "composition": "【中景】茶室内，初晴阳光穿透木格子窗，聚焦于天青色茶盏。",
      "motion_effect": "阳光投射在茶水釉面上，水波晃动折射出金线，镜头缓慢向前推入。"
    },
    "layout_design": {
      "primary_colour": "#E6FFFF",
      "secondary_colour": "#4A6E8A",
      "font_name": "Microsoft YaHei",
      "alignment": "Bottom-Left",
      "position_description": "Centred horizontally in the lower-left to avoid obscuring the tea cup on the center-right."
    },
    "reveal_animation_design": {
      "reveal_style": "Fading and subtle expansion character-by-character",
      "description": "Each Chinese character fades in sequentially as sung, creating a fluid porcelain-ink reveal."
    },
    "semantic_groups": [
      {
        "phrase": "浮光",
        "start": 0.500,
        "end": 0.880,
        "visual_effect": "字面泛起如水波粼粼的金光。"
      },
      {
        "phrase": "跃入瓷影",
        "start": 0.880,
        "end": 2.421,
        "visual_effect": "呈现青瓷釉色质感，微光散开。"
      }
    ]
  }
]
"""

SYSTEM_PROMPT_SHOT_DIRECTOR = """You are a professional Music Video Director and Master Cinematographer.
You focus exclusively on the VIDEO TRACK (纯画面分镜与摄影视听语法，两阶段动静解耦体系):
1. Pure Visual Keyframe Prompt ("keyframe_prompt"): High-fidelity cinematic description for FLUX 12B T2I. Highly tactile materials, lighting, lens, depth of field. STRICTLY NO CAMERA MOVEMENT WORDS.
2. Motion & Physics Prompt ("motion_prompt"): Camera trajectory, speed, and subject rigidity for LTX/Wan I2V.
3. Ending Frame ("endframe_prompt", optional): Description of the ending frame for one-take continuous transitions.
4. Continuity Mode ("continuity_mode", optional): "cut", "match_cut", "one_take_continuous".
5. Machine Parameters: shot_size (ECU/CU/MCU/MS/MLS/WS/EWS), camera_motion (static, slow_dolly_in, dolly_out, pan_left, pan_right, tilt_up, tilt_down, tracking, crane_up, handheld).
6. Bilingual Dual-Core Engineering:
   - CHINESE ("design_rationale", "transition_rationale", "storyboard_design"): Poetic mood, emotional subtext, director rationale, and montage transition logic for human review and Chinese-native models (Kling, Jimeng).
   - ENGLISH ("video_prompt", "keyframe_prompt", "motion_prompt"): Strictly concrete, physically renderable optics, tactile materials, lens optics, and zero text/subtitles! Never literally translate poetic metaphors; convert abstract feelings into physical lighting and spatial geometry for Google Veo, Runway, and LTX.
7. Composition Safe Zones: primary_subject_zone, protected_regions, preferred_text_regions.
8. Directorial Review:
   - "design_rationale": Directorial reason for framing, lighting, camera motion, and lyric resonance.
   - "transition_rationale": Montage connective grammar (Match Cut, Eyeline Match, Scale Contrast, Motion Vector Match).

Example Output Format:
[
  {
    "line_index": 0,
    "shot_id": "shot_001",
    "shot_size": "MS",
    "camera_motion": "slow_dolly_in",
    "design_rationale": "【导演构思】选用中景（MS）与柔和侧逆光聚焦于茶盏，天青色釉面映射窗外古镇倒影...",
    "transition_rationale": "【镜头衔接】承接上一镜头雨后古镇全景（WS），采用景别反差（WS -> MS）...",
    "composition_safe_zones": {
      "primary_subject_zone": "center_right",
      "protected_regions": ["center_right"],
      "preferred_text_regions": ["bottom_left"]
    },
    "keyframe_prompt": "Cinematic medium shot of an antique Chinese tea room, morning sunlight streaming through wooden lattice windows with delicate Tyndall haze, 35mm lens, f/1.8 shallow depth of field, photorealistic 8k.",
    "motion_prompt": "Slow continuous forward dolly push, camera glides smoothly towards the tea cup. The cup remains a solid rigid body without warping.",
    "endframe_prompt": "Close-up of the azure celadon cup rim bathed in warm golden dawn light, glistening tea drop.",
    "continuity_mode": "cut",
    "video_prompt": "Cinematic medium shot (MS), 35mm anamorphic lens, soft warm side-backlighting. An antique Chinese tea room...",
    "storyboard_design": {
      "composition": "【中景】茶室内，初晴阳光穿透木格子窗，聚焦于天青色茶盏。",
      "motion_effect": "阳光投射在茶水釉面上，镜头缓慢向前推入。"
    }
  }
]
"""

SYSTEM_PROMPT_TYPOGRAPHY_DIRECTOR = """You are a professional Kinetic Typography Director and Motion Graphic Designer.
You focus exclusively on the TYPOGRAPHY TRACK (歌词动效排版与字级微动效):
1. Color Design: Primary (#RRGGBB) and secondary/shadow (#RRGGBB) palette reflecting emotional mood.
2. Layout & Safe Zone: Aligning text (Bottom-Center, Bottom-Left, Vertical-Left) to avoid obscuring visual subjects.
3. Reveal Animation: Progressive character-by-character reveal synchronized with vocal singing.
4. Semantic Word Groups: Splitting line into phrases with relative timestamps (starting at 0.500s) and kinetic visual effects.

Example Output Format:
[
  {
    "line_index": 0,
    "layout_design": {
      "primary_colour": "#E6FFFF",
      "secondary_colour": "#4A6E8A",
      "font_name": "Microsoft YaHei",
      "alignment": "Bottom-Left",
      "position_description": "Placed in the bottom-left quadrant to avoid obscuring the center-right subject."
    },
    "reveal_animation_design": {
      "reveal_style": "Fading and subtle expansion character-by-character",
      "description": "Each Chinese character fades in sequentially as sung."
    },
    "semantic_groups": [
      {
        "phrase": "浮光",
        "start": 0.500,
        "end": 0.880,
        "visual_effect": "字面泛起如水波粼粼的金光。"
      },
      {
        "phrase": "跃入瓷影",
        "start": 0.880,
        "end": 2.421,
        "visual_effect": "呈现青瓷釉色质感，微光散开。"
      }
    ]
  }
]
"""

# Backward compatibility alias
SYSTEM_PROMPT = SYSTEM_PROMPT_DUAL_TRACK


def generate_llm_prompt(
    alignment_source: Path | AlignmentResult | str,
    output_prompt_path: Path | None = None,
    mode: str = "dual_track",
) -> str:
    """
    读取对齐工程数据并生成包含字级相对时间轴的结构化大模型 Prompt 文本。
    支持返回文本供 Web 端直接复制，也支持写入文件。
    
    参数:
        alignment_source: 对齐工程对象或文件路径
        output_prompt_path: 可选输出提示词文件路径
        mode: 提示词模式 ('dual_track', 'shot_director', 'typography_director')
    """
    if isinstance(alignment_source, AlignmentResult):
        alignment = alignment_source
    else:
        path = Path(alignment_source).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Alignment JSON not found: {path}")
        alignment = AlignmentResult.load_json(path)
        
    prompt_lines = []
    if mode == "shot_director":
        prompt_lines.append(SYSTEM_PROMPT_SHOT_DIRECTOR)
    elif mode == "typography_director":
        prompt_lines.append(SYSTEM_PROMPT_TYPOGRAPHY_DIRECTOR)
    else:
        prompt_lines.append(SYSTEM_PROMPT_DUAL_TRACK)

    prompt_lines.append("\n====================================")
    prompt_lines.append(f"INPUT FOR ANALYSIS (MODE: {mode.upper()}):")
    prompt_lines.append("====================================")

    # 优先使用已存在的分镜镜头列表 (Shot-based)
    if alignment.storyboard and len(alignment.storyboard) > 0:
        prompt_lines.append("EXISTING SHOT LIST & TIMINGS (Offset to start at 0.500s locally for video generation):")
        for i, shot in enumerate(alignment.storyboard):
            dur = max(0.0, shot.end - shot.start)
            seq_info = f" [Sequence: {shot.section_name}]" if shot.section_name else ""
            prompt_lines.append(f"\nShot {shot.shot_id} (ID: {shot.id}){seq_info} [Local: 0.500s - {dur + 0.5:.3f}s] (Duration: {dur:.2f}s, Global: {shot.start:.2f}s - {shot.end:.2f}s):")
            prompt_lines.append(f"  - Initial Scale: {shot.shot_size or shot.scale or 'MS'}")
            prompt_lines.append(f"  - Initial Motion: {shot.camera_motion or shot.camera_movement or 'static'}")
            prompt_lines.append(f"  - Lyric Reference: {shot.lyric_reference or '(Instrumental / Ambient)'}")
            words_found = []
            if shot.line_indices:
                for l_idx in shot.line_indices:
                    if 0 <= l_idx < len(alignment.lines):
                        line = alignment.lines[l_idx]
                        for w in line.words:
                            if w.start >= shot.start - 0.2 and w.end <= shot.end + 0.2:
                                rel_s = max(0.0, w.start - shot.start + 0.5)
                                rel_e = max(rel_s, w.end - shot.start + 0.5)
                                words_found.append(f"\"{w.word}\" [{rel_s:.3f}s - {rel_e:.3f}s]")
            if words_found:
                prompt_lines.append(f"  - Word Timestamps (shifted to local 0.500s): {', '.join(words_found)}")
    else:
        # 降级按歌词行 (Line-based)
        prompt_lines.append("LYRICS INPUT FOR ANALYSIS (TIMINGS SHIFTED TO START AT 0.500s):")
        for i, line in enumerate(alignment.lines):
            if line.text.strip() in ("...", "", "♪"):
                continue
            duration = max(0.0, line.end - line.start)
            prompt_lines.append(f"\nLine {i} [Relative: 0.500s - {duration + 0.5:.3f}s] (Duration: {duration:.2f}s): {line.text}")
            prompt_lines.append("Character Timestamps (shifted to start from 0.500s):")
            for w in line.words:
                rel_start = max(0.0, w.start - line.start + 0.5)
                rel_end = max(rel_start, w.end - line.start + 0.5)
                prompt_lines.append(f"  - \"{w.word}\" [{rel_start:.3f}s - {rel_end:.3f}s]")
        
    prompt_text = "\n".join(prompt_lines)
    
    if output_prompt_path:
        output_path = Path(output_prompt_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(prompt_text, encoding="utf-8")
        log.info("Prompt generated and saved to: %s", output_path)
        print(f"\n[INFO] Prompt file created at: {output_path}")
        print("Please copy the contents of this file and paste it into Gemini / Claude / GPT to get the JSON analysis.")
        
    return prompt_text


# ── JSON Payload Parser ─────────────────────────────────────────────────────

def _parse_json_payload(content: str) -> Any:
    """
    健壮地反序列化大模型返回的 JSON 数据：
    1. 自动剥离 Markdown 代码块标记（```json ... ```）；
    2. 兼容处理模型输出的前后闲聊/解释性文字，自动提取核心 JSON 片段；
    3. 支持 list 与 dict。
    """
    text = content.strip()
    if text.startswith("```json"):
        text = text.split("```json", 1)[1]
    elif text.startswith("```"):
        text = text.split("```", 1)[1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 如果模型文本前后夹杂了解释文字，提取外层 [ ... ] 或 { ... }
        s_arr = text.find("[")
        e_arr = text.rfind("]")
        if s_arr != -1 and e_arr != -1 and e_arr > s_arr:
            try:
                return json.loads(text[s_arr : e_arr + 1])
            except Exception:
                pass

        s_obj = text.find("{")
        e_obj = text.rfind("}")
        if s_obj != -1 and e_obj != -1 and e_obj > s_obj:
            try:
                return json.loads(text[s_obj : e_obj + 1])
            except Exception:
                pass
        raise


# ── Safe Zones and Transition Parsers ───────────────────────────────────────

def _parse_safe_zones(item: dict) -> CompositionSafeZones:
    """解析大模型返回的构图安全区协议 (Layout Contract)"""
    csz_data = item.get("composition_safe_zones") or item.get("layout_contract") or {}
    zone = csz_data.get("primary_subject_zone") or item.get("primary_subject_zone", "center")

    coords = {
        "center": (0.5, 0.5),
        "center_left": (0.35, 0.5),
        "center_right": (0.65, 0.5),
        "top_center": (0.5, 0.3),
        "top_left": (0.35, 0.3),
        "top_right": (0.65, 0.3),
        "bottom_center": (0.5, 0.7),
        "bottom_left": (0.35, 0.7),
        "bottom_right": (0.65, 0.7),
    }
    px, py = coords.get(zone, (0.5, 0.5))
    if "primary_subject_x" in csz_data:
        try:
            px = float(csz_data["primary_subject_x"])
        except (ValueError, TypeError):
            pass
    if "primary_subject_y" in csz_data:
        try:
            py = float(csz_data["primary_subject_y"])
        except (ValueError, TypeError):
            pass

    prot = csz_data.get("protected_regions") or [zone]
    pref = csz_data.get("preferred_text_regions")
    if not pref:
        if "left" in zone:
            pref = ["bottom_right", "bottom_center"]
        elif "right" in zone:
            pref = ["bottom_left", "vertical_left"]
        else:
            pref = ["bottom_center"]

    return CompositionSafeZones(
        primary_subject_x=px,
        primary_subject_y=py,
        protected_regions=prot,
        preferred_text_regions=pref,
    )


def _parse_transition_spec(item: dict, trans_rat: str) -> TransitionSpec:
    """解析大模型返回的蒙太奇转场规格"""
    ttype = item.get("transition_type") or "cut"
    valid_types = [
        "cut", "match_cut", "eyeline_match", "motion_vector_match",
        "scale_contrast", "color_match", "sound_bridge", "dissolve"
    ]
    if ttype not in valid_types:
        lower = trans_rat.lower()
        if "match cut" in lower or "动势匹配" in trans_rat or "形状呼应" in trans_rat:
            ttype = "match_cut"
        elif "eyeline" in lower or "视线" in trans_rat:
            ttype = "eyeline_match"
        elif "scale contrast" in lower or "景别" in trans_rat or "反差" in trans_rat:
            ttype = "scale_contrast"
        elif "motion vector" in lower or "运动矢量" in trans_rat or "平摇" in trans_rat:
            ttype = "motion_vector_match"
        elif "dissolve" in lower or "叠化" in trans_rat:
            ttype = "dissolve"
        else:
            ttype = "cut"
    return TransitionSpec(
        target_shot_id=str(item.get("target_shot_id", "")),
        transition_type=ttype,
        description=trans_rat,
    )


# ── Merge Response ──────────────────────────────────────────────────────────

def detect_payload_track_mode(llm_data: Any) -> str:
    """
    智能分析回填 JSON 载荷包含的轨道信息：
    返回: 'dual_track' | 'shot_only' | 'typography_only' | 'unknown'
    """
    if isinstance(llm_data, dict):
        items = llm_data.get("shots") or llm_data.get("data") or [llm_data]
    elif isinstance(llm_data, list):
        items = llm_data
    elif isinstance(llm_data, (str, Path)):
        try:
            content = llm_data.read_text(encoding="utf-8") if isinstance(llm_data, Path) else str(llm_data)
            parsed = _parse_json_payload(content)
            return detect_payload_track_mode(parsed)
        except Exception:
            return "unknown"
    else:
        return "unknown"

    has_shot = False
    has_typo = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if any(k in item for k in ("video_prompt", "storyboard_design", "shot_size", "scale", "camera_motion", "camera_movement", "action")):
            has_shot = True
        if any(k in item for k in ("layout_design", "reveal_animation_design", "semantic_groups", "primary_colour")):
            has_typo = True

    if has_shot and has_typo:
        return "dual_track"
    elif has_shot and not has_typo:
        return "shot_only"
    elif not has_shot and has_typo:
        return "typography_only"
    return "unknown"


def merge_llm_response(
    alignment_source: Path | AlignmentResult | str,
    response_source: Path | str | list | dict,
    output_path: Path | str | None = None,
    clips_dir: Path | str | None = None,
    render_frames: bool = True,
) -> AlignmentResult:
    """
    读取大模型响应并回填到工程数据中：
    1. 注入 line.style_overrides 与歌词动效轨 (Typography Track)；
    2. 深度充实分镜 ShotPlan (纯画面提示词、构图安全区、影视景别与摄影运镜、转场蒙太奇)；
    3. 写入各个镜头的提示词文本文件 clip_XXX_prompt.txt；
    4. 自动重新渲染 Animatic 静态分镜卡片，供 Web 端实时预览。
    """
    if isinstance(alignment_source, AlignmentResult):
        alignment = alignment_source
    else:
        path = Path(alignment_source).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Alignment JSON not found: {path}")
        alignment = AlignmentResult.load_json(path)
        
    # 解析各种形态的 response_source (安全处理长 JSON 字符串，避免触发 [Errno 63] File name too long)
    if isinstance(response_source, (list, dict)):
        raw_obj = response_source
    elif isinstance(response_source, Path):
        content = response_source.read_text(encoding="utf-8").strip()
        raw_obj = _parse_json_payload(content)
    else:
        text = str(response_source).strip()
        # 仅当字符串长度较短且明显不包含 JSON 开头特征时，才尝试按本地文件路径读取
        if len(text) < 512 and not text.startswith(("[", "{", "```")):
            try:
                p = Path(text)
                if p.is_file():
                    text = p.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        raw_obj = _parse_json_payload(text)
        
    if isinstance(raw_obj, dict):
        llm_data = raw_obj.get("shots") or raw_obj.get("data") or [raw_obj]
    else:
        llm_data = raw_obj
        
    # 建立多维度索引映射 (支持 line_index, shot_id, index)
    llm_map: dict[Any, dict] = {}
    for idx, item in enumerate(llm_data):
        line_idx = item.get("line_index", idx)
        llm_map[line_idx] = item
        if "shot_id" in item:
            sid = item["shot_id"]
            llm_map[sid] = item
            if isinstance(sid, str) and sid.startswith("shot_"):
                try:
                    llm_map[int(sid.replace("shot_", ""))] = item
                except ValueError:
                    pass
            elif isinstance(sid, int):
                llm_map[f"shot_{sid:03d}"] = item
        if idx not in llm_map:
            llm_map[idx] = item
        
    target_clips_dir = Path(clips_dir).resolve() if clips_dir else (
        Path(output_path).resolve().parent / "clips" if output_path else None
    )
    if target_clips_dir:
        target_clips_dir.mkdir(parents=True, exist_ok=True)
        
    log.info("Merging LLM styles and enriching storyboard shots...")
    
    # 1. 回填歌词行样式覆盖 (Typography Track)
    for i, line in enumerate(alignment.lines):
        if line.text.strip() in ("...", "", "♪"):
            continue
            
        item = llm_map.get(i)
        if not item:
            continue
            
        layout = item.get("layout_design", {})
        primary_hex = layout.get("primary_colour") or item.get("primary_colour", "#FFFFFF")
        secondary_hex = layout.get("secondary_colour") or item.get("secondary_colour", "#888888")
        
        primary_ass = hex_to_ass_color(primary_hex, alpha=0)
        secondary_ass = hex_to_ass_color(secondary_hex, alpha=128)
        
        raw_groups = item.get("semantic_groups", [])
        abs_groups = []
        for g in raw_groups:
            r_start = g.get("start", 0.0)
            r_end = g.get("end", 0.0)
            abs_start = max(line.start, r_start - 0.5 + line.start)
            abs_end = min(line.end, r_end - 0.5 + line.start)
            abs_groups.append({
                "phrase": g.get("phrase", ""),
                "start": abs_start,
                "end": abs_end,
                "visual_effect": g.get("visual_effect", "")
            })
            
        des_rat = (item.get("design_rationale") or item.get("director_note") or item.get("storyboard_design", {}).get("design_rationale", "")).strip()
        trans_rat = (item.get("transition_rationale") or item.get("storyboard_design", {}).get("transition_rationale", "")).strip()
        safe_zones = _parse_safe_zones(item)

        # 增量非破坏性合并已有的覆盖数据，支持单轨与双轨智能并存
        merged_overrides = dict(getattr(line, "style_overrides", {}) or {})

        # 1. 歌词动效轨 (Typography Track)
        if "layout_design" in item or "primary_colour" in item:
            merged_overrides["primary_colour"] = primary_ass
            merged_overrides["secondary_colour"] = secondary_ass
            merged_overrides["layout_design"] = layout
        elif "primary_colour" not in merged_overrides:
            merged_overrides["primary_colour"] = primary_ass
            merged_overrides["secondary_colour"] = secondary_ass

        if "semantic_groups" in item and abs_groups:
            merged_overrides["semantic_groups"] = abs_groups
        if "reveal_animation_design" in item:
            merged_overrides["reveal_animation_design"] = item.get("reveal_animation_design", {})

        # 2. 视频画面轨 (Video Track)
        if "video_prompt" in item and item["video_prompt"]:
            merged_overrides["video_prompt"] = item["video_prompt"]
        if "storyboard_design" in item:
            merged_overrides["storyboard_design"] = item["storyboard_design"]
        if des_rat:
            merged_overrides["design_rationale"] = des_rat
        if trans_rat:
            merged_overrides["transition_rationale"] = trans_rat
        if item.get("composition_safe_zones") or item.get("layout_contract"):
            merged_overrides["composition_safe_zones"] = safe_zones.model_dump()

        line.style_overrides = merged_overrides
        
        # 写入每个镜头的提示词文本文件
        if target_clips_dir:
            prompt_txt_path = target_clips_dir / f"clip_{i:03d}_prompt.txt"
            storyboard = item.get("storyboard_design", {})
            shot_size_val = item.get("shot_size") or item.get("scale", "MS")
            motion_val = item.get("camera_motion") or item.get("camera_movement", "static")
            
            storyboard_content = [
                "============================================================",
                f"镜头 {i:02d} | 视频时间：0.500s — {line.end - line.start + 0.5:.3f}s (时长: {line.end - line.start:.3f}s) (原歌词全局时间: {line.start:.3f}s — {line.end:.3f}s)",
                f"歌词内容：“{line.text}”",
                "============================================================",
                "",
                "【🎬 镜头参数与构图安全区 (Cinematography & Safe Zones)】",
                f"- 影视景别: {shot_size_val}",
                f"- 摄影运镜: {motion_val}",
                f"- 主体安全区: {safe_zones.primary_subject_zone} (保护避免遮挡)",
                f"- 建议字幕排版区: {', '.join(safe_zones.preferred_text_regions)}",
                "",
                "【导演设计构思与理念 (Design Rationale)】",
                des_rat or "未指定",
                "",
                "【镜头衔接与转场语言 (Transition / Montage)】",
                trans_rat or "未指定",
                "",
                "【AI 视频生成纯画面提示词 (Pure Visual Prompt - NO Subtitles)】",
                item.get("video_prompt", ""),
                "",
                "【歌词动效轨与排版设计 (Typography Track - Composed in NLE)】",
                f"- 字体: {layout.get('font_name', '默认')} | 主色: {primary_hex}, 辅色: {secondary_hex}",
                f"- 排版锚点: {layout.get('alignment', 'Bottom-Center')}",
                "- 语义词组拆分：" + " -> ".join([f"[{g.get('phrase')}]" for g in raw_groups]),
                "- 动态特效设计 (动画时间戳已对齐本地 0.500s 起始)：",
            ]
            for g in raw_groups:
                r_start = g.get('start', 0.0)
                r_end = g.get('end', 0.0)
                storyboard_content.append(f"  * [{g.get('phrase')}] [{r_start:.3f}s - {r_end:.3f}s]：{g.get('visual_effect', '无')}")
            prompt_txt_path.write_text("\n".join(storyboard_content), encoding="utf-8")
            
    # 2. 映射充实分镜列表 ShotPlan
    if alignment.storyboard and len(alignment.storyboard) > 0:
        # 已有分镜：按 ID、line_indices 或序号寻找匹配并深度更新
        for shot in alignment.storyboard:
            matched_item = None
            if shot.id in llm_map:
                matched_item = llm_map[shot.id]
            elif shot.shot_id in llm_map:
                matched_item = llm_map[shot.shot_id]
            elif shot.line_indices:
                for l_idx in shot.line_indices:
                    if l_idx in llm_map:
                        matched_item = llm_map[l_idx]
                        break
            if not matched_item and (shot.shot_id - 1) in llm_map:
                matched_item = llm_map[shot.shot_id - 1]
                
            if matched_item:
                sb = matched_item.get("storyboard_design", {})
                comp = sb.get("composition", "")
                motion = sb.get("motion_effect", "") or matched_item.get("action", "")
                video_prompt = matched_item.get("video_prompt", "")
                des_rat = (matched_item.get("design_rationale") or matched_item.get("director_note") or sb.get("design_rationale") or "").strip()
                trans_rat = (matched_item.get("transition_rationale") or sb.get("transition_rationale") or "").strip()
                
                # 景别与运镜更新
                shot_size = matched_item.get("shot_size") or matched_item.get("scale")
                if shot_size:
                    shot.shot_size = shot_size
                    shot.scale = shot_size
                camera_motion = matched_item.get("camera_motion") or matched_item.get("camera_movement")
                if camera_motion:
                    shot.camera_motion = camera_motion
                    shot.camera_movement = camera_motion
                    
                # 构图安全区更新
                shot.layout_contract = _parse_safe_zones(matched_item)
                
                # 纯画面视频提示词与动静解耦提示词体系
                keyframe_prompt = matched_item.get("keyframe_prompt", "")
                motion_prompt = matched_item.get("motion_prompt", "")
                endframe_prompt = matched_item.get("endframe_prompt", "")
                continuity_mode = matched_item.get("continuity_mode", "")

                if video_prompt:
                    shot.prompt_en = video_prompt
                if keyframe_prompt:
                    shot.keyframe_prompt = keyframe_prompt
                elif video_prompt and not shot.keyframe_prompt:
                    from src.compilers.flux_compiler import FluxPromptCompiler
                    shot.keyframe_prompt = FluxPromptCompiler()._clean_static_prompt(video_prompt)

                if motion_prompt:
                    shot.motion_prompt = motion_prompt
                elif not shot.motion_prompt:
                    shot.motion_prompt = f"{shot.camera_motion} camera movement, primary subject remains a solid rigid structure without warping, subtle ambient lighting shifts, steady continuous motion"

                if endframe_prompt:
                    shot.endframe_prompt = endframe_prompt
                if continuity_mode in ("cut", "match_cut", "one_take_continuous"):
                    shot.continuity_mode = continuity_mode

                if comp or motion:
                    shot.prompt_zh = f"【构图】{comp} 【动效】{motion}"
                    shot.action = motion or comp
                if des_rat:
                    shot.director_note = des_rat
                    shot.design_rationale = des_rat
                if trans_rat:
                    shot.transition_rationale = trans_rat
                    shot.incoming_transition = _parse_transition_spec(matched_item, trans_rat)
                    
                if not shot.takes:
                    take = Take(
                        id=f"take_{shot.shot_id:03d}_llm",
                        shot_id=shot.id,
                        provider="llm_director",
                        prompt=shot.prompt_en,
                        selected=True,
                    )
                    shot.takes.append(take)
                    shot.selected_take_id = take.id
                else:
                    for t in shot.takes:
                        if t.selected or not shot.selected_take_id:
                            t.prompt = shot.prompt_en
    else:
        # 原工程无分镜：为每一项大模型返回构建全新 ShotPlan
        new_shots: list[ShotPlan] = []
        shot_num = 1
        for i, line in enumerate(alignment.lines):
            if line.text.strip() in ("...", "", "♪"):
                continue
            item = llm_map.get(i)
            sb = item.get("storyboard_design", {}) if item else {}
            comp = sb.get("composition", "")
            motion = sb.get("motion_effect", "") or (item.get("action", "") if item else "")
            video_prompt = item.get("video_prompt", "") if item else ""
            keyframe_prompt = item.get("keyframe_prompt", "") if item else ""
            motion_prompt = item.get("motion_prompt", "") if item else ""
            endframe_prompt = item.get("endframe_prompt", "") if item else ""
            continuity_mode = item.get("continuity_mode", "cut") if item else "cut"
            if not keyframe_prompt and video_prompt:
                from src.compilers.flux_compiler import FluxPromptCompiler
                keyframe_prompt = FluxPromptCompiler()._clean_static_prompt(video_prompt)
            if not motion_prompt:
                cam = item.get("camera_motion") or item.get("camera_movement", "static") if item else "static"
                motion_prompt = f"{cam} camera movement, primary subject remains a solid rigid structure without warping, steady continuous motion"

            des_rat = (item.get("design_rationale") or item.get("director_note") or sb.get("design_rationale") or "").strip() if item else ""
            trans_rat = (item.get("transition_rationale") or sb.get("transition_rationale") or "").strip() if item else ""
            safe_zones = _parse_safe_zones(item) if item else CompositionSafeZones()
            
            shot_id_str = f"shot_{shot_num:03d}"
            take = Take(
                id=f"take_{shot_num:03d}_1",
                shot_id=shot_id_str,
                provider="llm_director",
                prompt=video_prompt,
                selected=True,
            )
            shot = ShotPlan(
                shot_id=shot_num,
                id=shot_id_str,
                start=line.start,
                end=line.end,
                line_indices=[i],
                lyric_reference=line.text,
                shot_size=item.get("shot_size") or item.get("scale", "MS") if item else "MS",
                camera_motion=item.get("camera_motion") or item.get("camera_movement", "static") if item else "static",
                layout_contract=safe_zones,
                prompt_zh=f"【构图】{comp} 【动效】{motion}" if (comp or motion) else "",
                prompt_en=video_prompt,
                keyframe_prompt=keyframe_prompt,
                motion_prompt=motion_prompt,
                endframe_prompt=endframe_prompt,
                continuity_mode=continuity_mode if continuity_mode in ("cut", "match_cut", "one_take_continuous") else "cut",
                action=motion or comp,
                director_note=des_rat,
                design_rationale=des_rat,
                transition_rationale=trans_rat,
                incoming_transition=_parse_transition_spec(item, trans_rat) if item else TransitionSpec(),
                preview_image=f"storyboard/{shot_id_str}.png",
                path=f"storyboard/{shot_id_str}.png",
                takes=[take],
                selected_take_id=take.id,
            )
            new_shots.append(shot)
            shot_num += 1
        alignment.storyboard = new_shots
        
    # 3. 自动重新渲染动态卡片
    if render_frames:
        try:
            from src.storyboard_renderer import render_all_storyboard_frames
            sb_dir = (Path(output_path).resolve().parent if output_path else target_clips_dir.parent) / "storyboard"
            render_all_storyboard_frames(alignment, output_dir=sb_dir)
            log.info("Animatic 分镜卡片已根据大模型剧作重新渲染: %s", sb_dir)
        except Exception as e:
            log.warning("重新渲染分镜卡片跳过: %s", e)
            
    # 4. 保存工程
    if output_path:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        alignment.save_json(out_p)
        log.info("Successfully merged LLM metadata and saved to: %s", out_p)
        print(f"\n[OK] Merged alignment JSON saved to: {out_p}")
        
    return alignment

# ── Dynamic ASS Generator Override ──────────────────────────────────────────

def generate_llm_ass(alignment_path: Path, output_ass_path: Path, config_path: Path = None):
    """
    Custom ASS generator that reads line-specific style_overrides and generates
    ASS events with dynamic color shifting.
    """
    from src.config import SubtitleConfig
    from src.subtitle import _load_template_header, _wrap_lines, seconds_to_ass_time
    
    config = SubtitleConfig()
    alignment = AlignmentResult.load_json(alignment_path)
    
    header = _load_template_header(config)
    max_width = 1920 - 200
    alignment = _wrap_lines(alignment, max_width, config.font_size, config.font_name)
    
    lines = alignment.lines
    N = len(lines)
    if N == 0:
        return
        
    slots = []
    for i in range(N):
        start_t = lines[i].start
        end_t = lines[i+1].start if i < N - 1 else lines[i].end + 3.0
        slots.append((start_t, end_t))
        
    local_y = [0.0] * N
    for i in range(1, N):
        prev_lines = lines[i-1].text.count("\\N") + 1
        curr_lines = lines[i].text.count("\\N") + 1
        dist = (prev_lines + curr_lines) * 0.6 * config.font_size + 0.6 * config.font_size
        local_y[i] = local_y[i-1] + dist
        
    center_y = config.font_size * 4.5
    
    # Helper to split ASS color
    def parse_color(ass_color: str) -> tuple[str, str]:
        if ass_color.startswith("&H") and len(ass_color) >= 10:
            return "&H" + ass_color[2:4] + "&", "&H" + ass_color[4:10] + "&"
        return "&H00&", ass_color

    def get_alpha(d: int, base_a: str) -> str:
        try:
            base_val = int(base_a[2:4], 16)
        except:
            base_val = 128
        if d == 0:
            return base_a
        target = 255
        val = base_val + (target - base_val) * (d / 4.0)
        val = min(255, max(0, val))
        return f"&H{val:02X}&"

    events = []
    for j in range(N):
        k_min = max(0, j-4)
        k_max = min(N-1, j+4)
        
        # Load custom styles for line j
        overrides = getattr(lines[j], 'style_overrides', {}) if hasattr(lines[j], 'style_overrides') else {}
        line_pri_color = overrides.get("primary_colour", config.primary_colour)
        line_sec_color = overrides.get("secondary_colour", config.secondary_colour)
        
        a_pri, c_pri = parse_color(line_pri_color)
        a_sec, c_sec = parse_color(line_sec_color)
        
        def get_tags(d: int, is_active: bool, is_before: bool, for_anim_end: bool = False) -> str:
            scale = max(100 - d * 5, 70) if d > 0 else 100
            blur = d * 2.5
            alpha = get_alpha(d, a_sec)
            c = c_sec if is_before else c_pri
            
            if is_active:
                if for_anim_end:
                    return f"\\1c{c_sec}\\1a{a_sec}\\fscx100\\fscy100\\blur0"
                else:
                    return f"\\1c{c_pri}\\1a{a_pri}\\2c{c_sec}\\2a{a_sec}\\fscx100\\fscy100\\blur0"
            else:
                return f"\\1c{c}\\1a{alpha}\\fscx{scale}\\fscy{scale}\\blur{blur:.1f}"
                
        for k in range(k_min, k_max + 1):
            slot_start, slot_end = slots[k]
            if slot_end <= slot_start:
                continue
                
            trans_duration = min(0.6, slot_end - slot_start)
            t_base_start = slot_end - trans_duration
            
            d_new = abs(j - (k + 1))
            delay_step = trans_duration * 0.15 
            move_dur = trans_duration * 0.5    
            
            t1_offset = d_new * delay_step
            if t1_offset + move_dur > trans_duration:
                t1_offset = trans_duration - move_dur
                
            trans_start_t = t_base_start + t1_offset
            trans_end_t = trans_start_t + move_dur
            
            t1 = int((trans_start_t - slot_start) * 1000)
            t2 = int((trans_end_t - slot_start) * 1000)
            
            y_start = center_y + local_y[j] - local_y[k]
            y_end = center_y + local_y[j] - local_y[k+1] if k < N - 1 else center_y + local_y[j] - local_y[k]
            
            d_start = abs(j - k)
            is_active_start = (k == j)
            is_before_start = (k < j)
            tag_start = get_tags(d_start, is_active_start, is_before_start, False)
            
            d_end = abs(j - (k + 1))
            is_active_end = (k + 1 == j)
            is_before_end = (k + 1 < j)
            tag_end = get_tags(d_end, is_active_end, is_before_end, True)
            
            ass_t_start = seconds_to_ass_time(slot_start)
            ass_t_end = seconds_to_ass_time(slot_end)
            
            if y_start == y_end:
                pos_tag = f"\\pos(100,{y_start:.1f})"
            else:
                pos_tag = f"\\move(100,{y_start:.1f},100,{y_end:.1f},{t1},{t2})"
                
            anim_tag = f"\\t({t1},{t2},{tag_end})" if tag_start != tag_end else ""
            tags = f"\\an4{pos_tag}{tag_start}{anim_tag}"
            
            if k == j:
                tag_steady = get_tags(0, True, False, False)
                karaoke_text = ""
                current_t = lines[j].start
                
                for word in lines[j].words:
                    gap_cs = int((word.start - current_t) * 100)
                    if gap_cs > 0:
                        karaoke_text += f"{{\\k{gap_cs}}}"
                    
                    dur_cs = int((word.end - max(word.start, current_t)) * 100)
                    if dur_cs < 0: 
                        dur_cs = 0
                        
                    k_tag = "kf" if config.use_karaoke_gradient else "k"
                    karaoke_text += f"{{\\{k_tag}{dur_cs}}}{word.word}"
                    current_t = max(word.end, current_t)
                
                tags_active = f"\\an4{pos_tag}{tag_steady}{anim_tag}"
                events.append(f"Dialogue: 0,{ass_t_start},{ass_t_end},{config.style_name},,0,0,0,,{{{tags_active}}}{karaoke_text}")
            else:
                events.append(f"Dialogue: 0,{ass_t_start},{ass_t_end},{config.style_name},,0,0,0,,{{{tags}}}{lines[j].text}")

    events.sort(key=lambda x: x.split(",")[1])
    ass_content = header + "\n".join(events) + "\n"
    output_ass_path.write_text(ass_content, encoding="utf-8-sig")
    log.info("ASS Subtitles generated with semantic styling overrides at: %s", output_ass_path)


# ── CLI & Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LLM Director CLI for Music-to-Video Workflow")
    parser.add_argument("--input-json", "-i", required=True, help="Input alignment JSON path (e.g. output/{song_name}/{song_name}_alignment.json)")
    parser.add_argument("--action", "-a", choices=["prompt", "merge", "generate-ass"], required=True, 
                        help="Action to perform: 'prompt' to generate LLM prompt, 'merge' to merge LLM response, 'generate-ass' to create ASS subtitles")
    parser.add_argument("--response-json", "-r", default=None, help="Path to LLM JSON response file (default: {song_dir}/llm_response.json)")
    parser.add_argument("--output-json", "-o", default=None, help="Output alignment JSON path (default: {song_dir}/{stem}_alignment_llm.json)")
    parser.add_argument("--clips-dir", "-c", default=None, help="Directory where generated video clips are stored (default: {song_dir}/clips)")
    parser.add_argument("--output-ass", default=None, help="Output ASS subtitle path (default: {song_dir}/{stem}_llm.ass)")
    
    args = parser.parse_args()
    
    input_path = Path(args.input_json).resolve()
    song_dir = input_path.parent
    stem = input_path.stem.replace("_alignment", "")
    
    if args.action == "prompt":
        output_prompt = song_dir / f"{stem}_llm_prompt.txt"
        generate_llm_prompt(input_path, output_prompt)
        
    elif args.action == "merge":
        resp_path = Path(args.response_json).resolve() if args.response_json else song_dir / "llm_response.json"
        out_json = Path(args.output_json).resolve() if args.output_json else song_dir / f"{stem}_alignment_llm.json"
        clips_dir = Path(args.clips_dir).resolve() if args.clips_dir else song_dir / "clips"
        merge_llm_response(input_path, resp_path, out_json, clips_dir)
        
    elif args.action == "generate-ass":
        out_ass = Path(args.output_ass).resolve() if args.output_ass else song_dir / f"{stem}_llm.ass"
        generate_llm_ass(input_path, out_ass)

if __name__ == "__main__":
    main()
