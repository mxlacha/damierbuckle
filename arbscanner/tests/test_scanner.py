import copy
import unittest
from datetime import timedelta

from arbscanner import demo_data
from arbscanner.arb import kalshi_eff_odds, kalshi_order_fee
from arbscanner.kalshi import _price, group_markets, parse_event_date
from arbscanner.matching import map_names, name_score
from arbscanner.oddsapi import parse_events
from arbscanner.scanner import ScanConfig, find_arbs


def run(markets=None, payload=None, cfg=None, now=demo_data.NOW):
    k = group_markets(markets or demo_data.KALSHI_MARKETS, "KXNFLGAME")
    o = parse_events(payload or demo_data.ODDS_PAYLOAD)
    return find_arbs(o, k, cfg or ScanConfig(), now=now)


class Math(unittest.TestCase):
    def test_fee_rounds_up_to_cent(self):
        # 0.07 * 10 * .5 * .5 = 0.175 -> 0.18
        self.assertEqual(kalshi_order_fee(0.5, 10), 0.18)
        self.assertEqual(kalshi_order_fee(0.5, 0), 0.0)

    def test_eff_odds_worse_than_raw(self):
        self.assertLess(kalshi_eff_odds(0.44), 1 / 0.44)

    def test_profit_is_guaranteed_in_every_outcome(self):
        (a,) = run()
        for winner in a.legs:
            payout = winner.contracts if winner.is_kalshi else winner.stake * winner.quoted
            self.assertGreaterEqual(round(payout - a.outlay, 2), round(a.profit, 2) - 0.01)
        self.assertGreater(a.profit, 0)
        self.assertLessEqual(a.outlay, 100.0)


class Parsing(unittest.TestCase):
    def test_price_formats(self):
        self.assertEqual(_price({"yes_ask": 44}, "yes_ask"), 0.44)
        self.assertEqual(_price({"yes_ask_dollars": "0.4400"}, "yes_ask"), 0.44)
        self.assertIsNone(_price({"yes_ask": 0}, "yes_ask"))  # empty book
        self.assertIsNone(_price({"yes_ask": 100}, "yes_ask"))
        self.assertIsNone(_price({}, "yes_ask"))

    def test_event_date(self):
        self.assertEqual(str(parse_event_date("KXNFLGAME-26NOV16BUFKC")), "2026-11-16")
        self.assertIsNone(parse_event_date("KXFOO-BAR"))

    def test_closed_markets_ignored(self):
        ms = copy.deepcopy(demo_data.KALSHI_MARKETS)
        for m in ms:
            m["status"] = "closed"
        self.assertEqual(group_markets(ms, "X"), [])


class Matching(unittest.TestCase):
    def test_names(self):
        self.assertGreaterEqual(name_score("Kansas City", "Kansas City Chiefs"), 0.9)
        self.assertGreaterEqual(name_score("LA Clippers", "Los Angeles Clippers"), 0.9)
        self.assertGreaterEqual(name_score("Tie", "Draw"), 0.9)
        self.assertLess(name_score("Kansas City Chiefs", "Kansas City Royals"), 0.85)

    def test_ambiguous_names_refused(self):
        m, _ = map_names(["New York"], ["New York Giants", "New York Jets"])
        self.assertIsNone(m)


class Scanning(unittest.TestCase):
    def test_finds_only_the_real_arb(self):
        arbs = run()
        self.assertEqual([a.event for a in arbs], ["Buffalo Bills @ Kansas City Chiefs"])

    def test_no_arb_when_prices_efficient(self):
        ms = copy.deepcopy(demo_data.KALSHI_MARKETS)
        ms[0]["yes_ask"], ms[1]["yes_ask"] = 62, 42  # KC 62c, BUF 42c
        self.assertEqual(run(ms), [])

    def test_min_profit_filter(self):
        self.assertEqual(run(cfg=ScanConfig(min_profit_pct=50)), [])

    def test_started_games_skipped_unless_live(self):
        late = demo_data.NOW + timedelta(days=3)
        self.assertEqual(run(now=late), [])
        self.assertTrue(run(now=late, cfg=ScanConfig(include_live=True)))

    def test_wrong_date_not_matched(self):
        ms = copy.deepcopy(demo_data.KALSHI_MARKETS)
        for m in ms:
            m["event_ticker"] = m["event_ticker"].replace("26NOV16", "26NOV25")
        self.assertEqual(run(ms), [])

    def test_empty_kalshi_book_not_used(self):
        ms = copy.deepcopy(demo_data.KALSHI_MARKETS)
        ms[0]["yes_ask"] = 0
        self.assertEqual(run(ms), [])

    def test_bankroll_too_small(self):
        self.assertEqual(run(cfg=ScanConfig(bankroll=0.3)), [])

    def test_three_way_soccer(self):
        kick = demo_data.KICK
        payload = [{"id": "s1", "sport_key": "soccer_epl", "commence_time": kick,
                    "home_team": "Arsenal", "away_team": "Chelsea", "bookmakers": [
                        {"key": "a", "title": "BookA", "markets": [{"key": "h2h", "outcomes": [
                            {"name": "Arsenal", "price": 2.0}, {"name": "Chelsea", "price": 3.2},
                            {"name": "Draw", "price": 3.1}]}]}]}]
        ev = "KXEPLGAME-26NOV16CHEARS"
        ms = [{"event_ticker": ev, "ticker": f"{ev}-{t}", "yes_sub_title": n, "title": "x",
               "status": "open", "yes_ask": p}
              for t, n, p in [("ARS", "Arsenal", 70), ("CHE", "Chelsea", 25), ("TIE", "Tie", 18)]]
        # book: Arsenal 2.0 (0.50) ; Kalshi Chelsea 25c ; Kalshi Draw 18c => 0.93 raw
        arbs = run(ms, payload)
        self.assertEqual(len(arbs), 1)
        self.assertEqual({l.outcome for l in arbs[0].legs}, {"Arsenal", "Chelsea", "Draw"})
        self.assertGreater(arbs[0].profit, 0)


if __name__ == "__main__":
    unittest.main()
