"""Assemble a story Short: one b-roll shot per line, a card, karaoke captions, voice and music."""

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


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *cmd], check=True, cwd=cwd)


def _segment(asset: Asset | None, dur: float, out: Path, flip: bool) -> None:
    if asset is None:
        _run(["-f", "lavfi", "-i", f"color=c=0x101418:s={W}x{H}:r={FPS}", "-t", f"{dur:.3f}", *ENC, out.name], out.parent)
    elif asset.kind == "image":
        # slow Ken Burns pan across the photo, alternating direction each shot
        x = f"(iw-{W})*(1-t/{dur:.3f})" if flip else f"(iw-{W})*t/{dur:.3f}"
        vf = (f"scale={int(W * 1.15)}:{int(H * 1.15)}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H}:x='{x}':y='(ih-{H})/2',setsar=1,fps={FPS}")
        _run(["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(asset.path),
              "-vf", vf, "-t", f"{dur:.3f}", *ENC, out.name], out.parent)
    else:
        length = probe(asset.path)["duration"]
        start = random.uniform(0, max(length - dur - 0.5, 0)) if length > dur + 1 else 0
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
        _run(["-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(asset.path), "-an",
              "-vf", vf, "-t", f"{dur:.3f}", *ENC, out.name], out.parent)


def _captions(cfg: dict, path: Path, words: list[dict], hook_text: str, hook_until: float, style: dict) -> None:
    c = cfg["captions"]
    size, font = int(c["size"]), style["font"]
    bgr = style["color"][-6:]  # config colours are &HAABBGGRR; override tags want &HBBGGRR&
    hi = f"&H{bgr}&"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,7,3,5,70,70,0,1",
        f"Style: Hook,{font},{int(size * 0.95)},&H00101010,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,3,22,0,8,70,70,260,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if hook_text and hook_until > 0:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_until)},Hook,,0,0,0,,"
                     f"{{\\3c{hi}\\fad(0,200)}}{_ass_text(hook_text).upper()}")
    # chunks of up to 3 words, broken at sentence ends; the spoken word is highlighted and pops
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or w["word"].endswith((".", "!", "?")):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    for n, chunk in enumerate(chunks):
        chunk_end = chunks[n + 1][0]["start"] if n + 1 < len(chunks) else chunk[-1]["end"] + 0.4
        for i, w in enumerate(chunk):
            end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk_end
            parts = []
            for j, x in enumerate(chunk):
                t = _ass_text(x["word"]).upper()
                parts.append(f"{{\\c{hi}\\fscx112\\fscy112}}{t}{{\\c&HFFFFFF&\\fscx100\\fscy100}}" if i == j else t)
            lines.append(f"Dialogue: 0,{_ts(w['start'])},{_ts(max(end, w['start'] + 0.05))},Cap,,0,0,0,,{' '.join(parts)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(cfg: dict, workdir: Path, voice_wav: Path, words: list[dict], line_starts: list[float],
          assets: list[Asset | None], hook_text: str, card: Path | None, card_until: float, music: bool = True) -> Path:
    duration = probe(voice_wav)["duration"] + 0.6
    style = {"font": random.choice(cfg["captions"]["fonts"]), "color": random.choice(cfg["captions"]["highlight_colors"])}

    # 1) one shot per line, cut on the line's first word
    bounds = line_starts[1:] + [duration]
    concat = []
    for i, (start, end, asset) in enumerate(zip(line_starts, bounds, assets)):
        seg = workdir / f"seg{i:02d}.mp4"
        _segment(asset, max(end - start, 0.4), seg, flip=bool(i % 2))
        concat.append(f"file '{seg.name}'")
    (workdir / "segments.txt").write_text("\n".join(concat) + "\n")
    _run(["-f", "concat", "-safe", "0", "-i", "segments.txt", "-c", "copy", "bg.mp4"], workdir)

    # 2) overlay card + captions, mix voice and music
    _captions(cfg, workdir / "subs.ass", words, "" if card else hook_text, min(2.5, duration), style)
    cmd = ["-i", "bg.mp4", "-i", voice_wav.name]
    idx = 2
    vf = "[0:v]"
    if card:
        cmd += ["-i", card.name]
        vf += f"[{idx}:v]overlay=(W-w)/2:H*0.2:enable='lt(t,{card_until:.2f})'"
        idx += 1
    vf += ",ass=subs.ass[v]" if card else "ass=subs.ass[v]"
    audio = "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[voice]"
    mix = "[voice]"
    music_dir = Path(cfg["audio"].get("music_dir") or "/nonexistent")
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in AUDIO_EXTS] if music and music_dir.is_dir() else []
    if tracks:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(tracks))]
        audio += (f";[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                  f"afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5,volume={cfg['audio']['music_volume']}[mus]")
        mix += "[mus]"
    audio += f";{mix}amix=inputs={mix.count('[')}:duration=first:normalize=0,alimiter=limit=0.95[aout]"
    _run([*cmd, "-filter_complex", f"{vf};{audio}", "-map", "[v]", "-map", "[aout]",
          "-t", f"{duration:.2f}", *ENC, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "video.mp4"], workdir)

    for f in [*workdir.glob("seg*.mp4"), workdir / "segments.txt", workdir / "bg.mp4", workdir / "subs.ass"]:
        f.unlink(missing_ok=True)
    return workdir / "video.mp4"
