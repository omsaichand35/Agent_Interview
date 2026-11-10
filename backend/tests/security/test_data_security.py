"""Data Security and Privacy Test Suite (Requirement F1 & F6.1).

Verifies the platform's data isolation, privacy boundaries, and retention controls:
[x] Candidate A cannot access Candidate B profile
[x] Candidate A cannot access Candidate B resume or transcript
[x] Candidate cannot access raw identity or biometric records
[x] Recruiter access adheres strictly to the authorization matrix
[x] File storage partitions are non-public and tenant-segregated
[x] Cascaded deletion purges all associated records across domains
[x] Retention policy purges expired data while preserving active records
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.security.access_control import AccessControlEnforcer
from app.security.deletion_service import CandidateDeletionService
from app.security.storage_manager import StorageManager


def test_candidate_cannot_access_another_candidate_profile():
    """F1.3: Candidate A cannot access Candidate B profile."""
    allowed, msg = AccessControlEnforcer.can_access_profile(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_001",
    )
    assert allowed is True

    allowed, msg = AccessControlEnforcer.can_access_profile(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_002",
    )
    assert allowed is False
    assert "Access Denied" in msg


def test_candidate_cannot_access_another_candidate_resume_or_transcript():
    """F1.3: Candidate A cannot access Candidate B resume or transcript."""
    allowed_res, _ = AccessControlEnforcer.can_access_resume(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_002",
    )
    assert allowed_res is False

    allowed_trans, _ = AccessControlEnforcer.can_access_transcript(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_002",
    )
    assert allowed_trans is False


def test_candidate_cannot_access_raw_identity_records():
    """F1.3: Candidate has zero access to raw identity records or biometrics."""
    allowed, msg = AccessControlEnforcer.can_access_identity_records(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_001",
        is_raw_biometrics=True,
    )
    assert allowed is False
    assert "Access Denied" in msg


def test_recruiter_access_follows_authorization_matrix():
    """F1.3: Recruiter can access candidate profiles, resumes, and evaluations."""
    allowed, _ = AccessControlEnforcer.can_access_profile(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
    )
    assert allowed is True

    allowed, _ = AccessControlEnforcer.can_access_resume(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
    )
    assert allowed is True


def test_storage_partitions_and_non_public_directories():
    """F1.4: Storage directories are properly segregated and placed outside public web roots."""
    mgr = StorageManager()
    base = mgr.base_dir.resolve()

    assert not any(p.name == "static" for p in base.parents)
    assert "static" not in base.name.lower()

    for path in (mgr.resumes_dir, mgr.audio_dir, mgr.identity_dir, mgr.transcripts_dir):
        assert path.exists()
        assert base in path.resolve().parents or path.resolve() == base


def test_cascaded_candidate_deletion(tmp_path):
    """F1.5 & F1.7: Deleting a candidate cascades to private files and database records."""
    storage = StorageManager(base_storage_dir=tmp_path / "storage")
    service = CandidateDeletionService(storage_manager=storage)

    cid = "CAND_DEL_TEST"
    sid = "SESS_DEL_TEST"

    # Seed candidate files
    res_path = storage.get_resume_path(cid, "resume.pdf")
    res_path.write_bytes(b"dummy pdf")
    aud_path = storage.get_audio_path(sid, "audio.wav")
    aud_path.write_bytes(b"dummy audio")
    ident_path = storage.get_identity_path(cid, "photo.jpg")
    ident_path.write_bytes(b"dummy photo")

    mock_db = {
        "candidates": {cid: {"name": "Test Candidate"}},
        "sessions": {sid: {"candidate_id": cid, "status": "completed"}},
    }

    result = service.delete_candidate_complete(
        candidate_id=cid,
        actor_id="admin_user",
        actor_role="admin",
        session_ids=[sid],
        mock_db=mock_db,
    )

    assert result["status"] == "purged"
    assert result["deleted_files_count"] >= 3
    assert result["db_records_removed"] == 2

    # Verify folders & files wiped
    assert not res_path.exists()
    assert not aud_path.exists()
    assert not ident_path.exists()
    assert not (storage.resumes_dir / cid).exists()
    assert not (storage.identity_dir / cid).exists()


def test_retention_purge_expired_records():
    """F1.6: Expired records beyond retention period can be purged."""
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
