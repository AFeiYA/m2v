"""Generate the official 1200x630 OpenGraph share image for Fovea Studio."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).resolve().parents[1] / "frontend" / "og-image.png"

def create_og_image():
    W, H = 1200, 630
    img = Image.new("RGBA", (W, H), (14, 17, 12, 255))
    draw = ImageDraw.Draw(img)

    # 1. Subtle radial/glow effect from top-left/center
    # Draw soft decorative background elements
    for r in range(400, 0, -5):
        alpha = int(18 * (1 - r / 400))
        draw.ellipse([600 - r, 200 - r, 600 + r, 200 + r], fill=(200, 255, 0, alpha))

    # Dark overlay to keep text crisp
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    
    # 2. Outer border
    ov_draw.rounded_rectangle([30, 30, W - 30, H - 30], radius=24, outline=(45, 55, 38, 255), width=2)
    # Inner subtle corner glow
    ov_draw.rounded_rectangle([32, 32, W - 32, H - 32], radius=22, outline=(200, 255, 0, 30), width=1)

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_bold = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    font_reg = "/System/Library/Fonts/Supplemental/Arial.ttf"
    if not Path(font_bold).exists():
        font_bold = "/System/Library/Fonts/Helvetica.ttc"
        font_reg = "/System/Library/Fonts/Helvetica.ttc"

    title_font = ImageFont.truetype(font_bold, 72)
    brand_sub_font = ImageFont.truetype(font_bold, 40)
    sub_font = ImageFont.truetype(font_reg, 32)
    tag_font = ImageFont.truetype(font_bold, 20)
    footer_font = ImageFont.truetype(font_reg, 24)

    # Draw Brand Tag (Top)
    # Lime accent pill
    draw.rounded_rectangle([80, 75, 360, 120], radius=12, fill=(200, 255, 0, 30), outline=(200, 255, 0, 180), width=1)
    draw.text((100, 85), "AI LYRIC VIDEO STUDIO", fill=(200, 255, 0, 255), font=tag_font)

    # Main Brand & Title
    # Sparkle / Diamond icon
    cx, cy = 100, 200
    sparkle = [(cx, cy - 22), (cx + 7, cy - 7), (cx + 22, cy), (cx + 7, cy + 7),
               (cx, cy + 22), (cx - 7, cy + 7), (cx - 22, cy), (cx - 7, cy - 7)]
    draw.polygon(sparkle, fill=(200, 255, 0, 255))
    draw.ellipse([cx + 12, cy + 12, cx + 18, cy + 18], fill=(200, 255, 0, 255))

    draw.text((135, 170), "Fovea Studio", fill=(245, 247, 242, 255), font=title_font)

    # Tagline / Description
    draw.text((80, 275), "Turn your songs into cinematic lyric videos", fill=(230, 235, 225, 255), font=brand_sub_font)
    draw.text((80, 335), "Animated typography, kinetic posters & word-level timing sync.", fill=(160, 172, 150, 255), font=sub_font)

    # Feature badges
    badges = [
        "Suno & Udio Ready",
        "Kinetic Posters",
        "Apple Scroll Lyrics",
        "16:9 & 9:16 Formats",
        "4K / 60 FPS Export"
    ]
    bx = 80
    by = 425
    for badge in badges:
        bbox = draw.textbbox((0, 0), badge, font=tag_font)
        bw = (bbox[2] - bbox[0]) + 32
        draw.rounded_rectangle([bx, by, bx + bw, by + 46], radius=23, fill=(25, 32, 22, 255), outline=(50, 62, 42, 255), width=1)
        draw.text((bx + 16, by + 12), badge, fill=(210, 220, 200, 255), font=tag_font)
        bx += bw + 14

    # Footer line & domain
    draw.line([(80, 520), (W - 80, 520)], fill=(40, 48, 35, 255), width=1)
    draw.text((80, 545), "fovea.si", fill=(200, 255, 0, 255), font=ImageFont.truetype(font_bold, 26))
    draw.text((200, 547), "·  Independent creative software for musicians & songwriters", fill=(130, 140, 125, 255), font=footer_font)

    # Save to RGB PNG
    final = img.convert("RGB")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final.save(OUTPUT, "PNG", optimize=True)
    print(f"Generated OG image at {OUTPUT} ({W}x{H})")

if __name__ == "__main__":
    create_og_image()
