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
import argparse
import subprocess
from pathlib import Path
from dataclasses import asdict

# Ensure we can load src modules
import sys
sys.path.append(str(Path(__file__).parent.parent))
from src.aligner import AlignmentResult, StoryboardEvent, AlignedLine, WordTimestamp
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

SYSTEM_PROMPT = """You are a professional Music Video Director and Visual Designer.
You will analyze the lyrics of a song, parse their semantic meaning/mood, and for EACH lyric line, complete the design in two sequential phases:

PHASE 1: LAYOUT & TYPESETTING DESIGN (排版设计)
- Design the font selection, sizing, and colors (primary and secondary/outline in standard #RRGGBB format).
- Design the screen layout: positioning (e.g. center, lower third, vertical alignment), line wrap structure, margins, and letter spacing. Explain the visual rationale for the layout in relation to the lyric's meaning.

PHASE 2: GRADUAL REVEAL & DYNAMIC ANIMATION DESIGN (动画设计)
- Design how the text appears GRADUALLY character-by-character or word-by-word as it is sung (每一句期间字是逐渐出现的). Specify the entry style (e.g., progressive fade-in, rising up from bottom, ink stroke growth, or gentle expansion).
- Design how the highlight effect sweeps across the text synchronized with the vocal.
- Split the line into semantic word groups (phrases), look up their exact start and end times from the provided relative character timestamps (which are already shifted to start from 0.500s of the clip timeline), and design specialized dynamic/transition effects for each phrase.
- Write a detailed storyboard design in Chinese containing "composition" (构图) and "motion_effect" (画面动效).

Guidelines:
- Color Design: Colors should reflect the mood. Historical/Traditional themes should use jade greens, ink blacks, gold, stone grays. Cyber/electronic themes should use neon, cyan, purple. Romantic themes should use warm pastel, soft rose, gold.
- Subtitle Integration in Video Prompts (字幕融入视频生成):
  * Since subtitles must be generated directly inside the video clips (字幕也需要和视频一起生成), the English "video_prompt" MUST explicitly include instructions for rendering the Chinese text as part of the video scene!
  * You MUST describe:
    1. The visual background scene (environment, lighting, composition, camera movement).
    2. The Chinese subtitle text itself: E.g., "The Chinese text '浮光 跃入瓷影 像时空 悄然重组' is displayed at the bottom-center of the screen..."
    3. The typesetting & animation of the subtitles: E.g., font style, colors, gradual appearance (starting at 0.5s character-by-character), and dynamic transitions/highlights matching the timestamps.
- Timings relative to Clip Start:
  * Since each video clip is generated sentence-by-sentence starting at local time 0.0s, the provided character timestamps for each line are already offset so that the first character starts exactly at 0.500s.
  * You MUST use these relative timestamps directly for your semantic groups starts/ends and in your video_prompt animation timelines.
- Storyboard Design (Chinese):
  * "composition": E.g., "【中景】。茶室内，雨后初晴的一束柔和阳光（Tyndall effect）穿透古旧的木格子窗。"
  * "motion_effect": E.g., "阳光精准地投射在桌上一盏盛满茶水的天青色瓷盏内。釉面反射出的窗外古镇倒影在晃动的水波中扭曲、重组，水面折射出炫目的金线。"
- Semantic Grouping & Timing:
  * Divide the lyric line into coherent semantic groups (e.g. "浮光 跃入瓷影 像时空 悄然重组" -> ["浮光", "跃入瓷影", "像时空 悄然重组"]).
  * For each group, determine its "start" and "end" timestamps directly from the provided character timestamps list.
  * Write a detailed "visual_effect" describing how the characters reveal themselves gradually and any special highlighting or transition effects (e.g. "字体表面闪烁着如水面反光般粼粼的金色高光。" or "在 4.362s 至 5.189s 的旋律重拍中，所有汉字的笔画碎裂成数个三维瓷片颗粒，在空中快速旋转移位，重新拼接并定格成整齐的汉字，随后消散。").
- Output Format: You MUST output a JSON array of objects. Do not wrap in markdown except for standard JSON code blocks.

Example Output Format:
[
  {
    "line_index": 3,
    "text": "浮光 跃入瓷影 像时空 悄然重组",
    "layout_design": {
      "primary_colour": "#E6FFFF",
      "secondary_colour": "#4A6E8A",
      "font_name": "Microsoft YaHei",
      "font_size": 48,
      "alignment": "Bottom-Center",
      "position_description": "Centred horizontally in the lower third to keep the tea cup background fully visible.",
      "layout_rationale": "Uses a elegant porcelain-white color with an slate-blue shadow to mimic tea cup glaze colors."
    },
    "reveal_animation_design": {
      "reveal_style": "Fading and slight scaling character-by-character",
      "description": "Each Chinese character fades in sequentially from left to right as the voice sings it, creating a gradual appearance of the sentence."
    },
    "video_prompt": "A middle shot in a traditional Chinese tea room. Soft light shines through an old wooden lattice window onto an azure glazed porcelain cup. Golden ripples shimmer on the water surface. The Chinese text '浮光 跃入瓷影 像时空 悄然重组' is rendered in elegant porcelain-white calligraphy with an slate-blue shadow at the bottom-center of the screen. Starting at 0.5s, the characters fade in gradually from left to right. From 4.362s to 5.189s, the strokes of '重组' shatter into 3D porcelain fragments, rotate, and snap back to form the characters, then dissolve.",
    "storyboard_design": {
      "composition": "【中景】。茶室内，雨后初晴的一束柔和阳光（Tyndall effect）穿透古旧 of 木格子窗。",
      "motion_effect": "阳光精准地投射在桌上一盏盛满茶水的天青色瓷盏内。釉面反射出的窗外古镇倒影在晃动的水波中扭曲、重组，水面折射出炫目的金线。"
    },
    "semantic_groups": [
      {
        "phrase": "浮光",
        "start": 0.500,
        "end": 0.880,
        "visual_effect": "字体表面闪烁着如水面反光般粼粼的金色高光。"
      },
      {
        "phrase": "跃入瓷影",
        "start": 0.880,
        "end": 2.421,
        "visual_effect": "字体呈现淡蓝色青瓷质感，并在亮起的瞬间产生微微的重影。"
      },
      {
        "phrase": "像时空 悄然重组",
        "start": 2.421,
        "end": 5.189,
        "visual_effect": "在 4.362s (重) 至 5.189s (组) 的旋律重拍中，所有汉字的笔画碎裂成数个三维瓷片颗粒，在空中快速旋转移位，重新拼接并定格成整齐的汉字，随后消散。"
      }
    ]
  }
]
"""

def generate_llm_prompt(alignment_path: Path, output_prompt_path: Path):
    """Reads alignment JSON and outputs a text prompt with relative word timestamps for copy-pasting to an LLM."""
    if not alignment_path.exists():
        raise FileNotFoundError(f"Alignment JSON not found: {alignment_path}")
        
    alignment = AlignmentResult.load_json(alignment_path)
    
    prompt_lines = []
    prompt_lines.append(SYSTEM_PROMPT)
    prompt_lines.append("\n====================================")
    prompt_lines.append("LYRICS INPUT FOR ANALYSIS (TIMINGS SHIFTED TO START AT 0.500s):")
    prompt_lines.append("====================================")
    
    for i, line in enumerate(alignment.lines):
        if line.text.strip() == "...":
            continue
        duration = line.end - line.start
        prompt_lines.append(f"\nLine {i} [Relative: 0.500s - {duration + 0.5:.3f}s] (Duration: {duration:.2f}s): {line.text}")
        prompt_lines.append("Character Timestamps (shifted to start from 0.500s):")
        for w in line.words:
            rel_start = w.start - line.start + 0.5
            rel_end = w.end - line.start + 0.5
            prompt_lines.append(f"  - \"{w.word}\" [{rel_start:.3f}s - {rel_end:.3f}s]")
        
    output_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    output_prompt_path.write_text("\n".join(prompt_lines), encoding="utf-8")
    log.info("Prompt generated and saved to: %s", output_prompt_path)
    print(f"\n[INFO] Prompt file created at: {output_prompt_path}")
    print("Please copy the contents of this file and paste it into Gemini / Claude / GPT to get the JSON analysis.")

# ── Merge Response ──────────────────────────────────────────────────────────

def merge_llm_response(alignment_path: Path, response_path: Path, output_path: Path, clips_dir: Path):
    """
    Reads the LLM response JSON and merges it into the original alignment JSON.
    Generates ASS overrides and storyboard events pointing to clip_001.mp4, clip_002.mp4, etc.
    """
    if not alignment_path.exists():
        raise FileNotFoundError(f"Alignment JSON not found: {alignment_path}")
    if not response_path.exists():
        raise FileNotFoundError(f"LLM Response JSON not found: {response_path}")
        
    alignment = AlignmentResult.load_json(alignment_path)
    
    with open(response_path, "r", encoding="utf-8") as f:
        # Clean potential markdown wrapping
        content = f.read().strip()
        if content.startswith("```json"):
            content = content.split("```json", 1)[1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        llm_data = json.loads(content.strip())
        
    # Map index to response object
    llm_map = {item["line_index"]: item for item in llm_data}
    
    storyboard_events = []
    
    log.info("Merging LLM styles and creating storyboard events...")
    clips_dir.mkdir(parents=True, exist_ok=True)
    
    for i, line in enumerate(alignment.lines):
        if line.text.strip() == "...":
            continue
            
        # Get LLM suggestions
        item = llm_map.get(i)
        if not item:
            log.warning("No LLM metadata for line %d: %s", i, line.text)
            continue
            
        # Convert Hex colors to ASS BGR format
        layout = item.get("layout_design", {})
        primary_hex = layout.get("primary_colour") or item.get("primary_colour", "#FFFFFF")
        secondary_hex = layout.get("secondary_colour") or item.get("secondary_colour", "#888888")
        
        primary_ass = hex_to_ass_color(primary_hex, alpha=0)
        secondary_ass = hex_to_ass_color(secondary_hex, alpha=128)
        
        # Convert relative times back to absolute times for global alignment JSON
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
            
        # Override the style in line.words metadata
        line.style_overrides = {
            "primary_colour": primary_ass,
            "secondary_colour": secondary_ass,
            "video_prompt": item.get("video_prompt", ""),
            "semantic_groups": abs_groups,
            "layout_design": layout,
            "reveal_animation_design": item.get("reveal_animation_design", {}),
            "storyboard_design": item.get("storyboard_design", {})
        }
        
        # Setup storyboard event for this line's video clip
        clip_name = f"clip_{i:03d}.mp4"
        clip_path = clips_dir / clip_name
        
        # Build a detailed, readable storyboard description file for the clip
        prompt_txt_path = clips_dir / f"clip_{i:03d}_prompt.txt"
        
        storyboard = item.get("storyboard_design", {})
        
        storyboard_content = []
        storyboard_content.append(f"============================================================")
        storyboard_content.append(f"镜头 {i:02d} | 视频时间：0.500s — {line.end - line.start + 0.5:.3f}s (时长: {line.end - line.start:.3f}s) (原歌词全局时间: {line.start:.3f}s — {line.end:.3f}s)")
        storyboard_content.append(f"歌词内容：“{line.text}”")
        storyboard_content.append(f"============================================================")
        storyboard_content.append("")
        storyboard_content.append("【分镜画面设计】")
        storyboard_content.append(f"- 构图：{storyboard.get('composition', '未指定')}")
        storyboard_content.append(f"- 动效：{storyboard.get('motion_effect', '未指定')}")
        storyboard_content.append("")
        storyboard_content.append("【AI 视频生成提示词 (Prompt)】")
        storyboard_content.append(item.get("video_prompt", ""))
        storyboard_content.append("")
        storyboard_content.append("【词组字幕动画及精确时间轴】")
        storyboard_content.append(f"- 语义词组拆分：" + " -> ".join([f"[{g.get('phrase')}]" for g in raw_groups]))
        storyboard_content.append("- 动态特效设计 (已全部偏移动画起始为 0.500s)：")
        for g in raw_groups:
            r_start = g.get('start', 0.0)
            r_end = g.get('end', 0.0)
            storyboard_content.append(f"  * [{g.get('phrase')}] [{r_start:.3f}s - {r_end:.3f}s]：{g.get('visual_effect', '无')}")
            
        prompt_txt_path.write_text("\n".join(storyboard_content), encoding="utf-8")
        
        # We add storyboard event for this video clip
        storyboard_events.append(StoryboardEvent(
            type="video",
            path=str(clip_path.resolve()),
            start=line.start,
            end=line.end,
            speed_align=True  # Auto speed stretch!
        ))
        
    alignment.storyboard = storyboard_events
    alignment.save_json(output_path)
    log.info("Successfully merged LLM metadata and saved to: %s", output_path)
    print(f"\n[OK] Merged alignment JSON saved to: {output_path}")
    print(f"[INFO] Clip video placeholders and prompts generated in: {clips_dir}")
    print("Please generate the video clips using the prompt files (*_prompt.txt) and place them in that folder.")

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
    parser.add_argument("--input-json", "-i", default="./output/匠心入梦01_alignment.json", help="Input alignment JSON path")
    parser.add_argument("--action", "-a", choices=["prompt", "merge", "generate-ass"], required=True, 
                        help="Action to perform: 'prompt' to generate LLM prompt, 'merge' to merge LLM response, 'generate-ass' to create ASS subtitles")
    parser.add_argument("--response-json", "-r", default="./output/llm_response.json", help="Path to LLM JSON response file")
    parser.add_argument("--output-json", "-o", default="./output/匠心入梦01_alignment_llm.json", help="Output alignment JSON path")
    parser.add_argument("--clips-dir", "-c", default="./output/clips", help="Directory where generated video clips are/will be stored")
    parser.add_argument("--output-ass", default="./output/匠心入梦01_llm.ass", help="Output ASS subtitle path")
    
    args = parser.parse_args()
    
    input_path = Path(args.input_json)
    
    if args.action == "prompt":
        output_prompt = input_path.parent / "llm_prompt.txt"
        generate_llm_prompt(input_path, output_prompt)
        
    elif args.action == "merge":
        resp_path = Path(args.response_json)
        out_json = Path(args.output_json)
        clips_dir = Path(args.clips_dir)
        merge_llm_response(input_path, resp_path, out_json, clips_dir)
        
    elif args.action == "generate-ass":
        out_ass = Path(args.output_ass)
        generate_llm_ass(input_path, out_ass)

if __name__ == "__main__":
    main()
