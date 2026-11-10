"""Tests for Role-Based Access Control and Tenant Isolation (Requirement F1.3 & F1.9)."""

import pytest
from pathlib import Path
from app.security.access_control import AccessControlEnforcer
from app.security.storage_manager import StorageManager


def test_candidate_cannot_access_another_candidate_profile():
    """Requirement F1.3 & F1.9: Candidate A cannot access Candidate B profile."""
    # Candidate accessing own profile -> OK
    allowed, msg = AccessControlEnforcer.can_access_profile(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_001",
    )
    assert allowed is True
    assert "Authorized" in msg

    # Candidate accessing another candidate -> DENIED
    allowed, msg = AccessControlEnforcer.can_access_profile(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_002",
    )
    assert allowed is False
    assert "Access Denied" in msg


def test_candidate_cannot_access_another_candidate_resume_or_transcript():
    """Requirement F1.3: Candidate A cannot access Candidate B resume or transcript."""
    # Resume check
    allowed_res, msg_res = AccessControlEnforcer.can_access_resume(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_002",
    )
    assert allowed_res is False
    assert "Access Denied" in msg_res

    # Transcript check
    allowed_trans, msg_trans = AccessControlEnforcer.can_access_transcript(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_002",
    )
    assert allowed_trans is False
    assert "Access Denied" in msg_trans


def test_candidate_cannot_access_identity_records():
    """Requirement F1.3: Candidate has zero access to raw identity records or biometrics."""
    allowed, msg = AccessControlEnforcer.can_access_identity_records(
        user_role="candidate",
        user_candidate_id="CAND_001",
        target_candidate_id="CAND_001",
        is_raw_biometrics=True,
    )
    assert allowed is False
    assert "Access Denied" in msg


def test_recruiter_access_follows_authorization_matrix():
    """Requirement F1.3: Recruiters have authorized access to candidate data."""
    # Profile access
    allowed_p, _ = AccessControlEnforcer.can_access_profile(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
    )
    assert allowed_p is True

    # Resume access
    allowed_r, _ = AccessControlEnforcer.can_access_resume(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
    )
    assert allowed_r is True

    # Transcript access
    allowed_t, _ = AccessControlEnforcer.can_access_transcript(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
    )
    assert allowed_t is True

    # Raw biometrics (face images) are RESTRICTED from regular recruiters
    allowed_bio, _ = AccessControlEnforcer.can_access_identity_records(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
        is_raw_biometrics=True,
    )
    assert allowed_bio is False

    # But identity audit logs are authorized for recruiters
    allowed_ident_logs, _ = AccessControlEnforcer.can_access_identity_records(
        user_role="recruiter",
        user_candidate_id=None,
        target_candidate_id="CAND_001",
        is_raw_biometrics=False,
    )
    assert allowed_ident_logs is True


def test_storage_partitions_and_non_public_directories(tmp_path):
    """Requirement F1.4 & F1.9: Identity images and audio recordings must NEVER be in public static directories."""
    storage = StorageManager(base_storage_dir=tmp_path / "storage")

    ident_path = storage.get_identity_path("CAND_001", "face.jpg")
    audio_path = storage.get_audio_path("SESS_001", "audio.wav")

    assert storage.is_publicly_accessible(ident_path) is False
    assert storage.is_publicly_accessible(audio_path) is False

    # Simulate static asset path
    mock_static = tmp_path / "static" / "images" / "logo.png"
    assert storage.is_publicly_accessible(mock_static) is True
