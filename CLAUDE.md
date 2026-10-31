# Project notes

- The Raspberry Pi 5 that runs the bot is named **max** (hostname `max`, reachable at `max.local`).
- The Shorts bot lives in `clipbot/` (see `clipbot/README.md`). The rest of the repo is an unrelated CORS proxy.
- Strategy files tuned from the weekly reviews: `clipbot/channels.yaml` and `clipbot/niches.yaml`.
  max pulls them before each nightly run and pushes stats to `clipbot/reports/` afterwards.
