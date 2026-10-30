"""Small atomic artifacts shared by camera, API and notification processes."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError


def write_json(path: Path, value) -> None:
    """One writer per artifact; replace instead of accumulating history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, limit: int = 131072):
    def invalid_constant(_value):
        raise ValueError("Non-finite JSON number")

    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Artifact exceeds size limit.")
    return json.loads(content, parse_constant=invalid_constant)


class TrackState(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: int = Field(ge=0)
    class_id: int = Field(ge=0, le=79)
    elapsed_seconds: float = Field(ge=0)
    observed_seconds: float = Field(ge=0)
    stationary_seconds: float = Field(default=0, ge=0)
    motion: Literal["moving", "stationary", "unknown"] = "unknown"
    label: str = Field(default="object", max_length=20)
    activity: Literal[
        "moving", "stationary", "unknown", "possibly_parked", "stopped_in_road", "lingering_in_road"
    ] = "unknown"
    light_observation: Literal[
        "unknown", "not_applicable", "bright_regions_visible", "no_bright_regions_visible"
    ] = "unknown"
    zone: Literal["unknown", "road", "outside_road"] = "unknown"
    road_stationary_seconds: float = Field(default=0, ge=0)


class PersonArrivalState(BaseModel):
    observed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    id: int = Field(ge=0)
    occurred_at: AwareDatetime


class DetectionState(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    class_id: int = Field(ge=0, le=79)
    label: str = Field(max_length=20)
    confidence: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float]


class VisionState(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    monitoring: bool
    state: Literal["starting", "analyzing", "stopped"]
    run_id: str = Field(default="", max_length=64)
    captured_at: datetime | None = None
    frames_analyzed: int = Field(default=0, ge=0)
    inference_ms: float | None = Field(default=None, ge=0)
    analysis_fps: float = Field(default=0, ge=0, le=120)
    capture_fps: float = Field(default=0, ge=0, le=240)
    decoded_fps: float = Field(default=0, ge=0, le=240)
    capture_age_ms: float = Field(default=0, ge=0)
    frames_decoded: int = Field(default=0, ge=0)
    captured_frames: int | None = Field(default=None, ge=0)
    detections: list[DetectionState] | None = Field(default=None, max_length=100)
    people_visible: int = Field(default=0, ge=0, le=100)
    tracks: list[TrackState] = Field(default_factory=list, max_length=100)
    person_arrivals: list[PersonArrivalState] = Field(default_factory=list, max_length=100)
    parking: dict = Field(default_factory=dict)
    road_zone_status: Literal[
        "not_configured", "needs_review", "active", "waiting_for_stable_camera"
    ] = "not_configured"


def read_vision(directory: Path, *, now: datetime | None = None) -> dict:
    """Old/missing/broken frames must never appear as live zero people/free parking."""
    result = {
        "monitoring": False,
        "fresh": False,
        "state": "unavailable",
        "age_seconds": None,
        "people_visible": None,
        "vehicles_visible": None,
        "vehicles_stationary": None,
        "objects_visible": None,
        "analysis_fps": None,
        "capture_fps": None,
        "decoded_fps": None,
        "capture_age_ms": None,
        "inference_ms": None,
        "longest_observed_seconds": None,
        "tracks": [],
        "detections": [],
        "person_arrivals": [],
        "road_zone_status": "unavailable",
        "parking": {"availability": "unknown", "available_spaces": None},
    }
    try:
        state = VisionState.model_validate(read_json(directory / "vision-status.json"))
        result.update(state=state.state, frames_analyzed=state.frames_analyzed)
        if state.captured_at is None or state.captured_at.tzinfo is None:
            return result
        age = ((now or datetime.now(UTC)) - state.captured_at).total_seconds()
        result["age_seconds"] = round(age, 1)
        if not state.monitoring or state.state != "analyzing" or not 0 <= age <= 15:
            if state.monitoring:
                result["state"] = "stale"
            return result
        result.update(state.model_dump(mode="json"))
        result.update(fresh=True, monitoring=True)
        people = [t for t in state.tracks if t.class_id == 0]
        vehicles = [t for t in state.tracks if t.class_id in (2, 3, 5, 7)]
        # Old artifacts remain readable during rollout; new counts always use detections.
        visible = state.detections if state.detections is not None else state.tracks
        result["people_visible"] = sum(d.class_id == 0 for d in visible)
        result["vehicles_visible"] = sum(d.class_id in (2, 3, 5, 7) for d in visible)
        result["objects_visible"] = len(visible)
        result["detections"] = [d.model_dump(mode="json") for d in state.detections or []]
        result["vehicles_stationary"] = sum(t.motion == "stationary" for t in vehicles)
        result["longest_observed_seconds"] = max((t.observed_seconds for t in people), default=0)
        # Candidate geometry cannot establish visibility or legal parking permission.
        result["parking"].update(availability="unknown", available_spaces=None)
    except (OSError, ValueError, TypeError, RecursionError, ValidationError):
        pass
    return result
