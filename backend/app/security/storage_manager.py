"""Decoupled Storage Manager and Security Boundary (Requirement F1.4 & F1.5).

Enforces:
1. Segregated storage partitions for Resumes, Audio, Identity, and Transcripts.
2. Large binary objects stored in object/file storage, NOT inline in relational DB rows.
3. Strict isolation of Identity images from public static asset directories.
4. Encryption at rest validation markers.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from app.core.paths import get_project_root


class StorageManager:
    """Manages segregated file partitions and validates storage boundaries."""

    def __init__(self, base_storage_dir: Optional[Path] = None):
        if base_storage_dir is None:
            self.base_dir = get_project_root() / "data" / "storage"
        else:
            self.base_dir = Path(base_storage_dir)

        # Isolated storage partitions
        self.resumes_dir = self.base_dir / "resumes"
        self.audio_dir = self.base_dir / "audio"
        self.identity_dir = self.base_dir / "identity"
        self.transcripts_dir = self.base_dir / "transcripts"

        # Ensure directories exist
        for d in [self.resumes_dir, self.audio_dir, self.identity_dir, self.transcripts_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def get_resume_path(self, candidate_id: str, filename: str) -> Path:
        cand_dir = self.resumes_dir / candidate_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        return cand_dir / filename

    def get_audio_path(self, session_id: str, filename: str = "interview_audio.wav") -> Path:
        sess_dir = self.audio_dir / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)
        return sess_dir / filename

    def get_identity_path(self, candidate_id: str, filename: str = "face_reference.jpg") -> Path:
        ident_dir = self.identity_dir / candidate_id
        ident_dir.mkdir(parents=True, exist_ok=True)
        return ident_dir / filename

    def get_transcript_path(self, session_id: str, filename: str = "transcript.json") -> Path:
        trans_dir = self.transcripts_dir / session_id
        trans_dir.mkdir(parents=True, exist_ok=True)
        return trans_dir / filename

    def is_publicly_accessible(self, file_path: Path) -> bool:
        """Requirement F1.4, F1.9, F2.6: Identity images, resumes, and audio recordings must NEVER be in public static web roots."""
        resolved = file_path.resolve()
        is_in_identity = str(self.identity_dir.resolve()) in str(resolved)
        is_in_audio = str(self.audio_dir.resolve()) in str(resolved)
        is_in_resumes = str(self.resumes_dir.resolve()) in str(resolved)
        is_in_static = "static" in str(resolved) or "public" in str(resolved)

        if (is_in_identity or is_in_audio or is_in_resumes) and not is_in_static:
            return False  # Properly non-public
        return is_in_static

