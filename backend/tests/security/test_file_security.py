"""Security Test Suite for File & Upload Boundaries (Requirement F2).

Verifies:
[x] oversized PDF rejected
[x] fake PDF rejected
[x] malformed PDF handled safely
[x] oversized image rejected
[x] corrupt image rejected
[x] oversized audio rejected
[x] unsupported audio rejected
[x] path traversal filename rejected
[x] special characters handled
[x] generated storage names are safe
[x] temporary files cleaned (even on exception)
[x] unauthorized file access rejected
[x] uploads aren't publicly accessible
"""

import io
from pathlib import Path
import cv2
from fastapi.testclient import TestClient
import numpy as np
import pymupdf
import pytest
import wave

from app.core.exceptions import (
    InvalidAudioException,
    InvalidImageException,
    InvalidResumeException,
    InvalidUploadException,
)
from app.core.file_validation import (
    generate_safe_storage_name,
    sanitize_filename,
    temporary_processing_file,
    validate_audio,
    validate_image,
    validate_resume,
)
from app.core.upload_limits import (
    AudioLimits,
    ImageLimits,
    ResumeLimits,
)
from app.main import app
from app.security.storage_manager import StorageManager


# ---------------------------------------------------------------------------
# Helpers for Generating Valid Synthetic Test Media
# ---------------------------------------------------------------------------

def create_valid_pdf(pages: int = 1, width: float = 595.0, height: float = 842.0) -> bytes:
    """Creates a valid in-memory PDF with specified page count and dimensions."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((50, 72), f"Candidate Technical Profile Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def create_valid_jpeg(width: int = 200, height: int = 200) -> bytes:
    """Creates a valid 3-channel JPEG image in memory."""
    img = np.full((height, width, 3), 128, dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


def create_valid_wav(duration_seconds: float = 1.0, framerate: int = 16000) -> bytes:
    """Creates a valid 16-bit mono PCM WAV audio stream in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        nframes = int(duration_seconds * framerate)
        # Write silence/tone
        wav_out.writeframes(b"\x00\x00" * nframes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# F2.2: Resume Security Tests
# ---------------------------------------------------------------------------

def test_oversized_pdf_rejected():
    """Requirement F2.2 & F2.8: PDF exceeding size limit must be rejected."""
    valid_pdf = create_valid_pdf()
    limits = ResumeLimits(max_size_bytes=len(valid_pdf) - 10)

    with pytest.raises(InvalidResumeException) as exc_info:
        validate_resume(valid_pdf, filename="resume.pdf", limits=limits)
    assert "exceeds maximum allowed size" in str(exc_info.value)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code in ("INVALID_RESUME", "INVALID_UPLOAD")


def test_fake_pdf_rejected():
    """Requirement F2.2: Plain text with .pdf extension must fail PDF signature check."""
    fake_bytes = b"Hello world, I am not a real PDF document!"
    with pytest.raises(InvalidResumeException) as exc_info:
        validate_resume(fake_bytes, filename="fake.pdf")
    assert "magic bytes signature" in str(exc_info.value)
    assert exc_info.value.code in ("INVALID_RESUME", "INVALID_UPLOAD")


def test_malformed_pdf_handled_safely():
    """Requirement F2.2: Malformed PDF must raise 422 INVALID_RESUME, not an unhandled 500."""
    # Magic bytes present, but garbage internal stream
    corrupt_bytes = b"%PDF-1.4\n%MalformedGarbageData\x00\xff\xee\xdd\x00%%EOF"
    with pytest.raises(InvalidResumeException) as exc_info:
        validate_resume(corrupt_bytes, filename="corrupt.pdf")
    assert exc_info.value.status_code == 422
    assert exc_info.value.code in ("INVALID_RESUME", "INVALID_UPLOAD")


def test_pdf_page_count_limit_rejected():
    """Requirement F2.2 & F2.8: PDF with excessive pages rejected to prevent memory exhaustion."""
    multi_page_pdf = create_valid_pdf(pages=16)
    limits = ResumeLimits(max_pages=15)

    with pytest.raises(InvalidResumeException) as exc_info:
        validate_resume(multi_page_pdf, filename="long_resume.pdf", limits=limits)
    assert "exceeds maximum allowed limit of 15 pages" in str(exc_info.value)


def test_pdf_unreasonable_dimensions_rejected():
    """Requirement F2.2 & F2.8: PDF with microscopic or enormous dimensions rejected."""
    # Microscopic page (10x10 pts)
    tiny_pdf = create_valid_pdf(pages=1, width=10.0, height=10.0)
    with pytest.raises(InvalidResumeException) as exc_info:
        validate_resume(tiny_pdf, filename="micro_resume.pdf")
    assert "unreasonable dimensions" in str(exc_info.value)


# ---------------------------------------------------------------------------
# F2.3: Identity Image Security Tests
# ---------------------------------------------------------------------------

def test_oversized_image_rejected():
    """Requirement F2.3 & F2.8: Oversized image must be rejected."""
    valid_img = create_valid_jpeg(width=300, height=300)
    limits = ImageLimits(max_size_bytes=len(valid_img) - 10)

    with pytest.raises(InvalidImageException) as exc_info:
        validate_image(valid_img, filename="face.jpg", limits=limits)
    assert "exceeds maximum allowed size" in str(exc_info.value)
    assert exc_info.value.code in ("INVALID_IMAGE", "INVALID_UPLOAD")


def test_corrupt_image_rejected():
    """Requirement F2.3: Image header present but corrupted payload must be rejected."""
    # JPEG SOI header followed by garbage
    corrupt_img = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00\x01\x01\x00" + b"CorruptGarbageData" * 10
    with pytest.raises(InvalidImageException) as exc_info:
        validate_image(corrupt_img, filename="corrupt.jpg")
    assert "Could not decode image" in str(exc_info.value) or "corrupted" in str(exc_info.value)


def test_image_dimensions_bounds_rejected():
    """Requirement F2.3: Images outside min/max dimensions must be rejected."""
    # Too small (20x20 vs min 50x50)
    small_img = create_valid_jpeg(width=20, height=20)
    with pytest.raises(InvalidImageException) as exc_info:
        validate_image(small_img, filename="small.jpg")
    assert "Image dimensions too small" in str(exc_info.value)


# ---------------------------------------------------------------------------
# F2.4: Audio Security Tests
# ---------------------------------------------------------------------------

def test_oversized_audio_rejected():
    """Requirement F2.4 & F2.8: Audio exceeding max file size rejected."""
    valid_wav = create_valid_wav(duration_seconds=2.0)
    limits = AudioLimits(max_size_bytes=len(valid_wav) - 50)

    with pytest.raises(InvalidAudioException) as exc_info:
        validate_audio(valid_wav, filename="answer.wav", limits=limits)
    assert "exceeds maximum allowed size" in str(exc_info.value)
    assert exc_info.value.code in ("INVALID_AUDIO", "INVALID_UPLOAD")



def test_unsupported_audio_rejected():
    """Requirement F2.4: Non-audio bytes rejected."""
    garbage = b"This is not a WAV or WebM or MP3 audio file!"
    with pytest.raises(InvalidAudioException) as exc_info:
        validate_audio(garbage, filename="answer.wav")
    assert "Unsupported or corrupted audio format" in str(exc_info.value)


def test_oversized_audio_duration_rejected():
    """Requirement F2.4 & F2.8: Audio duration exceeding limit rejected."""
    # Create 3-second audio when limit is 1.5 seconds
    wav_bytes = create_valid_wav(duration_seconds=3.0)
    limits = AudioLimits(max_duration_seconds=1.5)

    with pytest.raises(InvalidAudioException) as exc_info:
        validate_audio(wav_bytes, filename="long.wav", limits=limits)
    assert "exceeds maximum allowed limit" in str(exc_info.value)


# ---------------------------------------------------------------------------
# F2.5: Filename Attacks & Traversal Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "malicious_name",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\cmd.exe",
        "....//....//shadow",
        "%2e%2e%2fsecret.pdf",
        "resume\x00hidden.pdf",
        "/absolute/root/path.pdf",
        "C:\\autoexec.bat",
    ],
)
def test_path_traversal_filename_rejected(malicious_name):
    """Requirement F2.5: Path traversal sequences in filenames must be detected and rejected."""
    with pytest.raises(InvalidUploadException) as exc_info:
        sanitize_filename(malicious_name)
    assert "traversal" in str(exc_info.value).lower() or "illegal" in str(exc_info.value).lower()


def test_special_characters_handled():
    """Requirement F2.5: User filenames with spaces and symbols sanitized safely."""
    messy_name = "Candidate Resume (v2.1) [Final Draft] #1.pdf"
    cleaned = sanitize_filename(messy_name)
    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert " " not in cleaned  # Space replaced or sanitized
    assert cleaned.endswith(".pdf")


def test_generated_storage_names_are_safe():
    """Requirement F2.5: Internal storage name must be a secure UUID without user path tokens."""
    internal_id, safe_name = generate_safe_storage_name("my_resume_original.pdf", default_ext=".pdf")
    assert len(internal_id) == 32  # UUID hex
    assert safe_name.endswith(".pdf")
    assert "/" not in safe_name
    assert "\\" not in safe_name
    assert ".." not in safe_name


# ---------------------------------------------------------------------------
# F2.7: Temporary File Management & Cleanup Tests
# ---------------------------------------------------------------------------

def test_temporary_files_cleaned_on_success(tmp_path):
    """Requirement F2.7: Temp file exists during processing and is cleaned up afterwards."""
    content = b"temporary speech recognition chunk"
    temp_file_ref = None

    with temporary_processing_file(content, suffix=".wav", tmp_dir=tmp_path) as temp_file:
        temp_file_ref = temp_file
        assert temp_file.exists()
        assert temp_file.read_bytes() == content

    # Guaranteed cleanup
    assert not temp_file_ref.exists()


def test_temporary_files_cleaned_on_exception(tmp_path):
    """Requirement F2.7: Temp file cleaned up even when processing raises an error."""
    content = b"temporary audio chunk"
    temp_file_ref = None

    with pytest.raises(RuntimeError):
        with temporary_processing_file(content, suffix=".wav", tmp_dir=tmp_path) as temp_file:
            temp_file_ref = temp_file
            assert temp_file.exists()
            raise RuntimeError("Simulated processing crash inside Whisper STT")

    # Guaranteed cleanup via finally block
    assert temp_file_ref is not None
    assert not temp_file_ref.exists()


# ---------------------------------------------------------------------------
# F2.6: Direct Upload Exposure & Unauthorized Access Tests
# ---------------------------------------------------------------------------

def test_uploads_arent_publicly_accessible():
    """Requirement F2.6: Upload partitions must NOT be inside public web roots."""
    storage = StorageManager()
    assert storage.is_publicly_accessible(storage.resumes_dir / "C001" / "resume.pdf") is False
    assert storage.is_publicly_accessible(storage.identity_dir / "C001" / "face.jpg") is False
    assert storage.is_publicly_accessible(storage.audio_dir / "SESS_01" / "turn1.wav") is False

    # A mock public file should be recognized as public
    public_path = Path("static/interview.html")
    assert storage.is_publicly_accessible(public_path) is True


def test_unauthorized_file_access_rejected():
    """Requirement F2.6: GET /candidates/{candidate_id}/resume must enforce authorization."""
    from app.api.auth_dependencies import get_current_user
    from app.models.user import Role, UserResponse

    client = TestClient(app)

    # 1. Anonymous request -> 401 Unauthorized
    res_anon = client.get("/candidates/C001/resume")
    assert res_anon.status_code == 401

    # 2. Candidate C002 attempting to fetch C001's resume -> 403 Forbidden
    candidate_c002_user = UserResponse(
        id="u2",
        email="c002@test.com",
        name="Candidate Two",
        role=Role.CANDIDATE.value,
        candidate_id="C002",
    )
    app.dependency_overrides[get_current_user] = lambda: candidate_c002_user
    try:
        res_cross = client.get("/candidates/C001/resume")
        assert res_cross.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # 3. Direct GET to arbitrary /uploads/ does not exist (not served statically)
    res_direct = client.get("/uploads/C001/resume.pdf")
    assert res_direct.status_code == 404
