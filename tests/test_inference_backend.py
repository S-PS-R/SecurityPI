"""Optional inference preserves the decoder and keeps CPU work bounded."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from securitypi.config import Settings
from securitypi.vision import Detector, VisionError


def fake_runtime(monkeypatch, *, shape=None, fail_run=False):
    calls = {}

    class Options:
        def add_session_config_entry(self, name, value):
            calls[name] = value

    class Session:
        def __init__(self, path, sess_options, providers):
            calls.update(options=sess_options, providers=providers)

        def get_inputs(self):
            return [
                SimpleNamespace(
                    name="images", shape=shape or [1, 3, 640, 640], type="tensor(float)"
                )
            ]

        def get_outputs(self):
            return [SimpleNamespace(name="output")]

        def run(self, outputs, inputs):
            assert inputs["images"].shape == (1, 3, 640, 640)
            if fail_run:
                raise RuntimeError("Internal backend details")
            return [np.array([[[10, 20, 100, 120, 0.9, 0], [20, 30, 100, 120, 0.8, 9]]])]

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(
            disable_telemetry_events=lambda: calls.update(telemetry_disabled=True),
            SessionOptions=Options,
            InferenceSession=Session,
            ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        ),
    )
    return calls


def test_optional_cpu_backend_uses_shared_class_filter_and_bounded_threads(tmp_path, monkeypatch):
    model = tmp_path / "test.onnx"
    model.write_bytes(b"test")
    calls = fake_runtime(monkeypatch)
    detector = Detector(model, threads=2, backend="onnxruntime")
    result = detector.predict(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert [value.class_id for value in result] == [0]
    assert calls["providers"] == ["CPUExecutionProvider"]
    assert calls["telemetry_disabled"]
    assert calls["options"].intra_op_num_threads == 2
    assert calls["options"].inter_op_num_threads == 1
    assert calls["options"].execution_mode == "sequential"
    assert calls["options"].enable_cpu_mem_arena is False
    assert calls["session.intra_op.allow_spinning"] == "0"
    assert calls["session.inter_op.allow_spinning"] == "0"


def test_optional_backend_rejects_incompatible_model_input(tmp_path, monkeypatch):
    model = tmp_path / "test.onnx"
    model.write_bytes(b"test")
    fake_runtime(monkeypatch, shape=[1, 3, 320, 320])
    with pytest.raises(VisionError, match="Cannot load"):
        Detector(model, backend="onnxruntime")


def test_optional_backend_missing_package_has_actionable_error(tmp_path, monkeypatch):
    model = tmp_path / "test.onnx"
    model.write_bytes(b"test")
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    with pytest.raises(VisionError, match="requirements/onnxruntime.txt"):
        Detector(model, backend="onnxruntime")


def test_optional_backend_failure_does_not_expose_internal_details(tmp_path, monkeypatch):
    model = tmp_path / "test.onnx"
    model.write_bytes(b"test")
    fake_runtime(monkeypatch, fail_run=True)
    detector = Detector(model, backend="onnxruntime")
    with pytest.raises(VisionError, match="CPU runtime inference failed") as error:
        detector.predict(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert "Internal backend" not in str(error.value)


def test_portable_default_does_not_require_optional_backend():
    assert Settings().vision.backend == "opencv"
