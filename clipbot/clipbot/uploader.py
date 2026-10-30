"""Upload ready clips to YouTube as private videos with a scheduled publish time."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .state import State

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def ready_clips(cfg: dict) -> list[Path]:
    ready = Path(cfg["paths"]["ready"])
    return sorted(p for p in ready.iterdir() if (p / "video.mp4").exists() and (p / "metadata.json").exists())


def next_slots(cfg: dict, taken: set[str], count: int) -> list[str]:
    """Next free publish times (RFC3339 UTC) from schedule.publish_times, at least 1h out."""
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    times = sorted(cfg["schedule"]["publish_times"])
    earliest = datetime.now(timezone.utc) + timedelta(hours=1)
    day = earliest.astimezone(tz).date()
    slots: list[str] = []
    while len(slots) < count:
        for hhmm in times:
            hour, minute = map(int, hhmm.split(":"))
            local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            utc = local.astimezone(timezone.utc)
            iso = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            if utc >= earliest and iso not in taken and len(slots) < count:
                slots.append(iso)
        day += timedelta(days=1)
    return slots


def credentials(cfg: dict, interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = Path(cfg["youtube"]["token"])
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise SystemExit("No valid YouTube token. Run: python -m clipbot auth")
        flow = InstalledAppFlow.from_client_secrets_file(cfg["youtube"]["client_secrets"], SCOPES)
        # Headless Pi: open the printed URL on your laptop after `ssh -L 8080:localhost:8080 pi@<pi>`
        creds = flow.run_local_server(port=8080, open_browser=False)
    token.write_text(creds.to_json())
    return creds


def upload(cfg: dict) -> int:
    if not cfg["youtube"].get("enabled"):
        log.info("youtube.enabled is false — clips stay in %s for manual upload", cfg["paths"]["ready"])
        return 0
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    clips = ready_clips(cfg)[: int(cfg["schedule"]["max_uploads_per_run"])]
    if not clips:
        log.info("nothing ready to upload")
        return 0

    state = State(cfg["paths"]["work"])
    youtube = build("youtube", "v3", credentials=credentials(cfg), cache_discovery=False)
    slots = next_slots(cfg, state.taken_slots(), len(clips))
    done = 0
    for folder, publish_at in zip(clips, slots):
        meta = json.loads((folder / "metadata.json").read_text())
        body = {
            "snippet": {
                "title": meta["title"][:100],
                "description": meta["description"][:5000],
                "tags": meta.get("tags", []),
                "categoryId": cfg["youtube"]["category_id"],
            },
            "status": {
                "privacyStatus": "private",  # required for publishAt; YouTube flips it public on schedule
                "publishAt": publish_at,
                "selfDeclaredMadeForKids": bool(cfg["youtube"]["made_for_kids"]),
            },
        }
        media = MediaFileUpload(str(folder / "video.mp4"), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        log.info("uploading %s for %s", folder.name, publish_at)
        response = None
        while response is None:
            _status, response = request.next_chunk()
        video_id = response["id"]
        state.book_slot(publish_at, folder.name, video_id)
        meta.update(video_id=video_id, publish_at=publish_at)
        (folder / "metadata.json").write_text(json.dumps(meta, indent=2))
        shutil.move(str(folder), Path(cfg["paths"]["uploaded"]) / folder.name)
        log.info("uploaded https://youtu.be/%s (publishes %s)", video_id, publish_at)
        done += 1
    return done
