"""Source -> transcript -> Ollama picks -> TTS -> render -> ready/ folder."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

from . import brain, render, sources, transcribe, tts
from .state import State

log = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "clip"


def _description(cfg: dict, clip: dict, source: sources.Source) -> str:
    parts = [clip["description"]]
    credit = source.credit
    if credit.get("url"):
        line = f"Source: {source.title} by {credit.get('uploader') or 'unknown'} — {credit['url']}"
        if credit.get("license"):
            line += f" ({credit['license']})"
        parts.append(line)
    tags = list(cfg["channel"].get("hashtags") or []) + [f"#{t.replace(' ', '')}" for t in clip["tags"][:3]]
    parts.append(" ".join(dict.fromkeys(tags)))
    return "\n\n".join(p for p in parts if p)


def make_clips(cfg: dict, source: sources.Source) -> int:
    work = Path(cfg["paths"]["work"])
    transcript = transcribe.transcribe(cfg, source.path, work)
    if not transcript["segments"]:
        log.info("no speech found in %s", source.path.name)
        return 0

    picks = brain.pick_clips(cfg, transcript, source.title)
    log.info("%s: %d clip(s) picked", source.path.name, len(picks))
    made = 0
    for n, clip in enumerate(picks, 1):
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{n}_{_slug(clip['title'])}"
        building = work / "building" / name
        building.mkdir(parents=True, exist_ok=True)
        try:
            voice = tts.speak(cfg, clip["narration"], building / "narration.wav")
            render.render(cfg, source.path, clip, transcript["words"], voice, building)
            if voice:
                voice.unlink(missing_ok=True)
            meta = {
                **clip,
                "description": _description(cfg, clip, source),
                "source": {"key": source.key, "title": source.title, **source.credit},
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            (building / "metadata.json").write_text(json.dumps(meta, indent=2))
            (building / "title.txt").write_text(meta["title"] + "\n")
            (building / "description.txt").write_text(meta["description"] + "\n")
            # move only when complete so the uploader never sees half-built clips
            shutil.move(str(building), Path(cfg["paths"]["ready"]) / name)
            made += 1
        except Exception:
            log.exception("failed to build clip %s", name)
            shutil.rmtree(building, ignore_errors=True)
    return made


def run(cfg: dict) -> int:
    state = State(cfg["paths"]["work"])
    found = sources.collect(cfg, state)
    log.info("%d new source video(s)", len(found))
    total = 0
    for source in found:
        try:
            made = make_clips(cfg, source)
            state.mark(source.key, "done", made)
            sources.archive(cfg, source)
            total += made
        except Exception:
            log.exception("source %s failed; will retry next run", source.path.name)
    log.info("done: %d clip(s) added to %s", total, cfg["paths"]["ready"])
    return total
