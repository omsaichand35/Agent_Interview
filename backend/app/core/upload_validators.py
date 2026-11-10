"""Upload validators for resumes, identity images, and interview audio files.
Delegates to centralized file_validation module for deep content validation,
resource limits, and attack prevention.
"""

from typing import Optional, Tuple
import numpy as np

from app.core.exceptions import InvalidUploadException
from app.core.file_validation import (
    AudioValidationResult,
    validate_audio,
    validate_image,
    validate_resume,
)
from app.core.upload_limits import (
    AudioLimits,
    DEFAULT_AUDIO_LIMITS,
    DEFAULT_IMAGE_LIMITS,
    DEFAULT_RESUME_LIMITS,
    ImageLimits,
    ResumeLimits,
)

# Backwards-compatible size limits
MAX_RESUME_SIZE_BYTES = DEFAULT_RESUME_LIMITS.max_size_bytes
MAX_IMAGE_SIZE_BYTES = DEFAULT_IMAGE_LIMITS.max_size_bytes
MAX_AUDIO_SIZE_BYTES = DEFAULT_AUDIO_LIMITS.max_size_bytes


def validate_resume_upload(
    file_bytes: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    max_size_bytes: int = MAX_RESUME_SIZE_BYTES,
) -> None:
    """Validates resume file format, magic bytes, PyMuPDF page parsing, and size limit.
    Must be a valid PDF document.
    """
    limits = ResumeLimits(max_size_bytes=max_size_bytes)
    validate_resume(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        limits=limits,
    )


def validate_image_upload(
    file_bytes: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    max_size_bytes: int = MAX_IMAGE_SIZE_BYTES,
    min_dimensions: Tuple[int, int] = (50, 50),
    max_dimensions: Tuple[int, int] = (4096, 4096),
) -> np.ndarray:
    """Validates image file size, magic bytes, OpenCV decodability, color format,
    and pixel dimensions. Returns decoded OpenCV BGR image array.
    """
    limits = ImageLimits(
        max_size_bytes=max_size_bytes,
        min_width=min_dimensions[0],
        min_height=min_dimensions[1],
        max_width=max_dimensions[0],
        max_height=max_dimensions[1],
    )
    result = validate_image(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        limits=limits,
    )
    return result.cv2_image


def validate_audio_upload(
    file_bytes: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    max_size_bytes: int = MAX_AUDIO_SIZE_BYTES,
) -> AudioValidationResult:
    """Validates audio file size, MIME type, binary audio signature,
    and stream decodability.
    """
    limits = AudioLimits(max_size_bytes=max_size_bytes)
    return validate_audio(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        limits=limits,
    )
