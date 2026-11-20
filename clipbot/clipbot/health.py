"""One-screen status for CreamPi, and push alerts to your phone via ntfy (https://ntfy.sh).

Read-only: it only looks at systemd, the database, git and the Pi's sensors."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import channels
from .config import HERE
from .state import State

log = logging.getLogger(__name__)
ISO = "%Y-%m-%dT%H:%M:%SZ"


def _sh(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect(cfg: dict) -> tuple[list[str], list[str]]:
    """(lines to show, problems worth an alert)."""
    lines, problems = [], []

    # the nightly job
    show = dict(l.split("=", 1) for l in _sh("systemctl", "show", "clipbot-stories", "-p", "ActiveState",
                                               "-p", "Result", "-p", "ExecMainExitTimestamp").splitlines() if "=" in l)
    nxt = _sh("systemctl", "list-timers", "clipbot-stories.timer", "--no-legend", "--no-pager")
    lines.append(f"nightly run: {show.get('ActiveState', '?')}, last result {show.get('Result', '?')}"
                 f" ({show.get('ExecMainExitTimestamp') or 'never'})")
    lines.append(f"next run:    {' '.join(nxt.split()[:3]) if nxt else 'timer not found'}")
    if show.get("Result") not in (None, "success"):
        problems.append(f"last nightly run ended with '{show.get('Result')}'")

    # per-channel queue
    state = State(cfg["paths"]["work"])
    now = datetime.now(timezone.utc)
    for view in channels.views(cfg):
        cid = view["_channel"]
        ready, last = state.q("SELECT COUNT(*), MAX(publish_at) FROM videos WHERE channel=? AND status='ready'", cid)[0]
        niche = state.q("SELECT name, status FROM niches WHERE name LIKE ? AND status IN ('trial','extended','winner') "
                        "ORDER BY started DESC LIMIT 1", f"{cid}/%")
        days = (datetime.strptime(last, ISO).replace(tzinfo=timezone.utc) - now).days if last else -1
        niche_txt = f"{niche[0][0].split('/', 1)[1]} ({niche[0][1]})" if niche else "none active"
        lines.append(f"[{cid}] {ready} ready to upload, scheduled {max(days, 0)} day(s) ahead, niche {niche_txt}")
        if days < 1:
            problems.append(f"{cid}: less than a day of videos ready")
        dry = [n.split("/", 1)[1] for (n,) in state.q("SELECT name FROM niches WHERE name LIKE ? AND status='dry'",
                                                        f"{cid}/%")]
        if dry:
            lines.append(f"[{cid}] marked dry: {', '.join(dry)}  (clear with: clipbot reset-niches --channel {cid})")

    # hardware
    throttled = _sh("vcgencmd", "get_throttled")
    temp = _sh("vcgencmd", "measure_temp")
    if throttled:
        lines.append(f"power/heat:  {throttled}  {temp}")
        if not throttled.endswith("=0x0"):
            problems.append(f"Pi reports power/heat trouble ({throttled})")
    disk = shutil.disk_usage(Path(cfg["paths"]["work"]))
    free_gb = disk.free / 1e9
    lines.append(f"disk free:   {free_gb:.1f} GB")
    if free_gb < 5:
        problems.append(f"only {free_gb:.1f} GB disk left")

    # code + strategy sync (read-only)
    branch = _sh("git", "-C", str(HERE), "status", "-sb").splitlines()
    if branch:
        lines.append(f"git:         {branch[0].lstrip('# ')}")
        if "behind" in branch[0]:
            problems.append("CreamPi's code is behind GitHub (git pull can't fast-forward)")
    lines.append(f"claude CLI:  {'found' if shutil.which('claude') or Path('~/.local/bin/claude').expanduser().exists() else 'missing'}")
    return lines, problems


def notify(cfg: dict, title: str, message: str, priority: str = "default", tags: str = "") -> bool:
    """Push to the ntfy topic in alerts.ntfy_topic. Silently does nothing if no topic is set."""
    alerts = cfg.get("alerts") or {}
    topic = alerts.get("ntfy_topic")
    if not topic:
        return False
    try:
        r = requests.post(f"{alerts.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{topic}",
                          data=message.encode()[:3900],
                          headers={"Title": title, "Priority": priority, "Tags": tags}, timeout=15)
        return r.ok
    except requests.RequestException as exc:
        log.warning("ntfy alert failed: %s", exc)
        return False


def failure_alert(cfg: dict, unit: str) -> None:
    tail = _sh("journalctl", "-u", unit, "-n", "15", "--no-pager", "-o", "cat")
    notify(cfg, f"CreamPi: {unit} failed", tail or "(no log lines)", priority="high", tags="warning")


def daily_summary(cfg: dict, made: int) -> None:
    lines, problems = collect(cfg)
    body = f"{made} new video(s) tonight\n" + "\n".join(l for l in lines if l.startswith("["))
    if problems:
        body += "\n\nNeeds attention:\n- " + "\n- ".join(problems)
    if problems or (cfg.get("alerts") or {}).get("daily_summary", True):
        notify(cfg, "CreamPi nightly run", body, priority="high" if problems else "low",
               tags="warning" if problems else "white_check_mark")
