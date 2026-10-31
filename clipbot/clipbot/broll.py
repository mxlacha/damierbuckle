"""Find background visuals for each script line.

Order is per niche (e.g. [local, commons, pexels]):
  local       — your own/licensed clips in stories.library/<tag>/ (folder name = tag, e.g. "f-15", "kobe")
  backgrounds — any file in stories.backgrounds/ (for Reddit-style stories)
  commons     — Wikimedia Commons photos that are public domain or CC (credited in the description)
  pexels      — Pexels stock video (free license, needs stories.pexels_api_key)
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from .research import UA

log = logging.getLogger(__name__)
VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
FREE_LICENSES = ("public domain", "pd", "cc0", "cc by")


@dataclass
class Asset:
    path: Path
    kind: str                # "video" | "image"
    credit: str = ""         # attribution line, empty if none required


def _tokens(text: str) -> set[str]:
    return {re.sub(r"[^a-z0-9]", "", t) for t in re.split(r"[\s_/]+", text.lower())} - {""}


def _media(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [p for p in folder.rglob("*") if p.suffix.lower() in VIDEO | IMAGE]


def _asset(path: Path, credit: str = "") -> Asset:
    return Asset(path, "video" if path.suffix.lower() in VIDEO else "image", credit)


def local(cfg: dict, query: str, used: set) -> Asset | None:
    root = Path(cfg["stories"]["library"])
    if not root.is_dir():
        return None
    want = _tokens(query)
    best, best_score = [], 0
    for tag_dir in (d for d in root.iterdir() if d.is_dir()):
        score = len(want & _tokens(tag_dir.name))
        if score > best_score:
            best, best_score = _media(tag_dir), score
        elif score == best_score and score:
            best += _media(tag_dir)
    fresh = [p for p in best if str(p) not in used]
    return _asset(random.choice(fresh or best)) if best else None


def backgrounds(cfg: dict, query: str, used: set) -> Asset | None:
    files = [p for p in _media(Path(cfg["stories"]["backgrounds"])) if p.suffix.lower() in VIDEO]
    fresh = [p for p in files if str(p) not in used]
    return _asset(random.choice(fresh or files)) if files else None


def _download(url: str, cache: Path, suffix: str, headers: dict | None = None) -> Path:
    path = cache / (hashlib.sha1(url.encode()).hexdigest()[:16] + suffix)
    if not path.exists():
        with requests.get(url, headers=headers or UA, timeout=60, stream=True) as r:
            r.raise_for_status()
            tmp = path.with_suffix(".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
            tmp.rename(path)
    return path


def commons(cfg: dict, query: str, used: set, cache: Path) -> Asset | None:
    if not cfg["stories"].get("commons", True):
        return None
    r = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 15,
                "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 1600},
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    pages = list(r.json().get("query", {}).get("pages", {}).values())
    random.shuffle(pages)
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        if not license_name.lower().startswith(FREE_LICENSES) or info.get("width", 0) < 800:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url or url in used:
            continue
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "unknown"
        path = _download(url, cache, Path(url).suffix.split("?")[0] or ".jpg")
        used.add(url)
        credit = "" if "public domain" in license_name.lower() or license_name.lower().startswith("cc0") \
            else f"{page.get('title', '').removeprefix('File:')} by {artist[:60]}, {license_name}, via Wikimedia Commons"
        return Asset(path, "image", credit)
    return None


def commons_file(filename: str, cache: Path) -> Asset | None:
    """A specific Commons file (e.g. a Wikipedia lead image), only if freely licensed."""
    if not filename:
        return None
    r = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={"action": "query", "format": "json", "titles": f"File:{filename}",
                "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1600},
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    for page in r.json().get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]  # missing = local enwiki file, usually non-free: skip
        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        url = info.get("thumburl") or info.get("url")
        if url and license_name.lower().startswith(FREE_LICENSES):
            artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "unknown"
            credit = "" if license_name.lower().startswith(("public domain", "pd", "cc0")) \
                else f"{filename} by {artist[:60]}, {license_name}, via Wikimedia Commons"
            return Asset(_download(url, cache, Path(url).suffix.split("?")[0] or ".jpg"), "image", credit)
    return None


def nasa(cfg: dict, query: str, used: set, cache: Path) -> Asset | None:
    from .research import nasa_clip_url, nasa_videos

    for item in nasa_videos(query, 10):
        if item["key"] in used:
            continue
        url = nasa_clip_url(item["assets"])
        if url:
            used.add(item["key"])
            return Asset(_download(url, cache, ".mp4"), "video")
    return None


def pexels(cfg: dict, query: str, used: set, cache: Path) -> Asset | None:
    key = cfg["stories"].get("pexels_api_key")
    if not key:
        return None
    r = requests.get(
        "https://api.pexels.com/videos/search",
        params={"query": query, "orientation": "portrait", "per_page": 10, "size": "medium"},
        headers={"Authorization": key, **UA}, timeout=20,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    random.shuffle(videos)
    for video in videos:
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and 720 <= (f.get("height") or 0) <= 2160]
        if not files or video.get("url") in used:
            continue
        best = min(files, key=lambda f: abs((f.get("height") or 0) - 1920))
        used.add(video.get("url"))
        return Asset(_download(best["link"], cache, ".mp4"), "video")
    return None


def find(cfg: dict, niche: dict, query: str, used: set) -> Asset | None:
    cache = Path(cfg["paths"]["work"]) / "broll_cache"
    cache.mkdir(parents=True, exist_ok=True)
    words = query.split()
    queries = list(dict.fromkeys([query, " ".join(words[:2]), niche.get("subject", "")]))
    for q in (q for q in queries if q):
        for source in niche.get("broll", ["local", "commons", "pexels"]):
            try:
                if source == "local":
                    asset = local(cfg, q, used)
                elif source == "backgrounds":
                    asset = backgrounds(cfg, q, used)
                elif source == "commons":
                    asset = commons(cfg, q, used, cache)
                elif source == "pexels":
                    asset = pexels(cfg, q, used, cache)
                elif source == "nasa":
                    asset = nasa(cfg, q, used, cache)
                else:
                    continue
            except (requests.RequestException, OSError, ValueError) as exc:
                log.warning("%s lookup for %r failed: %s", source, q, exc)
                continue
            if asset:
                used.add(str(asset.path))
                return asset
    return None
