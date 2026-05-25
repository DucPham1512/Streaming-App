"""Laptop-side broadcaster components for the streaming app.

Kept as a top-level sibling to `app/` rather than `app/broadcaster/` so it
can run without importing Flask, SQLAlchemy, MinIO, etc. — the broadcaster
process only needs OpenCV, MediaPipe, and the LiveKit RTC SDK.

See docs/decisions/003-python-broadcaster-not-phone.md.
"""
