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
- About {words_target} words in total (8-12 sentences).
Respond ONLY with JSON:
{{"title": "<YouTube title, max 60 chars, curiosity without lying>",
  "hook_text": "<max 6 words shown on screen in the first seconds>",
  "script": "<the full voiceover, plain sentences>",
  "visuals": ["<2-5 word footage search phrase>", "<one per 2-3 sentences>"],
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
You are reacting to a real public post. The first sentence must read the post VERBATIM.
Then give a sharp, fair, original take: context, why it blew up, and your verdict.
Never state unverified claims about real people as fact. No insults about protected traits.
""" + RULES

EXPLAINER = """You write voiceovers for a fast split-screen explainer Shorts channel: {title}.
Angle: {angle}. Tone: {tone}. Talk like you're telling a friend a wild fact: casual, confident, quick.
Use ONLY facts stated in SOURCE. If a detail is not in SOURCE, leave it out.
Open with a bold claim or question about the subject (e.g. "This director has more aura than his movies.").
Visual phrases should name the real subject so a matching photo can be found.
""" + RULES

FACTCARD = """You write the on-screen caption for a silent Shorts clip on: {title}. Angle: {angle}.
SOURCE is the footage's official description. Use ONLY facts from it.
{words_min}-{words_max} words, 2-4 sentences, plain conversational English, first sentence is the hook
(start mid-thought, like "Hitting desert ruts at 100 mph would rip the wheels off a normal truck.").
Wrap the 2-4 most striking phrases in **double asterisks** so they get highlighted.
Respond ONLY with JSON:
{{"title": "<YouTube title, max 60 chars>", "caption": "<the caption with **highlights**>",
  "description": "<1 sentence>", "tags": ["<tag>", "..."]}}"""

POST_FILTER = """A channel about {angle} is considering this public post for a commentary Short:
POST: {text}
Is it (a) clearly on-topic or broadly funny/interesting, and (b) free of politics, tragedy, sexual content,
harassment and medical/financial advice? Respond ONLY with JSON: {{"ok": true|false}}"""

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


def _sentences(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if t.strip()]


def _validate(data: dict, words_min: int, words_max: int) -> tuple[dict | None, str]:
    """Accept anything usable; fix near-misses instead of paying for another slow rewrite."""
    if not isinstance(data, dict):
        return None, "Respond with a JSON object."
    # small models mix up the shape: take "script" text, "lines" objects or plain strings
    if isinstance(data.get("script"), str):
        sentences = _sentences(data["script"])
    else:
        sentences = []
        for line in data.get("lines") or data.get("script") or []:
            text = line.get("text", "") if isinstance(line, dict) else str(line)
            sentences += _sentences(text)
    if len(sentences) < 3 or sum(len(s.split()) for s in sentences) < words_min * 0.6:
        return None, f"Too short. Write about {(words_min + words_max) // 2} words in 8-12 sentences."
    # too long: drop sentences before the last one (keeps the hook and the loop-back ending)
    while len(sentences) > 4 and sum(len(s.split()) for s in sentences) > words_max * 1.1:
        sentences.pop(-2)
    visuals = [str(v).strip() for v in data.get("visuals") or [] if str(v).strip()]
    visuals += [str(l.get("visual", "")).strip() for l in data.get("lines") or [] if isinstance(l, dict)]
    visuals = [v for v in visuals if v]
    lines = [{"text": s, "visual": visuals[i * len(visuals) // len(sentences)] if visuals else ""}
             for i, s in enumerate(sentences)]
    return {
        "title": str(data.get("title") or sentences[0]).strip().strip('"')[:90],
        "hook_text": str(data.get("hook_text") or "").strip().strip('"')[:40],
        "lines": lines,
        "description": str(data.get("description") or "").strip()[:900],
        "tags": [str(t).lstrip("#").strip() for t in data.get("tags") or [] if str(t).strip()][:12],
    }, ""


def post_ok(cfg: dict, niche: dict, text: str) -> bool:
    try:
        data = _chat(cfg, "You are a careful content reviewer. Output JSON only.",
                     POST_FILTER.format(angle=niche.get("angle", ""), text=text), _model(niche), temperature=0)
    except (requests.RequestException, json.JSONDecodeError, KeyError):
        return False
    return isinstance(data, dict) and data.get("ok") is True


def _words(cfg: dict, niche: dict, fmt: str) -> tuple[int, int]:
    own = niche.get("format") == fmt or (niche.get("format") == "post" and fmt == "tweet")
    words = (niche.get("words") if own else None) or cfg["stories"]["words"][fmt]  # per-niche override
    return int(words[0]), int(words[1])


def factcard(cfg: dict, niche: dict, material: str) -> dict | None:
    words_min, words_max = _words(cfg, niche, "factcard")
    system = FACTCARD.format(title=niche.get("title", niche["name"]), angle=niche.get("angle", ""),
                             words_min=words_min, words_max=words_max)
    user = f"SOURCE:\n{material}"
    for attempt in range(2):
        try:
            data = _chat(cfg, system, user, _model(niche), temperature=0.5)
        except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
            log.warning("caption attempt %d failed: %s", attempt + 1, exc)
            continue
        caption = re.sub(r"\s+", " ", str((data or {}).get("caption", ""))).strip() if isinstance(data, dict) else ""
        count = len(caption.replace("**", "").split())
        if count >= words_min * 0.6:
            if "**" not in caption:  # no highlights: emphasise the first clause instead of retrying
                head, _, rest = caption.partition(",")
                caption = f"**{head}**,{rest}" if rest else f"**{caption}**"
            return {"title": str(data.get("title") or caption[:60]).strip().strip('"')[:90], "caption": caption,
                    "description": str(data.get("description") or "").strip()[:900],
                    "tags": [str(t).lstrip("#").strip() for t in data.get("tags") or [] if str(t).strip()][:12],
                    "hook_text": "", "lines": [{"text": t, "visual": ""} for t in
                                               re.split(r"(?<=[.!?])\s+", caption.replace("**", "")) if t]}
        user = f"SOURCE:\n{material}\n\nRejected: write {words_min}-{words_max} words with 2-4 **highlights**."
    return None


def script(cfg: dict, niche: dict, fmt: str, material: str) -> dict | None:
    """fmt: story | explainer | reddit | tweet. material: SOURCE text, premise, or the post text."""
    words_min, words_max = _words(cfg, niche, fmt)
    template = {"story": STORY, "explainer": EXPLAINER, "reddit": REDDIT, "tweet": TWEET}[fmt]
    system = template.format(
        title=niche.get("title", niche["name"]), angle=niche.get("angle", ""), tone=niche.get("tone", ""),
        words_min=words_min, words_max=words_max, words_target=(words_min + words_max) // 2,
    )
    label = {"story": "SOURCE", "explainer": "SOURCE", "reddit": "PREMISE", "tweet": "POST"}[fmt]
    user = f"{label}:\n{material}"
    for attempt in range(2):
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
