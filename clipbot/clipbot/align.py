"""Word timings for captions: whisper listens to the voiceover, then we map its timings
back onto the exact script words (so captions are always spelled right)."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

_align_model = None


def _get_align_model(cfg: dict):
    global _align_model
    if _align_model is None:
        from faster_whisper import WhisperModel

        w = cfg["whisper"]
        _align_model = WhisperModel(w.get("align_model", "tiny.en"), device="cpu", compute_type=w["compute_type"],
                                    cpu_threads=min(int(w["threads"]), int(cfg.get("max_threads", 4))))
    return _align_model


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def align(cfg: dict, wav: Path, script_words: list[str], duration: float) -> list[dict]:
    segments, _ = _get_align_model(cfg).transcribe(str(wav), word_timestamps=True, beam_size=1, language="en")
    heard = [w for seg in segments for w in (seg.words or [])]
    return map_timings(script_words, [(w.word, w.start, w.end) for w in heard], duration)


def map_timings(script_words: list[str], heard: list[tuple[str, float, float]], duration: float) -> list[dict]:
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    matcher = difflib.SequenceMatcher(
        None, [_norm(w) for w in script_words], [_norm(h[0]) for h in heard], autojunk=False
    )
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            _, start, end = heard[block.b + k]
            times[block.a + k] = (start, end)

    # interpolate words whisper missed between the nearest known neighbours
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < len(times) else duration
        step = max(right - left, 0.01) / (j - i)
        for k in range(i, j):
            times[k] = (left + step * (k - i), left + step * (k - i + 1))
        i = j
    return [{"word": w, "start": round(t[0], 2), "end": round(t[1], 2)} for w, t in zip(script_words, times)]
