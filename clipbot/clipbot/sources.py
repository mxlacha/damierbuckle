"""Find new source videos: your local inbox, plus optional yt-dlp URLs."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


@dataclass
class Source:
    key: str                 # unique id used for de-duplication
    path: Path               # local video file
    title: str = ""
    credit: dict = field(default_factory=dict)  # uploader/url/license for attribution


def local_inbox(cfg: dict, state) -> list[Source]:
    inbox = Path(cfg["paths"]["inbox"])
    found = []
    for path in sorted(inbox.iterdir()):
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        key = f"local:{path.name}:{path.stat().st_size}"
        if not state.seen(key):
            found.append(Source(key=key, path=path, title=path.stem.replace("_", " ")))
    return found


def remote(cfg: dict, state) -> list[Source]:
    entries = cfg["sources"].get("urls") or []
    if not entries:
        return []
    try:
        import yt_dlp
        from yt_dlp.utils import match_filter_func
    except ImportError:
        log.warning("yt-dlp not installed; skipping remote sources")
        return []

    dl_dir = Path(cfg["paths"]["work"]) / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    limit = int(cfg["sources"]["max_downloads_per_run"])
    max_secs = int(cfg["sources"]["max_video_minutes"]) * 60
    height = int(cfg["sources"]["max_height"])
    found: list[Source] = []

    for entry in entries:
        if len(found) >= limit:
            break
        if isinstance(entry, str):
            entry = {"url": entry}
        rule = f"duration < {max_secs} & !is_live"
        if not entry.get("own"):
            # Only allow Creative Commons re-use unless you own the channel.
            rule += " & license ~= '(?i)creative commons'"

        opts = {
            "outtmpl": str(dl_dir / "%(id)s.%(ext)s"),
            "format": f"bv*[height<={height}]+ba/b[height<={height}]",
            "merge_output_format": "mp4",
            "match_filter": match_filter_func(rule),
            "download_archive": str(dl_dir / "archive.txt"),
            "max_downloads": limit - len(found),
            "playlistend": 30,
            "writeinfojson": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([entry["url"]])
        except yt_dlp.utils.MaxDownloadsReached:
            pass
        except Exception as exc:  # network hiccups shouldn't kill the run
            log.warning("yt-dlp failed for %s: %s", entry["url"], exc)

        for info_file in sorted(dl_dir.glob("*.info.json")):
            info = json.loads(info_file.read_text())
            key = f"yt:{info['id']}"
            video = next(
                (p for p in dl_dir.glob(f"{info['id']}.*") if p.suffix.lower() in VIDEO_EXTS), None
            )
            if video is None or state.seen(key) or any(s.key == key for s in found):
                continue
            found.append(
                Source(
                    key=key,
                    path=video,
                    title=info.get("title", ""),
                    credit={
                        "uploader": info.get("uploader") or info.get("channel"),
                        "url": info.get("webpage_url"),
                        "license": info.get("license") or ("own content" if entry.get("own") else ""),
                    },
                )
            )
    return found[:limit]


def collect(cfg: dict, state) -> list[Source]:
    sources: list[Source] = []
    if cfg["sources"].get("local_inbox", True):
        sources += local_inbox(cfg, state)
    sources += remote(cfg, state)
    return sources


def archive(cfg: dict, source: Source) -> None:
    """Move a processed inbox file out of the way so the inbox stays clean."""
    if source.key.startswith("local:"):
        done = Path(cfg["paths"]["work"]) / "processed"
        done.mkdir(exist_ok=True)
        shutil.move(str(source.path), done / source.path.name)
    else:
        source.path.unlink(missing_ok=True)
        source.path.with_suffix(".info.json").unlink(missing_ok=True)
