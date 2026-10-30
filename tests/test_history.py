from datetime import UTC, datetime, timedelta

from securitypi.history import TrackHistory, read_tracks


def track(id=1, elapsed=5):
    return {
        "id": id,
        "label": "car",
        "elapsed_seconds": elapsed,
        "observed_seconds": elapsed,
        "stationary_seconds": elapsed,
        "activity": "stationary",
    }


def test_history_keeps_brief_tracks_updates_and_survives_restart(tmp_path):
    now = datetime.now(UTC)
    history = TrackHistory(tmp_path, "run-a")
    history.update([track()], now)
    history.update([track(2)], now + timedelta(seconds=1))
    history.update([], now + timedelta(seconds=2))
    history.update([track(elapsed=15)], now + timedelta(seconds=10))
    history.close(now.timestamp() + 10)
    rows = read_tracks(tmp_path, now.timestamp() + 10)["tracks"]
    assert {r["id"] for r in rows} == {1, 2}
    assert rows[0]["observed_seconds"] == 15
    assert rows[0]["first_seen"] == now.timestamp() - 5
    other = TrackHistory(tmp_path, "run-b")
    other.update([track()], now + timedelta(seconds=11))
    other.close(now.timestamp() + 11)
    assert len(read_tracks(tmp_path, now.timestamp() + 11)["tracks"]) == 3


def test_history_expires_old_tracks_and_caps_rows(tmp_path, monkeypatch):
    import securitypi.history as module

    monkeypatch.setattr(module, "MAX_ROWS", 200)
    now = datetime.now(UTC)
    history = TrackHistory(tmp_path, "bounded")
    for batch in range(5):
        history.update(
            [track(id) for id in range(batch * 100, (batch + 1) * 100)],
            now + timedelta(seconds=batch * 10),
        )
    assert history.connection.execute("SELECT count(*) FROM tracks").fetchone()[0] <= 200
    assert history.connection.execute("PRAGMA max_page_count").fetchone()[0] == 4096
    history.close(now.timestamp() + 15 * 86400)
    assert read_tracks(tmp_path, now.timestamp() + 15 * 86400)["tracks"] == []


def test_reading_missing_history_does_not_create_database(tmp_path):
    assert read_tracks(tmp_path, 1000)["available"] is False
    assert not (tmp_path / "tracks.sqlite3").exists()


def test_track_history_uses_the_same_seven_day_retention_as_dashboard(tmp_path):
    now = datetime.now(UTC)
    history = TrackHistory(tmp_path, "seven-days")
    history.update([track(1)], now - timedelta(days=8))
    history.update([track(2)], now - timedelta(days=6))
    history.close(now.timestamp())
    result = read_tracks(tmp_path, now.timestamp())
    assert result["retention_days"] == 7
    assert [row["id"] for row in result["tracks"]] == [2]


def test_reading_missing_relative_history_is_unavailable(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    assert read_tracks(Path("missing"), 1000)["available"] is False
    assert not (tmp_path / "missing").exists()
