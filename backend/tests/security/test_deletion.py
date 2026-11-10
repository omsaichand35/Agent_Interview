"""Tests for Comprehensive Deletion Workflow and Retention Purging (Requirement F1.7 & F1.9)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.security.deletion_service import CandidateDeletionService
from app.security.storage_manager import StorageManager


def test_cascaded_candidate_deletion(tmp_path):
    """Requirement F1.7 & F1.9: Deleting a candidate removes files across all storage partitions and DB records."""
    storage = StorageManager(base_storage_dir=tmp_path / "storage")
    service = CandidateDeletionService(storage_manager=storage)

    candidate_id = "CAND_PURGE_01"
    session_id = "SESS_PURGE_01"

    # 1. Create simulated candidate files
    resume_file = storage.get_resume_path(candidate_id, "resume.pdf")
    resume_file.write_text("Simulated resume content")

    ident_file = storage.get_identity_path(candidate_id, "face_ref.jpg")
    ident_file.write_text("Simulated face image data")

    audio_file = storage.get_audio_path(session_id, "audio.wav")
    audio_file.write_text("Simulated audio data")

    trans_file = storage.get_transcript_path(session_id, "transcript.json")
    trans_file.write_text('{"turns": []}')

    assert resume_file.exists()
    assert ident_file.exists()
    assert audio_file.exists()
    assert trans_file.exists()

    # 2. Simulated DB records
    mock_db = {
        "candidates": {candidate_id: {"name": "Test Candidate"}},
        "sessions": {session_id: {"candidate_id": candidate_id, "status": "completed"}},
    }

    # 3. Perform complete cascaded deletion
    res = service.delete_candidate_complete(
        candidate_id=candidate_id,
        actor_id="RECRUITER_ADMIN_01",
        actor_role="admin",
        session_ids=[session_id],
        mock_db=mock_db,
    )

    # 4. Verify all copies on disk are destroyed
    assert not resume_file.exists()
    assert not ident_file.exists()
    assert not audio_file.exists()
    assert not trans_file.exists()
    assert not (storage.resumes_dir / candidate_id).exists()
    assert not (storage.identity_dir / candidate_id).exists()
    assert not (storage.audio_dir / session_id).exists()
    assert not (storage.transcripts_dir / session_id).exists()

    # 5. Verify database records removed
    assert candidate_id not in mock_db["candidates"]
    assert session_id not in mock_db["sessions"]

    # 6. Verify immutable audit event emitted
    assert len(service.audit_log) == 1
    event = service.audit_log[0]
    assert event.event_type == "candidate_data_purged"
    assert event.target_candidate_id == candidate_id
    assert event.actor_id == "RECRUITER_ADMIN_01"


def test_retention_purge_expired_records():
    """Requirement F1.6 & F1.9: Expired records beyond retention period can be purged."""
    service = CandidateDeletionService()

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=200)   # 200 days old (> 180 days)
    fresh_time = now - timedelta(days=10)  # 10 days old

    records = [
        {"id": "REC_OLD_1", "created_at": old_time.isoformat()},
        {"id": "REC_FRESH_2", "created_at": fresh_time.isoformat()},
    ]

    active = service.purge_expired_records(records, retention_days=180, current_time=now)

    assert len(active) == 1
    assert active[0]["id"] == "REC_FRESH_2"
