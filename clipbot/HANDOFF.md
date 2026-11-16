# Handoff: clipbot on CreamPi (2026-11-16)

For a Claude Code session running **on CreamPi** (or attached to it). Read `CLAUDE.md` at the repo root first;
its hub rules are hard limits (no network/Tailscale/Pi Connect/firewall changes, no reboots without Max's approval
of the exact command).

## Where things stand

- Pi: CreamPi (`max`), official 27W supply installed, always on, on campus Sewanee-IoT with Tailscale; hotspot Max15
  is tried first at boot (`wifi-fallback.service`, untested with a real reboot). See `~/hub/CLAUDE.md`.
- Bot: `~/damierbuckle/clipbot`, branch `claude/ollama-clip-bot-rpi-yle8t6`. `clipbot-stories` (01:30) is enabled;
  `clipbot-make` and `clipbot-upload` stay **disabled** (upload would post to YouTube: never enable without Max).
- Only the `brainfacts` channel is enabled (`channels.yaml`). Writing uses Max's Claude Pro plan via the `claude` CLI
  (`llm.provider: claude-code`, Haiku). Keep usage low.
- Last nightly run failed with "every niche has run dry". Cause: a bug that counted outages as strikes. Fixed on
  GitHub, but **not yet on the Pi**, because the Pi's branch diverged (2 local commits ahead, several behind).
- The paper trader is out of scope for now.

## To do, in order (ask Max before each step marked ⚠)

1. Inspect the divergence (read-only):
   `git fetch origin && git log --oneline --stat origin/claude/ollama-clip-bot-rpi-yle8t6..HEAD`
   and `git status`. Expected: the 2 local commits and the local edits touch only `reports/`.
2. ⚠ If and only if step 1 shows reports-only changes, show Max this and get approval:
   ```
   cp -r reports ~/reports-backup
   git reset --hard origin/claude/ollama-clip-bot-rpi-yle8t6
   mkdir -p reports && cp ~/reports-backup/* reports/
   ```
   If anything else is in those commits, stop and report it instead.
3. `.venv/bin/pip install -r requirements.txt`, validate `config.yaml` (see CLAUDE.md), and confirm it has no
   `max_threads` line (that low-power workaround is obsolete now).
4. `.venv/bin/python -m clipbot reset-niches --channel brainfacts` (clears the false "dry" flags).
5. ⚠ Install the updated systemd units the way install.sh does (fill `@USER@`=max, `@DIR@`=repo path):
   `clipbot-alert@.service` (new) and `clipbot-stories.service` (now has `OnFailure=`), then `daemon-reload`.
   Check for leftover `limit.conf` drop-ins and an `arm_freq=1800` line; removing `arm_freq` needs a reboot, which
   needs Max's explicit approval.
6. Alerts: ask Max for the ntfy topic he subscribed to in the ntfy app, put it in `config.yaml` under
   `alerts.ntfy_topic`, validate, then send a test (`.venv/bin/python -c` calling `clipbot.health.notify`).
7. `.venv/bin/python -m clipbot health`, then ⚠ a test run: `sudo systemctl start --no-block clipbot-stories`,
   follow `journalctl -u clipbot-stories -f`, and report each `(+Ns)` step time and whether a video landed in
   `~/clipbot/ready/brainfacts/`. Watch `vcgencmd get_throttled` (should stay `0x0`).
8. Optional, if Max wants it: `claude remote-control` in the repo, kept in tmux with an `@reboot` crontab entry,
   so the session is reachable from his phone.

Report at the end: what's done, the step timings, and anything still open.
