"""Offline text-to-speech with Piper (fast enough on a Pi 5)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def speak(cfg: dict, text: str, out_wav: Path) -> Path | None:
    """Render `text` to a wav file. Returns None if TTS isn't available."""
    if not text or not cfg["audio"].get("narration"):
        return None
    model = Path(cfg["audio"]["piper_model"])
    piper = shutil.which("piper")
    if piper and model.exists():
        cmd = [piper, "--model", str(model), "--output_file", str(out_wav)]
    elif shutil.which("espeak-ng"):
        log.warning("piper/voice missing, falling back to espeak-ng")
        cmd = ["espeak-ng", "-s", "165", "-w", str(out_wav), "--stdin"]
    else:
        log.warning("no TTS engine found; skipping narration")
        return None
    subprocess.run(cmd, input=text.encode(), check=True, capture_output=True)
    return out_wav if out_wav.exists() and out_wav.stat().st_size > 0 else None
