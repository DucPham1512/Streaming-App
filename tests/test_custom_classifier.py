"""Unit tests for broadcaster.custom_classifier.

The classifier is pure Python (math + dicts), no camera or MediaPipe
dependency, so it's easy to unit-test directly. We exercise the
normalize → mean+std → threshold → hysteresis path with a synthetic
"hand" represented as 63 floats (skipping real landmark objects).
"""

import importlib.util
import sys
import pathlib


def _load_classifier_module():
    """Import broadcaster.custom_classifier as a stand-alone module.

    The broadcaster/ package uses relative imports between its modules,
    which the Streaming-App tests can't go through (the test runner has
    `app` on sys.path but not `broadcaster` as a package). Loading the
    file directly via importlib avoids the relative-import problem since
    classifier.py has no inner-package imports.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "broadcaster" / "custom_classifier.py"
    spec = importlib.util.spec_from_file_location(
        "broadcaster_custom_classifier", path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["broadcaster_custom_classifier"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


classifier_mod = _load_classifier_module()
CustomGestureClassifier = classifier_mod.CustomGestureClassifier


def _make_sample(seed: float) -> list[float]:
    """Produce a deterministic 63-float vector around `seed`."""
    return [seed + i * 0.001 for i in range(63)]


def _make_template_row(template_id, name, action, samples):
    return {"id": template_id, "name": name, "action": action, "landmarks": samples}


def test_empty_classifier_returns_none():
    c = CustomGestureClassifier([])
    assert c.template_count == 0
    assert c.classify(_make_sample(0.5)) is None


def test_match_after_hysteresis_then_silence():
    samples = [_make_sample(0.5) for _ in range(5)]
    c = CustomGestureClassifier(
        [_make_template_row(1, "wave", "entertainment_heart", samples)],
        std_factor=10.0,             # generous tolerance for the test
        min_consecutive_frames=3,
    )
    # First two frames: building up consecutive count → None.
    assert c.classify(_make_sample(0.5)) is None
    assert c.classify(_make_sample(0.5)) is None
    # Third frame: fires.
    result = c.classify(_make_sample(0.5))
    assert result is not None
    assert result.name == "wave"
    assert result.action == "entertainment_heart"
    # Fourth frame at same pose: no re-fire (edge-trigger only once).
    assert c.classify(_make_sample(0.5)) is None


def test_unmapped_template_does_not_fire_but_does_recognise():
    samples = [_make_sample(0.5) for _ in range(5)]
    c = CustomGestureClassifier(
        [_make_template_row(1, "wave", "unmapped", samples)],
        std_factor=10.0,
        min_consecutive_frames=2,
    )
    assert c.classify(_make_sample(0.5)) is None  # building hysteresis
    assert c.classify(_make_sample(0.5)) is None  # would fire, but action="unmapped"


def test_distance_far_from_any_template_returns_none():
    samples = [_make_sample(0.5) for _ in range(5)]
    c = CustomGestureClassifier(
        [_make_template_row(1, "wave", "entertainment_heart", samples)],
        std_factor=2.5,
        min_consecutive_frames=1,
    )
    # A frame WILDLY different from the template should not match.
    out = c.classify(_make_sample(5.0))
    assert out is None


def test_malformed_template_skipped_not_crashing():
    bad_row = {"id": 99, "name": "bad", "action": "x", "landmarks": []}
    good_samples = [_make_sample(0.5) for _ in range(3)]
    good_row = _make_template_row(1, "wave", "entertainment_heart", good_samples)
    c = CustomGestureClassifier([bad_row, good_row])
    # Bad row is silently dropped; good row still works.
    assert c.template_count == 1
