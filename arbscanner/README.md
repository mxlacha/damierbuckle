# arbscanner

Scans Kalshi sports markets and sportsbook moneylines for guaranteed-profit
(arbitrage) combinations, sized for a bankroll you choose.

```
pip install requests
export ODDS_API_KEY=...            # free tier at https://the-odds-api.com
python -m arbscanner --demo --min-profit -10                  # offline demo
python -m arbscanner --sport nfl --sport nba --bankroll 500   # one scan
python -m arbscanner --books draftkings,fanduel --watch 60 --log arbs.jsonl
```

Run from the repo root. Kalshi market data is public (no key). `--min-profit`
takes a percent; negative values print near-misses, handy for checking that
matching works. Tests: `python -m unittest discover -s arbscanner/tests -t .`

## How it works
1. **Kalshi**: pulls open markets per sport series (`KXNFLGAME`, ...), groups
   them into games; each market's YES ask is the price to back that team.
2. **Sportsbooks**: pulls h2h (moneyline) decimal odds from The Odds API
   (DraftKings, FanDuel, BetMGM, ...). Direct scraping of sportsbook sites is
   against their ToS and breaks constantly, so an aggregator API is used.
3. **Matching**: Kalshi teams are fuzzy-matched to book team names and the game
   date must be within a day. Ambiguous matches (doubleheaders, "New York")
   are skipped rather than guessed.
4. **Math**: best price per outcome across all venues. Kalshi odds are
   `1 / (ask + 0.07*ask*(1-ask))` to include the taker fee. An arb exists if
   `sum(1/odds) < 1`. Stakes equalise the payout, then are rounded to whole
   Kalshi contracts / cents and profit is re-computed as the *worst case*.
   Handles 3-way (soccer) markets.

## Read before betting real money
- **Not tested against live APIs** (built in a sandbox that blocked both
  hosts). Kalshi series tickers and field names are best effort; override with
  `--sport nba:KXNBAGAME:basketball_nba` if one is wrong, and check the first
  results by hand.
- Kalshi liquidity is **not** checked: the ask may only be a few contracts deep.
- Sportsbook odds are cached/delayed a bit by the aggregator and lines move
  fast; verify both prices before placing either leg. Place the less liquid
  leg (usually Kalshi) first.
- Rules differ: postponed/overtime/void handling, and "win" definitions, can
  differ between Kalshi and a book, which turns an arb into a risk.
- Books limit or close accounts that win consistently; you also need accounts
  funded in a state where each book operates. Kalshi's fee schedule can change
  (`--fee-rate`).
- Odds API quota: 1 request per sport per region per scan; `--watch` burns it.
