# clipbot — Ollama Shorts bot for Raspberry Pi 5

Two modes, both running fully on the Pi:

- **Story mode** (`clipbot stories`, the default): writes, voices and edits original Shorts for a niche, three a day, and keeps a week of them ready for you to upload.
- **Clip mode** (`clipbot make`): cuts highlights out of long videos you own. See [Clip mode](#clip-mode) below.

## Story mode

Every night at 01:30 the bot:

1. **Checks stats** (read-only YouTube API key) and decides whether to stick with the current niche or switch.
2. **Picks a topic** for each open slot in the next `buffer_days`:
   - `story` niches (military, sports, cars, money…): a real event, grounded in its Wikipedia article (or an RSS news item). The script may only use facts from that source, which keeps you clear of misinformation strikes.
   - `reddit` niches: an original fictional story in a forum-post style, clearly labeled as fiction.
   - `tweet` posts: commentary on real posts you drop into `~/clipbot/inbox/tweets/`, at most one a day.
3. **Writes the script** with Ollama. The hook comes first, short spoken lines, a payoff, and a last line that loops back to the start. Each line also gets a footage search phrase.
4. **Records the voiceover** with Kokoro, a natural-sounding offline voice. It rotates voices per niche and never uses the same one twice in a row.
5. **Edits the video**: a new shot on every line. It uses your clip library first (`~/clipbot/broll/f-15/`, `~/clipbot/broll/kobe/`, …), then Wikimedia Commons photos with a slow pan (credited automatically), then Pexels stock video. On top go karaoke captions (the spoken word is highlighted), a hook banner or story card, and music.
6. **Files it** under `~/clipbot/ready/<date>/<time>_<title>/` and updates `ready/UPLOAD_SHEET.csv`.

### Weekly upload routine (YouTube Studio, by hand)

Uploading through Studio yourself keeps the channel a normal creator account: no API project, no automation flags.

1. Open `ready/UPLOAD_SHEET.csv`. Each row has the date, time, folder, title and whether to tick "altered content".
2. In Studio, click **Create → Upload videos** and drag in up to 15 `video.mp4` files at once.
3. For each one, paste `title.txt` and `description.txt`, choose **Made for kids: No**, and answer "Altered or synthetic content" as the sheet says (Yes for fictional stories). On the Visibility step, choose **Schedule** and enter the sheet's date and time.
4. When done, run `.venv/bin/python -m clipbot uploaded 2026-11-07`, using the last date you scheduled. That moves those folders to `uploaded/`. If analytics is set up, the bot also detects uploads by title automatically. Keep the titles as written so it can match them.

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
- **Reddit-style backgrounds:** use footage you recorded yourself (your own gameplay, driving, satisfying clips) or Pexels. Re-uploaded "Minecraft parkour" from other channels gets claimed.

### Staying monetizable

Since July 2025, YouTube's "inauthentic content" policy explicitly targets *"channels that upload narrative stories with only superficial differences between them"* and *"slideshows that all have the same narration."* AI-assisted channels stay eligible when the videos add real value. The bot is built to do that: it rotates voices, caption styles and music, rejects repeated topics and premises, grounds facts in sources, and labels fiction as fiction. What helps most beyond that is your own input: record an intro in your own voice sometimes, pick topics you find interesting, and cut weak videos before uploading. Nothing here disguises automation or dodges Content ID; that is what gets channels terminated rather than just demonetized.

### Tuning to accounts that work

Send Claude screenshots of top accounts, showing their hooks, video lengths, caption style and posting rhythm. That turns them into niche entries (`angle`, `tone`, `seeds`, voices) and length or caption settings. A larger writer model also helps a lot. On an 8 GB Pi, set `model: qwen2.5:7b` on a niche (`ollama pull qwen2.5:7b`). It's about 2–3× slower, which is fine for an overnight run.

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

Then edit `clipbot/config.yaml` (set `channel.name`, `stories.pexels_api_key` and `analytics`) and `clipbot/niches.yaml`.

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
