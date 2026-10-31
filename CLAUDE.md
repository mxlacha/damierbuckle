# Project notes

- The user's name is **Max**.
- The Raspberry Pi 5 that runs the bot is named **CreamPi** (hostname `creampi`, reachable at `creampi.local`). Login: `max@creampi.local`, home `/home/max`.
- The Shorts bot lives in `clipbot/` (see `clipbot/README.md`). The rest of the repo is an unrelated CORS proxy.
- Strategy files tuned from the weekly reviews: `clipbot/channels.yaml` and `clipbot/niches.yaml`.
  CreamPi pulls them before each nightly run and pushes stats to `clipbot/reports/` afterwards.
