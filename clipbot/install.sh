#!/usr/bin/env bash
# One-shot setup for Raspberry Pi 5 (Raspberry Pi OS Bookworm, 64-bit).
# Usage: cd clipbot && ./install.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(id -un)"
DATA="$HOME/clipbot"
MODEL="${CLIPBOT_MODEL:-llama3.2:3b}"
VOICE="${CLIPBOT_VOICE:-en_US-lessac-medium}"

echo "==> System packages"
sudo apt-get update
sudo apt-get install -y ffmpeg python3-venv python3-pip fonts-dejavu-core espeak-ng curl tesseract-ocr

echo "==> Ollama"
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
sudo systemctl enable --now ollama
ollama pull "$MODEL"

echo "==> Python environment"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --upgrade pip
"$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
# expose the piper CLI installed in the venv
sudo ln -sf "$DIR/.venv/bin/piper" /usr/local/bin/piper

echo "==> Folders + Piper voice"
mkdir -p "$DATA"/{inbox/tweets,work,ready,uploaded,music,voices,broll,backgrounds}
# Kokoro: the natural-sounding voice used for story narration
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -f "$DATA/voices/$f" ] || curl -fL -o "$DATA/voices/$f" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"
done
lang="${VOICE%%-*}"; speaker="$(echo "$VOICE" | cut -d- -f2)"; quality="${VOICE##*-}"
base="https://huggingface.co/rhasspy/piper-voices/resolve/main/${lang%%_*}/$lang/$speaker/$quality"
for ext in onnx onnx.json; do
  [ -f "$DATA/voices/$VOICE.$ext" ] || curl -fL -o "$DATA/voices/$VOICE.$ext" "$base/$VOICE.$ext"
done

[ -f "$DIR/niches.yaml" ] || cp "$DIR/niches.example.yaml" "$DIR/niches.yaml"
[ -f "$DIR/config.yaml" ] || sed "s#model: llama3.2:3b#model: $MODEL#" "$DIR/config.example.yaml" > "$DIR/config.yaml"

echo "==> systemd timers"
for unit in clipbot-stories.service clipbot-stories.timer clipbot-make.service clipbot-make.timer \
            clipbot-upload.service clipbot-upload.timer; do
  sed -e "s#@USER@#$USER_NAME#g" -e "s#@DIR@#$DIR#g" "$DIR/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo systemctl daemon-reload
# Story mode is the default. The clip-cutting (make) and API-upload timers are installed
# but off; enable them with: sudo systemctl enable --now clipbot-make.timer
sudo systemctl enable --now clipbot-stories.timer

echo "==> Self-check"
"$DIR/.venv/bin/python" -m clipbot check || true

cat <<MSG

Done. Next steps:
  1. Edit $DIR/config.yaml (channel name, pexels key, analytics key) and $DIR/niches.yaml.
  2. Make a first batch now:   $DIR/.venv/bin/python -m clipbot stories
  3. Upload from $DATA/ready using UPLOAD_SHEET.csv (see README → "Weekly upload routine").
  4. It refills the calendar every night at 01:30.
MSG
