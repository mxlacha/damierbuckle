# clipbot — Ollama Shorts bot for Raspberry Pi 5

Runs entirely on a Pi 5. Every night it:

1. **Finds source videos**: files you drop in `~/clipbot/inbox`, plus optional channel or playlist URLs fetched with `yt-dlp`.
2. **Transcribes** them locally with `faster-whisper`.
3. **Asks a local Ollama model** to pick the best 15–58 s moments and write an on-screen hook, a voiceover line, a title, a description and tags.
4. **Renders** each clip with `ffmpeg` as a vertical 1080×1920 video with a blurred background fill, the hook text, and word-by-word captions. It also adds an offline **Piper TTS** voiceover (the original audio is turned down while it plays) and, if you supply tracks, background music.
5. **Drops** the finished clip into its own folder in `~/clipbot/ready/` (`video.mp4`, `title.txt`, `description.txt`, `metadata.json`).
6. *(Optional)* **Uploads** clips to YouTube as private videos with a scheduled `publishAt` time. YouTube then publishes them at your chosen time slots.

```
inbox/ or yt-dlp ─▶ whisper ─▶ Ollama (pick + write) ─▶ Piper TTS ─▶ ffmpeg ─▶ ready/ ─▶ YouTube (scheduled)
```

## Install (Pi 5, Raspberry Pi OS Bookworm 64-bit)

```bash
git clone <this repo> && cd <repo>/clipbot
./install.sh                         # apt deps, Ollama + model, venv, Piper voice, systemd timers
# On a 4 GB Pi use a smaller model:  CLIPBOT_MODEL=llama3.2:1b ./install.sh
```

Then edit `clipbot/config.yaml`. At minimum, set `channel.niche` so the hooks match your channel.

```bash
.venv/bin/python -m clipbot check     # verify ffmpeg, Ollama, whisper and TTS
cp ~/Videos/some_talk.mp4 ~/clipbot/inbox/
.venv/bin/python -m clipbot make      # process now instead of waiting for the timer
.venv/bin/python -m clipbot status    # list ready clips and the next publish slots
```

## Schedule

| Timer | When | What |
|---|---|---|
| `clipbot-make.timer` | 02:30 daily | finds new sources and renders clips into `ready/` |
| `clipbot-upload.timer` | 07:15 daily | uploads up to `schedule.max_uploads_per_run` clips, each booked into the next free slot in `schedule.publish_times` |

To change the times, edit `/etc/systemd/system/clipbot-*.timer`, then run `sudo systemctl daemon-reload`.
To see logs, run `journalctl -u clipbot-make -f`.

## YouTube scheduling (optional)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen (External) and add yourself as a test user.
3. Create an **OAuth client ID** of type *Desktop app*, download the JSON, and save it as `~/clipbot/client_secret.json`.
4. Authorize once. The Pi is headless, so tunnel the callback port from your laptop:
   ```bash
   ssh -L 8080:localhost:8080 pi@raspberrypi.local
   cd clipbot && .venv/bin/python -m clipbot auth   # open the printed URL on your laptop
   ```
5. Set `youtube.enabled: true` in `config.yaml`.

Things to know:
- **Unverified API projects can only upload private videos.** YouTube locks uploads from unaudited projects to private, so the scheduled publish won't take effect until you pass the [API compliance audit](https://support.google.com/youtube/contact/yt_api_form). Until then, leave `enabled: false`. You can still upload the clips in `ready/` through YouTube Studio's own scheduler; `title.txt` and `description.txt` are there for copy-paste.
- Each upload costs about 1,600 of the default 10,000 daily quota units, so you can do about 6 uploads a day.
- While the consent screen is in "Testing" mode, refresh tokens expire after 7 days. Publish the app (it can stay unverified for personal use) so the token keeps working.

## Content sources and copyright

Only feed the bot videos **you own** or that are **Creative Commons** licensed. Re-uploading other people's clips gets copyright strikes, and YouTube's "reused content" policy blocks monetization for channels that add little of their own. The bot enforces this for URLs: unless an entry has `own: true`, `yt-dlp` only downloads videos whose license is Creative Commons. Attribution (title, uploader, link, license) is added to each description automatically, which CC BY requires. The hook text, voiceover and captions count as your added commentary, but whether a clip is transformative enough is still your call.

## Tuning for the Pi 5

- **Speed**: with `llama3.2:3b` and `whisper base.en`, a 30-minute video takes roughly 15–30 minutes end to end. That's fine overnight. For faster runs, use `whisper.model: tiny.en` and `llama3.2:1b`.
- **Cooling**: use the active cooler. Whisper and x264 keep all four cores busy.
- **Storage**: put `~/clipbot` on an SSD (the Pi 5 has PCIe/USB 3) rather than the SD card.
- **Voices**: you can use any [Piper voice](https://huggingface.co/rhasspy/piper-voices). Run `CLIPBOT_VOICE=en_US-ryan-high ./install.sh` and update `audio.piper_model`.
- **Music**: put royalty-free tracks you have rights to in `~/clipbot/music/`. One is picked at random for each clip.

## Layout

```
clipbot/
├── clipbot/
│   ├── sources.py     # inbox + yt-dlp (with license filter)
│   ├── transcribe.py  # faster-whisper, cached per video
│   ├── brain.py       # Ollama prompt, chunking, timestamp snapping
│   ├── tts.py         # Piper (espeak-ng fallback)
│   ├── render.py      # ffmpeg: 9:16 reframe, ASS text overlay, audio mix
│   ├── pipeline.py    # orchestrates make → ready/
│   ├── uploader.py    # YouTube Data API scheduled uploads
│   └── state.py       # SQLite: processed sources + booked slots
├── config.example.yaml
├── install.sh
└── systemd/
```
