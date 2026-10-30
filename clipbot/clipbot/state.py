"""Tiny SQLite store so the bot never processes a source twice or double-books a slot."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class State:
    def __init__(self, work_dir: str):
        self.db = sqlite3.connect(Path(work_dir) / "state.db")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                key TEXT PRIMARY KEY, status TEXT, clips INTEGER, at REAL
            );
            CREATE TABLE IF NOT EXISTS slots (
                publish_at TEXT PRIMARY KEY, clip TEXT, video_id TEXT
            );
            """
        )

    def seen(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM sources WHERE key=?", (key,)).fetchone() is not None

    def mark(self, key: str, status: str, clips: int = 0) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO sources VALUES (?,?,?,?)", (key, status, clips, time.time())
        )
        self.db.commit()

    def taken_slots(self) -> set[str]:
        return {row[0] for row in self.db.execute("SELECT publish_at FROM slots")}

    def book_slot(self, publish_at: str, clip: str, video_id: str) -> None:
        self.db.execute("INSERT INTO slots VALUES (?,?,?)", (publish_at, clip, video_id))
        self.db.commit()
