"""Procedural 'blocky corridor' fly-through backgrounds.

Original footage generated on the Pi (no third-party gameplay, nothing for Content ID to
match). Each loop gets its own palette, block pattern, floating blocks and camera sway."""

from __future__ import annotations

import colorsys
import logging
import math
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger(__name__)
W, H, FPS = 540, 960, 30          # rendered small, scaled up in the final edit
FOCAL = 0.9 * W
NEAR, FAR, SLICE = 0.35, 22.0, 0.5
HALF = 1.0                        # corridor half-width/height in world units

PALETTES = [  # base hues seen working in the niche: grass green, brick red, purple, white tile, orange
    (0.30, 0.65), (0.0, 0.70), (0.78, 0.55), (0.0, 0.0), (0.08, 0.75), (0.58, 0.55),
]


def _shade(hue: float, sat: float, val: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(hue % 1, max(0, min(sat, 1)), max(0, min(val, 1)))
    return int(r * 255), int(g * 255), int(b * 255)


def _proj(x: float, y: float, z: float, cx: float, cy: float) -> tuple[float, float]:
    return W / 2 + (x - cx) * FOCAL / z, H / 2 + (y - cy) * FOCAL / z


def render(out: Path, seconds: float = 90, seed: int | None = None) -> Path:
    rnd = random.Random(seed)
    hue, sat = rnd.choice(PALETTES)
    base_hue = hue
    hue += rnd.uniform(-0.03, 0.03)
    base_val = 0.95 if sat == 0 else 0.75
    speed = rnd.uniform(2.2, 3.2)                     # units per second
    cols = rnd.choice([3, 4, 5])
    # floating blocks / parkour pillars along the corridor
    length = speed * seconds + FAR + 5
    blocks = []
    z = 4.0
    while z < length:
        blocks.append((rnd.uniform(-0.6, 0.6), rnd.uniform(0.0, 0.7), z, rnd.uniform(0.18, 0.35)))
        z += rnd.uniform(2.5, 5.0)
    names = {0.30: "green", 0.0: "red", 0.78: "purple", 0.08: "orange", 0.58: "blue"}
    look = {"palette": "white" if sat == 0 else names.get(base_hue, "other"),
            "speed": round(speed, 2), "blocks": cols}
    out.with_suffix(".json").write_text(__import__("json").dumps(look))
    accent = _shade(hue + rnd.choice([0.0, 0.5]), 0.6 if sat else 0.0, 0.35)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-vf", "scale=1080:1920:flags=neighbor",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", str(out)],
        stdin=subprocess.PIPE,
    )
    frames = int(seconds * FPS)
    for f in range(frames):
        t = f / FPS
        cam_z = t * speed
        cx = 0.35 * math.sin(t * 0.37)
        cy = 0.25 + 0.15 * math.sin(t * 0.23)
        img = Image.new("RGB", (W, H), _shade(hue, sat, base_val * 0.25))
        d = ImageDraw.Draw(img)
        first = math.floor((cam_z + NEAR) / SLICE) * SLICE
        zs = [first + i * SLICE for i in range(int((FAR) / SLICE) + 2)]
        for z0 in reversed(zs):
            z1 = z0 + SLICE
            a, b = max(z0 - cam_z, NEAR), z1 - cam_z
            if b <= NEAR:
                continue
            fog = max(0.15, 1 - (a / FAR) ** 0.8)
            stripe = int(z0 / SLICE) % 2
            # walls: (axis points) floor y=+HALF, ceiling y=-HALF, left x=-HALF, right x=+HALF
            for wall, light in (("floor", 1.0), ("left", 0.8), ("right", 0.72), ("ceil", 0.6)):
                for c in range(cols):
                    u0, u1 = -HALF + 2 * HALF * c / cols, -HALF + 2 * HALF * (c + 1) / cols
                    check = (stripe + c) % 2
                    val = base_val * light * fog * (0.92 if check else 1.0)
                    col = _shade(hue, sat * (0.95 if check else 1.0), val)
                    if wall == "floor":
                        pts = [(u0, HALF, a), (u1, HALF, a), (u1, HALF, b), (u0, HALF, b)]
                    elif wall == "ceil":
                        pts = [(u0, -HALF, a), (u1, -HALF, a), (u1, -HALF, b), (u0, -HALF, b)]
                    elif wall == "left":
                        pts = [(-HALF, u0, a), (-HALF, u1, a), (-HALF, u1, b), (-HALF, u0, b)]
                    else:
                        pts = [(HALF, u0, a), (HALF, u1, a), (HALF, u1, b), (HALF, u0, b)]
                    d.polygon([_proj(x, y, zz, cx, cy) for x, y, zz in pts], fill=col)
        for bx, by, bz, size in sorted(blocks, key=lambda q: -q[2]):
            rz = bz - cam_z
            if not NEAR + size < rz < FAR:
                continue
            fog = max(0.15, 1 - (rz / FAR) ** 0.8)
            front = [_proj(bx - size, by - size, rz - size, cx, cy), _proj(bx + size, by + size, rz - size, cx, cy)]
            top = [_proj(bx - size, by - size, rz - size, cx, cy), _proj(bx + size, by - size, rz - size, cx, cy),
                   _proj(bx + size, by - size, rz + size, cx, cy), _proj(bx - size, by - size, rz + size, cx, cy)]
            d.polygon(top, fill=tuple(int(v * fog * 1.25) for v in accent))
            d.rectangle([front[0], front[1]], fill=tuple(int(v * fog) for v in accent))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while writing background")
    return out


def ensure_pool(folder: Path, count: int = 8, seconds: float = 90) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    existing = sorted(folder.glob("tunnel_*.mp4"))
    for i in range(len(existing), count):
        out = folder / f"tunnel_{i:02d}.mp4"
        log.info("rendering background %s (%.0fs)", out.name, seconds)
        render(out, seconds, seed=random.randrange(1 << 30))
    return sorted(folder.glob("tunnel_*.mp4"))
