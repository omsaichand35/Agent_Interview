"""Resume Upload and Security Routing (Requirement F2.2).

Enforces:
1. Multi-tier validation boundary for uploaded resumes (PDF magic bytes, PyMuPDF parsing).
2. Internal UUID identifier generation (F2.5: No path traversal).
3. Storage outside public web roots (F2.6: Private storage).
4. Error handling with 422 INVALID_RESUME status code.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.auth_dependencies import get_current_user, verify_candidate_access
from app.core.file_validation import (
    ResumeValidationResult,
    validate_resume,
)
from app.models.user import UserResponse
from app.security.storage_manager import StorageManager



from app.security.rate_limiter import rate_limit

router = APIRouter(prefix="/resume", tags=["Resume"])


@router.post(
    "/upload",
    dependencies=[Depends(rate_limit(limit=10, window_seconds=60, key_prefix="resume_upload"))],
)
async def upload_resume(
    resume: UploadFile = File(...),
    candidate_id: Optional[str] = None,
    current_user: Optional[UserResponse] = Depends(get_current_user),
):

    """Secure endpoint for uploading resumes.

    Runs full validation pipeline:
    - Size check
    - Extension check
    - PDF magic signature check
    - PyMuPDF parsing boundary (422 INVALID_RESUME on corrupt file)
    - Reasonable dimensions & page bounds
    - UUID generation & private storage
    """
    if candidate_id and current_user:
        verify_candidate_access(candidate_id, current_user)

    file_bytes = await resume.read()

    # Centralized validation pipeline
    validation: ResumeValidationResult = validate_resume(
        file_bytes=file_bytes,
        filename=resume.filename,
        content_type=resume.content_type,
    )

    # Store in private storage partition outside public web root
    storage = StorageManager()
    target_dir = storage.resumes_dir / (candidate_id or "unassigned")
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_path = target_dir / validation.safe_filename
    saved_path.write_bytes(file_bytes)

    return {
        "file_id": validation.internal_id,
        "safe_filename": validation.safe_filename,
        "page_count": validation.page_count,
        "size_bytes": validation.size_bytes,
        "original_filename": validation.sanitized_original_filename,
        "status": "validated",
    }
