"""Fact sources for story scripts: Wikipedia articles and RSS news items."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger(__name__)
UA = {"User-Agent": "clipbot/1.0 (personal Raspberry Pi project)"}
WIKI = "https://en.wikipedia.org/w/api.php"


def wikipedia(topic: str, max_chars: int = 3000) -> dict | None:
    """Best-matching article for `topic`: {key, title, url, text}."""
    r = requests.get(
        WIKI,
        params={"action": "query", "format": "json", "list": "search", "srsearch": topic, "srlimit": 1},
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    if not hits:
        return None
    page_id = hits[0]["pageid"]
    r = requests.get(
        WIKI,
        params={"action": "query", "format": "json", "prop": "extracts|info|pageimages", "explaintext": 1,
                "inprop": "url", "piprop": "name", "pageids": page_id},
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    page = r.json()["query"]["pages"][str(page_id)]
    text = page.get("extract", "")
    # drop reference-ish tail sections
    text = re.split(r"\n== (See also|References|Notes|External links|Further reading) ==", text)[0]
    if len(text) < 400:
        return None
    return {"key": f"wiki:{page_id}", "title": page["title"], "url": page.get("fullurl", ""),
            "text": text[:max_chars], "image": page.get("pageimage", "")}


def rss(urls: list[str]) -> list[dict]:
    items = []
    for url in urls:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except (requests.RequestException, ET.ParseError) as exc:
            log.warning("rss %s failed: %s", url, exc)
            continue
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or "").strip()
            desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
            if link and title:
                items.append({"key": f"rss:{link}", "title": title, "url": link, "text": f"{title}\n{desc.strip()}"})
    return items


def nasa_videos(query: str, limit: int = 20) -> list[dict]:
    """NASA Image and Video Library (public domain). Returns clips with their official description."""
    r = requests.get("https://images-api.nasa.gov/search",
                     params={"q": query, "media_type": "video", "page_size": limit}, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for item in r.json().get("collection", {}).get("items", []):
        data = (item.get("data") or [{}])[0]
        desc = re.sub(r"<[^>]+>", " ", data.get("description", "")).strip()
        if data.get("nasa_id") and item.get("href") and len(desc) > 80:
            out.append({"key": f"nasa:{data['nasa_id']}", "title": data.get("title", ""), "text": desc[:3000],
                        "assets": item["href"], "url": f"https://images.nasa.gov/details/{data['nasa_id']}"})
    return out


def nasa_clip_url(assets_href: str) -> str | None:
    r = requests.get(assets_href.replace("http://", "https://"), headers=UA, timeout=30)
    r.raise_for_status()
    files = [u.replace("http://", "https://") for u in r.json() if isinstance(u, str) and u.endswith(".mp4")]
    for pref in ("~mobile.mp4", "~medium.mp4", "~small.mp4", "~orig.mp4"):
        for u in files:
            if u.endswith(pref):
                return u
    return files[0] if files else None


BSKY = "https://public.api.bsky.app/xrpc"
WHATS_HOT = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"


def bluesky_posts(feeds: list[str] | None = None, min_likes: int = 500) -> list[dict]:
    """Popular public text posts from Bluesky feeds (open API, no key)."""
    out = []
    for feed in feeds or [WHATS_HOT]:
        try:
            r = requests.get(f"{BSKY}/app.bsky.feed.getFeed", params={"feed": feed, "limit": 100},
                             headers=UA, timeout=30)
            r.raise_for_status()
        except requests.RequestException as exc:
            log.warning("bluesky feed failed: %s", exc)
            continue
        for entry in r.json().get("feed", []):
            post = entry.get("post", {})
            rec = post.get("record", {})
            text = (rec.get("text") or "").strip()
            if rec.get("reply") or post.get("likeCount", 0) < min_likes or not 60 <= len(text) <= 500:
                continue
            if rec.get("langs") and "en" not in rec["langs"]:
                continue
            author = post.get("author", {})
            rkey = post.get("uri", "").rsplit("/", 1)[-1]
            out.append({"key": f"bsky:{post.get('uri')}", "text": text, "handle": "@" + author.get("handle", ""),
                        "name": author.get("displayName") or author.get("handle", ""),
                        "avatar": author.get("avatar", ""), "likes": post.get("likeCount", 0),
                        "url": f"https://bsky.app/profile/{author.get('handle')}/post/{rkey}"})
    return sorted(out, key=lambda p: -p["likes"])
