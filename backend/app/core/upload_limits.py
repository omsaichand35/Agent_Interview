"""Upload Limits Configuration (Requirement F2.1, F2.8).

Defines centralized, configurable limits for all untrusted file uploads:
- Resumes: max file size, page limits, min/max page dimensions
- Images: max file size, pixel dimensions, color channels
- Audio: max file size, duration, format constraints

Prevents resource exhaustion attacks (PDF bombs, zip bombs, memory exhaustion, decompression bombs).
"""

from dataclasses import dataclass
import os
from typing import Tuple


@dataclass(frozen=True)
class ResumeLimits:
    """Configurable security boundaries for uploaded candidate resumes."""
    max_size_bytes: int = int(os.getenv("MAX_RESUME_SIZE_BYTES", 10 * 1024 * 1024))  # 10 MB
    max_pages: int = int(os.getenv("MAX_RESUME_PAGES", 15))
    min_page_dimension_pts: float = float(os.getenv("MIN_RESUME_PAGE_DIM", 72.0))     # 1 inch (72 pts)
    max_page_dimension_pts: float = float(os.getenv("MAX_RESUME_PAGE_DIM", 2880.0))   # 40 inches (2880 pts)
    allowed_extensions: Tuple[str, ...] = (".pdf",)
    allowed_mime_types: Tuple[str, ...] = (
        "application/pdf",
        "application/x-pdf",
        "application/acrobat",
        "applications/vnd.pdf",
        "text/pdf",
        "text/x-pdf",
    )


@dataclass(frozen=True)
class ImageLimits:
    """Configurable security boundaries for uploaded identity & verification images."""
    max_size_bytes: int = int(os.getenv("MAX_IMAGE_SIZE_BYTES", 5 * 1024 * 1024))    # 5 MB
    min_width: int = int(os.getenv("MIN_IMAGE_WIDTH", 50))
    min_height: int = int(os.getenv("MIN_IMAGE_HEIGHT", 50))
    max_width: int = int(os.getenv("MAX_IMAGE_WIDTH", 4096))
    max_height: int = int(os.getenv("MAX_IMAGE_HEIGHT", 4096))
    allowed_extensions: Tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
    allowed_mime_types: Tuple[str, ...] = (
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    )
    allowed_channels: Tuple[int, ...] = (3,)  # BGR/RGB 3-channel for face verification


@dataclass(frozen=True)
class AudioLimits:
    """Configurable security boundaries for interview audio recordings."""
    max_size_bytes: int = int(os.getenv("MAX_AUDIO_SIZE_BYTES", 25 * 1024 * 1024))   # 25 MB
    max_duration_seconds: float = float(os.getenv("MAX_AUDIO_DURATION_SECONDS", 300.0))  # 5 minutes
    min_duration_seconds: float = float(os.getenv("MIN_AUDIO_DURATION_SECONDS", 0.05))
    allowed_extensions: Tuple[str, ...] = (".wav", ".mp3", ".webm", ".ogg", ".m4a", ".mp4")
    allowed_mime_types: Tuple[str, ...] = (
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/webm",
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/m4a",
        "audio/x-m4a",
        "audio/mp4",
        "video/webm",
    )


# Standard singleton instances
DEFAULT_RESUME_LIMITS = ResumeLimits()
DEFAULT_IMAGE_LIMITS = ImageLimits()
DEFAULT_AUDIO_LIMITS = AudioLimits()
