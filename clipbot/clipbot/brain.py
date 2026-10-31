"""The Ollama 'brain': picks the best moments and writes hook text, voiceover and metadata."""

from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)

SYSTEM = """You are a short-form video editor for a YouTube Shorts channel.
Channel niche: {niche}
Writing voice: {voice}

You receive a timestamped transcript. Find self-contained moments that would make
great {min_s}-{max_s} second Shorts: a clear hook in the first seconds, a payoff,
and no missing context. Respond ONLY with JSON in exactly this shape:
{{"clips": [{{
  "start": <seconds, number>,
  "end": <seconds, number>,
  "score": <1-10 how likely this is to perform>,
  "hook": "<on-screen text, max 8 words, no hashtags>",
  "narration": "<voiceover intro read before the clip, max 20 words>",
  "title": "<YouTube title, max 70 chars>",
  "description": "<1-2 sentence description>",
  "tags": ["<tag>", "..."]
}}]}}
Return at most {n} clips. Use timestamps that exist in the transcript."""


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in ``` fences or add a sentence around it."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _cloud(cfg: dict, system: str, user: str, temperature: float) -> dict:
    """Any OpenAI-compatible API (Gemini, Groq, OpenRouter...): seconds instead of minutes per script."""
    llm = cfg["llm"]
    body = {"model": llm["model"], "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    url = f"{llm['base_url'].rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {llm['api_key']}"}
    resp = requests.post(url, json=body, headers=headers, timeout=120)
    if resp.status_code == 400 and "response_format" in resp.text:  # provider without JSON mode
        body.pop("response_format")
        resp = requests.post(url, json=body, headers=headers, timeout=120)
    if not resp.ok:  # surface the provider's reason (e.g. unknown model) instead of a bare status code
        raise requests.HTTPError(f"{resp.status_code} from {llm['base_url']}: {resp.text[:300]}", response=resp)
    return _parse_json(resp.json()["choices"][0]["message"]["content"])


def _chat(cfg: dict, system: str, user: str, model: str | None = None, temperature: float | None = None) -> dict:
    o = cfg["ollama"]
    llm = cfg.get("llm") or {}
    if llm.get("provider") == "cloud" and llm.get("api_key"):
        try:
            return _cloud(cfg, system, user, o["temperature"] if temperature is None else temperature)
        except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as exc:
            log.warning("cloud LLM failed (%s); falling back to Ollama on the Pi", str(exc)[:400])
    resp = requests.post(
        f"{o['host'].rstrip('/')}/api/chat",
        json={
            "model": model or o["model"],
            "stream": False,
            "format": "json",
            "options": {"temperature": o["temperature"] if temperature is None else temperature, "num_ctx": o["num_ctx"],
                        "num_thread": int(cfg.get("max_threads", 4))},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=o["timeout_s"],
    )
    resp.raise_for_status()
    return _parse_json(resp.json()["message"]["content"])


def _windows(segments: list[dict], max_chars: int) -> list[list[dict]]:
    """Split a long transcript into chunks that fit the small model's context."""
    windows, cur, size = [], [], 0
    for seg in segments:
        line_len = len(seg["text"]) + 16
        if cur and size + line_len > max_chars:
            windows.append(cur)
            # overlap a little so moments spanning the boundary aren't lost
            cur, size = cur[-3:], sum(len(s["text"]) + 16 for s in cur[-3:])
        cur.append(seg)
        size += line_len
    if cur:
        windows.append(cur)
    return windows


def _snap(clip: dict, segments: list[dict], min_s: float, max_s: float) -> dict | None:
    """Clamp LLM timestamps to real sentence boundaries and the allowed length."""
    try:
        start, end = float(clip["start"]), float(clip["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not segments or end <= start:
        return None
    start = min((s["start"] for s in segments), key=lambda t: abs(t - start))
    ends = [s["end"] for s in segments if s["end"] > start]
    if not ends:
        return None
    end = min(ends, key=lambda t: abs(t - end))
    if end - start > max_s:
        fitting = [e for e in ends if e - start <= max_s]
        end = max(fitting) if fitting else start + max_s
    if end - start < min_s:
        longer = [e for e in ends if e - start >= min_s]
        if not longer:
            return None
        end = min(longer)
        if end - start > max_s:
            end = start + max_s
    clip["start"], clip["end"] = round(start, 2), round(end, 2)
    return clip


def _overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def pick_clips(cfg: dict, transcript: dict, source_title: str) -> list[dict]:
    segments = transcript["segments"]
    c = cfg["clips"]
    n, min_s, max_s = int(c["per_video"]), float(c["min_seconds"]), float(c["max_seconds"])
    system = SYSTEM.format(
        niche=cfg["channel"]["niche"], voice=cfg["channel"]["voice"], min_s=int(min_s), max_s=int(max_s), n=n
    )
    # ~3 chars per token; leave room for the system prompt and the answer
    max_chars = int(cfg["ollama"]["num_ctx"]) * 2

    candidates: list[dict] = []
    for i, window in enumerate(_windows(segments, max_chars)):
        text = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in window)
        log.info("asking %s about window %d (%d segments)", cfg["ollama"]["model"], i + 1, len(window))
        try:
            data = _chat(cfg, system, f"Video title: {source_title}\n\nTranscript:\n{text}")
        except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
            log.warning("ollama call failed: %s", exc)
            continue
        for clip in data.get("clips", []) if isinstance(data, dict) else []:
            if isinstance(clip, dict):
                snapped = _snap(clip, window, min_s, max_s)
                if snapped:
                    candidates.append(snapped)

    candidates.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    picked: list[dict] = []
    for clip in candidates:
        if float(clip.get("score") or 0) < float(c["min_score"]):
            continue
        if any(_overlaps(clip, p) for p in picked):
            continue
        picked.append(_clean(clip, cfg))
        if len(picked) >= n:
            break
    return picked


def _clean(clip: dict, cfg: dict) -> dict:
    def s(key, limit):
        return str(clip.get(key) or "").strip().strip('"')[:limit]

    tags = [str(t).lstrip("#").strip() for t in clip.get("tags") or [] if str(t).strip()][:12]
    return {
        "start": clip["start"],
        "end": clip["end"],
        "score": clip.get("score"),
        "hook": s("hook", 60),
        "narration": s("narration", 200),
        "title": s("title", 95) or s("hook", 95),
        "description": s("description", 1000),
        "tags": tags,
    }
