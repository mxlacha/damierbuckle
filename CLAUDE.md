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
- **Power:** the official 27W supply is installed (Nov 2026), so CreamPi runs at full speed. The earlier
  MacBook-charger workarounds must be removed: no `max_threads` line in `config.yaml` (default 4), no `arm_freq=1800`
  line in `/boot/firmware/config.txt`, and no `limit.conf` drop-ins under `/etc/systemd/system/{clipbot-stories,ollama}.service.d/`.
  `vcgencmd get_throttled` should stay `0x0` during a run; anything else means power/heat trouble, so stop and tell Max.
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
3. config.yaml: valid YAML; no `max_threads` line; `llm` block as above; `schedule.timezone` set; `buffer_days: 1` for testing.
4. Remove the old power workarounds (see above): delete the drop-ins, `daemon-reload`, restart ollama; remove the
   `arm_freq=1800` line and reboot (ask Max first). Confirm `vcgencmd get_config arm_freq` shows the default.
5. `.venv/bin/python -m clipbot check`: everything ✓ except optional `!` items.
6. Corridor backgrounds exist: `ls ~/clipbot/backgrounds/generated/` (else `.venv/bin/python -m clipbot backgrounds`).
7. Test run: `sudo systemctl start --no-block clipbot-stories`, follow the log, and report each `(+Ns)` step time.
   If the Pi reboots, stop and tell Max (power supply).
8. Remote access that survives reboots: `rpi-connect on`, `loginctl enable-linger max`.
9. Always-on Claude Code: `claude remote-control` in `~/damierbuckle/clipbot`, kept alive in tmux and restarted at boot
   (`@reboot` crontab entry). Confirm the session appears in Max's Claude app.
10. Samba share of `~/clipbot` so Max can grab videos for upload (`smb://creampi.local`).
