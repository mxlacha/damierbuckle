"""On-screen cards: a story title card (generic design, no third-party logos) and tweet cards."""

from __future__ import annotations

import colorsys
import hashlib
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 960


def _font(bold: bool, size: int):
    pattern = "DejaVu Sans:bold" if bold else "DejaVu Sans"
    path = None
    if shutil.which("fc-match"):
        path = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout
    try:
        return ImageFont.truetype(path or "DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def _accent(seed: str) -> tuple[int, int, int]:
    hue = int(hashlib.md5(seed.encode()).hexdigest()[:4], 16) / 0xFFFF
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.9)
    return int(r * 255), int(g * 255), int(b * 255)


def text_card(out: Path, name: str, handle: str, body: str, label: str = "", dark: bool = False,
              avatar: Path | None = None) -> Path:
    """Rounded post card: avatar + name/handle, then wrapped body text. Dark = X/Bluesky night style."""
    fg, sub, bg = ((240, 240, 240), (140, 145, 150), (0, 0, 0, 250)) if dark else \
        ((15, 15, 15), (110, 110, 110), (255, 255, 255, 245))
    head_font, small_font, body_font = _font(True, 38), _font(False, 30), _font(True, 46)
    pad, line_h = 44, 60
    lines = []
    for para in body.split("\n"):  # wrap by rendered width so bold text never spills off the card
        cur = ""
        for word in para.split():
            test = f"{cur} {word}".strip()
            if cur and body_font.getlength(test) > WIDTH - 2 * pad:
                lines.append(cur)
                cur = word
            else:
                cur = test
        lines.append(cur)
    height = pad + 96 + 28 + line_h * len(lines) + (54 if label else 0) + pad
    img = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, WIDTH - 1, height - 1), radius=36, fill=bg)
    if avatar and avatar.exists():
        face = Image.open(avatar).convert("RGB").resize((96, 96))
        mask = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 95, 95), fill=255)
        img.paste(face, (pad, pad), mask)
    else:
        d.ellipse((pad, pad, pad + 96, pad + 96), fill=_accent(name))
        d.text((pad + 48, pad + 48), (name[:1] or "?").upper(), font=_font(True, 50), fill="white", anchor="mm")
    d.text((pad + 120, pad + 8), name, font=head_font, fill=fg)
    d.text((pad + 120, pad + 56), handle, font=small_font, fill=sub)
    y = pad + 96 + 28
    for line in lines:
        d.text((pad, y), line, font=body_font, fill=fg)
        y += line_h
    if label:
        d.text((pad, y + 14), label, font=small_font, fill=sub)
    img.save(out)
    return out


def screenshot_card(src: Path, out: Path) -> Path:
    """Scale a user-supplied screenshot to card width with rounded corners."""
    img = Image.open(src).convert("RGBA")
    img = img.resize((WIDTH, int(img.height * WIDTH / img.width)))
    if img.height > 1100:
        img = img.crop((0, 0, WIDTH, 1100))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=30, fill=255)
    img.putalpha(mask)
    img.save(out)
    return out


def fact_block(out: Path, text: str, dark: bool = True, width: int = 1000, size: int = 58) -> Path:
    """Caption block for fact cards. **phrases** are highlighted (yellow on dark, like the niche leaders)."""
    font = _font(True, size) if dark else _font(False, size)
    fg, hi, bg = ((255, 255, 255), (255, 226, 70), (0, 0, 0)) if dark else ((20, 20, 20), (20, 20, 20), (255, 255, 255))
    tokens = []
    for n, part in enumerate(text.split("**")):
        tokens += [(w, n % 2 == 1) for w in part.split()]
    pad, space = 34, font.getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    glued = []
    for word, high in tokens:  # keep "**free fall**." from rendering as "free fall ."
        if glued and all(ch in ".,!?;:" for ch in word):
            glued[-1] = (glued[-1][0] + word, glued[-1][1])
        else:
            glued.append((word, high))
    for word, high in glued:
        w = font.getlength(word)
        if cur and cur_w + space + w > width - 2 * pad:
            lines.append((cur, cur_w))
            cur, cur_w = [], 0.0
        cur_w += (space if cur else 0) + w
        cur.append((word, high, w))
    if cur:
        lines.append((cur, cur_w))
    line_h = int(size * 1.28)
    img = Image.new("RGB", (width, pad * 2 + line_h * len(lines)), bg)
    d = ImageDraw.Draw(img)
    for i, (words, line_w) in enumerate(lines):
        x = (width - line_w) / 2 if dark else pad
        for word, high, w in words:
            d.text((x, pad + i * line_h), word, font=font, fill=hi if high else fg)
            x += w + space
    img.save(out)
    return out
