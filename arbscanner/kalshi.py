"""Kalshi public market-data client (no API key needed for reading markets)."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date

import requests

from .models import KalshiEvent, KalshiOutcome

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_MONTHS = {m: i for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), start=1)}
_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")


def _price(market: dict, field: str) -> float | None:
    """Kalshi has served prices as integer cents (`yes_ask`) and as dollar
    strings (`yes_ask_dollars`); accept either. Returns dollars or None."""
    raw = market.get(f"{field}_dollars")
    if raw in (None, ""):
        raw = market.get(field)
        if raw in (None, ""):
            return None
        val = float(raw) / 100.0
    else:
        val = float(raw)
    return val if 0.0 < val < 1.0 else None


def parse_event_date(event_ticker: str) -> date | None:
    m = _DATE_RE.search(event_ticker)
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        return date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))
    except ValueError:
        return None


def group_markets(markets: list[dict], series_ticker: str) -> list[KalshiEvent]:
    by_event: dict[str, list[dict]] = defaultdict(list)
    for m in markets:
        if m.get("status") not in (None, "open", "active"):
            continue
        by_event[m.get("event_ticker", "")].append(m)
    events = []
    for et, ms in by_event.items():
        if not et:
            continue
        outcomes = []
        for m in ms:
            name = (m.get("yes_sub_title") or "").strip()
            if not name:
                continue
            outcomes.append(KalshiOutcome(m["ticker"], name, _price(m, "yes_ask")))
        if len(outcomes) < 2:
            continue
        title = ms[0].get("title", et)
        events.append(KalshiEvent(et, series_ticker, title, parse_event_date(et), tuple(outcomes)))
    return events


class KalshiClient:
    def __init__(self, base_url: str = BASE_URL, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()
        self.http.headers["User-Agent"] = "arbscanner/0.1"

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(4):
            r = self.http.get(f"{self.base_url}{path}", params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2 * (attempt + 1))))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Kalshi rate limit: gave up after retries")

    def open_markets(self, series_ticker: str) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            params = {"series_ticker": series_ticker, "status": "open", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/markets", params)
            out.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor:
                return out

    def events(self, series_ticker: str) -> list[KalshiEvent]:
        return group_markets(self.open_markets(series_ticker), series_ticker)
