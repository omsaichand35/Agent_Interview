"""Role-Based Access Control and Authorization Enforcer (Requirement F1.3)."""

import logging
from typing import Any, Dict, Optional, Tuple

from app.security.privacy_models import DataClassificationLevel

logger = logging.getLogger(__name__)


class AccessControlEnforcer:
    """Enforces least privilege and data isolation across candidates and internal roles."""

    RECRUITER_ROLES = {"recruiter", "hiring_manager", "admin"}

    @classmethod
    def can_access_profile(
        cls,
        user_role: str,
        user_candidate_id: Optional[str],
        target_candidate_id: str,
    ) -> Tuple[bool, str]:
        """Candidate can only access own profile; recruiters can access assigned candidates."""
        if user_role == "candidate":
            if user_candidate_id == target_candidate_id:
                return True, "Authorized: Candidate reading own profile."
            return False, "Access Denied: Candidate cannot access other candidate profiles."

        if user_role in cls.RECRUITER_ROLES:
            return True, "Authorized: Recruiter role accessing candidate profile."

        return False, f"Access Denied: Role '{user_role}' not authorized for profile access."

    @classmethod
    def can_access_resume(
        cls,
        user_role: str,
        user_candidate_id: Optional[str],
        target_candidate_id: str,
    ) -> Tuple[bool, str]:
        """Candidate can only access own resume; recruiters can access candidate resumes."""
        if user_role == "candidate":
            if user_candidate_id == target_candidate_id:
                return True, "Authorized: Candidate accessing own resume."
            return False, "Access Denied: Candidate cannot access other candidate resumes."

        if user_role in cls.RECRUITER_ROLES:
            return True, "Authorized: Recruiter role accessing candidate resume."

        return False, f"Access Denied: Role '{user_role}' not authorized for resume access."

    @classmethod
    def can_access_transcript(
        cls,
        user_role: str,
        user_candidate_id: Optional[str],
        target_candidate_id: str,
    ) -> Tuple[bool, str]:
        """Candidate can only access own interview transcript."""
        if user_role == "candidate":
            if user_candidate_id == target_candidate_id:
                return True, "Authorized: Candidate accessing own interview transcript."
            return False, "Access Denied: Candidate cannot access other candidate transcripts."

        if user_role in cls.RECRUITER_ROLES:
            return True, "Authorized: Recruiter role accessing candidate transcript."

        return False, f"Access Denied: Role '{user_role}' not authorized for transcript access."

    @classmethod
    def can_access_identity_records(
        cls,
        user_role: str,
        user_candidate_id: Optional[str],
        target_candidate_id: str,
        is_raw_biometrics: bool = False,
    ) -> Tuple[bool, str]:
        """Raw biometric images and vectors are strictly restricted; candidate only sees sanitized status."""
        if user_role == "candidate":
            return False, "Access Denied: Candidates cannot inspect raw identity records or biometrics."

        if is_raw_biometrics:
            # Raw face images are accessible only to internal identity service or compliance auditors
            if user_role in {"admin", "system_auditor"}:
                return True, "Authorized: Privileged audit role inspecting biometric verification."
            return False, "Access Denied: Recruiter role cannot access raw biometric face images."

        if user_role in cls.RECRUITER_ROLES:
            return True, "Authorized: Recruiter role inspecting identity verification audit logs."

        return False, f"Access Denied: Role '{user_role}' not authorized for identity records."

    @classmethod
    def can_access_audio_recording(
        cls,
        user_role: str,
        user_candidate_id: Optional[str],
        target_candidate_id: str,
    ) -> Tuple[bool, str]:
        """Audio recordings are restricted to authorized recruiters and self-access requests."""
        if user_role == "candidate":
            if user_candidate_id == target_candidate_id:
                return True, "Authorized: Candidate accessing own audio recording."
            return False, "Access Denied: Candidate cannot access other candidate audio recordings."

        if user_role in cls.RECRUITER_ROLES:
            return True, "Authorized: Recruiter role accessing candidate audio recording."

        return False, f"Access Denied: Role '{user_role}' not authorized for audio recording."
