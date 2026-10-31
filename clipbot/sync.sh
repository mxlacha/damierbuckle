#!/usr/bin/env bash
# Strategy loop with the repo:
#   sync.sh pull  — before a run: fetch tuned channels.yaml / niches.yaml
#   sync.sh push  — after a run: commit reports/ so the weekly review can read them
# Needs push access from the Pi (a deploy key with write access). Failures never block a run.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 0
case "${1:-}" in
  pull)
    git pull --ff-only --quiet || echo "sync: pull failed (local edits or no network); using current config"
    ;;
  push)
    git add reports/ 2>/dev/null
    if ! git diff --cached --quiet; then
      git -c user.name="clipbot" -c user.email="clipbot@localhost" commit --quiet -m "clipbot: stats report $(date +%F)"
      git push --quiet || echo "sync: push failed (check the deploy key)"
    fi
    ;;
  *) echo "usage: sync.sh pull|push" ;;
esac
exit 0
