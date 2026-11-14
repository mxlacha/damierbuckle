"""Arbitrage maths: fees, effective odds and stake sizing."""
from __future__ import annotations

import math

from .models import Leg

KALSHI_FEE_RATE = 0.07  # taker fee = ceil(rate * C * P * (1 - P)) per order


def kalshi_fee_per_contract(price: float, rate: float = KALSHI_FEE_RATE) -> float:
    """Approximate (un-rounded) taker fee in dollars for one contract at `price`."""
    return rate * price * (1.0 - price)


def kalshi_order_fee(price: float, contracts: int, rate: float = KALSHI_FEE_RATE) -> float:
    """Exact fee for an order: rounded up to the next cent."""
    return math.ceil(round(rate * contracts * price * (1.0 - price) * 100, 6)) / 100


def kalshi_eff_odds(price: float, rate: float = KALSHI_FEE_RATE) -> float:
    """Decimal odds of buying YES at `price` once the fee is paid."""
    return 1.0 / (price + kalshi_fee_per_contract(price, rate))


def implied_total(legs: list[Leg]) -> float:
    return sum(1.0 / l.eff_odds for l in legs)


def size_stakes(legs: list[Leg], bankroll: float, fee_rate: float = KALSHI_FEE_RATE):
    """Split `bankroll` so every outcome pays the same, then round to real units.

    Kalshi legs are whole contracts and sportsbook stakes are whole cents, so the
    result is re-evaluated after rounding; returns (sized_legs, outlay, profit)
    where profit is the *worst-case* profit across outcomes.
    """
    total = implied_total(legs)
    sized: list[Leg] = []
    payouts: list[float] = []
    outlay = 0.0
    for l in legs:
        share = bankroll * (1.0 / l.eff_odds) / total
        if l.is_kalshi:
            per = l.quoted + kalshi_fee_per_contract(l.quoted, fee_rate)
            n = int(share // per)
            while n > 0 and n * l.quoted + kalshi_order_fee(l.quoted, n, fee_rate) > share:
                n -= 1
            cost = n * l.quoted + (kalshi_order_fee(l.quoted, n, fee_rate) if n else 0.0)
            sized.append(Leg(**{**l.__dict__, "stake": round(cost, 2), "contracts": n}))
            payouts.append(float(n))
        else:
            stake = math.floor(share * 100) / 100
            cost = stake
            sized.append(Leg(**{**l.__dict__, "stake": stake}))
            payouts.append(stake * l.quoted)
        outlay += cost
    profit = min(payouts) - outlay if payouts else 0.0
    return tuple(sized), outlay, profit
