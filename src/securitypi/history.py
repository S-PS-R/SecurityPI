"""Compact track summaries: seven days, 50,000 rows and a 16 MiB SQLite page limit."""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

RETENTION_DAYS = 7
RETENTION_SECONDS = RETENTION_DAYS * 86400
MAX_ROWS = 50000
MAX_PAGES = 4096


class TrackHistory:
    """One analyzer owns writes. Batch updates; never store frames or trajectories."""

    def __init__(self, directory: Path, run_id: str):
        self.run_id = run_id
        self.pending = {}
        self.last_flush = 0
        self.failed = False
        self.connection = sqlite3.connect(directory / "tracks.sqlite3", timeout=0.1)
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute(f"PRAGMA max_page_count={MAX_PAGES}")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS tracks ("
            "run_id TEXT, id INTEGER, label TEXT, first_seen REAL, last_seen REAL, "
            "observed_seconds REAL, stationary_seconds REAL, activity TEXT, "
            "PRIMARY KEY (run_id, id))"
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS tracks_last_seen ON tracks(last_seen)")
        self.connection.commit()

    def update(self, tracks, captured_at):
        now = captured_at.timestamp()
        for track in tracks:
            self.pending[track["id"]] = (
                self.run_id,
                track["id"],
                track["label"],
                now - track["elapsed_seconds"],
                now,
                track["observed_seconds"],
                track["stationary_seconds"],
                track["activity"],
            )
            if len(self.pending) >= 100:
                self.flush(now)
        if now - self.last_flush >= 10:
            self.flush(now)

    def flush(self, now):
        try:
            with self.connection:
                self.connection.execute(
                    "DELETE FROM tracks WHERE last_seen < ?", (now - RETENTION_SECONDS,)
                )
                # Recycle oldest rows before the page limit can be reached.
                self.connection.execute(
                    "DELETE FROM tracks WHERE rowid IN (SELECT rowid FROM tracks "
                    "ORDER BY last_seen DESC LIMIT -1 OFFSET ?)",
                    (MAX_ROWS - 100,),
                )
                self.connection.executemany(
                    "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run_id,id) "
                    "DO UPDATE SET last_seen=excluded.last_seen, "
                    "observed_seconds=excluded.observed_seconds, "
                    "stationary_seconds=excluded.stationary_seconds, activity=excluded.activity",
                    self.pending.values(),
                )
            self.failed = False
        except sqlite3.Error:
            if not self.failed:
                logging.getLogger(__name__).warning(
                    "Track history write failed; live analysis continues."
                )
            self.failed = True
        self.pending.clear()
        self.last_flush = now

    def close(self, now):
        self.flush(now)
        self.connection.close()


def read_tracks(directory: Path, now: float, limit: int = 30):
    path = directory / "tracks.sqlite3"
    try:
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
        ) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM tracks WHERE last_seen >= ? ORDER BY last_seen DESC LIMIT ?",
                (now - RETENTION_SECONDS, min(max(limit, 1), 100)),
            ).fetchall()
        return {
            "available": True,
            "retention_days": RETENTION_DAYS,
            "tracks": [dict(row) for row in rows],
        }
    except sqlite3.Error:
        return {"available": False, "retention_days": RETENTION_DAYS, "tracks": []}
