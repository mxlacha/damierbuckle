"""Fuzzy team-name matching between Kalshi labels and sportsbook names."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_ALIASES = {
    "la": "los angeles",
    "ny": "new york",
    "st": "saint",
    "st.": "saint",
    "utd": "united",
    "tie": "draw",
}
_STOP = {"the", "fc", "cf", "afc"}


def normalize(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("&", " and "))
    toks = [_ALIASES.get(t, t) for t in s.split() if t not in _STOP]
    return " ".join(" ".join(toks).split())


def name_score(a: str, b: str) -> float:
    """1.0 when one name's tokens are all contained in the other
    ("Kansas City" vs "Kansas City Chiefs"), otherwise a string ratio."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta <= tb or tb <= ta:
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


def map_names(kalshi_names: list[str], book_names: list[str], threshold: float = 0.85):
    """One-to-one map kalshi name -> book name, or None if any name is
    unmatched or ambiguous. Also returns the summed score."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    total = 0.0
    for k in kalshi_names:
        scored = sorted(((name_score(k, b), b) for b in book_names), reverse=True)
        if not scored or scored[0][0] < threshold:
            return None, 0.0
        if len(scored) > 1 and scored[1][0] >= threshold and scored[0][0] - scored[1][0] < 0.05:
            return None, 0.0  # two candidates equally good: refuse to guess
        best = scored[0][1]
        if best in used:
            return None, 0.0
        used.add(best)
        mapping[k] = best
        total += scored[0][0]
    return mapping, total
