"""Script writing with Ollama: topic ideas, then a hook-first script split into lines,
each with a b-roll search phrase."""

from __future__ import annotations

import json
import logging
import re

import requests

from .brain import _chat

log = logging.getLogger(__name__)

RULES = """Rules for Shorts that hold attention:
- Line 1 IS the hook: under 12 words, creates stakes or curiosity. Never "In this video", never a greeting.
- Short spoken sentences, 5-14 words each. One idea per line. No lists, no emojis, no hashtags.
- Build tension, put the payoff near the end, and make the last line loop back to the hook.
- Write numbers the way a narrator says them.
- {words_min}-{words_max} words in total across all lines.
Respond ONLY with JSON:
{{"title": "<YouTube title, max 60 chars, curiosity without lying>",
  "hook_text": "<max 6 words shown on screen in the first seconds>",
  "lines": [{{"text": "<one spoken sentence>", "visual": "<2-5 word search phrase for footage of this line>"}}],
  "description": "<2 sentences>",
  "tags": ["<tag>", "..."]}}"""

STORY = """You write narration for a YouTube Shorts channel: {title}.
Angle: {angle}. Tone: {tone}.
Tell ONE true story using ONLY facts stated in SOURCE. If a detail is not in SOURCE, leave it out.
Visual phrases should name the real subject (e.g. "F-15 Eagle takeoff", "Kobe Bryant dunk").
""" + RULES

REDDIT = """You write ORIGINAL FICTIONAL stories for a YouTube Shorts channel: {title}.
Angle: {angle}. Tone: {tone}.
Write in first person like an online forum post. Invent everything: no real people, companies or places
that could be identified. Give it a specific setup, escalating conflict, and a satisfying twist.
The last line asks viewers what they would have done.
The title should read like a post title. Visual phrases describe the mood (e.g. "office at night").
""" + RULES

TWEET = """You make commentary Shorts for: {title}. Tone: {tone}.
You are reacting to a real public post. Line 1 must read the post VERBATIM (visual: "card").
Then give a sharp, fair, original take: context, why it blew up, and your verdict.
Never state unverified claims about real people as fact. No insults about protected traits.
""" + RULES

IDEAS = """Suggest {n} specific, distinct topics for a Shorts channel about {angle}.
Each must be a single real event, person, machine or company with its own English Wikipedia article.
Do NOT repeat or closely resemble any of these already-used topics: {used}.
Respond ONLY with JSON: {{"topics": ["<wikipedia-searchable topic>", "..."]}}"""

PREMISES = """Suggest {n} distinct premises for original fictional {angle}.
One sentence each, each with a different setting and conflict.
Do NOT resemble any of these already-used premises: {used}.
Respond ONLY with JSON: {{"premises": ["<premise>", "..."]}}"""


def _model(niche: dict) -> str | None:
    return niche.get("model")


def ideas(cfg: dict, niche: dict, used: list[str], n: int = 8) -> list[str]:
    reddit = niche["format"] == "reddit"
    prompt = (PREMISES if reddit else IDEAS).format(n=n, angle=niche["angle"], used="; ".join(used[-60:]) or "none")
    try:
        data = _chat(cfg, "You are a creative producer. Output JSON only.", prompt, _model(niche), temperature=0.9)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
        log.warning("idea generation failed: %s", exc)
        return []
    items = data.get("premises" if reddit else "topics", []) if isinstance(data, dict) else []
    return [str(x).strip() for x in items if str(x).strip()]


def _validate(data: dict, words_min: int, words_max: int) -> tuple[dict | None, str]:
    if not isinstance(data, dict):
        return None, "Respond with a JSON object."
    lines = [l for l in data.get("lines") or [] if isinstance(l, dict) and str(l.get("text", "")).strip()]
    if len(lines) < 4:
        return None, "Write at least 6 lines."
    count = sum(len(str(l["text"]).split()) for l in lines)
    if count < words_min * 0.85:
        return None, f"Too short ({count} words). Write {words_min}-{words_max} words."
    if count > words_max * 1.15:
        return None, f"Too long ({count} words). Cut to {words_min}-{words_max} words."
    clean_lines = [
        {"text": re.sub(r"\s+", " ", str(l["text"])).strip(), "visual": str(l.get("visual") or "").strip()}
        for l in lines
    ]
    return {
        "title": str(data.get("title") or clean_lines[0]["text"]).strip().strip('"')[:90],
        "hook_text": str(data.get("hook_text") or "").strip().strip('"')[:40],
        "lines": clean_lines,
        "description": str(data.get("description") or "").strip()[:900],
        "tags": [str(t).lstrip("#").strip() for t in data.get("tags") or [] if str(t).strip()][:12],
    }, ""


def script(cfg: dict, niche: dict, fmt: str, material: str) -> dict | None:
    """fmt: story | reddit | tweet. material: SOURCE text, premise, or the post text."""
    words_min, words_max = cfg["stories"]["words"][fmt]
    template = {"story": STORY, "reddit": REDDIT, "tweet": TWEET}[fmt]
    system = template.format(
        title=niche.get("title", niche["name"]), angle=niche.get("angle", ""), tone=niche.get("tone", ""),
        words_min=words_min, words_max=words_max,
    )
    label = {"story": "SOURCE", "reddit": "PREMISE", "tweet": "POST"}[fmt]
    user = f"{label}:\n{material}"
    for attempt in range(3):
        try:
            data = _chat(cfg, system, user, _model(niche), temperature=0.8 if fmt == "reddit" else 0.5)
        except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
            log.warning("script attempt %d failed: %s", attempt + 1, exc)
            continue
        result, problem = _validate(data, words_min, words_max)
        if result:
            return result
        log.info("script rejected (%s), retrying", problem)
        user = f"{label}:\n{material}\n\nYour last answer was rejected: {problem}"
    return None
