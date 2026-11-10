import time
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.core.logging import log_event
from app.core.metrics import get_metrics_collector


class SpeechToText(ABC):

    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        pass


class WhisperSTT(SpeechToText):

    def __init__(self, model_name: str = "small"):
        self.model_name = model_name
        self._model = None
        self.load_count = 0
        self._lock = threading.RLock()

    def _load_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    import whisper

                    self._model = whisper.load_model(self.model_name)
                    self.load_count += 1

        return self._model

    def transcribe(self, audio_path: str, prompt: Optional[str] = None) -> str:

        path = Path(audio_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {audio_path}"
            )

        start_time = time.perf_counter()
        try:
            model = self._load_model()

            options = {
                "fp16": False,
                "task": "transcribe",
                "temperature": 0.0,
                "condition_on_previous_text": False,
                "verbose": False,
            }
            if prompt and prompt.strip():
                options["initial_prompt"] = prompt.strip()[:400]
            # Whisper's model object is shared across requests; serialize inference
            # so concurrent candidates cannot race its decoder or exhaust RAM.
            with self._lock:
                result = model.transcribe(str(path), **options)

            text = result.get("text", "").strip()

            if not text:
                raise ValueError(
                    "Whisper returned an empty transcription."
                )

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log_event(
                event="stt_completed",
                audio_path=str(path),
                duration_ms=duration_ms,
            )
            get_metrics_collector().record_stt(success=True, latency_ms=duration_ms)
            return text

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            get_metrics_collector().record_stt(success=False, latency_ms=duration_ms)
            raise


_shared_whisper_instance: Optional[WhisperSTT] = None


_shared_whisper_lock = threading.Lock()


def get_whisper_stt(model_name: str = "small") -> WhisperSTT:
    """Returns singleton WhisperSTT instance to prevent reloading weights on each request."""
    global _shared_whisper_instance
    with _shared_whisper_lock:
        if _shared_whisper_instance is None or _shared_whisper_instance.model_name != model_name:
            _shared_whisper_instance = WhisperSTT(model_name=model_name)
        return _shared_whisper_instance

