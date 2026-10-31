"""Fill the posting calendar with story Shorts and write an upload sheet for YouTube Studio."""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import logging
import random
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import align, broll, cards, compose, niches, research, voice, writer
from .pipeline import _slug
from .render import probe
from .state import State

log = logging.getLogger(__name__)
ISO = "%Y-%m-%dT%H:%M:%SZ"


# ------------------------------------------------------------------ calendar
def open_slots(cfg: dict, state) -> list[datetime]:
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=float(cfg["schedule"]["buffer_days"]))
    taken = {p for (p,) in state.q("SELECT publish_at FROM videos")}
    slots, day = [], now.astimezone(tz).date()
    while True:
        for hhmm in sorted(cfg["schedule"]["publish_times"]):
            h, m = map(int, hhmm.split(":"))
            utc = datetime(day.year, day.month, day.day, h, m, tzinfo=tz).astimezone(timezone.utc)
            if utc > horizon:
                return slots
            if utc >= now + timedelta(hours=2) and utc.strftime(ISO) not in taken:
                slots.append(utc)
        day += timedelta(days=1)


# ------------------------------------------------------------------ inputs
def _pending_tweets(cfg: dict) -> list[Path]:
    inbox = Path(cfg["stories"]["tweets_inbox"])
    inbox.mkdir(parents=True, exist_ok=True)
    stems = {p.stem for p in inbox.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".txt"}}
    return [inbox / s for s in sorted(stems)]


def _read_tweet(stem: Path) -> tuple[str, str, Path | None]:
    """Returns (handle, text, screenshot). .txt: optional first line '@handle', then the post."""
    shot = next((stem.with_suffix(e) for e in (".png", ".jpg", ".jpeg") if stem.with_suffix(e).exists()), None)
    txt = stem.with_suffix(".txt")
    if txt.exists():
        lines = txt.read_text().strip().splitlines()
        handle = lines[0].strip() if lines and lines[0].startswith("@") else ""
        return handle, "\n".join(lines[1:] if handle else lines).strip(), shot
    if shot and shutil.which("tesseract"):
        text = subprocess.run(["tesseract", str(shot), "stdout"], capture_output=True, text=True).stdout.strip()
        return "", text, shot
    return "", "", shot


def _used_topics(state, niche: str) -> list[str]:
    return [t for (t,) in state.q("SELECT topic FROM videos WHERE niche=? ORDER BY rowid", niche)]


def _story_material(cfg: dict, state, niche: dict) -> tuple[str, str, str, str] | None:
    """(topic, key, source_text, source_url) for a fresh, fact-grounded topic."""
    used_keys = {k for (k,) in state.q("SELECT topic_key FROM videos")}
    if niche.get("rss"):
        for item in research.rss(niche["rss"]):
            if item["key"] not in used_keys:
                return item["title"], item["key"], item["text"], item["url"]
        return None
    used = _used_topics(state, niche["name"])
    candidates = [s for s in niche.get("seeds", []) if s not in used]
    random.shuffle(candidates)
    candidates += writer.ideas(cfg, niche, used)
    for topic in candidates:
        if not cfg["stories"].get("wikipedia_grounding", True):
            key = "topic:" + topic.lower()
            if key not in used_keys:
                return topic, key, topic, ""
            continue
        try:
            article = research.wikipedia(topic)
        except Exception as exc:
            log.warning("wikipedia lookup failed for %r: %s", topic, exc)
            continue
        if article and article["key"] not in used_keys:
            return topic, article["key"], f"{article['title']}\n\n{article['text']}", article["url"]
    return None


def _premise(cfg: dict, state, niche: dict) -> tuple[str, str] | None:
    used = _used_topics(state, niche["name"])
    for premise in writer.ideas(cfg, niche, used):
        if all(difflib.SequenceMatcher(None, premise.lower(), u.lower()).ratio() < 0.6 for u in used):
            return premise, "premise:" + hashlib.sha1(premise.encode()).hexdigest()[:12]
    return None


# ------------------------------------------------------------------ production
def _pick_voice(state, niche: dict) -> str:
    voices = niche.get("voices") or ["am_adam"]
    last = state.q("SELECT voice FROM videos WHERE niche=? ORDER BY publish_at DESC LIMIT 1", niche["name"])
    options = [v for v in voices if not last or v != last[0][0]] or voices
    return random.choice(options)


def produce(cfg: dict, state, niche: dict, fmt: str, slot: datetime, material: str, topic: str,
            topic_key: str, source_url: str = "", tweet: tuple | None = None) -> str | None:
    script = writer.script(cfg, niche, fmt, material)
    if not script:
        log.warning("no usable script for %r", topic)
        return None

    local = slot.astimezone(ZoneInfo(cfg["schedule"]["timezone"]))
    folder = f"{local:%Y-%m-%d}/{local:%H%M}_{_slug(script['title'])}"
    work = Path(cfg["paths"]["work"]) / "building" / folder.replace("/", "_")
    work.mkdir(parents=True, exist_ok=True)
    try:
        voice_name = _pick_voice(state, niche)
        texts = [l["text"] for l in script["lines"]]
        wav = voice.synth(cfg, " ".join(texts), voice_name, work / "voice.wav")
        duration = probe(wav)["duration"]
        words = align.align(cfg, wav, " ".join(texts).split(), duration)

        line_starts, i = [], 0
        for t in texts:
            line_starts.append(0.0 if i == 0 else words[i]["start"])
            i += len(t.split())

        used: set = set()
        subject = {**niche, "subject": topic if fmt == "story" else ""}
        credits: list[str] = []
        if fmt == "reddit":
            bg = broll.find(cfg, subject, random.choice(niche.get("background_queries") or ["satisfying"]), used)
            starts, assets = [0.0], [bg]
        else:
            starts, assets = line_starts, []
            for line in script["lines"]:
                query = line["visual"] if line["visual"] and line["visual"].lower() != "card" else topic
                asset = broll.find(cfg, subject, query, used) or (assets[-1] if assets else None)
                assets.append(asset)
        credits = list(dict.fromkeys(a.credit for a in assets if a and a.credit))

        card, card_until = None, 0.0
        if fmt == "reddit":
            card = cards.text_card(work / "card.png", cfg["channel"]["name"],
                                   "@" + _slug(cfg["channel"]["name"]).replace("-", ""), script["title"],
                                   label="Fictional story")
            card_until = max(line_starts[1] if len(line_starts) > 1 else 0.0, 3.0)
        elif fmt == "tweet":
            handle, text, shot = tweet
            card = cards.screenshot_card(shot, work / "card.png") if shot else \
                cards.text_card(work / "card.png", handle.lstrip("@") or "Post", handle, text)
            card_until = max((line_starts[1] if len(line_starts) > 1 else 0.0) + 1.5, 4.0)

        compose.build(cfg, work, wav, words, starts, assets, script["hook_text"], card, card_until)
        (work / "card.png").unlink(missing_ok=True)
        wav.unlink(missing_ok=True)

        desc = [script["description"]]
        if fmt == "reddit":
            desc.append("This is a fictional story. Names, people and events are invented. Narrated with an AI voice.")
        if source_url:
            desc.append(f"Source: {source_url}")
        if credits:
            desc.append("Images: " + "; ".join(credits))
        hashtags = list(niche.get("hashtags") or []) + list(cfg["channel"].get("hashtags") or [])
        desc.append(" ".join(dict.fromkeys(hashtags)))
        meta = {
            "title": script["title"], "description": "\n\n".join(d for d in desc if d), "tags": script["tags"],
            "publish_local": f"{local:%Y-%m-%d %H:%M}", "publish_utc": slot.strftime(ISO),
            "niche": niche["name"], "format": fmt, "topic": topic, "voice": voice_name,
            # Studio asks "altered or synthetic content?" — say yes for invented stories told as if real
            "disclose_altered_content": fmt == "reddit",
            "script": texts,
        }
        (work / "metadata.json").write_text(json.dumps(meta, indent=2))
        (work / "title.txt").write_text(meta["title"] + "\n")
        (work / "description.txt").write_text(meta["description"] + "\n")
        dest = Path(cfg["paths"]["ready"]) / folder
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(work), dest)
        state.x("INSERT INTO videos (folder, niche, format, title, topic_key, topic, voice, publish_at) "
                "VALUES (?,?,?,?,?,?,?,?)", folder, niche["name"], fmt, meta["title"], topic_key, topic,
                voice_name, meta["publish_utc"])
        log.info("ready: %s  [%s] %s", meta["publish_local"], niche["name"], meta["title"])
        return folder
    except Exception:
        log.exception("failed to build %r", topic)
        shutil.rmtree(work, ignore_errors=True)
        return None


def fill(cfg: dict, subs: int | None = None) -> int:
    state = State(cfg["paths"]["work"])
    slots = open_slots(cfg, state)
    log.info("%d open slot(s) in the next %s days", len(slots), cfg["schedule"]["buffer_days"])
    tweet_niche = next((n for n in cfg["niches"] if n.get("format") == "tweet"), None)
    made = failures = 0
    for slot in slots:
        if failures >= 3:
            log.error("3 failures in a row; stopping (is Ollama running? run `clipbot check`)")
            break
        niche = niches.active(cfg, state, subs)
        day = slot.astimezone(ZoneInfo(cfg["schedule"]["timezone"])).date().isoformat()
        tweets_today = state.q("SELECT 1 FROM videos WHERE format='tweet' AND folder LIKE ?", f"{day}/%")
        pending = _pending_tweets(cfg)
        folder = None

        if pending and not tweets_today:  # at most one commentary post per day
            stem = pending[0]
            handle, text, shot = _read_tweet(stem)
            post_niche = {**(tweet_niche or {}), **niche, "format": "tweet",
                          "title": (tweet_niche or niche).get("title", niche["name"])}
            if text:
                folder = produce(cfg, state, post_niche, "tweet", slot, f"{handle}: {text}" if handle else text,
                                 text[:80], "tweet:" + stem.name, tweet=(handle, text, shot))
            else:
                log.warning("%s: no text (add a .txt next to the screenshot, or install tesseract)", stem.name)
            done = stem.parent / "done"
            done.mkdir(exist_ok=True)
            for f in stem.parent.glob(stem.name + ".*"):
                shutil.move(str(f), done / f.name)
        if folder is None and niche["format"] == "reddit":
            picked = _premise(cfg, state, niche)
            if picked:
                folder = produce(cfg, state, niche, "reddit", slot, picked[0], picked[0], picked[1])
            else:
                niches.strike(cfg, state, niche, subs)
        elif folder is None:
            picked = _story_material(cfg, state, niche)
            if picked:
                topic, key, text, url = picked
                folder = produce(cfg, state, niche, "story", slot, text, topic, key, url)
            else:
                niches.strike(cfg, state, niche, subs)

        if folder:
            made, failures = made + 1, 0
            niches.clear_strikes(state, niche)
        else:
            failures += 1
    write_sheet(cfg, state)
    return made


# ------------------------------------------------------------------ manual upload helpers
def write_sheet(cfg: dict, state) -> Path:
    ready = Path(cfg["paths"]["ready"])
    rows = state.q("SELECT folder, publish_at, title, niche, format FROM videos WHERE status='ready' ORDER BY publish_at")
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    with open(ready / "UPLOAD_SHEET.csv", "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["publish_date", "publish_time", "folder", "title", "altered_content", "niche"])
        for folder, publish_at, title, niche, fmt in rows:
            local = datetime.strptime(publish_at, ISO).replace(tzinfo=timezone.utc).astimezone(tz)
            out.writerow([f"{local:%Y-%m-%d}", f"{local:%I:%M %p}", folder, title,
                          "Yes" if fmt == "reddit" else "No", niche])
    return ready / "UPLOAD_SHEET.csv"


def mark_uploaded(cfg: dict, through: str) -> int:
    """Move every ready folder dated on/before `through` (YYYY-MM-DD) to uploaded/."""
    state = State(cfg["paths"]["work"])
    moved = 0
    for (folder,) in state.q("SELECT folder FROM videos WHERE status='ready' AND substr(folder,1,10)<=?", through):
        src = Path(cfg["paths"]["ready"]) / folder
        if src.exists():
            dest = Path(cfg["paths"]["uploaded"]) / folder
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dest)
            parent = src.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        state.x("UPDATE videos SET status='uploaded' WHERE folder=?", folder)
        moved += 1
    write_sheet(cfg, state)
    return moved
