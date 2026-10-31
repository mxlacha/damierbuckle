"""Pick the active niche and decide when to stick with it or move on.

Lifecycle: trial -> (winner | extended -> winner | retired) ; winner -> faded ; any -> dry
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)
LIVE = ("trial", "extended", "winner")


def _story_niches(cfg: dict) -> dict[str, dict]:
    return {n["name"]: n for n in cfg["niches"] if n.get("format") in ("story", "reddit")}


def _start(state, name: str, subs: int | None, note: str) -> None:
    state.x(
        "INSERT INTO niches (name, status, started, subs_start, strikes, note) VALUES (?, 'trial', ?, ?, 0, ?) "
        "ON CONFLICT(name) DO UPDATE SET status='trial', started=excluded.started, "
        "subs_start=excluded.subs_start, strikes=0, note=excluded.note",
        name, time.time(), subs, note,
    )
    log.info("niche -> %s (%s)", name, note)


def active(cfg: dict, state, subs: int | None = None) -> dict:
    niches = _story_niches(cfg)
    if not niches:
        raise SystemExit("no story/reddit niches defined in niches.yaml")
    row = state.q(f"SELECT name FROM niches WHERE status IN {LIVE} ORDER BY started DESC LIMIT 1")
    if row and row[0][0] in niches:
        return niches[row[0][0]]
    return rotate(cfg, state, subs, "first run")


def rotate(cfg: dict, state, subs: int | None, reason: str) -> dict:
    niches = _story_niches(cfg)
    tried = {name for (name,) in state.q("SELECT name FROM niches")}
    for name in niches:
        if name not in tried:
            _start(state, name, subs, reason)
            return niches[name]
    # every niche has had a go: re-open the best performer that hasn't run dry
    for (name,) in state.q("SELECT name FROM niches WHERE status NOT IN ('dry') AND status NOT IN "
                           f"{LIVE} ORDER BY best_median DESC"):
        if name in niches:
            _start(state, name, subs, f"{reason}; revisiting best previous niche")
            return niches[name]
    raise SystemExit("every niche has run dry — add more to niches.yaml")


def strike(cfg: dict, state, niche: dict, subs: int | None = None) -> dict:
    """Topic search came up empty. Too many in a row means the niche ran dry."""
    state.x("UPDATE niches SET strikes = strikes + 1 WHERE name=?", niche["name"])
    (strikes,) = state.q("SELECT strikes FROM niches WHERE name=?", niche["name"])[0]
    if strikes >= int(cfg["niche_rules"]["dry_strikes"]):
        state.x("UPDATE niches SET status='dry' WHERE name=?", niche["name"])
        return rotate(cfg, state, subs, f"{niche['name']} ran out of fresh topics")
    return niche


def clear_strikes(state, niche: dict) -> None:
    state.x("UPDATE niches SET strikes=0 WHERE name=?", niche["name"])


def evaluate(cfg: dict, state, subs: int | None) -> str:
    """Judge the active niche on videos old enough to have settled. Returns a status line."""
    r = cfg["niche_rules"]
    row = state.q(f"SELECT name, status, started, subs_start, best_median FROM niches "
                  f"WHERE status IN {LIVE} ORDER BY started DESC LIMIT 1")
    if not row:
        return "no active niche yet"
    name, status, started, subs_start, best = row[0]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=float(r["min_age_hours"]))).strftime("%Y-%m-%dT%H:%M:%SZ")
    since = datetime.fromtimestamp(started, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    views = [v for (v,) in state.q(
        "SELECT views FROM videos WHERE niche=? AND views IS NOT NULL AND publish_at<=? AND publish_at>=? "
        "ORDER BY publish_at", name, cutoff, since)]
    n, trial = len(views), int(r["trial_posts"])
    if not n:
        return f"{name}: {status}, no settled videos yet"
    med, top = statistics.median(views), max(views)
    gained = subs - subs_start if subs is not None and subs_start is not None else None
    recent = statistics.median(views[-21:])
    state.x("UPDATE niches SET best_median=MAX(best_median, ?) WHERE name=?", recent if n >= 21 else med, name)
    summary = f"{name}: {status}, {n} settled videos, median {med:.0f}, best {top}, subs gained {gained}"

    is_winner = (med >= r["winner_median_views"] and n >= 10) or top >= r["winner_max_views"] \
        or (gained is not None and gained >= r["winner_subs_gained"])
    if status == "winner":
        if n >= 21 and best and recent < float(r["fatigue_ratio"]) * best:
            state.x("UPDATE niches SET status='faded' WHERE name=?", name)
            new = rotate(cfg, state, subs, f"{name} faded (recent median {recent:.0f} vs best {best:.0f})")
            return f"{summary} -> faded, switching to {new['name']}"
        return f"{summary} -> sticking (winner)"
    if is_winner:
        state.x("UPDATE niches SET status='winner' WHERE name=?", name)
        return f"{summary} -> WINNER, sticking with it"
    if status == "trial" and n >= trial:
        if med < r["dud_median_views"] and top < r["dud_max_views"]:
            state.x("UPDATE niches SET status='retired' WHERE name=?", name)
            new = rotate(cfg, state, subs, f"{name} underperformed")
            return f"{summary} -> dud, switching to {new['name']}"
        state.x("UPDATE niches SET status='extended' WHERE name=?", name)
        return f"{summary} -> promising, extending trial"
    if status == "extended" and n >= 2 * trial:
        state.x("UPDATE niches SET status='retired' WHERE name=?", name)
        new = rotate(cfg, state, subs, f"{name} never broke out")
        return f"{summary} -> retired, switching to {new['name']}"
    return f"{summary} -> keep testing ({n}/{trial if status == 'trial' else 2 * trial})"
