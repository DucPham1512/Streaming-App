# 004 — k-NN Landmark Template Matching for Custom Gestures

**Status:** Accepted
**Date:** 2026-05-16

## Context

Today's gesture detector (`gesture_demo/detector.py`) is **rule-based**: `classify()` inspects which fingers are extended and matches against hardcoded patterns (peace sign, fist, thumbs up, etc.). This is fast, predictable, and easy to debug, but streamers cannot:

1. **Re-map a built-in gesture** to a different action (e.g., "I want peace sign to trigger fireworks instead of confetti").
2. **Record a new custom gesture** that the rule-based system doesn't know about.

A goal of the next phase is to let each streamer customize their gesture → action mapping.

## Decision

Add **two layers** of customization on top of the existing rule-based detector:

1. **Per-user action overrides** for built-in gestures, stored in a new `gesture_overrides` table (`user_id`, `gesture_name`, `action`). The existing rule-based `classify()` still fires; the dispatcher just looks up the user's preferred action.
2. **Per-user custom gestures** via **k-Nearest-Neighbor template matching on hand landmarks**, stored in a new `gesture_templates` table. A streamer records ~10 frames while holding the pose; the system saves the normalized 63-float landmark vectors and matches future frames against them.

Built-in rule-based detection runs **first** every frame; k-NN matching is the fallback when no built-in fires. This guarantees the rule-based floor is never worse than today.

## Alternatives Considered

| Option | Why not |
|---|---|
| **Train a small neural net (MLP)** on landmarks | Needs more training data per gesture (20–50 frames vs. 10), needs a training step (annoying for "record and use immediately"), gives marginally better accuracy at far higher complexity. |
| **Use MediaPipe's Gesture Recognizer (custom training)** | Requires Google's training pipeline, image uploads, fine-tuning. Heavy infrastructure for a demo project. |
| **Pure k-NN with no rule-based floor** | Would replace today's working built-in gestures with templates that depend on recorded data per user. Worse default behavior on day one. |
| **Don't support customization** | Asked for explicitly by the user. |

## Consequences

**Positive:**
- ~100 lines of NumPy for the entire k-NN classifier. No ML training pipeline.
- Recording a new gesture takes ~3 seconds (hold pose, capture 10 frames, done).
- Built-in gestures keep working unchanged for any user who doesn't customize.
- Per-template auto-tuned threshold (`2.5 × within_template_std`) means tight gestures (fist) and loose gestures (wave) both work without manual tuning.
- Explainable: the streamer can see live "distance to each template" in the OpenCV preview while rehearsing.

**Negative:**
- k-NN can be sensitive to camera angle and lighting changes. If a streamer records a gesture under one setup and demos under different lighting, accuracy drops. Mitigation: encourage re-recording before demo day; show live distance scores so the streamer notices.
- Two tables (`gesture_overrides` + `gesture_templates`) instead of one unified table. The unified version would duplicate built-in rows for every user; this design keeps the overrides table small. See plan Step 10 for the resolution algorithm.
- The action picker is currently a fixed list (heart, confetti, fireworks, like, end_stream, mute_toggle). Extending it to user-defined actions (custom sounds, text overlays) is a future concern, not part of this decision.

**Implementation note:** landmark normalization (wrist-centered, palm-scale-invariant) is what makes k-NN robust to absolute position and distance from camera. Without it, "peace sign at top-left of frame" and "peace sign at center" would be different templates. The normalization step lives in `app/broadcaster/custom_classifier.py`.
