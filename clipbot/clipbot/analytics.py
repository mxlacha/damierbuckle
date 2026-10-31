"""Read-only channel stats via the YouTube Data API (API key, no OAuth, no uploading).

Matches your manually uploaded videos to the bot's records by title, so the niche
switcher knows how each one performed. Costs only a handful of quota units per run."""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _get(endpoint: str, key: str, **params) -> dict:
    r = requests.get(f"{API}/{endpoint}", params={**params, "key": key}, timeout=30)
    r.raise_for_status()
    return r.json()


def refresh(cfg: dict, state) -> int | None:
    """Update views/likes for matched videos. Returns subscriber count (or None)."""
    a = cfg["analytics"]
    if not a.get("api_key") or not a.get("channel_id"):
        log.info("analytics not configured; niche switching will only react to topics running dry")
        return None
    chan = _get("channels", a["api_key"], part="statistics,contentDetails", id=a["channel_id"])["items"][0]
    stats = chan["statistics"]
    subs = None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0))
    uploads = chan["contentDetails"]["relatedPlaylists"]["uploads"]

    found: dict[str, str] = {}
    token = None
    for _ in range(6):  # newest 300 uploads
        page = _get("playlistItems", a["api_key"], part="snippet", playlistId=uploads, maxResults=50,
                    **({"pageToken": token} if token else {}))
        for item in page.get("items", []):
            found[item["snippet"]["resourceId"]["videoId"]] = item["snippet"]["title"]
        token = page.get("nextPageToken")
        if not token:
            break

    by_title = {_norm(t): f for f, t in state.q("SELECT folder, title FROM videos WHERE yt_id IS NULL")}
    for vid, title in found.items():
        folder = by_title.get(_norm(title))
        if folder:
            state.x("UPDATE videos SET yt_id=?, status='uploaded' WHERE folder=?", vid, folder)
            src = Path(cfg["paths"]["ready"]) / folder
            if src.exists():
                dest = Path(cfg["paths"]["uploaded"]) / folder
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), dest)

    ids = [i for (i,) in state.q("SELECT yt_id FROM videos WHERE yt_id IS NOT NULL")]
    for i in range(0, len(ids), 50):
        for item in _get("videos", a["api_key"], part="statistics", id=",".join(ids[i:i + 50])).get("items", []):
            s = item["statistics"]
            state.x("UPDATE videos SET views=?, likes=?, checked=? WHERE yt_id=?",
                    int(s.get("viewCount", 0)), int(s.get("likeCount", 0)), time.time(), item["id"])
    log.info("analytics: %d uploads on channel, %d tracked, %s subs", len(found), len(ids), subs)
    return subs
