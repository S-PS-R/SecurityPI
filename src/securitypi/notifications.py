"""Opt-in Home Assistant push worker with a small durable outbox.

The camera never waits for the network. Home Assistant accepting a request is
not proof of iPhone receipt. Stable tags reduce duplicates after ambiguous retries.
"""

import json
import os
import sqlite3
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from securitypi.config import ConfigError
from securitypi.state import read_vision, write_json


def notification_candidates(vision, config, now):
    """Only describe observable events; road alerts require a valid configured zone."""
    if not vision["monitoring"] or not vision.get("run_id"):
        return []
    candidates = []
    people = {t["id"]: (t, None) for t in vision.get("tracks", []) if t["class_id"] == 0}
    for arrival in vision.get("person_arrivals", []):
        occurred = datetime.fromisoformat(arrival["occurred_at"]).timestamp()
        if (
            0 <= now - occurred < config.expiry_seconds
            and arrival.get("observed_seconds", 0) >= config.person_seconds
        ):
            people[arrival["id"]] = (arrival, occurred)
    for person, occurred in people.values():
        if person.get("observed_seconds", 0) < config.person_seconds:
            continue
        candidates.append(
            (f"{vision['run_id']}:{person['id']}", "SecurityPI", "Person detected.", occurred)
        )
    for track in vision.get("tracks", []):
        key = f"{vision['run_id']}:{track['id']}"
        if (
            track["class_id"] in (2, 3, 5, 7)
            and vision.get("road_zone_status") == "active"
            and track.get("zone") == "road"
            and track.get("motion") == "stationary"
            and track.get("activity") == "lingering_in_road"
        ):
            candidates.insert(
                0,
                (
                    key + ":road",
                    "SecurityPI: vehicle stationary in roadway",
                    f"{track.get('label', 'Vehicle').capitalize()} "
                    "stationary in the "
                    f"marked roadway for {int(track.get('road_stationary_seconds', 0))} seconds. "
                    "Reason for stopping is unknown. Open SecurityPI to review.",
                    None,
                ),
            )
    return candidates


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def send_notification(config, payload):
    token = os.environ.get(config.token_env)
    if not token:
        return "rejected"
    request = Request(
        str(config.url).rstrip("/") + "/api/services/notify/" + config.notify_service,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    # Do not forward the bearer token through redirects or environment proxies.
    opener = build_opener(NoRedirect(), ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return "accepted" if 200 <= response.status < 300 else "rejected"
    except HTTPError as exc:
        exc.close()
        return "retry" if exc.code in (408, 429) or exc.code >= 500 else "rejected"
    except (OSError, URLError):
        return "retry"


class NotificationQueue:
    """Single worker per database. At most 20 pending and 100 total event rows."""

    def __init__(self, path, config):
        self.config = config
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA max_page_count=256")  # 1 MiB with default 4 KiB pages.
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                key TEXT PRIMARY KEY, created REAL NOT NULL, expires REAL NOT NULL,
                next_try REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS announced (key TEXT PRIMARY KEY, last_seen REAL NOT NULL);
            INSERT OR IGNORE INTO announced SELECT key,created FROM events;
        """)

    def close(self):
        self.db.close()

    def recent(self):
        rows = self.db.execute(
            "SELECT key,created,state,payload FROM events ORDER BY created DESC,rowid DESC LIMIT 5"
        )
        return [
            {
                "created": row["created"],
                "state": row["state"],
                "track_id": int(row["key"].split(":")[1]),
                **{
                    key: value
                    for key, value in json.loads(row["payload"]).items()
                    if key in ("title", "message")
                },
            }
            for row in rows
        ]

    def tick(self, vision, now, sender, *, dry_run=False):
        candidates = notification_candidates(vision, self.config, now)
        with self.db:
            self.db.execute(
                "UPDATE events SET state='expired' WHERE state='pending' AND expires<=?", (now,)
            )
            if not vision["monitoring"]:
                self.db.execute("UPDATE events SET state='cancelled' WHERE state='pending'")
            else:
                # Drop events from an earlier analysis run after a camera/process restart.
                prefix = vision.get("run_id", "") + ":"
                self.db.execute(
                    "UPDATE events SET state='cancelled' WHERE state='pending' "
                    "AND substr(key,1,?)!=?",
                    (len(prefix), prefix),
                )
                self._enqueue(candidates, now)
                # Arrival events can survive a brief appearance; roadway alerts
                # still cancel as soon as the current stop no longer qualifies.
                keys = [candidate[0] for candidate in candidates]
                if keys:
                    placeholders = ",".join("?" for _ in keys)
                    self.db.execute(
                        f"UPDATE events SET state='cancelled' WHERE state='pending' "
                        f"AND key NOT IN ({placeholders})",
                        keys,
                    )
                else:
                    self.db.execute("UPDATE events SET state='cancelled' WHERE state='pending'")
            events = self.db.execute(
                "SELECT * FROM events WHERE state='pending' AND next_try<=? "
                "ORDER BY created LIMIT 5",
                (now,),
            ).fetchall()
            for event in events:
                outcome = "simulated" if dry_run else sender(json.loads(event["payload"]))
                attempts = event["attempts"] + 1
                state = "pending" if outcome == "retry" and attempts < 5 else outcome
                if state == "retry":
                    state = "failed"
                self.db.execute(
                    "UPDATE events SET state=?, attempts=?, next_try=? WHERE key=?",
                    (state, attempts, now + min(120, 10 * 2 ** (attempts - 1)), event["key"]),
                )
                if outcome == "retry":
                    break  # A slow/unavailable phone service must not stall a whole group.
            # Deduplication outlives the visible 100-message history. Refresh active
            # and recently arrived IDs, then keep at most 500 small records.
            protected = {item[0] for item in candidates}
            for track in vision.get("tracks", []) if vision["monitoring"] else []:
                key = f"{vision.get('run_id', '')}:{track['id']}"
                protected.update((key, key + ":road"))
            self.db.executemany(
                "UPDATE announced SET last_seen=? WHERE key=?",
                [(now, key) for key in protected],
            )
            self.db.execute("DELETE FROM announced WHERE last_seen<?", (now - 180,))
            self.db.execute("""
                DELETE FROM announced WHERE key IN (
                    SELECT key FROM announced ORDER BY last_seen DESC,rowid DESC
                    LIMIT -1 OFFSET 500
                )
            """)
            self.db.execute("""
                DELETE FROM events WHERE key IN (
                    SELECT key FROM events ORDER BY created DESC, rowid DESC LIMIT -1 OFFSET 100
                )
            """)
        return dict(self.db.execute("SELECT state,count(*) FROM events GROUP BY state").fetchall())

    def _enqueue(self, candidates, now):
        if not candidates:
            return
        pending = self.db.execute("SELECT count(*) FROM events WHERE state='pending'").fetchone()[0]
        if pending >= 20:
            return
        for key, title, message, occurred in candidates:
            if self.db.execute("SELECT 1 FROM announced WHERE key=?", (key,)).fetchone():
                continue
            created = now if occurred is None else occurred
            payload = {
                "title": title,
                "message": message,
                "data": {"tag": "securitypi-" + key, "url": "/securitypi-dashboard/overview"},
            }
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO events(key,created,expires,next_try,state,payload) "
                "VALUES(?,?,?,?,'pending',?)",
                (key, created, created + self.config.expiry_seconds, now, json.dumps(payload)),
            ).rowcount
            if inserted:
                self.db.execute("INSERT OR IGNORE INTO announced VALUES(?,?)", (key, now))
                pending += 1
                if pending >= 20:
                    break


def run_notifications(settings, args):
    config = settings.home_assistant
    if not args.dry_run and (
        not config.notifications_enabled or not os.environ.get(config.token_env)
    ):
        raise ConfigError(
            "Enable notifications, configure the phone service and set the token env."
        )
    directory = settings.storage.directory
    # Dry runs cannot consume live events or delay future real notifications.
    suffix = "-dry-run" if args.dry_run else ""
    queue = NotificationQueue(directory / f"notifications{suffix}.sqlite3", config)
    started = time.monotonic()
    stats = {}
    try:
        while args.seconds == 0 or time.monotonic() - started < args.seconds:
            stats = queue.tick(
                read_vision(directory),
                time.time(),
                lambda payload: send_notification(config, payload),
                dry_run=args.dry_run,
            )
            write_json(
                directory / f"notifications{suffix}.json",
                {
                    "updated_at": time.time(),
                    "running": True,
                    "dry_run": args.dry_run,
                    "events": stats,
                    "recent_events": queue.recent(),
                    "delivery": "phone_receipt_unverified",
                },
            )
            time.sleep(2)
    except KeyboardInterrupt:
        return 130
    finally:
        recent = queue.recent()
        queue.close()
        write_json(
            directory / f"notifications{suffix}.json",
            {
                "updated_at": time.time(),
                "running": False,
                "dry_run": args.dry_run,
                "events": stats,
                "recent_events": recent,
                "delivery": "phone_receipt_unverified",
            },
        )
    return 0
