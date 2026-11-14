from __future__ import annotations

import json

from .models import Arb


def format_arb(a: Arb) -> str:
    when = a.commence.strftime("%a %b %d %H:%M UTC")
    lines = [f"{a.event}  [{a.sport}]  {when}",
             f"  guaranteed profit ${a.profit:+.2f} on ${a.outlay:.2f}  "
             f"(ROI {a.roi * 100:+.2f}%, implied total {a.implied_total:.4f})"]
    for l in a.legs:
        if l.is_kalshi:
            what = f"{l.contracts} contracts YES @ ${l.quoted:.2f}  ({l.ref})"
        else:
            what = f"bet ${l.stake:.2f} @ {l.quoted:.2f} decimal"
        spend = f"${l.stake:.2f}" if l.is_kalshi else ""
        lines.append(f"    {l.outcome:<24} {l.venue:<12} {what} {spend}".rstrip())
    return "\n".join(lines)


def to_json(a: Arb) -> str:
    return json.dumps({
        "event": a.event, "sport": a.sport, "commence": a.commence.isoformat(),
        "kalshi_event": a.kalshi_event, "roi": round(a.roi, 6),
        "profit": round(a.profit, 2), "outlay": round(a.outlay, 2),
        "legs": [{"outcome": l.outcome, "venue": l.venue, "quoted": l.quoted,
                  "stake": l.stake, "contracts": l.contracts, "ref": l.ref} for l in a.legs],
    })
