"""Read-only channel stats, and the weekly report the strategy review works from.

Two levels, both read-only (nothing here can upload or change anything on YouTube):
  1. Data API key   — public views/likes, matched to the bot's videos by title. Enough for niche switching.
  2. Analytics OAuth (`clipbot auth-analytics <channel>`) — retention (avg % viewed, avg view duration),
     subscribers gained per video, and estimated revenue → RPM once the channel is monetized.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import statistics
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

from .config import HERE

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly",
          "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"]
REPORTS = HERE / "reports"


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _get(endpoint: str, key: str, **params) -> dict:
    r = requests.get(f"{API}/{endpoint}", params={**params, "key": key}, timeout=30)
    r.raise_for_status()
    return r.json()


def _token_path(cfg: dict) -> Path:
    return Path(cfg["paths"]["work"]).parent / "tokens" / f"{cfg['_channel']}.json"


def authorize(cfg: dict) -> Path:
    """One-time per channel. Sign in with the Google account that owns THAT channel."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(cfg["youtube"]["client_secrets"], SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=False)
    path = _token_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json())
    return path


def refresh(cfg: dict, state) -> int | None:
    """Update views/likes for this channel's matched videos. Returns subscriber count (or None)."""
    a, cid = cfg["analytics"], cfg["_channel"]
    if not a.get("api_key") or not a.get("channel_id"):
        log.info("[%s] analytics not configured; niche switching only reacts to topics running dry", cid)
        return None
    chan = _get("channels", a["api_key"], part="statistics,contentDetails", id=a["channel_id"])["items"][0]
    stats = chan["statistics"]
    subs = None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0))
    uploads = chan["contentDetails"]["relatedPlaylists"]["uploads"]

    found: dict[str, str] = {}
    token = None
    for _ in range(6):  # newest 300 uploads
        try:
            page = _get("playlistItems", a["api_key"], part="snippet", playlistId=uploads, maxResults=50,
                        **({"pageToken": token} if token else {}))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                break  # brand-new channel: YouTube creates the uploads playlist with the first video
            raise
        for item in page.get("items", []):
            found[item["snippet"]["resourceId"]["videoId"]] = item["snippet"]["title"]
        token = page.get("nextPageToken")
        if not token:
            break

    by_title = {_norm(t): f for f, t in state.q("SELECT folder, title FROM videos WHERE yt_id IS NULL AND channel=?", cid)}
    for vid, title in found.items():
        folder = by_title.get(_norm(title))
        if folder:
            state.x("UPDATE videos SET yt_id=?, status='uploaded' WHERE folder=?", vid, folder)
            rel = folder.split("/", 1)[1]
            src = Path(cfg["paths"]["ready"]) / rel
            if src.exists():
                dest = Path(cfg["paths"]["uploaded"]) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), dest)

    ids = [i for (i,) in state.q("SELECT yt_id FROM videos WHERE yt_id IS NOT NULL AND channel=?", cid)]
    for i in range(0, len(ids), 50):
        for item in _get("videos", a["api_key"], part="statistics", id=",".join(ids[i:i + 50])).get("items", []):
            s = item["statistics"]
            state.x("UPDATE videos SET views=?, likes=?, checked=? WHERE yt_id=?",
                    int(s.get("viewCount", 0)), int(s.get("likeCount", 0)), time.time(), item["id"])
    _deep(cfg, state)
    log.info("[%s] analytics: %d uploads, %d tracked, %s subs", cid, len(found), len(ids), subs)
    return subs


def _deep(cfg: dict, state) -> None:
    """Retention, subs gained and revenue per video via the Analytics API (if authorized)."""
    path = _token_path(cfg)
    if not path.exists():
        return
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json())
    session = AuthorizedSession(creds)
    params = {"ids": "channel==MINE", "startDate": (date.today() - timedelta(days=120)).isoformat(),
              "endDate": date.today().isoformat(), "dimensions": "video", "sort": "-views", "maxResults": 200}
    metrics = "views,averageViewDuration,averageViewPercentage,subscribersGained"
    r = session.get(ANALYTICS, params={**params, "metrics": metrics + ",estimatedRevenue"}, timeout=60)
    if r.status_code == 403:  # not monetized / monetary scope refused: retention only
        r = session.get(ANALYTICS, params={**params, "metrics": metrics}, timeout=60)
    if not r.ok:
        log.warning("[%s] analytics API %s: %s", cfg["_channel"], r.status_code, r.text[:200])
        return
    body = r.json()
    cols = [h["name"] for h in body.get("columnHeaders", [])]
    for row in body.get("rows", []):
        rec = dict(zip(cols, row))
        state.x("UPDATE videos SET retention=?, avg_dur=?, subs=?, revenue=? WHERE yt_id=?",
                rec.get("averageViewPercentage"), rec.get("averageViewDuration"), rec.get("subscribersGained"),
                rec.get("estimatedRevenue"), rec["video"])


# ------------------------------------------------------------------ weekly report
def _agg(rows: list[dict], key: str) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[r.get(key)].append(r)
    out = []
    for value, items in groups.items():
        views = [i["views"] for i in items]
        ret = [i["retention"] for i in items if i.get("retention") is not None]
        out.append({key: value, "videos": len(items), "median_views": statistics.median(views),
                    "median_retention": round(statistics.median(ret), 1) if ret else None})
    return sorted(out, key=lambda x: -x["median_views"])


def report(cfg: dict, state, niche_line: str) -> Path:
    """reports/<channel>.json + .md: what's working, broken down by every lever the bot controls."""
    cid = cfg["_channel"]
    rows = []
    for folder, niche, fmt, title, views, likes, ret, avg, subs, rev, publish_at, meta in state.q(
            "SELECT folder, niche, format, title, views, likes, retention, avg_dur, subs, revenue, publish_at, meta "
            "FROM videos WHERE channel=? AND views IS NOT NULL ORDER BY publish_at DESC LIMIT 300", cid):
        style = json.loads(meta or "{}")
        dur = style.get("duration") or 0
        rows.append({"title": title, "niche": niche.split("/", 1)[-1], "format": fmt, "published": publish_at,
                     "views": views, "likes": likes, "retention": ret, "avg_view_s": avg, "subs": subs,
                     "rpm": round(rev / views * 1000, 3) if rev and views else None,
                     "layout": style.get("layout"), "captions": style.get("captions"), "voice": style.get("voice"),
                     "hour": style.get("hour"), "length": f"{int(dur // 15) * 15}-{int(dur // 15) * 15 + 15}s",
                     "hook": style.get("hook")})
    niches = [dict(zip(("niche", "status", "strikes", "best_median"), r)) for r in
              state.q("SELECT name, status, strikes, best_median FROM niches WHERE name LIKE ?", f"{cid}/%")]
    data = {"channel": cid, "generated": time.strftime("%Y-%m-%d %H:%M"), "decision": niche_line, "niches": niches,
            "by": {k: _agg(rows, k) for k in ("niche", "format", "captions", "voice", "hour", "length")} if rows else {},
            "top": sorted(rows, key=lambda r: -r["views"])[:10], "bottom": sorted(rows, key=lambda r: r["views"])[:5],
            "videos": rows}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{cid}.json").write_text(json.dumps(data, indent=1, default=str))

    md = [f"# {cid} — {data['generated']}", "", f"**Niche decision:** {niche_line}", "",
          "| niche | status | strikes | best median |", "|---|---|---|---|"]
    md += [f"| {n['niche'].split('/', 1)[-1]} | {n['status']} | {n['strikes']} | {n['best_median']:.0f} |" for n in niches]
    for key, groups in data["by"].items():
        md += ["", f"## By {key}", "", f"| {key} | videos | median views | median retention % |", "|---|---|---|---|"]
        md += [f"| {g[key]} | {g['videos']} | {g['median_views']:,.0f} | {g['median_retention']} |" for g in groups]
    md += ["", "## Top 10", "", "| views | ret % | rpm | format | hook |", "|---|---|---|---|---|"]
    md += [f"| {r['views']:,} | {r['retention']} | {r['rpm']} | {r['format']} | {(r['hook'] or '')[:70]} |"
           for r in data["top"]]
    (REPORTS / f"{cid}.md").write_text("\n".join(md) + "\n")
    return REPORTS / f"{cid}.md"
