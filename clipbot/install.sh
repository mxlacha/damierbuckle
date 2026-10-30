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
sudo apt-get install -y ffmpeg python3-venv python3-pip fonts-dejavu-core espeak-ng curl

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
mkdir -p "$DATA"/{inbox,work,ready,uploaded,music,voices}
lang="${VOICE%%-*}"; speaker="$(echo "$VOICE" | cut -d- -f2)"; quality="${VOICE##*-}"
base="https://huggingface.co/rhasspy/piper-voices/resolve/main/${lang%%_*}/$lang/$speaker/$quality"
for ext in onnx onnx.json; do
  [ -f "$DATA/voices/$VOICE.$ext" ] || curl -fL -o "$DATA/voices/$VOICE.$ext" "$base/$VOICE.$ext"
done

[ -f "$DIR/config.yaml" ] || sed "s#model: llama3.2:3b#model: $MODEL#" "$DIR/config.example.yaml" > "$DIR/config.yaml"

echo "==> systemd timers"
for unit in clipbot-make.service clipbot-make.timer clipbot-upload.service clipbot-upload.timer; do
  sed -e "s#@USER@#$USER_NAME#g" -e "s#@DIR@#$DIR#g" "$DIR/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now clipbot-make.timer clipbot-upload.timer

echo "==> Self-check"
"$DIR/.venv/bin/python" -m clipbot check || true

cat <<MSG

Done. Next steps:
  1. Edit $DIR/config.yaml (channel niche, sources, schedule).
  2. Drop a video into $DATA/inbox and test:  $DIR/.venv/bin/python -m clipbot make
  3. Finished clips appear in $DATA/ready
  4. (Optional) YouTube auto-upload: see README.md → "YouTube scheduling".
MSG
