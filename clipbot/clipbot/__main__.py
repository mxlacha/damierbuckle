"""CLI: python -m clipbot {stories,stats,uploaded,make,upload,auth,status,check}"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys

import requests

from . import analytics, channels, config, niches, pipeline, stories, tunnel, uploader
from .state import State


def check(cfg: dict) -> int:
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        print(f"{'✓' if found else '✗'} {tool}")
        ok &= bool(found)
    try:
        tags = requests.get(f"{cfg['ollama']['host']}/api/tags", timeout=5).json()
        models = [m["name"] for m in tags.get("models", [])]
        has = any(m.split(":")[0] == cfg["ollama"]["model"].split(":")[0] for m in models)
        print(f"{'✓' if has else '✗'} ollama model {cfg['ollama']['model']} (installed: {', '.join(models) or 'none'})")
        ok &= has
    except requests.RequestException as exc:
        print(f"✗ ollama not reachable at {cfg['ollama']['host']}: {exc}")
        ok = False
    try:
        import faster_whisper  # noqa: F401
        print("✓ faster-whisper")
    except ImportError:
        print("✗ faster-whisper (pip install -r requirements.txt)")
        ok = False
    from pathlib import Path
    kokoro = Path(cfg["voices"]["kokoro_model"]).exists()
    print(f"{'✓' if kokoro else '!'} Kokoro voice model {'found' if kokoro else 'missing — falls back to Piper'}")
    print(f"{'✓' if cfg['stories'].get('pexels_api_key') else '!'} Pexels key (stock b-roll)")
    print(f"{'✓' if cfg['analytics'].get('api_key') else '!'} analytics key (needed for performance-based niche switching)")
    tts = shutil.which("piper") or shutil.which("espeak-ng")
    print(f"{'✓' if tts else '!'} TTS: {tts or 'none — narration will be skipped'}")
    return 0 if ok else 1


def status(cfg: dict) -> int:
    ready = uploader.ready_clips(cfg)
    print(f"{len(ready)} clip(s) ready in {cfg['paths']['ready']}")
    for p in ready[:10]:
        print("  ", p.name)
    slots = uploader.next_slots(cfg, State(cfg["paths"]["work"]).taken_slots(), min(len(ready), 5) or 1)
    print("next publish slots (UTC):", ", ".join(slots))
    return 0


def _subs(view: dict, state) -> int | None:
    try:
        return analytics.refresh(view, state)
    except Exception as exc:  # stats are a nice-to-have; never block making videos
        print(f"! [{view['_channel']}] analytics refresh failed: {exc}")
        return None


def review(cfg: dict, only: str | None = None) -> dict:
    """Refresh stats, apply niche rules and write reports for every channel. Returns subs per channel."""
    state = State(cfg["paths"]["work"])
    subs = {}
    for view in channels.views(cfg):
        if only and view["_channel"] != only:
            continue
        subs[view["_channel"]] = _subs(view, state)
        line = niches.evaluate(view, state, subs[view["_channel"]])
        path = analytics.report(view, state, line)
        print(f"[{view['_channel']}] {line}\n    report: {path}")
    return subs


def main() -> int:
    parser = argparse.ArgumentParser(prog="clipbot")
    parser.add_argument("command", choices=["stories", "stats", "uploaded", "backgrounds", "auth-analytics",
                                            "make", "upload", "auth", "status", "check"])
    parser.add_argument("arg", nargs="?", help="uploaded: last scheduled date (YYYY-MM-DD); auth-analytics: channel id")
    parser.add_argument("--channel", help="limit stats/uploaded to one channel id")
    parser.add_argument("-c", "--config", help="path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = config.load(args.config)
    if args.command == "stories":
        made = stories.fill(cfg, review(cfg))
        print(f"{made} new video(s); upload lists: {cfg['paths']['ready']}/<channel>/UPLOAD_SHEET.csv")
    elif args.command == "stats":
        review(cfg, args.channel)
    elif args.command == "uploaded":
        if not args.arg:
            parser.error("usage: clipbot uploaded YYYY-MM-DD [--channel id]")
        print(f"moved {stories.mark_uploaded(cfg, args.arg, args.channel)} video(s) to uploaded/")
    elif args.command == "backgrounds":
        from pathlib import Path
        pool = tunnel.ensure_pool(Path(cfg["stories"]["backgrounds"]) / "generated",
                                  int(cfg["stories"].get("generated_backgrounds", 8)))
        print(f"{len(pool)} corridor backgrounds ready")
    elif args.command == "auth-analytics":
        view = next((v for v in channels.views(cfg) if v["_channel"] == args.arg), None)
        if not view:
            parser.error("usage: clipbot auth-analytics <channel id from channels.yaml>")
        print("saved", analytics.authorize(view))
    elif args.command == "make":
        pipeline.run(cfg)
    elif args.command == "upload":
        uploader.upload(cfg)
    elif args.command == "auth":
        uploader.credentials(cfg, interactive=True)
        print("YouTube token saved to", cfg["youtube"]["token"])
    elif args.command == "status":
        return status(cfg)
    elif args.command == "check":
        return check(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
