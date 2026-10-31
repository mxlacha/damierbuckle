"""Assemble a Short. Layouts (modelled on what's working in the niche):

  full     — b-roll fills the frame, one shot per line (documentary style)
  split    — topic image/clip in a top panel, corridor background below, one huge word at a time
  card     — post card over the corridor background (post commentary, forum stories)
  factcard — highlighted caption block above a clip, blurred copy of the clip behind (music-led)
"""

from __future__ import annotations

import logging
import random
import subprocess
from pathlib import Path

from .broll import Asset
from .render import AUDIO_EXTS, _ass_text, _ts, probe

log = logging.getLogger(__name__)
W, H, FPS = 1080, 1920, 30
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"]


def configure(cfg: dict) -> None:
    """Cap encoder threads (lower = less power draw on a weak supply)."""
    global ENC
    ENC = [*ENC[:8], "-threads", str(int(cfg.get("max_threads", 4)))]
PANEL = {"split": (1000, 600, 40, 170)}      # w, h, x, y


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *cmd], check=True, cwd=cwd)


def _segment(asset: Asset | None, dur: float, out: Path, flip: bool, w: int = W, h: int = H) -> None:
    if asset is None:
        _run(["-f", "lavfi", "-i", f"color=c=0x101418:s={w}x{h}:r={FPS}", "-t", f"{dur:.3f}", *ENC, out.name], out.parent)
    elif asset.kind == "image":
        # slow Ken Burns pan across the photo, alternating direction each shot
        x = f"(iw-{w})*(1-t/{dur:.3f})" if flip else f"(iw-{w})*t/{dur:.3f}"
        vf = (f"scale={int(w * 1.15)}:{int(h * 1.15)}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h}:x='{x}':y='(ih-{h})/2',setsar=1,fps={FPS}")
        _run(["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(asset.path),
              "-vf", vf, "-t", f"{dur:.3f}", *ENC, out.name], out.parent)
    else:
        length = probe(asset.path)["duration"]
        start = random.uniform(0, max(length - dur - 0.5, 0)) if length > dur + 1 else 0
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS}"
        _run(["-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(asset.path), "-an",
              "-vf", vf, "-t", f"{dur:.3f}", *ENC, out.name], out.parent)


def _chunks(words: list[dict], size: int) -> list[list[dict]]:
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == size or w["word"].endswith((".", "!", "?")):
            chunks.append(cur)
            cur = []
    return chunks + ([cur] if cur else [])


def _captions(cfg: dict, path: Path, words: list[dict], hook_text: str, hook_until: float, style: dict) -> None:
    c = cfg["captions"]
    font, kind, y = style["font"], style["kind"], style["y"]
    hi = f"&H{style['color'][-6:]}&"  # config colours are &HAABBGGRR; override tags want &HBBGGRR&
    size = int(c["size"] * (1.8 if kind == "word" else 1))
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,"
        f"{9 if kind == 'word' else 7},4,5,60,60,0,1",
        f"Style: Hook,{font},{int(c['size'] * 0.95)},&H00101010,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,3,22,0,8,70,70,260,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if hook_text and hook_until > 0:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_until)},Hook,,0,0,0,,"
                     f"{{\\3c{hi}\\fad(0,200)}}{_ass_text(hook_text).upper()}")
    pos = f"\\pos({W // 2},{y})"
    if kind == "word":
        # one huge word at a time with a quick pop-in (the split-screen explainer look)
        for i, w in enumerate(words):
            end = words[i + 1]["start"] if i + 1 < len(words) else w["end"] + 0.4
            text = _ass_text(w["word"]).strip(".,!?;:\"")
            lines.append(f"Dialogue: 0,{_ts(w['start'])},{_ts(max(end, w['start'] + 0.05))},Cap,,0,0,0,,"
                         f"{{{pos}\\fscx70\\fscy70\\t(0,70,\\fscx100\\fscy100)}}{text}")
    elif kind == "karaoke":
        chunks = _chunks(words, 3)
        for n, chunk in enumerate(chunks):
            chunk_end = chunks[n + 1][0]["start"] if n + 1 < len(chunks) else chunk[-1]["end"] + 0.4
            for i, w in enumerate(chunk):
                end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk_end
                parts = []
                for j, x in enumerate(chunk):
                    t = _ass_text(x["word"]).upper()
                    parts.append(f"{{\\c{hi}\\fscx112\\fscy112}}{t}{{\\c&HFFFFFF&\\fscx100\\fscy100}}" if i == j else t)
                lines.append(f"Dialogue: 0,{_ts(w['start'])},{_ts(max(end, w['start'] + 0.05))},Cap,,0,0,0,,"
                             f"{{{pos}}}{' '.join(parts)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _shots(workdir: Path, starts: list[float], assets: list, duration: float, w: int, h: int) -> Path:
    """One shot per line, cut on the line's first word, concatenated into shots.mp4."""
    bounds = starts[1:] + [duration]
    concat = []
    for i, (start, end, asset) in enumerate(zip(starts, bounds, assets)):
        seg = workdir / f"seg{i:02d}.mp4"
        _segment(asset, max(end - start, 0.4), seg, flip=bool(i % 2), w=w, h=h)
        concat.append(f"file '{seg.name}'")
    (workdir / "segments.txt").write_text("\n".join(concat) + "\n")
    _run(["-f", "concat", "-safe", "0", "-i", "segments.txt", "-c", "copy", "shots.mp4"], workdir)
    return workdir / "shots.mp4"


def build(cfg: dict, workdir: Path, *, duration: float, layout: str = "full", voice_wav: Path | None = None,
          words: list[dict] | None = None, starts: list[float] | None = None, assets: list | None = None,
          background: Path | None = None, hook_text: str = "", card: Path | None = None,
          card_until: float | None = None, caption_style: str = "karaoke", music: bool = True,
          progress_bar: bool = True) -> Path:
    words, starts, assets = words or [], starts or [0.0], assets or [None]
    style = {"font": random.choice(cfg["captions"]["fonts"]), "color": random.choice(cfg["captions"]["highlight_colors"]),
             "kind": caption_style, "y": H // 2}
    inputs: list[str] = []
    vf: list[str] = []

    def add(*args: str) -> int:
        inputs.extend(args)
        return sum(1 for a in inputs if a == "-i") - 1

    if layout == "full":
        base = add("-i", str(_shots(workdir, starts, assets, duration, W, H)))
        vf.append(f"[{base}:v]null[base]")
    elif layout == "factcard":
        clip = _shots(workdir, starts, assets, duration, 1000, 760)
        base = add("-i", str(clip))
        block = add("-i", card.name)
        blk_h = _png_height(workdir / card.name)
        top = max(160, (H - blk_h - 760) // 2 - 60)
        vf.append(f"[{base}:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"boxblur=30:3,eq=brightness=-0.12[bgx];[bgx][{block}:v]overlay=(W-w)/2:{top}[bg2];"
                  f"[bg2][b]overlay=(W-w)/2:{top + blk_h}[base]")
        card = None
    else:  # split / card: generated corridor (or your own gameplay) as the moving background
        if background is None:
            raise RuntimeError("no background footage — run `clipbot backgrounds` first")
        length = probe(background)["duration"]
        offset = random.uniform(0, max(length - duration - 1, 0))
        bg = add("-stream_loop", "-1", "-ss", f"{offset:.2f}", "-i", str(background))
        vf.append(f"[{bg}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}[bg0]")
        if layout == "split":
            pw, ph, px, py = PANEL["split"]
            panel = add("-i", str(_shots(workdir, starts, assets, duration, pw, ph)))
            vf.append(f"[bg0][{panel}:v]overlay={px}:{py}[base]")
            style["y"] = py + ph + 210
        else:
            vf.append("[bg0]null[base]")
    last = "base"
    if card is not None:
        ci = add("-i", card.name)
        until = duration if card_until is None else card_until
        card_y = int(H * 0.17)
        vf.append(f"[{last}][{ci}:v]overlay=(W-w)/2:{card_y}:enable='lt(t,{until:.2f})'[carded]")
        last = "carded"
        if layout == "card":
            style["y"] = min(card_y + _png_height(workdir / card.name) + 200, H - 420)

    _captions(cfg, workdir / "subs.ass", words, "" if (card or layout != "full") else hook_text,
              min(2.5, duration), style)
    if progress_bar:
        # thin bar along the top that fills as the video plays (slides in from the left)
        bar = f"&H{style['color'][-6:]}"
        rgb = f"0x{bar[-2:]}{bar[-4:-2]}{bar[-6:-4]}"  # ASS is BBGGRR, ffmpeg wants RRGGBB
        vf.append(f"color=c={rgb}:s={W}x14:r={FPS}[barsrc]")
        vf.append(f"[{last}]drawbox=x=0:y=0:w=iw:h=14:color=black@0.55:t=fill[track]")
        vf.append(f"[track][barsrc]overlay=x='-W+W*t/{duration:.2f}':y=0:shortest=1[barred]")
        last = "barred"
    vf.append(f"[{last}]ass=subs.ass[v]")

    audio, mix = [], []
    if voice_wav is not None:
        vi = add("-i", voice_wav.name)
        audio.append(f"[{vi}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[voice]")
        mix.append("[voice]")
    music_dir = Path(cfg["audio"].get("music_dir") or "/nonexistent")
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in AUDIO_EXTS] if music and music_dir.is_dir() else []
    if tracks:
        mi = add("-stream_loop", "-1", "-i", str(random.choice(tracks)))
        vol = cfg["audio"]["music_volume"] if voice_wav is not None else 0.7  # music-led formats
        audio.append(f"[{mi}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5,volume={vol}[mus]")
        mix.append("[mus]")
    if not mix:
        audio.append(f"anullsrc=r=48000:cl=stereo[sil]")
        mix.append("[sil]")
    audio.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[aout]")

    _run([*inputs, "-filter_complex", ";".join(vf + audio), "-map", "[v]", "-map", "[aout]",
          "-t", f"{duration:.2f}", *ENC, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "video.mp4"], workdir)

    for f in [*workdir.glob("seg*.mp4"), workdir / "segments.txt", workdir / "shots.mp4", workdir / "subs.ass"]:
        f.unlink(missing_ok=True)
    return workdir / "video.mp4"


def _png_height(path: Path) -> int:
    from PIL import Image

    with Image.open(path) as img:
        return img.height
