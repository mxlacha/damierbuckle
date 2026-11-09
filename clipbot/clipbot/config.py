"""Load config.yaml, merge with defaults, and expand paths."""

from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent.parent
EXAMPLE = HERE / "config.example.yaml"


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _expand(value):
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, str) and value.startswith("~"):
        return os.path.expanduser(value)
    return value


def load(path: str | os.PathLike | None = None) -> dict:
    defaults = yaml.safe_load(EXAMPLE.read_text())
    path = Path(path or os.environ.get("CLIPBOT_CONFIG", HERE / "config.yaml"))
    user = yaml.safe_load(path.read_text()) if path.exists() else {}
    cfg = _expand(_merge(defaults, user or {}))

    niches_path = Path(cfg["stories"]["niches_file"])
    if not niches_path.is_absolute():
        niches_path = path.parent / niches_path
    if not niches_path.exists():
        niches_path = HERE / "niches.yaml"
    cfg["niches"] = _expand(yaml.safe_load(niches_path.read_text()) or {}).get("niches", [])

    channels_path = path.parent / "channels.yaml"
    cfg["channels"] = (_expand(yaml.safe_load(channels_path.read_text()) or {}).get("channels")
                       if channels_path.exists() else None)

    for key in ("inbox", "work", "ready", "uploaded"):
        Path(cfg["paths"][key]).mkdir(parents=True, exist_ok=True)
    return cfg
