"""Speech-to-text with faster-whisper (runs fine on a Pi 5 CPU with int8)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
_model = None


def _get_model(cfg: dict):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        w = cfg["whisper"]
        log.info("loading whisper model %s", w["model"])
        _model = WhisperModel(
            w["model"], device="cpu", compute_type=w["compute_type"], cpu_threads=min(int(w["threads"]), int(cfg.get("max_threads", 4)))
        )
    return _model


def transcribe(cfg: dict, video: Path, cache_dir: Path) -> dict:
    """Return {"segments": [{start,end,text}], "words": [{start,end,word}]}; cached on disk."""
    cache = cache_dir / f"{video.stem}.transcript.json"
    if cache.exists():
        return json.loads(cache.read_text())

    segments_iter, _info = _get_model(cfg).transcribe(
        str(video), word_timestamps=True, vad_filter=True, beam_size=1
    )
    segments, words = [], []
    for seg in segments_iter:
        segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
        for w in seg.words or []:
            words.append({"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()})
        log.debug("[%.1f] %s", seg.start, seg.text)

    result = {"segments": segments, "words": words}
    cache.write_text(json.dumps(result))
    return result
