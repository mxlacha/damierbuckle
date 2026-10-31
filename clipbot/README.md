# clipbot — Ollama Shorts bot for Raspberry Pi 5

Two modes, both running fully on the Pi:

- **Story mode** (`clipbot stories`, the default): writes, voices and edits original Shorts for a niche, three a day, and keeps a week of them ready for you to upload.
- **Clip mode** (`clipbot make`): cuts highlights out of long videos you own. See [Clip mode](#clip-mode) below.

## Story mode

### Channels and formats

`channels.yaml` lists your YouTube accounts. Each one runs its own niche rotation, its own 3-a-day schedule and its own output folder, `~/clipbot/ready/<channel>/`, so you can trial several niches at once on separate accounts. Niches live in `niches.yaml`. Every niche uses one of five formats, each modeled on a style that's already performing:

| Format | Looks like | Where the content comes from |
|---|---|---|
| `explainer` | topic photo in a top panel, blocky corridor fly-through below, one huge word on screen at a time | Wikipedia article (facts) and its lead photo, used only when the photo is freely licensed |
| `post` | a real public post as a dark card over the corridor; the voice reads it and adds a take | Bluesky trending posts (open API) plus screenshots or `.txt` files you drop in `~/clipbot/inbox/tweets/<channel>/` |
| `factcard` | caption with **highlighted** phrases above a clip, blurred copy behind it, music only | NASA video library (public domain, with the official description as facts), or your own clips with a `.txt` of facts beside them |
| `story` | documentary narration over full-screen b-roll | Wikipedia or RSS |
| `reddit` | original fictional forum-style story, labeled as fiction | Ollama |

The corridor backgrounds are **generated on the Pi** (`clipbot backgrounds`). They're original footage, so there's no gameplay for Content ID to claim, and every loop gets its own palette, blocks and camera sway. If you record your own gameplay, drop it in `~/clipbot/backgrounds/` and it gets mixed in.

### What runs every night (01:30)

1. `sync.sh pull` fetches the latest `channels.yaml` and `niches.yaml` from the repo, so strategy changes reach the Pi.
2. For each channel: read stats, apply the niche rules, write `reports/<channel>.md` and `.json`.
3. Fill each channel's open slots for the next `buffer_days`. Ollama finds the material, writes the script (hook first, payoff, loop back) and the title, description and tags. Kokoro voices it, Whisper times the captions, and ffmpeg edits it.
4. `sync.sh push` commits `reports/` to the repo.

### The strategy loop (Ollama does the volume, Claude does the strategy)

The Pi does all the token-heavy work locally, at no per-video cost. The weekly reports break performance down by every lever the bot controls: niche, format, caption style, voice, posting hour, length bucket and hook, with median views, **retention** (average % viewed) and **RPM** once you're monetized. A weekly Claude review reads `reports/` from the repo, decides what to change, and commits it to `channels.yaml` or `niches.yaml`: word counts, voice speed, caption style, posting times, which niches each account runs, and new seed topics. The Pi picks those changes up the next night.

Setup for the loop:
- **Push access from the Pi:** create a GitHub deploy key with write access for this repo on the Pi. `sync.sh` never blocks a run if it fails.
- **Views:** put a Data API key in `config.yaml → analytics.api_key` and each account's `youtube_channel_id` in `channels.yaml`.
- **Retention and RPM:** run `.venv/bin/python -m clipbot auth-analytics <channel>` once per account, signed in as that channel's owner. This is read-only (`yt-analytics.readonly` and `yt-analytics-monetary.readonly` scopes); nothing can upload or edit.

### Weekly upload routine (YouTube Studio, by hand)

Uploading through Studio yourself keeps the channel a normal creator account: no API project, no automation flags.

1. Open `ready/<channel>/UPLOAD_SHEET.csv` (switch to that channel in Studio first). Each row has the date, time, folder, title and whether to tick "altered content".
2. In Studio, click **Create → Upload videos** and drag in up to 15 `video.mp4` files at once.
3. For each one, paste `title.txt` and `description.txt`, choose **Made for kids: No**, and answer "Altered or synthetic content" as the sheet says (Yes for fictional stories). On the Visibility step, choose **Schedule** and enter the sheet's date and time.
4. When done, run `.venv/bin/python -m clipbot uploaded 2026-11-07 --channel <id>`, using the last date you scheduled. That moves those folders to `uploaded/`. If analytics is set up, the bot also detects uploads by title automatically. Keep the titles as written so it can match them.

**Scheduling a month out:** Studio's scheduler accepts dates months ahead, so you *can* set `buffer_days: 30` and do one big session of about 90 uploads. A week at a time is better, for two reasons. YouTube's daily upload cap isn't published and is lower for new channels, so 90 in one day may hit it. And the niche switcher can't change what's already scheduled, so a month-long queue means a month of a dud niche.

### Niche switching (the numbers)

| Rule | Default | Meaning |
|---|---|---|
| `trial_posts` | 30 | about 10 days at 3/day before judging a niche |
| `min_age_hours` | 72 | a video's views only count once it's 3 days old |
| winner | median ≥ 3,000 views, **or** one video ≥ 100k, **or** +500 subs during the niche | stick with it indefinitely |
| dud | median < 800 **and** nothing over 10k after the trial | switch now |
| in between | — | one more trial of 30 posts, then switch unless it became a winner |
| fatigue | last 21 posts' median < 25% of the niche's best stretch | a winner that has gone stale rotates out |
| ran dry | 3 failed topic searches in a row | no fresh Wikipedia articles, RSS items or distinct premises left |

Once every niche has been tried, the bot goes back to the best performer that hasn't run dry. You can change all of this in `niche_rules`. Run `clipbot stats` to see where things stand.

To enable performance tracking, create a Google Cloud **API key** with YouTube Data API v3 enabled and put it in `analytics.api_key` along with your `channel_id`. This only reads public stats and never posts.

### Footage and copyright

- **Real sports and news footage (Kobe highlights, broadcast clips) belongs to the leagues and networks.** Content ID will claim it, and the revenue goes to them or the video gets blocked. The bot doesn't download it. For athletes it uses CC-licensed photos from Commons. Only put clips in `~/clipbot/broll/<tag>/` that you have the rights to.
- **Military footage is easy.** U.S. government footage (DVIDS, defense.gov) is public domain. Download it into `broll/f-15/`, `broll/a-10/` and so on.
- **Reddit-style backgrounds:** use footage you recorded yourself (your own gameplay, driving, satisfying clips) or Pixabay stock video. Re-uploaded "Minecraft parkour" from other channels gets claimed.

- **Fact-card accounts that repost viral clips** (many of the big ones) are re-uploading other people's videos. Their reach is real, but so are the claims and strikes, and that's the pattern YouTube's reused-content rule targets. Here the clip is public domain (NASA) or yours, and the caption is original writing.

### Staying monetizable

Since July 2025, YouTube's "inauthentic content" policy explicitly targets *"channels that upload narrative stories with only superficial differences between them"* and *"slideshows that all have the same narration."* AI-assisted channels stay eligible when the videos add real value. The bot is built to do that: it rotates voices, caption styles and music, rejects repeated topics and premises, grounds facts in sources, and labels fiction as fiction. What helps most beyond that is your own input: record an intro in your own voice sometimes, pick topics you find interesting, and cut weak videos before uploading. Nothing here disguises automation or dodges Content ID; that is what gets channels terminated rather than just demonetized.

### Faster, more reliable writing: the Claude API

Writing scripts on the Pi takes minutes each and small models sometimes miss the format. Set `llm.provider: claude` in `config.yaml` (with your `sk-ant-...` key) to write with Claude Haiku 5.5 instead: seconds per script, and structured outputs guarantee the JSON is valid. At roughly 3-5K tokens per video and $0.10 / $0.50 per million input / output tokens, a channel posting 3 a day costs on the order of a few cents a month. If the API is unreachable, the bot falls back to Ollama on the Pi.

### Bigger writer model

On an 8 GB Pi, `model: qwen2.5:7b` on a niche (`ollama pull qwen2.5:7b`) writes noticeably better hooks. It's about 2–3× slower, which is fine for an overnight run. With several channels, keep `llama3.2:3b` for `factcard` (short captions) and spend the time on `explainer` and `post`.

## Clip mode

When `clipbot make` runs (manually or from `clipbot-make.timer`), it:

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
./install.sh                         # apt deps, Ollama + model, venv, Kokoro + Piper voices, systemd timers
# On a 4 GB Pi use a smaller model:  CLIPBOT_MODEL=llama3.2:1b ./install.sh
```

Then edit `clipbot/config.yaml` (set `stories.pixabay_api_key` and `analytics`) and `clipbot/channels.yaml`.

```bash
.venv/bin/python -m clipbot check     # verify ffmpeg, Ollama, whisper, voices and keys
.venv/bin/python -m clipbot stories   # story mode: fill the next week now
.venv/bin/python -m clipbot stats     # niche status and top videos
# clip mode:
cp ~/Videos/some_talk.mp4 ~/clipbot/inbox/
.venv/bin/python -m clipbot make      # process now instead of waiting for the timer
.venv/bin/python -m clipbot status    # list ready clips and the next publish slots
```

## Schedule

| Timer | When | What |
|---|---|---|
| `clipbot-stories.timer` | 01:30 daily (on) | stats → niche decision → fills the calendar in `ready/` |
| `clipbot-make.timer` | 02:30 daily (off by default) | finds new sources and renders clips into `ready/` |
| `clipbot-upload.timer` | 07:15 daily (off by default) | uploads up to `schedule.max_uploads_per_run` clips, each booked into the next free slot in `schedule.publish_times` |

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
│   ├── stories.py     # story mode: material → script → voice → edit → ready/<channel>/
│   ├── channels.py    # per-account views of the config
│   ├── niches.py      # trial / winner / dud / dry rotation per channel
│   ├── writer.py      # Ollama prompts per format
│   ├── compose.py     # layouts: full, split, card, factcard; word/karaoke captions
│   ├── tunnel.py      # generated corridor backgrounds
│   ├── research.py    # Wikipedia, RSS, NASA, Bluesky
│   ├── analytics.py   # read-only stats, retention/RPM, weekly reports
│   ├── sources.py     # clip mode: inbox + yt-dlp (with license filter)
│   ├── transcribe.py  # faster-whisper, cached per video
│   ├── brain.py       # Ollama prompt, chunking, timestamp snapping
│   ├── tts.py         # Piper (espeak-ng fallback)
│   ├── render.py      # ffmpeg: 9:16 reframe, ASS text overlay, audio mix
│   ├── pipeline.py    # orchestrates make → ready/
│   ├── uploader.py    # YouTube Data API scheduled uploads
│   └── state.py       # SQLite: processed sources + booked slots
├── channels.yaml      # your accounts (strategy, tracked in git)
├── niches.yaml        # niche definitions (strategy, tracked in git)
├── reports/           # written nightly, pushed by sync.sh
├── sync.sh
├── config.example.yaml
├── install.sh
└── systemd/
```
