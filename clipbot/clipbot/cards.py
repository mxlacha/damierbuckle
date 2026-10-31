"""On-screen cards: a story title card (generic design, no third-party logos) and tweet cards."""

from __future__ import annotations

import colorsys
import hashlib
import shutil
import subprocess
import textwrap
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


def text_card(out: Path, name: str, handle: str, body: str, label: str = "") -> Path:
    """White rounded card: avatar + name/handle, then wrapped body text."""
    head_font, small_font, body_font = _font(True, 38), _font(False, 30), _font(True, 46)
    lines = []
    for para in body.split("\n"):
        lines += textwrap.wrap(para, 34) or [""]
    pad, line_h = 44, 60
    height = pad + 96 + 28 + line_h * len(lines) + (54 if label else 0) + pad
    img = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, WIDTH - 1, height - 1), radius=36, fill=(255, 255, 255, 245))
    d.ellipse((pad, pad, pad + 96, pad + 96), fill=_accent(name))
    d.text((pad + 48, pad + 48), (name[:1] or "?").upper(), font=_font(True, 50), fill="white", anchor="mm")
    d.text((pad + 120, pad + 8), name, font=head_font, fill=(20, 20, 20))
    d.text((pad + 120, pad + 56), handle, font=small_font, fill=(110, 110, 110))
    y = pad + 96 + 28
    for line in lines:
        d.text((pad, y), line, font=body_font, fill=(15, 15, 15))
        y += line_h
    if label:
        d.text((pad, y + 14), label, font=small_font, fill=(130, 130, 130))
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
