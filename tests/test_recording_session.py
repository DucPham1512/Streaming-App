"""Unit tests for broadcaster.recording.RecordingSession.

The state machine is pure Python so we drive it directly with a
monkey-patched `time.monotonic` and a list of fake-landmark frames.
"""
import importlib.util
import pathlib
import sys
import types


def _load(module_name: str, file_name: str):
    """Load a single broadcaster/ file as a standalone module.

    Mirrors test_custom_classifier.py — we avoid the relative-import
    machinery by loading the file directly.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "broadcaster" / file_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# recording.py imports from .custom_classifier via relative import,
# which won't work in our hand-load setup. We work around it by
# providing a stub custom_classifier module before loading recording.py.
_fake_normalize = lambda lm: list(lm) if (
    isinstance(lm, list) and len(lm) == 63
    and all(isinstance(x, (int, float)) for x in lm)
) else None
stub = types.ModuleType("broadcaster.custom_classifier")
stub._normalize = _fake_normalize
sys.modules["broadcaster.custom_classifier"] = stub
# Also seed an empty broadcaster package so `from .custom_classifier`
# inside recording.py resolves.
pkg = types.ModuleType("broadcaster")
pkg.__path__ = [str(pathlib.Path(__file__).resolve().parent.parent / "broadcaster")]
sys.modules.setdefault("broadcaster", pkg)

recording_mod = _load("broadcaster.recording", "recording.py")
RecordingSession = recording_mod.RecordingSession


def _good_sample():
    return [0.0] * 63


def test_phase_progresses(monkeypatch):
    fake_clock = [100.0]
    monkeypatch.setattr(
        recording_mod.time, "monotonic", lambda: fake_clock[0]
    )
    # started_at must be passed explicitly: the dataclass default_factory
    # holds a reference to the original time.monotonic that was captured
    # at module load (before the test's monkeypatch).
    s = RecordingSession(
        name="wave", countdown_seconds=3, target_samples=3,
        started_at=fake_clock[0],
    )

    # t = 0: in countdown
    assert s.phase == "countdown"
    s.tick(_good_sample())                 # ignored during countdown
    assert len(s.samples) == 0

    # t = 3: countdown done, now capturing
    fake_clock[0] = 103.0
    assert s.phase == "capturing"
    s.tick(_good_sample())                 # ok
    s.tick(None)                           # no hand → skipped, not aborted
    s.tick(_good_sample())                 # ok
    s.tick(_good_sample())                 # ok → reaches target
    assert s.phase == "done"
    assert len(s.samples) == 3


def test_abort_locks_phase():
    s = RecordingSession(name="x", countdown_seconds=0, target_samples=1)
    s.abort()
    assert s.phase == "aborted"
    # tick after abort is a no-op
    s.tick(_good_sample())
    assert s.samples == []


def test_countdown_label_decreases(monkeypatch):
    fake_clock = [100.0]
    monkeypatch.setattr(recording_mod.time, "monotonic", lambda: fake_clock[0])
    s = RecordingSession(
        name="bow", countdown_seconds=3, started_at=fake_clock[0],
    )
    assert "3" in s.countdown_label()
    fake_clock[0] = 101.5
    assert "2" in s.countdown_label() or "1" in s.countdown_label()


def test_upload_recording_posts_correct_payload():
    sent = {}

    class FakeApi:
        def post(self, path, body):
            sent["path"] = path
            sent["body"] = body
            return {"template": {"id": 42, "name": body["name"]}}

    s = RecordingSession(name="wave", handedness="Right")
    s.samples = [_good_sample(), _good_sample()]
    resp = recording_mod.upload_recording(FakeApi(), s)

    assert sent["path"] == "/api/v1/gestures/templates"
    assert sent["body"]["name"] == "wave"
    assert sent["body"]["action"] == "unmapped"
    assert sent["body"]["handedness"] == "Right"
    assert len(sent["body"]["landmarks"]) == 2
    assert resp["template"]["id"] == 42
