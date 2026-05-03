"""Speech-to-Text engine service.

Wraps faster-whisper (if available) behind a simple interface so the
rest of the application doesn't care which STT backend is used.

If faster-whisper is not installed the engine falls back to a stub that
returns a placeholder string — useful for development and testing without
GPU/model dependencies.
"""

import io
import logging
import tempfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import faster-whisper; fall back gracefully
# ---------------------------------------------------------------------------
try:
    from faster_whisper import WhisperModel

    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False
    logger.warning(
        "faster-whisper is not installed. "
        "STT engine will use a stub. Install with: pip install faster-whisper"
    )


class STTEngine:
    """Speech-to-Text processor.

    Usage::

        engine = STTEngine()             # uses "base" model by default
        text = engine.transcribe(audio_bytes)
    """

    def __init__(self, model_size="base", device="cpu", compute_type="int8"):
        self._model = None
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type

        if _WHISPER_AVAILABLE:
            try:
                self._model = WhisperModel(
                    model_size, device=device, compute_type=compute_type
                )
                logger.info("Loaded faster-whisper model: %s", model_size)
            except Exception as exc:
                logger.error("Failed to load Whisper model: %s", exc)
                self._model = None

    @property
    def is_available(self):
        """Return True if a real STT model is loaded."""
        return self._model is not None

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe raw audio bytes to text.

        Parameters
        ----------
        audio_bytes : bytes
            Raw audio data (WAV, WebM, PCM, etc.).

        Returns
        -------
        str
            The transcribed text, or a stub message if no model is loaded.
        """
        if self._model is None:
            return "[STT stub] Audio received — install faster-whisper for real transcription."

        # Write bytes to a temp file so faster-whisper can read it
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            segments, _info = self._model.transcribe(tmp_path, beam_size=5)
            text = " ".join(segment.text.strip() for segment in segments)
            return text if text else ""
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            return f"[STT error] {exc}"


# Module-level singleton
stt_engine = STTEngine()
