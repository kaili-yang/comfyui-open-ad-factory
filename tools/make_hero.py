"""Render the product photo for the self-ad: a phone running Open Ad Factory, on a white studio background.

    python tools/make_hero.py assets/open_ad_factory_hero.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = os.path.join(os.path.dirname(__file__), "..", "open_ad_factory", "fonts", "Anton-Regular.ttf")
YELLOW = (240, 255, 79)
SIZE = 1024


def font(size):
    return ImageFont.truetype(FONT, size)


def centered(draw, y, text, size, fill, x0, x1):
    f = font(size)
    w = draw.textlength(text, font=f)
    draw.text((x0 + (x1 - x0 - w) / 2, y), text, font=f, fill=fill)


def main(out):
    img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))

    # Phone geometry, 9:19.5 like a modern handset
    pw, ph = 420, 860
    px, py = (SIZE - pw) // 2, (SIZE - ph) // 2

    shadow = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((px + 18, py + 30, px + pw + 18, py + ph + 30), 70, fill=110)
    img.paste((150, 150, 160), mask=shadow.filter(ImageFilter.GaussianBlur(28)))

    d = ImageDraw.Draw(img)
    d.rounded_rectangle((px, py, px + pw, py + ph), 70, fill=(18, 18, 22))
    sx0, sy0, sx1, sy1 = px + 16, py + 16, px + pw - 16, py + ph - 16

    screen = Image.new("RGB", (sx1 - sx0, sy1 - sy0))
    sd = ImageDraw.Draw(screen)
    sw, sh = screen.size
    for y in range(sh):
        t = y / sh
        sd.line([(0, y), (sw, y)], fill=(int(10 + 30 * t), int(10 + 16 * t), int(16 + 62 * t)))
    mask = Image.new("L", screen.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw, sh), 56, fill=255)
    img.paste(screen, (sx0, sy0), mask)

    d.rounded_rectangle((px + pw // 2 - 60, sy0 + 14, px + pw // 2 + 60, sy0 + 40), 13, fill=(0, 0, 0))
    centered(d, sy0 + 70, "OPEN AD FACTORY", 40, (255, 255, 255), sx0, sx1)

    # URL field
    d.rounded_rectangle((sx0 + 28, sy0 + 150, sx1 - 28, sy0 + 206), 16, fill=(40, 36, 58), outline=(90, 80, 130), width=2)
    d.text((sx0 + 48, sy0 + 163), "https://your-store.com/product", font=font(22), fill=(170, 165, 195))

    # Four shot thumbnails
    tw, th, gap = 76, 124, 10
    tx = sx0 + (sx1 - sx0 - (4 * tw + 3 * gap)) // 2
    colors = [((109, 75, 216), (194, 79, 216)), ((60, 60, 70), (120, 120, 135)), ((43, 43, 117), (90, 140, 200)), ((240, 200, 60), (240, 255, 79))]
    for i, (c0, c1) in enumerate(colors):
        x = tx + i * (tw + gap)
        thumb = Image.new("RGB", (tw, th))
        td = ImageDraw.Draw(thumb)
        for y in range(th):
            t = y / th
            td.line([(0, y), (tw, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c0, c1)))
        tm = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(tm).rounded_rectangle((0, 0, tw, th), 12, fill=255)
        img.paste(thumb, (x, sy0 + 250), tm)
        centered(d, sy0 + 250 + th + 8, f"SHOT {i + 1}", 18, (200, 195, 225), x, x + tw)

    # Score badge
    centered(d, sy0 + 440, "VIRALITY SCORE", 26, (200, 195, 225), sx0, sx1)
    centered(d, sy0 + 470, "92", 150, YELLOW, sx0, sx1)
    centered(d, sy0 + 668, "/ 100", 30, (200, 195, 225), sx0, sx1)

    d.rounded_rectangle((sx0 + 60, sy1 - 110, sx1 - 60, sy1 - 46), 32, fill=YELLOW)
    centered(d, sy1 - 102, "GENERATE AD", 34, (20, 20, 20), sx0, sx1)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    img.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "assets/open_ad_factory_hero.png")
