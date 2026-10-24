"""
Cast Studio Prompt Engine & Protocol Builder
--------------------------------------------
Constructs structured LLM prompts that guide AI models to architect complete,
consistent character profiles adhering to the CharacterProfile schema.
"""
from __future__ import annotations

import json
import re
from typing import Any
from src.cast_schema import CharacterProfile


CAST_SYSTEM_PROMPT = """你是一位享誉全球的虚拟艺人（Virtual Artist / VTuber）与动漫影视概念总监。
你的任务是将用户的灵感短语或粗略构想，推演并设计为一个具有深刻戏剧张力、高辨识度视觉基因、且能稳定进行 AI 生图与视频生成的【生产级虚拟角色设定】。

### 角色设计的七大黄金法则：
1. **反差塑造灵魂 (Contradiction)**：
   不要设计扁平的角色。挖掘角色“外在展现”与“内心渴望/恐惧”的深刻矛盾（例如：表面傲慢追求绝对理性，内心却极度渴望失控的真情；表面毒舌搞笑，唱起歌来却孤注一掷）。
2. **视觉极度具体，杜绝模糊形容词 (Concrete Visual DNA)**：
   严禁使用“帅气”、“好看”、“精致”等无效词。必须精确到：
   - 发色色系与色阶（如：#E6E8EA 浅银白配合冷灰发根阴影）
   - 瞳孔细节与眼型（如：琥珀金色细长眼、瞳孔中央带有类似时钟或几何刻度的微光）
   - 面部微小辨识锚点（如：右眼睑下方的单点泪痣、不对称银质长耳坠）
   - 服饰剪裁与材质（如：不对称高领战术夹克结合反光丝绸内衬）
3. **色彩基因三段式 (Color DNA)**：
   主色（60%）、辅色（30%）、高饱和点睛色（10%，如荧光橙、青金石蓝、激光紫）。
4. **声音与演唱性格 (Vocal Identity)**：
   具体描述音色（如清亮中音、微带颗粒感沙哑、薄声假音）及咬字特征（如极速念唱、尾音微微上扬）。
5. **生图提示词引擎 (Prompt Engine)**：
   必须在 `prompt_engine.positive_character_anchor` 中输出一组高权重的英文关键词，作为后续 Midjourney/Flux/ComfyUI 的必带词头（如 "masterpiece, 1boy, silver layered messy hair, glowing amber eyes, mole under right eye, asymmetrical techwear jacket..."）。

### 输出协议要求：
你必须【严格仅输出一个符合规范的 JSON 代码块】，不要在前后附带任何闲聊或引言。输出需严格匹配目标 JSON Schema。
"""


def build_character_design_prompt(user_idea: str, style_preference: str = "Anime / Techwear Cinematic") -> list[dict[str, str]]:
    """
    Constructs multi-turn prompt messages for an LLM (Gemini, Claude, GPT)
    to design a comprehensive character profile.
    """
    user_content = f"""请根据以下灵感构想，为我们设计一个完整的虚拟艺人/角色档案：

【用户灵感/要求】：
{user_idea.strip()}

【整体美学风格偏好】：
{style_preference.strip()}

请遵循 Cast Studio 规范，设计该角色的 identity、visual_dna、expression_sheet、vocal_profile、stage_aesthetic 和 prompt_engine，并以单个 JSON 格式输出。"""

    return [
        {"role": "system", "content": CAST_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_character_profile_json(llm_output: str) -> CharacterProfile:
    """
    Safely extracts and validates a CharacterProfile from raw LLM output,
    handling markdown code blocks and whitespace.
    """
    clean_text = llm_output.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
    if match:
        clean_text = match.group(1).strip()

    data = json.loads(clean_text)
    return CharacterProfile.model_validate(data)


def get_reference_golden_ratio_character() -> CharacterProfile:
    """
    Returns a built-in benchmark CharacterProfile ('0.618 / 零点六一八')
    serving as a canonical design example.
    """
    raw_data: dict[str, Any] = {
        "id": "char_golden_0618",
        "created_at": "2026-10-25T02:00:00Z",
        "identity": {
            "name": "零点六一八",
            "alias": "0.618 / Golden Ratio Boy",
            "tagline": "一个痴迷完美比例，却唱着不完美人生的毒舌少年音乐人",
            "archetype": "Perfectionist Rebel & Satirical Prodigy",
            "core_contradiction": "表面极度自恋且执着用数学丈量万物，其实内心深处最渴望体会无法被公式计算的真情",
            "personality_traits": ["高智商自恋", "毒舌幽默", "狂放少年感", "微小脆弱", "强秩序感"]
        },
        "visual_dna": {
            "gender": "male",
            "age_appearance": "17-18 years old",
            "silhouette": "slender athletic youth with sharp asymmetrical outer lines",
            "hair": {
                "style": "layered messy medium crop with sharp forward fringe",
                "color": "#E6EAEF metallic silver-white",
                "highlights": "pale champagne gold tips on the inner bangs",
                "texture": "silky with defined dynamic strands"
            },
            "eyes": {
                "shape": "sharp elongated almond eyes with confident narrow gaze",
                "iris_color": "#E5A93B glowing amber gold",
                "pupil_feature": "subtle faint geometric ring pattern in the pupil",
                "gaze_expression": "piercing, slightly mockingly tilted upward"
            },
            "facial_marks": ["single dark beauty mark beneath right outer eye corner", "thin silver geometric ear stud on left ear"],
            "wardrobe": {
                "genre_style": "Avant-garde streetwear meets bespoke tailoring",
                "signature_outerwear": "Asymmetrical matte black cropped tactical blazer with gold lining",
                "innerwear": "High-collar crisp white sleeveless mock-neck with thin gold ratio lines",
                "accessories": ["Single black leather fingerless glove on right hand", "Slender silver measuring chain necklace"],
                "materials": ["Matte techwear nylon", "Heavy structured wool", "Reflective gold piping"]
            },
            "color_palette": {
                "dominant_hex": "#0D0F12",
                "dominant_name": "Obsidian Void Black",
                "secondary_hex": "#E6EAEF",
                "secondary_name": "Platinum Silver",
                "accent_hex": "#E5A93B",
                "accent_name": "Golden Ratio Ochre",
                "glow_accent": "#F5C869 warm gold pulse"
            },
            "signature_prop": "An intricate collapsible brass-and-acrylic golden ratio caliper"
        },
        "expression_sheet": {
            "neutral": "Half-lidded detached calm with lips pressed into a faint calculating line",
            "performance_focus": "Head thrown back, wild bright eyes dilated, intense electric energy",
            "vulnerable_climax": "Swept hair over furrowed brow, mouth slightly parted, gaze trembling",
            "smug_ironic": "One eyebrow raised high, crooked smirk exposing canine tooth, tilted chin"
        },
        "vocal_profile": {
            "timbre_description": "Bright youthful tenor with crisp airy friction and subtle nasal resonance",
            "pitch_range": "High Tenor (C3 to D5, extending into effortless falsetto)",
            "delivery_style": "Rapid rhythmic speech-singing alternating into soaring melodic hooks",
            "signature_audio_tag": "A dry whisper 'Zero point six one eight...' followed by a brief rhythmic chuckle"
        },
        "stage_aesthetic": {
            "primary_environment": "A dimly lit digital observatory surrounded by floating luminous geometric wireframes",
            "lighting_atmosphere": "Dramatic high-contrast cold rim lighting with warm golden volumetric light beams",
            "camera_feel": "Cinematic dynamic low-angle tracking with sharp Dutch tilts on rhythm hits"
        },
        "prompt_engine": {
            "positive_character_anchor": "masterpiece, best quality, 1boy, solo, silver white layered messy hair, glowing amber eyes, mole under right eye, asymmetrical black and gold blazer, techwear, sharp facial features, confident smirk, golden ratio wireframes, cinematic rim lighting, 8k resolution",
            "negative_prompt_anchor": "worst quality, low quality, blurry, symmetrical generic clothes, flat lighting, deformed anatomy, bad hands, missing fingers, extra limbs, ugly face",
            "recommended_aspect_ratios": ["9:16", "16:9", "1:1"]
        }
    }
    return CharacterProfile.model_validate(raw_data)
