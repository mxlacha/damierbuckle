"""Fill each channel's posting calendar and write an upload sheet for YouTube Studio.

Formats (niche `format:`):
  story     — documentary narration, b-roll fills the frame          (layout full)
  explainer — split screen: topic image on top, corridor below, 1-word captions (layout split)
  post      — commentary on a real public post, card over corridor  (layout card)
  reddit    — original fictional forum story, card + corridor        (layout card)
  factcard  — highlighted caption over a public-domain clip, music-led (layout factcard)
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import logging
import random
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import align, broll, cards, channels, compose, niches, research, tunnel, voice, writer
from .pipeline import _slug
from .render import probe
from .sources import VIDEO_EXTS
from .state import State

log = logging.getLogger(__name__)
ISO = "%Y-%m-%dT%H:%M:%SZ"
LAYOUT = {"story": "full", "explainer": "split", "tweet": "card", "reddit": "card", "factcard": "factcard"}
CAPTIONS = {"story": "karaoke", "explainer": "word", "tweet": "word", "reddit": "karaoke", "factcard": "none"}


# ------------------------------------------------------------------ calendar
def open_slots(cfg: dict, state) -> list[datetime]:
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=float(cfg["schedule"]["buffer_days"]))
    taken = {p for (p,) in state.q("SELECT publish_at FROM videos WHERE channel=?", cfg["_channel"])}
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


# ------------------------------------------------------------------ material
def _used_keys(state) -> set[str]:
    return {k for (k,) in state.q("SELECT topic_key FROM videos")}


def _used_topics(state, niche: dict) -> list[str]:
    return [t for (t,) in state.q("SELECT topic FROM videos WHERE niche=? ORDER BY rowid", niche["name"])]


def _candidates(cfg: dict, state, niche: dict) -> list[str]:
    used = _used_topics(state, niche)
    seeds = [s for s in niche.get("seeds", []) if s not in used]
    random.shuffle(seeds)
    return seeds + writer.ideas(cfg, niche, used)


def _story_material(cfg: dict, state, niche: dict) -> dict | None:
    used_keys = _used_keys(state)
    if niche.get("rss"):
        for item in research.rss(niche["rss"]):
            if item["key"] not in used_keys:
                return {"topic": item["title"], **item}
        return None
    for topic in _candidates(cfg, state, niche):
        if not cfg["stories"].get("wikipedia_grounding", True):
            key = "topic:" + topic.lower()
            if key not in used_keys:
                return {"topic": topic, "key": key, "text": topic, "url": ""}
            continue
        try:
            article = research.wikipedia(topic)
        except Exception as exc:
            log.warning("wikipedia lookup failed for %r: %s", topic, exc)
            continue
        if article and article["key"] not in used_keys:
            return {**article, "topic": topic, "text": f"{article['title']}\n\n{article['text']}"}
    return None


def _premise(cfg: dict, state, niche: dict) -> dict | None:
    used = _used_topics(state, niche)
    for premise in writer.ideas(cfg, niche, used):
        if all(difflib.SequenceMatcher(None, premise.lower(), u.lower()).ratio() < 0.6 for u in used):
            return {"topic": premise, "key": "premise:" + hashlib.sha1(premise.encode()).hexdigest()[:12],
                    "text": premise, "url": ""}
    return None


def _fact_material(cfg: dict, state, niche: dict) -> dict | None:
    """A clip plus the facts that describe it: NASA (public domain) or your library (clip + .txt sidecar)."""
    used_keys = _used_keys(state)
    cache = Path(cfg["paths"]["work"]) / "broll_cache"
    cache.mkdir(parents=True, exist_ok=True)
    sources = niche.get("clips", ["local", "nasa"])
    if "local" in sources:
        root = Path(cfg["stories"]["library"])
        for clip in sorted(root.rglob("*")) if root.is_dir() else []:
            facts = clip.with_suffix(".txt")
            key = f"local:{clip.relative_to(root)}"
            if clip.suffix.lower() in VIDEO_EXTS and facts.exists() and key not in used_keys:
                if niche.get("library_tags") and clip.parent.name not in niche["library_tags"]:
                    continue
                return {"topic": clip.stem.replace("_", " "), "key": key, "text": facts.read_text()[:3000],
                        "url": "", "asset": broll.Asset(clip, "video")}
    if "nasa" in sources:
        for query in _candidates(cfg, state, niche):
            try:
                for item in research.nasa_videos(query, 15):
                    if item["key"] in used_keys:
                        continue
                    url = research.nasa_clip_url(item["assets"])
                    if url:
                        path = broll._download(url, cache, ".mp4")
                        return {**item, "topic": query, "asset": broll.Asset(path, "video", "Footage: NASA")}
            except Exception as exc:
                log.warning("nasa lookup failed for %r: %s", query, exc)
    return None


def _inbox_posts(cfg: dict) -> list[Path]:
    inbox = Path(cfg["stories"]["tweets_inbox"])
    stems = {p.stem for p in inbox.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".txt"}}
    return [inbox / s for s in sorted(stems)]


def _read_inbox_post(stem: Path) -> dict:
    """.txt: optional first line '@handle', then the post. A screenshot alone is OCR'd if tesseract exists."""
    shot = next((stem.with_suffix(e) for e in (".png", ".jpg", ".jpeg") if stem.with_suffix(e).exists()), None)
    txt = stem.with_suffix(".txt")
    handle, text = "", ""
    if txt.exists():
        lines = txt.read_text().strip().splitlines()
        handle = lines[0].strip() if lines and lines[0].startswith("@") else ""
        text = "\n".join(lines[1:] if handle else lines).strip()
    elif shot and shutil.which("tesseract"):
        text = subprocess.run(["tesseract", str(shot), "stdout"], capture_output=True, text=True).stdout.strip()
    done = stem.parent / "done"
    done.mkdir(exist_ok=True)
    for f in stem.parent.glob(stem.name + ".*"):
        shutil.move(str(f), done / f.name)
    shot = done / shot.name if shot else None
    return {"topic": text[:80], "key": "inbox:" + stem.name, "text": text, "url": "", "handle": handle,
            "name": handle.lstrip("@") or "Post", "shot": shot}


def _post_material(cfg: dict, state, niche: dict) -> dict | None:
    for stem in _inbox_posts(cfg):
        item = _read_inbox_post(stem)
        if item["text"]:
            return item
        log.warning("%s: no text (add a .txt next to the screenshot, or install tesseract)", stem.name)
    if "bluesky" not in niche.get("posts", ["bluesky"]):
        return None
    used_keys = _used_keys(state)
    for post in research.bluesky_posts(niche.get("bluesky_feeds"), int(niche.get("min_likes", 500)))[:6]:
        if post["key"] not in used_keys and writer.post_ok(cfg, niche, post["text"]):
            return {**post, "topic": post["text"][:80]}
    return None


# ------------------------------------------------------------------ production
def _pick_voice(state, niche: dict) -> str:
    voices = niche.get("voices") or ["am_adam"]
    last = state.q("SELECT voice FROM videos WHERE niche=? ORDER BY publish_at DESC LIMIT 1", niche["name"])
    options = [v for v in voices if not last or v != last[0][0]] or voices
    return random.choice(options)


def _background(cfg: dict) -> Path:
    root = Path(cfg["stories"]["backgrounds"])
    own = [p for p in root.glob("*") if p.suffix.lower() in VIDEO_EXTS] if root.is_dir() else []
    pool = tunnel.ensure_pool(root / "generated", int(cfg["stories"].get("generated_backgrounds", 8)))
    return random.choice(own + pool)


def produce(cfg: dict, state, niche: dict, fmt: str, slot: datetime, item: dict, tag: str = "") -> str | None:
    clock = {"start": time.monotonic(), "last": time.monotonic()}

    def step(msg: str) -> None:  # each line also says how long the previous step took
        now = time.monotonic()
        log.info("%s %s  (+%.0fs)", tag, msg, now - clock["last"])
        clock["last"] = now

    step(f"writing script: {item['topic'][:70]}")
    script = writer.factcard(cfg, niche, item["text"]) if fmt == "factcard" else \
        writer.script(cfg, niche, fmt, f"{item.get('handle', '')}: {item['text']}" if fmt == "tweet" else item["text"])
    if not script:
        log.warning("no usable script for %r", item["topic"])
        return None

    local = slot.astimezone(ZoneInfo(cfg["schedule"]["timezone"]))
    folder = f"{local:%Y-%m-%d}/{local:%H%M}_{_slug(script['title'])}"
    work = Path(cfg["paths"]["work"]) / "building" / f"{cfg['_channel']}_{folder.replace('/', '_')}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        texts = [l["text"] for l in script["lines"]]
        speak = fmt != "factcard" or niche.get("voiceover", False)
        voice_name, wav, words, line_starts = "", None, [], [0.0]
        if speak:
            voice_name = _pick_voice(state, niche)
            step(f"recording voiceover ({voice_name})")
            timed = voice.synth_lines(cfg, texts, voice_name, work / "voice.wav", niche.get("speed"))
            if timed:  # Kokoro: timings come free, no Whisper pass needed
                wav, words = timed
                duration = probe(wav)["duration"] + 0.6
            else:
                wav = voice.synth(cfg, " ".join(texts), voice_name, work / "voice.wav", niche.get("speed"))
                duration = probe(wav)["duration"] + 0.6
                words = align.align(cfg, wav, " ".join(texts).split(), duration)
            line_starts, i = [], 0
            for t in texts:
                line_starts.append(0.0 if i == 0 else words[min(i, len(words) - 1)]["start"])
                i += len(t.split())
        else:  # silent caption: long enough to read twice-ish, short enough to loop
            duration = min(max(len(" ".join(texts).split()) / 3.0 + 3, 8), 30)

        layout = niche.get("layout") or LAYOUT[fmt]
        caption_style = niche.get("captions") or CAPTIONS[fmt]
        used: set = set()
        subject = {**niche, "subject": item["topic"] if fmt in ("story", "explainer") else ""}
        cache = Path(cfg["paths"]["work"]) / "broll_cache"
        card, card_until, background = None, None, None
        starts, assets = [0.0], [None]

        if layout in ("full", "split"):
            starts, assets = line_starts, []
            lead = None
            if item.get("image"):
                try:
                    lead = broll.commons_file(item["image"], cache)
                except Exception as exc:
                    log.warning("lead image lookup failed: %s", exc)
            step(f"finding visuals for {len(script['lines'])} shots")
            for n, line in enumerate(script["lines"]):
                query = line["visual"] if line["visual"] and line["visual"].lower() != "card" else item["topic"]
                asset = lead if n == 0 and lead else broll.find(cfg, subject, query, used)
                assets.append(asset or (assets[-1] if assets else lead))
        if layout in ("split", "card"):
            background = _background(cfg)
        if fmt == "reddit":
            card = cards.text_card(work / "card.png", cfg["channel"]["name"],
                                   "@" + _slug(cfg["channel"]["name"]).replace("-", ""), script["title"],
                                   label="Fictional story", dark=niche.get("dark_card", False))
            card_until = max(line_starts[1] if len(line_starts) > 1 else 0.0, 3.0)
        elif fmt == "tweet":
            avatar = None
            if item.get("avatar"):
                try:
                    avatar = broll._download(item["avatar"], cache, ".jpg")
                except Exception:
                    avatar = None
            card = cards.screenshot_card(item["shot"], work / "card.png") if item.get("shot") else \
                cards.text_card(work / "card.png", item.get("name", "Post"), item.get("handle", ""), item["text"],
                                dark=niche.get("dark_card", True), avatar=avatar)
        elif fmt == "factcard":
            card = cards.fact_block(work / "card.png", script["caption"], dark=niche.get("dark_card", True))
            assets = [item["asset"]]

        step(f"rendering {duration:.0f}s video ({layout} layout)")
        choices = compose.build(cfg, work, progress_bar=niche.get("progress_bar", cfg["captions"].get("progress_bar", True)),
                      duration=duration, layout=layout, voice_wav=wav, words=words, starts=starts,
                      assets=assets, background=background, hook_text=script.get("hook_text", ""), card=card,
                      card_until=card_until, caption_style=caption_style)
        (work / "card.png").unlink(missing_ok=True)
        if wav:
            wav.unlink(missing_ok=True)

        credits = list(dict.fromkeys(a.credit for a in assets if a and a.credit))
        desc = [script["description"]]
        if fmt == "reddit":
            desc.append("This is a fictional story. Names, people and events are invented. Narrated with an AI voice.")
        if fmt == "tweet" and item.get("url"):
            desc.append(f"Original post by {item.get('handle')}: {item['url']}")
        elif item.get("url"):
            desc.append(f"Source: {item['url']}")
        if credits:
            desc.append("Credits: " + "; ".join(credits))
        hashtags = list(niche.get("hashtags") or []) + list(cfg["channel"].get("hashtags") or [])
        desc.append(" ".join(dict.fromkeys(hashtags)))
        delivery = voice.style_for(cfg, voice_name, niche.get("speed")) if voice_name else {}
        bg_look = {}
        if background is not None and background.with_suffix(".json").exists():
            bg_look = json.loads(background.with_suffix(".json").read_text())
        style = {"layout": layout, "captions": caption_style, "voice": voice_name, "duration": round(duration, 1),
                 "words": len(" ".join(texts).split()), "hour": local.hour, "weekday": local.strftime("%a"),
                 "format": fmt, "hook": texts[0] if texts else "", "title_len": len(script["title"]),
                 "speed": delivery.get("speed"), "energy": delivery.get("energy"),
                 "background": background.stem if background is not None else ("b-roll" if layout == "full" else None),
                 "bg_palette": bg_look.get("palette"), "bg_speed": bg_look.get("speed"), **(choices or {})}
        meta = {
            "title": script["title"], "description": "\n\n".join(d for d in desc if d), "tags": script["tags"],
            "publish_local": f"{local:%Y-%m-%d %H:%M}", "publish_utc": slot.strftime(ISO),
            "channel": cfg["_channel"], "niche": niche["label"], "topic": item["topic"],
            # Studio asks "altered or synthetic content?" — say yes for invented stories told as if real
            "disclose_altered_content": fmt == "reddit", "style": style, "script": texts,
        }
        (work / "metadata.json").write_text(json.dumps(meta, indent=2))
        (work / "title.txt").write_text(meta["title"] + "\n")
        (work / "description.txt").write_text(meta["description"] + "\n")
        dest = Path(cfg["paths"]["ready"]) / folder
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(work), dest)
        state.x("INSERT INTO videos (folder, niche, format, title, topic_key, topic, voice, publish_at, channel, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", f"{cfg['_channel']}/{folder}", niche["name"], fmt, meta["title"],
                item["key"], item["topic"], voice_name, meta["publish_utc"], cfg["_channel"], json.dumps(style))
        step("finished")
        log.info("ready: [%s] %s  %s  %s  (%.1f min total)", cfg["_channel"], meta["publish_local"], niche["label"],
                 meta["title"], (time.monotonic() - clock["start"]) / 60)
        return folder
    except Exception:
        log.exception("failed to build %r", item["topic"])
        shutil.rmtree(work, ignore_errors=True)
        return None


MATERIAL = {"story": _story_material, "explainer": _story_material, "reddit": _premise,
            "post": _post_material, "factcard": _fact_material}


def fill_channel(cfg: dict, subs: int | None = None) -> int:
    state = State(cfg["paths"]["work"])
    slots = open_slots(cfg, state)
    log.info("[%s] %d open slot(s) in the next %s days", cfg["_channel"], len(slots), cfg["schedule"]["buffer_days"])
    made = failures = 0
    for n_slot, slot in enumerate(slots, 1):
        tag = f"[{cfg['_channel']} {n_slot}/{len(slots)}]"
        if failures >= 3:
            log.error("[%s] 3 failures in a row; stopping (is Ollama running? `clipbot check`)", cfg["_channel"])
            break
        niche = niches.active(cfg, state, subs)
        folder = None
        # posts you drop in the inbox jump the queue (max one per day) on any channel
        day = slot.astimezone(ZoneInfo(cfg["schedule"]["timezone"])).date().isoformat()
        tweeted = state.q("SELECT 1 FROM videos WHERE channel=? AND format='tweet' AND folder LIKE ?",
                          cfg["_channel"], f"{cfg['_channel']}/{day}/%")
        if niche["format"] != "post" and not tweeted and _inbox_posts(cfg):
            item = _post_material(cfg, state, {**niche, "posts": []})
            if item:
                folder = produce(cfg, state, niche, "tweet", slot, item, tag)
        if folder is None:
            item = MATERIAL[niche["format"]](cfg, state, niche)
            if item:
                fmt = "tweet" if niche["format"] == "post" else niche["format"]
                folder = produce(cfg, state, niche, fmt, slot, item, tag)
            else:
                niches.strike(cfg, state, niche, subs)
        if folder:
            made, failures = made + 1, 0
            niches.clear_strikes(state, niche)
        else:
            failures += 1
    write_sheet(cfg, state)
    return made


def fill(cfg: dict, subs: dict | None = None) -> int:
    compose.configure(cfg)
    return sum(fill_channel(view, (subs or {}).get(view["_channel"])) for view in channels.views(cfg))


# ------------------------------------------------------------------ manual upload helpers
def write_sheet(cfg: dict, state) -> Path:
    ready = Path(cfg["paths"]["ready"])
    rows = state.q("SELECT folder, publish_at, title, niche, format FROM videos WHERE status='ready' AND channel=? "
                   "ORDER BY publish_at", cfg["_channel"])
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    with open(ready / "UPLOAD_SHEET.csv", "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["publish_date", "publish_time", "folder", "title", "altered_content", "niche"])
        for folder, publish_at, title, niche, fmt in rows:
            local = datetime.strptime(publish_at, ISO).replace(tzinfo=timezone.utc).astimezone(tz)
            out.writerow([f"{local:%Y-%m-%d}", f"{local:%I:%M %p}", folder.split("/", 1)[1], title,
                          "Yes" if fmt == "reddit" else "No", niche.split("/", 1)[-1]])
    return ready / "UPLOAD_SHEET.csv"


def mark_uploaded(cfg: dict, through: str, channel: str | None = None) -> int:
    """Move every ready folder dated on/before `through` (YYYY-MM-DD) to uploaded/."""
    moved = 0
    for view in channels.views(cfg):
        if channel and view["_channel"] != channel:
            continue
        state = State(view["paths"]["work"])
        for (folder,) in state.q("SELECT folder FROM videos WHERE status='ready' AND channel=? "
                                 "AND substr(folder, length(channel) + 2, 10)<=?", view["_channel"], through):
            rel = folder.split("/", 1)[1]
            src = Path(view["paths"]["ready"]) / rel
            if src.exists():
                dest = Path(view["paths"]["uploaded"]) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), dest)
                if src.parent.exists() and not any(src.parent.iterdir()):
                    src.parent.rmdir()
            state.x("UPDATE videos SET status='uploaded' WHERE folder=?", folder)
            moved += 1
        write_sheet(view, state)
    return moved
