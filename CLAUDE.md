# Project notes

- The user's name is **Max**.
- The Raspberry Pi 5 that runs the bot is named **CreamPi** (hostname `creampi`, reachable at `creampi.local`). Login: `max@creampi.local`, home `/home/max`.
- The Shorts bot lives in `clipbot/` (see `clipbot/README.md`). The rest of the repo is an unrelated CORS proxy.
- Strategy files tuned from the weekly reviews: `clipbot/channels.yaml` and `clipbot/niches.yaml`.
  CreamPi pulls them before each nightly run and pushes stats to `clipbot/reports/` afterwards.

## Working on CreamPi itself (Claude Code running on the Pi)

Repo: `~/damierbuckle/clipbot` (branch `claude/ollama-clip-bot-rpi-yle8t6`). Data: `~/clipbot/` (ready/, work/state.db, tokens/).
Runs as the `clipbot-stories` systemd service, fired by `clipbot-stories.timer` at 01:30. Logs: `journalctl -u clipbot-stories`.

Known state and pitfalls:
- **Power:** CreamPi is on a MacBook USB-C charger (~15W at 5V) until the official 27W supply arrives. Full load reboots it.
  Keep `max_threads: 2` at the top of `config.yaml`, `arm_freq=1800` in `/boot/firmware/config.txt`, and
  `AllowedCPUs=0-1` drop-ins for `clipbot-stories` and `ollama`. Check `vcgencmd get_throttled` after any heavy step.
- **config.yaml is not in git** (keys live there). Validate after every edit:
  `.venv/bin/python -c "import yaml; yaml.safe_load(open('config.yaml')); print('config OK')"`.
  It was once corrupted by shell commands typed into nano; check `head -5 config.yaml` starts with the comment header.
- Writing uses `llm: {provider: claude-code, model: haiku}`: the `claude` CLI on Max's Pro plan. Keep usage low.
- Never print or commit API keys. Don't commit `clipbot/reports/` from test runs (only `sync.sh` pushes real reports).
- Ask Max before anything that spends money, deletes videos, or posts publicly.

## Pi setup checklist (work through it top to bottom, verify each step, report what's left)

1. Network: connected to the internet (`ping -c2 github.com`). If on a captive-portal network (library, cafe), Max must
   accept it in the Pi's browser first. Long term CreamPi should live on home Ethernet/Wi-Fi.
2. `cd ~/damierbuckle/clipbot && git pull`, then `.venv/bin/pip install -r requirements.txt`.
3. config.yaml: valid YAML; `max_threads: 2`; `llm` block as above; `schedule.timezone` set; `buffer_days: 1` for testing.
4. Power limits present (see above); create the systemd drop-ins if missing, `daemon-reload`, restart ollama.
5. `.venv/bin/python -m clipbot check`: everything ✓ except optional `!` items.
6. Corridor backgrounds exist: `ls ~/clipbot/backgrounds/generated/` (else `.venv/bin/python -m clipbot backgrounds`).
7. Test run: `sudo systemctl start --no-block clipbot-stories`, follow the log, and report each `(+Ns)` step time.
   If the Pi reboots, stop and tell Max (power supply).
8. Remote access that survives reboots: `rpi-connect on`, `loginctl enable-linger max`.
9. Always-on Claude Code: `claude remote-control` in `~/damierbuckle/clipbot`, kept alive in tmux and restarted at boot
   (`@reboot` crontab entry). Confirm the session appears in Max's Claude app.
10. Samba share of `~/clipbot` so Max can grab videos for upload (`smb://creampi.local`).
