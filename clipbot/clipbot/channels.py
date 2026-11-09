"""Several YouTube accounts, each with its own niches, schedule, output folder and stats.

channels.yaml lives next to config.yaml and is safe to commit (no secrets): it's the
strategy file that gets tuned from the weekly reports."""

from __future__ import annotations

import copy
from pathlib import Path


def views(cfg: dict) -> list[dict]:
    """One config per channel, with that channel's niches, schedule and paths swapped in."""
    by_name = {n["name"]: n for n in cfg["niches"]}
    channels = cfg.get("channels") or [{
        "id": "main", "name": cfg["channel"]["name"], "niches": [n["name"] for n in cfg["niches"]],
    }]
    out = []
    for ch in channels:
        if ch.get("enabled", True) is False:
            continue
        view = copy.deepcopy(cfg)
        cid = ch["id"]
        view["_channel"] = cid
        view["channel"] = {**cfg["channel"], **{k: v for k, v in ch.items() if k in ("name", "hashtags")}}
        view["schedule"] = {**cfg["schedule"], **(ch.get("schedule") or {})}
        view["analytics"] = {**cfg["analytics"], "channel_id": ch.get("youtube_channel_id", "")}
        view["paths"] = {**cfg["paths"],
                         "ready": str(Path(cfg["paths"]["ready"]) / cid),
                         "uploaded": str(Path(cfg["paths"]["uploaded"]) / cid)}
        view["stories"] = {**cfg["stories"], "tweets_inbox": str(Path(cfg["stories"]["tweets_inbox"]) / cid)}
        niches = []
        for entry in ch.get("niches", []):
            base = by_name.get(entry) if isinstance(entry, str) else {**by_name.get(entry["name"], {}), **entry}
            if not base:
                raise SystemExit(f"channel {cid}: unknown niche {entry!r} (not in niches.yaml)")
            # niche names are namespaced per channel so rotation/stats never mix accounts
            niches.append({**base, "label": base["name"], "name": f"{cid}/{base['name']}"})
        view["niches"] = niches
        for key in ("ready", "uploaded"):
            Path(view["paths"][key]).mkdir(parents=True, exist_ok=True)
        Path(view["stories"]["tweets_inbox"]).mkdir(parents=True, exist_ok=True)
        out.append(view)
    return out
