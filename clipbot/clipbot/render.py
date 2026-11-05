"""Cut, reframe, overlay text and mix audio with ffmpeg."""

from __future__ import annotations

import json
import logging
import random
import subprocess
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    return {
        "width": int(video.get("width", 1920)),
        "height": int(video.get("height", 1080)),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        "duration": float(data["format"].get("duration", 0)),
    }


def _ts(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _ass_text(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(cfg: dict, path: Path, w: int, h: int, clip: dict, words: list[dict], duration: float) -> None:
    t = cfg["text"]
    font = t["font"]
    scale = h / 1920
    hook_size, cap_size = int(t["hook_size"] * scale), int(t["caption_size"] * scale)
    # Colours are &HAABBGGRR. Hook: white on translucent black box. Captions: yellow, thick outline.
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,"
        f"1,0,0,0,100,100,0,0,3,{int(18 * scale)},0,8,60,60,{int(220 * scale)},1",
        f"Style: Cap,{font},{cap_size},&H0000F0FF,&H00FFFFFF,&H00000000,&H64000000,"
        f"1,0,0,0,100,100,0,0,1,{max(int(6 * scale), 2)},2,2,60,60,{int(420 * scale)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if clip.get("hook"):
        hook = "\\N".join(textwrap.wrap(_ass_text(clip["hook"]).upper(), 20))
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Hook,,0,0,0,,{hook}")

    if t.get("burn_captions"):
        n = max(int(t["words_per_caption"]), 1)
        inside = [x for x in words if x["start"] >= clip["start"] and x["end"] <= clip["end"]]
        for i in range(0, len(inside), n):
            chunk = inside[i:i + n]
            start = chunk[0]["start"] - clip["start"]
            # hold each caption until the next one starts so it doesn't flicker
            nxt = inside[i + n]["start"] - clip["start"] if i + n < len(inside) else chunk[-1]["end"] - clip["start"]
            text = _ass_text(" ".join(x["word"] for x in chunk)).upper()
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(max(nxt, start + 0.2))},Cap,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _wav_seconds(path: Path) -> float:
    return probe(path)["duration"]


def render(cfg: dict, source: Path, clip: dict, words: list[dict], narration: Path | None, out_dir: Path) -> Path:
    info = probe(source)
    duration = round(clip["end"] - clip["start"], 2)
    vertical = cfg["clips"].get("vertical", True)
    w, h = (1080, 1920) if vertical else (info["width"] - info["width"] % 2, info["height"] - info["height"] % 2)

    write_ass(cfg, out_dir / "subs.ass", w, h, clip, words, duration)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(clip["start"]), "-t", str(duration), "-i", str(source)]
    idx = 1
    narr_idx = music_idx = None
    if narration:
        cmd += ["-i", str(narration)]
        narr_idx, idx = idx, idx + 1
    music_dir = Path(cfg["audio"].get("music_dir") or "/nonexistent")
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in AUDIO_EXTS] if music_dir.is_dir() else []
    if tracks:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(tracks))]
        music_idx, idx = idx, idx + 1

    if vertical:
        video = (
            "[0:v]split[a][b];"
            "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,"
            "scale=1080:1920,setsar=1[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,ass=subs.ass[v]"
        )
    else:
        video = f"[0:v]scale={w}:{h},setsar=1,fps=30,ass=subs.ass[v]"

    a = cfg["audio"]
    delay = float(a["narration_delay_s"])
    if info["has_audio"]:
        orig = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo"
    else:
        orig = f"anullsrc=r=48000:cl=stereo,atrim=0:{duration}"
    if narr_idx is not None:
        end = delay + _wav_seconds(narration) + 0.2
        orig += f",volume='if(between(t,{delay},{end:.2f}),{a['duck_original_to']},1)':eval=frame"
    audio = [orig + "[orig]"]
    mix = ["[orig]"]
    if narr_idx is not None:
        ms = int(delay * 1000)
        audio.append(
            f"[{narr_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms},volume=1.6[narr]"
        )
        mix.append("[narr]")
    if music_idx is not None:
        audio.append(
            f"[{music_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=0:{duration},afade=t=out:st={max(duration - 1.5, 0)}:d=1.5,volume={a['music_volume']}[mus]"
        )
        mix.append("[mus]")
    audio.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[aout]")

    out = out_dir / "video.mp4"
    cmd += [
        "-filter_complex", ";".join([video] + audio),
        "-map", "[v]", "-map", "[aout]", "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "video.mp4",
    ]
    log.info("rendering %s (%.1fs)", out_dir.name, duration)
    subprocess.run(cmd, check=True, cwd=out_dir)
    (out_dir / "subs.ass").unlink(missing_ok=True)
    return out
