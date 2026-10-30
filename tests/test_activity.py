"""Motion, occlusion and road-rule contracts without camera, model or phone access."""

import asyncio
import time
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import numpy as np
import pytest
from pydantic import ValidationError

from securitypi.activity import Activities, light_evidence
from securitypi.api import create_app
from securitypi.config import ActivitySettings, HomeAssistantSettings, Settings
from securitypi.notifications import NotificationQueue
from securitypi.state import read_vision, write_json
from securitypi.tracking import Track, Tracker
from securitypi.vision import Detection

ROAD = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
IMAGE = np.zeros((200, 300, 3), np.uint8)


def car(**changes):
    value = Track(1, 2, (0.4, 0.4, 0.6, 0.6), 0.9, 120, 120, 60, "stationary")
    return replace(value, **changes)


def vision(tracks, *, zone="active"):
    return {
        "run_id": "activity-test",
        "monitoring": True,
        "state": "analyzing",
        "captured_at": datetime.now(UTC).isoformat(),
        "tracks": tracks,
        "road_zone_status": zone,
    }


def test_stationary_motion_survives_small_detector_jitter():
    tracker = Tracker()
    ids = set()
    for i in range(30):
        offset = 0.002 if i % 2 else -0.002
        tracks = tracker.update(
            [
                Detection(2, 0.9, (0.4 + offset, 0.4, 0.6 + offset, 0.6)),
            ],
            i / 2,
        )
        if tracks:
            ids.add(tracks[0].id)
    assert len(ids) == 1
    assert tracks[0].motion == "stationary"
    assert tracks[0].stationary_seconds > 10


def test_slow_drift_and_resumed_motion_do_not_remain_parked():
    tracker = Tracker()
    for i in range(25):
        tracker.update([Detection(2, 0.9, (0.2, 0.4, 0.4, 0.6))], i / 2)
    for i in range(25, 65):
        shift = (i - 25) * 0.003
        tracks = tracker.update([Detection(2, 0.9, (0.2 + shift, 0.4, 0.4 + shift, 0.6))], i / 2)
    assert tracks[0].motion == "moving"
    assert tracks[0].stationary_seconds < 5


def test_unobserved_gap_does_not_accumulate_stationary_time():
    tracker = Tracker()
    for i in range(20):
        tracker.update([Detection(2, 0.9, (0.4, 0.4, 0.6, 0.6))], i / 2)
    tracker.update([], 10)
    track = tracker.update([Detection(2, 0.9, (0.4, 0.4, 0.6, 0.6))], 11)[0]
    assert track.stationary_seconds == 0
    assert track.motion == "unknown"


def test_person_and_each_vehicle_class_have_distinct_track_numbers():
    tracks = Tracker().update(
        [Detection(cls, 0.9, (0.4, 0.4, 0.6, 0.6)) for cls in (0, 2, 3, 5, 7)], 0
    )
    assert len({track.id for track in tracks}) == 5


def test_lights_are_only_pixel_evidence_and_unknown_when_not_visible():
    box = car().box
    assert light_evidence(IMAGE, box, True) == "no_bright_regions_visible"
    bright = IMAGE.copy()
    bright[90:100, 130:140] = 255
    assert light_evidence(bright, box, True) == "bright_regions_visible"
    assert light_evidence(bright, box, False) == "unknown"
    assert light_evidence(IMAGE, (0, 0.4, 0.6, 0.6), True) == "unknown"
    assert light_evidence(IMAGE, (0.4, 0.4, 0.41, 0.41), True) == "unknown"


def test_parking_is_provisional_and_roadway_stop_is_never_classified_parked():
    unmarked = Activities(ActivitySettings())
    assert unmarked.update([car()], IMAGE, 0, "stable")[0]["activity"] == "possibly_parked"
    assert unmarked.zone_status == "not_configured"
    marked = Activities(ActivitySettings(road_polygon=ROAD))
    assert marked.update([car()], IMAGE, 0, "stable")[0]["activity"] == "stopped_in_road"
    assert marked.update([car()], IMAGE, 29, "stable")[0]["activity"] == "stopped_in_road"
    result = marked.update([car()], IMAGE, 30, "stable")[0]
    assert result["activity"] == "lingering_in_road"
    assert result["road_stationary_seconds"] == 30


def test_road_duration_does_not_include_time_before_entry_or_lost_detections():
    activity = Activities(ActivitySettings(road_polygon=ROAD))
    outside = car(box=(0.02, 0.1, 0.1, 0.2))
    activity.update([outside], IMAGE, 0, "stable")
    inside = activity.update([car()], IMAGE, 60, "stable")[0]
    assert inside["road_stationary_seconds"] == 0
    activity.update([], IMAGE, 61, "stable")
    assert not activity.current
    assert activity.update([car()], IMAGE, 100, "stable")[0]["road_stationary_seconds"] == 0
    moving = activity.update([car(motion="moving", stationary_seconds=0)], IMAGE, 101, "stable")[0]
    assert moving["activity"] == "moving" and moving["road_stationary_seconds"] == 0


@pytest.mark.parametrize("scene", ["moved", "unverifiable"])
def test_road_outline_stays_invalid_after_camera_or_visibility_change(scene):
    activity = Activities(ActivitySettings(road_polygon=ROAD))
    activity.update([car()], IMAGE, 0, "stable")
    invalid = activity.update([car()], IMAGE, 31, scene)[0]
    assert invalid["motion"] == "unknown"
    assert activity.zone_status == "needs_review"
    stable = activity.update([car()], IMAGE, 70, "stable")[0]
    assert stable["zone"] == "unknown"
    assert stable["activity"] != "lingering_in_road"


@pytest.mark.parametrize(
    "polygon",
    [
        ROAD[:2],
        [(0, 0), (1.1, 0), (0, 1)],
        [(0, 0), (0.5, 0.5), (1, 1)],
        [(0, 0), (1, 0), (float("nan"), 1)],
    ],
)
def test_invalid_road_outlines_are_rejected(polygon):
    with pytest.raises(ValidationError):
        ActivitySettings(road_polygon=polygon)


def test_api_keeps_car_motion_light_and_road_fields_and_clears_stopped_data(tmp_path):
    activity = Activities(ActivitySettings(road_polygon=ROAD))
    activity.update([car()], IMAGE, 0, "stable")
    current = vision(activity.update([car()], IMAGE, 31, "stable"))
    write_json(tmp_path / "vision-status.json", current)
    result = read_vision(tmp_path)
    track = result["tracks"][0]
    assert track["label"] == "car"
    assert track["activity"] == "lingering_in_road"
    assert track["stationary_seconds"] == 60
    assert track["light_observation"] == "no_bright_regions_visible"
    current["monitoring"] = False
    write_json(tmp_path / "vision-status.json", current)
    assert read_vision(tmp_path)["tracks"] == []
    assert read_vision(tmp_path)["road_zone_status"] == "unavailable"


def test_road_alert_includes_track_deduplicates_and_cancels_when_car_moves(tmp_path):
    activity = Activities(ActivitySettings(road_polygon=ROAD))
    activity.update([car()], IMAGE, 0, "stable")
    tracks = activity.update([car()], IMAGE, 31, "stable")
    config = HomeAssistantSettings()
    queue = NotificationQueue(tmp_path / "outbox.db", config)
    calls = []

    def retry(payload):
        calls.append(payload)
        return "retry"

    assert queue.tick(vision(tracks), 1000, retry) == {"pending": 1}
    assert "Car stationary" in calls[0]["message"] and "31 seconds" in calls[0]["message"]
    assert "#" not in calls[0]["message"]
    assert "parked" not in calls[0]["message"]
    assert queue.tick(vision(tracks), 1001, retry) == {"pending": 1}
    assert len(calls) == 1
    moving = activity.update([car(motion="moving", stationary_seconds=0)], IMAGE, 32, "stable")
    assert queue.tick(vision(moving), 1011, retry) == {"cancelled": 1}
    assert len(calls) == 1
    assert queue.recent()[0]["state"] == "cancelled"
    queue.close()


@pytest.mark.parametrize("zone", ["not_configured", "needs_review", "unavailable"])
def test_no_road_notification_without_valid_camera_zone(tmp_path, zone):
    track = {
        "id": 1,
        "class_id": 2,
        "observed_seconds": 100,
        "motion": "stationary",
        "zone": "road",
        "activity": "lingering_in_road",
    }
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings())
    assert (
        queue.tick(vision([track], zone=zone), 1000, lambda _: pytest.fail("Unexpected push")) == {}
    )
    queue.close()


def test_recent_message_history_is_bounded_and_exposed_without_push_metadata(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings())
    for i in range(9):
        person = {"id": i, "class_id": 0, "observed_seconds": 12}
        queue.tick(vision([person]), 1000 + i * 301, lambda _: "accepted")
    recent = queue.recent()
    assert len(recent) == 5
    assert recent[0]["track_id"] == 8
    assert all("data" not in event for event in recent)
    queue.close()
    write_json(
        tmp_path / "notifications.json",
        {
            "running": True,
            "updated_at": time.time(),
            "events": {"accepted": 9},
            "recent_events": recent,
        },
    )

    async def check():
        settings = Settings(
            storage={"directory": tmp_path},
            home_assistant={"notifications_enabled": True, "notify_service": "mobile_app_test"},
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
        ) as client:
            result = (await client.get("/api/notifications")).json()
            assert len(result["recent_events"]) == 5
            assert result["recent_events"][0]["message"] == "Person detected."

    asyncio.run(check())


def test_five_second_person_threshold_does_not_send_early(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings(person_seconds=5))
    sent = []

    def sender(payload):
        sent.append(payload)
        return "accepted"

    person = {"id": 5, "class_id": 0, "observed_seconds": 4.9}
    assert queue.tick(vision([person]), 1000, sender) == {}
    person["observed_seconds"] = 5.0
    assert queue.tick(vision([person]), 1001, sender) == {"accepted": 1}
    assert len(sent) == 1
    assert sent[0]["message"] == "Person detected."
    queue.close()
