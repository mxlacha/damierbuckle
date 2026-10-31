"""Fact sources for story scripts: Wikipedia articles and RSS news items."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger(__name__)
UA = {"User-Agent": "clipbot/1.0 (personal Raspberry Pi project)"}
WIKI = "https://en.wikipedia.org/w/api.php"


def wikipedia(topic: str, max_chars: int = 5000) -> dict | None:
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
        params={"action": "query", "format": "json", "prop": "extracts|info", "explaintext": 1,
                "inprop": "url", "pageids": page_id},
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    page = r.json()["query"]["pages"][str(page_id)]
    text = page.get("extract", "")
    # drop reference-ish tail sections
    text = re.split(r"\n== (See also|References|Notes|External links|Further reading) ==", text)[0]
    if len(text) < 400:
        return None
    return {"key": f"wiki:{page_id}", "title": page["title"], "url": page.get("fullurl", ""), "text": text[:max_chars]}


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
