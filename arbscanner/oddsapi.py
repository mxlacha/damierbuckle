"""Sportsbook odds via The Odds API (https://the-odds-api.com).

Scraping individual sportsbook sites breaks their terms of service, gets IPs
banned and is brittle, so this uses a licensed aggregator that exposes
DraftKings, FanDuel, BetMGM, Caesars, etc. in one request.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from .models import OddsEvent

BASE_URL = "https://api.the-odds-api.com/v4"


class OddsApiError(RuntimeError):
    pass


def parse_events(payload: list[dict]) -> list[OddsEvent]:
    events = []
    for e in payload:
        books: dict[str, dict[str, float]] = {}
        for b in e.get("bookmakers", []):
            for mk in b.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                prices = {o["name"]: float(o["price"]) for o in mk.get("outcomes", [])
                          if o.get("price") and float(o["price"]) > 1.0}
                if len(prices) >= 2:
                    books[b.get("title") or b["key"]] = prices
        commence = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        events.append(OddsEvent(e["id"], e["sport_key"], commence.astimezone(timezone.utc),
                                e["home_team"], e["away_team"], books))
    return events


class OddsApiClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL,
                 session: requests.Session | None = None):
        if not api_key:
            raise OddsApiError("Set ODDS_API_KEY (free key at https://the-odds-api.com)")
        self.key = api_key
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()
        self.remaining: str | None = None

    def odds(self, sport_key: str, regions: str = "us", bookmakers: str | None = None
             ) -> list[OddsEvent]:
        params = {"apiKey": self.key, "markets": "h2h", "oddsFormat": "decimal",
                  "dateFormat": "iso"}
        if bookmakers:
            params["bookmakers"] = bookmakers  # overrides regions
        else:
            params["regions"] = regions
        r = self.http.get(f"{self.base_url}/sports/{sport_key}/odds", params=params, timeout=20)
        self.remaining = r.headers.get("x-requests-remaining", self.remaining)
        if r.status_code == 401:
            raise OddsApiError("Odds API rejected the key (401)")
        if r.status_code == 429:
            raise OddsApiError("Odds API rate/quota limit hit (429)")
        if r.status_code == 404:
            return []  # sport out of season / unknown key
        r.raise_for_status()
        return parse_events(r.json())
