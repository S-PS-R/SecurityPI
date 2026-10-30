"""Every new confirmed person is independent; mock senders never contact a phone."""

import pytest

from securitypi.config import HomeAssistantSettings
from securitypi.notifications import NotificationQueue


def observation(*ids):
    return {
        "monitoring": True,
        "run_id": "entry-run",
        "tracks": [{"id": key, "class_id": 0, "observed_seconds": 10} for key in ids],
    }


def test_new_people_are_not_suppressed_by_another_person(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    sent = []

    def sender(message):
        sent.append(message)
        return "accepted"

    queue.tick(observation(1), 1000, sender)
    queue.tick(observation(1, 2), 1001, sender)
    assert len(sent) == 2
    assert sent[1]["message"] == "Person detected."
    queue.close()


def test_every_person_in_a_small_group_gets_their_own_alert(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    sent = []
    queue.tick(observation(1, 2, 3, 4), 1000, lambda message: sent.append(message) or "accepted")
    assert len(sent) == 4
    queue.close()


def test_active_person_is_not_realerted_after_message_history_rolls_over(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    sent = []

    def sender(message):
        sent.append(message)
        return "accepted"

    queue.tick(observation(1), 1000, sender)
    for i in range(2, 650):
        queue.tick(observation(1, i), 1000 + i, sender)
    assert len(sent) == 649
    assert sum(message["data"]["tag"] == "securitypi-entry-run:1" for message in sent) == 1
    assert queue.db.execute("SELECT count(*) FROM events").fetchone()[0] <= 100
    assert queue.db.execute("SELECT count(*) FROM announced").fetchone()[0] <= 500
    queue.close()


def test_first_confirmed_track_needs_no_observation_delay_and_same_id_is_not_repeated(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    current = observation(1)
    current["tracks"][0]["observed_seconds"] = 0
    calls = []

    def sender(message):
        calls.append(message)
        return "accepted"

    assert queue.tick(current, 1000, sender) == {"accepted": 1}
    queue.close()
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    queue.tick(observation(), 1001, sender)
    queue.tick(current, 1002, sender)
    assert len(calls) == 1
    queue.tick(observation(2), 1003, sender)
    assert len(calls) == 2
    queue.close()


def test_brief_confirmed_appearance_is_retained_until_notification_poll(tmp_path):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from securitypi.state import read_vision, write_json
    from securitypi.tracking import PersonArrivals

    arrivals = PersonArrivals()
    records, new = arrivals.update(
        [SimpleNamespace(id=9, class_id=0)], datetime.fromtimestamp(1000, UTC)
    )
    assert new
    records, new = arrivals.update([], datetime.fromtimestamp(1001, UTC))
    assert not new and len(records) == 1
    current = observation()
    current.update(
        state="analyzing",
        captured_at=datetime.fromtimestamp(1001, UTC).isoformat(),
        person_arrivals=records,
    )
    write_json(tmp_path / "vision-status.json", current)
    validated = read_vision(tmp_path, now=datetime.fromtimestamp(1002, UTC))
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    sent = []
    queue.tick(validated, 1002, lambda message: sent.append(message) or "accepted")
    assert len(sent) == 1 and sent[0]["message"] == "Person detected."
    queue.close()


def test_arrival_cache_is_bounded_and_does_not_reannounce_an_active_track():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from securitypi.tracking import PersonArrivals

    cache = PersonArrivals()
    for i in range(150):
        records, _ = cache.update(
            [SimpleNamespace(id=i, class_id=0)], datetime.fromtimestamp(1000 + i / 2, UTC)
        )
    assert len(records) == 100
    records, new = cache.update(
        [SimpleNamespace(id=149, class_id=0)], datetime.fromtimestamp(1300, UTC)
    )
    assert not records and not new
    assert len(cache.known) == 1


def test_expired_or_future_arrival_is_not_a_new_phone_alert(tmp_path):
    from datetime import UTC, datetime

    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    current = observation()
    current["person_arrivals"] = [
        {"id": i, "occurred_at": datetime.fromtimestamp(stamp, UTC).isoformat()}
        for i, stamp in enumerate([800, 1001])
    ]
    assert queue.tick(current, 1000, lambda _: pytest.fail("Stale arrival sent")) == {}
    queue.close()


def test_groups_drain_without_global_timer_and_keep_pending_storage_bounded(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=0))
    sent = []
    current = observation(*range(25))
    for i in range(8):
        queue.tick(current, 1000 + i, lambda message: sent.append(message) or "accepted")
        assert (
            queue.db.execute("SELECT count(*) FROM events WHERE state='pending'").fetchone()[0]
            <= 20
        )
    assert len(sent) == 25
    assert len({message["data"]["tag"] for message in sent}) == 25
    assert queue.db.execute("SELECT count(*) FROM announced").fetchone()[0] <= 500
    queue.close()
