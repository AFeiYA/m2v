"""
Cast Studio Prompt Engine & Protocol Builder
--------------------------------------------
Constructs structured LLM prompts that guide AI models to architect complete,
consistent character profiles adhering strictly to the CharacterProfile schema.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any
from src.cast_schema import CharacterProfile


STYLE_PRESETS: dict[str, str] = {
    "cinematic": "Realistic Cinematic / Live-Action Film Quality",
    "anime": "Modern High-End Japanese Anime / Manga Aesthetic",
    "techwear_cyber": "Cyberpunk Techwear & Geometric Avant-Garde",
    "indie_retro": "Lo-Fi Indie Musician / 35mm Vintage Film Grain",
    "pop_idol": "K-Pop / J-Pop High-Gloss Stage Idol Aesthetic",
    "dark_fantasy": "Gothic Dark Fantasy & Ethereal Mysticism"
}


CAST_SYSTEM_PROMPT = """你是一位享誉全球的虚拟艺人（Virtual Artist / VTuber）与动漫影视概念总监。
你的任务是将用户的灵感构想推演并设计为一个具有深刻戏剧张力、高辨识度视觉基因、解耦造型与演出场景的【生产级虚拟角色档案】。

### 角色设计的五大核心原则：
1. **反差塑造灵魂 (Contradiction)**：
   不要设计扁平的角色。挖掘角色“外在展现”与“内心渴望/恐惧”的深刻矛盾（例如：表面傲慢追求绝对理性，内心却极度渴望失控的真情；表面毒舌搞笑，唱起歌来却孤注一掷）。
2. **明确年龄与面容视觉特征 (Face Invariants)**：
   - 年龄填入具体数字（如用户指定则遵照用户设定，否则默认 16 岁）。
   - 严禁模糊词汇（如“帅气”、“好看”）。精确描述发型切面、虹膜色调（具体色号 Hex）与不可变识别特征（如眼下泪痣、耳钉）。
3. **造型与演出场景解耦 (Decoupled Wardrobe & Stage)**：
   - 将服装放在 `outfits` 列表中（作为一套可更换的穿搭）；
   - 将演出环境放在 `performance_context` 中（作为针对本首歌的舞台设定，不与角色本体绑死）。
4. **尊重用户选择的美学风格模板**：
   根据用户指定的风格模板（如影视电影风、日系动漫风、独立复古风等）调整用词与画面质感，不强加不相关的机能或二次元元素。
5. **严密格式契约**：
   输出必须【严格匹配提供的 JSON Schema】，且仅输出一个合法的 JSON 代码块，绝不在代码块外输出任何多余的引言或解释。
"""


def build_character_design_prompt(
    user_idea: str,
    character_id: str | None = None,
    style_key: str = "anime",
    forced_age: int | None = None,
) -> list[dict[str, str]]:
    """
    Constructs multi-turn prompt messages for an LLM (Gemini, Claude, GPT)
    to design a comprehensive character profile, including the exact JSON Schema.
    """
    assigned_id = character_id or f"char_{secrets.token_hex(6)}"
    style_desc = STYLE_PRESETS.get(style_key, style_key)
    schema_str = json.dumps(CharacterProfile.model_json_schema(), ensure_ascii=False, indent=2)

    age_instruction = f"- 角色年龄设为 {forced_age} 岁。\n" if forced_age else ""

    user_content = f"""请根据以下灵感构想与设定要求，为我们设计一个完整的虚拟艺人/角色档案：

【用户灵感/要求】：
{user_idea.strip()}

【整体美学风格偏好】：
{style_desc}

【前置系统约束】：
- 角色 ID 已由系统分配为: "{assigned_id}"，请在顶层 "id" 字段填入该值。
{age_instruction}- 请遵循五大设计原则，生成包含 identity、face_invariants、outfits、expression_sheet、vocal_profile、performance_context 和 prompt_engine 的完整结构。

【必须严格遵守的 JSON Schema】：
```json
{schema_str}
```

请直接输出符合上述 Schema 的单个 JSON 代码块。"""

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
    Returns the canonical benchmark CharacterProfile ('Zero.SOE / 零点六一八')
    with locked age (16), decoupled outfits, and asset slots.
    """
    raw_data: dict[str, Any] = {
        "id": "char_zero_soe_0618",
        "user_id": "default_local",
        "visibility": "private",
        "created_at": "2026-10-25T02:00:00Z",
        "identity": {
            "name": "零点六一八",
            "alias": "Zero.SOE / Golden Ratio Boy",
            "age": 16,
            "gender": "male",
            "tagline": "一个痴迷完美比例，却唱着不完美人生的毒舌少年音乐人",
            "archetype": "Perfectionist Rebel & Satirical Prodigy",
            "core_contradiction": "表面极度自恋且执着用数学丈量万物，其实内心深处最渴望体会无法被公式计算的真情",
            "personality_traits": ["高智商自恋", "毒舌幽默", "16岁少年狂气", "隐藏脆弱", "强秩序感"]
        },
        "face_invariants": {
            "silhouette": "slender athletic 16-year-old youth with sharp asymmetrical outer lines",
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
            "facial_marks": ["single dark beauty mark beneath right outer eye corner", "thin silver geometric ear stud on left ear"]
        },
        "active_outfit_id": "outfit_debut_blackgold",
        "outfits": [
            {
                "id": "outfit_debut_blackgold",
                "name": "Debut Black & Gold Techwear",
                "genre_style": "Avant-garde streetwear meets bespoke tailoring",
                "signature_outerwear": "Asymmetrical matte black cropped tactical blazer with gold lining",
                "innerwear": "High-collar crisp white sleeveless mock-neck with thin gold ratio lines",
                "accessories": ["Single black leather fingerless glove on right hand", "Slender silver measuring chain necklace"],
                "materials": ["Matte techwear nylon", "Heavy structured wool", "Reflective gold piping"],
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
            }
        ],
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
        "performance_context": {
            "primary_environment": "A dimly lit digital observatory surrounded by floating luminous geometric wireframes",
            "lighting_atmosphere": "Dramatic high-contrast cold rim lighting with warm golden volumetric light beams",
            "camera_feel": "Cinematic dynamic low-angle tracking with sharp Dutch tilts on rhythm hits"
        },
        "prompt_engine": {
            "positive_character_anchor": "masterpiece, best quality, 1boy, 16 years old, silver white layered messy hair, glowing amber eyes, mole under right eye, sharp facial features, confident smirk, golden ratio wireframes, cinematic rim lighting, 8k resolution",
            "negative_prompt_anchor": "worst quality, low quality, blurry, generic clothes, flat lighting, deformed anatomy, bad hands, missing fingers, extra limbs, ugly face, mature adult",
            "recommended_aspect_ratios": ["9:16", "16:9", "1:1"]
        },
        "assets": {
            "primary_image_url": "/assets/characters/zero_soe/primary.png",
            "secondary_images": [],
            "thumbnail_url": "/assets/characters/zero_soe/thumb.png"
        },
        "bound_songs": []
    }
    return CharacterProfile.model_validate(raw_data)
