"""CLI: python -m clipbot {make,upload,auth,status,check}"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys

import requests

from . import config, pipeline, uploader
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="clipbot")
    parser.add_argument("command", choices=["make", "upload", "auth", "status", "check"])
    parser.add_argument("-c", "--config", help="path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = config.load(args.config)
    if args.command == "make":
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
