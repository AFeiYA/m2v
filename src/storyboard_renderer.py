"""
Suno2MV 动态故事板 (Animatic) 画面渲染器
-------------------------------------------
使用 Pillow 生成影视级高保真 16:9 静态分镜卡片 (Storyboard Frames)：
- 包含景别标线、机位运动箭头、角色与场景实体标签、剧作动作描述与歌词字幕。
- 零外部生图 API 成本，秒级渲染 30+ 连贯分镜图，立刻支持 Web 端实时验片。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont

from src.storyboard_schema import AlignmentProject, ShotPlan
from src.utils import log


# 常用字体回退列表 (优先使用系统高清中文字体)
FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def _get_font(size: int) -> ImageFont.ImageFont:
    """获取可用系统字体或默认字体"""
    for font_path in FONT_CANDIDATES:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_shot_frame(
    shot: ShotPlan,
    output_path: str | Path,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """
    渲染单个 16:9 电影质感分镜卡片
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), color=(13, 17, 23))
    draw = ImageDraw.Draw(img)

    # 1. 情绪基调渐变底色
    is_chorus = "Chorus" in shot.section_name or shot.shot_size in ["EWS", "ECU"]
    accent_color = (255, 120, 60) if is_chorus else (60, 160, 240)
    bg_tint = (28, 20, 30) if is_chorus else (16, 24, 38)

    draw.rectangle([0, 0, width, height], fill=bg_tint)

    # 2. 电影 2.39:1 宽银幕遮幅 (Letterbox)
    letterbox_h = int(height * 0.08)
    draw.rectangle([0, 0, width, letterbox_h], fill=(8, 10, 14))
    draw.rectangle([0, height - letterbox_h, width, height], fill=(8, 10, 14))

    # 3. 三分法则构图辅助线 (Rule of Thirds Grid - 细暗线)
    grid_col = (40, 50, 65)
    draw.line([width / 3, letterbox_h, width / 3, height - letterbox_h], fill=grid_col, width=1)
    draw.line([2 * width / 3, letterbox_h, 2 * width / 3, height - letterbox_h], fill=grid_col, width=1)
    draw.line([0, height / 3, width, height / 3], fill=grid_col, width=1)
    draw.line([0, 2 * height / 3, width, 2 * height / 3], fill=grid_col, width=1)

    # 4. 视线中心十字准星 (Crosshair)
    cx, cy = width / 2, height / 2
    draw.line([cx - 20, cy, cx + 20, cy], fill=grid_col, width=1)
    draw.line([cx, cy - 20, cx, cy + 20], fill=grid_col, width=1)

    # 5. 顶部 HUD 栏
    font_hud_sm = _get_font(18)
    font_hud_lg = _get_font(24)

    # 左侧：分镜号与乐段
    shot_title = f"SHOT {shot.shot_id:02d}  •  [{shot.section_name or 'Verse'}]"
    draw.text((36, 18), shot_title, fill=(230, 235, 245), font=font_hud_lg)

    time_str = f"{shot.start:.3f}s ➔ {shot.end:.3f}s ({shot.duration:.2f}s)"
    draw.text((36, 48), time_str, fill=(130, 145, 165), font=font_hud_sm)

    # 右侧：专业摄影规格徽标 (Shot Size / Motion / Lens)
    spec_tags = [
        f"[{shot.shot_size}]",
        f"[{shot.camera_motion.upper()}]",
        f"[{shot.camera_angle.upper()}]",
    ]
    tag_str = "  ".join(spec_tags)
    draw.text((width - 420, 24), tag_str, fill=accent_color, font=font_hud_lg)

    # 6. 中部核心戏剧动作与叙事呈现
    font_action = _get_font(26)
    font_meta = _get_font(18)

    action_box_y = int(cy - 60)
    # 半透明深色卡片衬底
    draw.rounded_rectangle(
        [width * 0.12, action_box_y - 20, width * 0.88, action_box_y + 110],
        radius=8,
        fill=(10, 14, 20),
        outline=(50, 65, 85),
        width=1,
    )

    action_text = shot.action or shot.narrative_goal or "【环境与氛围流动】"
    draw.text((width * 0.15, action_box_y), action_text, fill=(245, 245, 250), font=font_action)

    # 角色与场景标签
    char_tag = "👤 " + (", ".join(shot.character_ids) if shot.character_ids else "主体")
    loc_tag = "📍 " + (shot.location_id or "场景")
    goal_tag = "🎯 " + (shot.narrative_goal or "叙事推进")
    meta_line = f"{char_tag}   |   {loc_tag}   |   {goal_tag}"
    draw.text((width * 0.15, action_box_y + 54), meta_line, fill=(150, 165, 185), font=font_meta)

    # 7. 转场或匹配剪辑标记
    if shot.match_cut_element:
        draw.text((width * 0.15, action_box_y + 80), f"🔗 匹配剪辑: {shot.match_cut_element}", fill=(255, 200, 80), font=font_meta)

    # 8. 底部歌词字幕条 (Subtitle Bar)
    if shot.lyric_reference and shot.lyric_reference != "【器乐段落】":
        font_sub = _get_font(28)
        lyric_y = height - letterbox_h - 60
        # 居中显示歌词
        bbox = draw.textbbox((0, 0), shot.lyric_reference, font=font_sub)
        text_w = bbox[2] - bbox[0]
        sub_x = (width - text_w) / 2
        draw.rounded_rectangle(
            [sub_x - 20, lyric_y - 6, sub_x + text_w + 20, lyric_y + 40],
            radius=6,
            fill=(0, 0, 0, 180),
        )
        draw.text((sub_x, lyric_y), shot.lyric_reference, fill=(255, 255, 255), font=font_sub)

    # 9. 运镜动势示意箭头 (Motion Graphic Cue)
    _draw_motion_cue(draw, shot.camera_motion, width, height, letterbox_h, accent_color)

    # 保存图片
    img.save(str(out_p), format="PNG")
    return out_p


def _draw_motion_cue(draw: ImageDraw.ImageDraw, motion: str, w: int, h: int, l_h: int, color: tuple[int, int, int]):
    """在四角或中心绘制镜头运动指示标记"""
    margin = 30
    if "dolly_in" in motion or "zoomin" in motion:
        # 四角向内收缩的导引折角
        corner_len = 24
        # 左上
        draw.line([margin, l_h + margin, margin + corner_len, l_h + margin], fill=color, width=3)
        draw.line([margin, l_h + margin, margin, l_h + margin + corner_len], fill=color, width=3)
        # 右上
        draw.line([w - margin, l_h + margin, w - margin - corner_len, l_h + margin], fill=color, width=3)
        draw.line([w - margin, l_h + margin, w - margin, l_h + margin + corner_len], fill=color, width=3)
        # 左下
        draw.line([margin, h - l_h - margin, margin + corner_len, h - l_h - margin], fill=color, width=3)
        draw.line([margin, h - l_h - margin, margin, h - l_h - margin - corner_len], fill=color, width=3)
        # 右下
        draw.line([w - margin, h - l_h - margin, w - margin - corner_len, h - l_h - margin], fill=color, width=3)
        draw.line([w - margin, h - l_h - margin, w - margin, h - l_h - margin - corner_len], fill=color, width=3)
    elif "pan_left" in motion or "pan_right" in motion:
        # 水平平移导轨线
        arr_y = h / 2
        if "pan_left" in motion:
            draw.line([w - 60, arr_y, w - 120, arr_y], fill=color, width=4)
        else:
            draw.line([60, arr_y, 120, arr_y], fill=color, width=4)


def render_all_storyboard_frames(
    project: AlignmentProject,
    output_dir: str | Path,
) -> list[Path]:
    """
    批量渲染工程中所有 Shot 的分镜卡片，并自动回填 preview_image 相对路径
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    log.info("🖼 开始渲染 %d 个 Shot 的动态分镜卡片: %s", len(project.storyboard), out_dir)

    for shot in project.storyboard:
        frame_name = f"{shot.id}.png"
        frame_full_path = out_dir / frame_name
        render_shot_frame(shot, frame_full_path)
        generated_paths.append(frame_full_path)

        # 回填相对路径
        rel_path = f"storyboard/{frame_name}"
        shot.preview_image = rel_path
        shot.path = rel_path
        if shot.takes:
            shot.takes[0].media_path = rel_path

    log.info("✅ 已成功生成全部 %d 张分镜预览图", len(generated_paths))
    return generated_paths
