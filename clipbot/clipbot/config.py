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
    if isinstance(value, str) and value.startswith("~"):
        return os.path.expanduser(value)
    return value


def load(path: str | os.PathLike | None = None) -> dict:
    defaults = yaml.safe_load(EXAMPLE.read_text())
    path = Path(path or os.environ.get("CLIPBOT_CONFIG", HERE / "config.yaml"))
    user = yaml.safe_load(path.read_text()) if path.exists() else {}
    cfg = _merge(defaults, user or {})

    for section in ("paths", "audio", "youtube"):
        cfg[section] = {k: _expand(v) for k, v in cfg[section].items()}
    for key in ("inbox", "work", "ready", "uploaded"):
        Path(cfg["paths"][key]).mkdir(parents=True, exist_ok=True)
    return cfg
