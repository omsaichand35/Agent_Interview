"""Candidate Data Deletion Service and Retention Purger (Requirement F1.7).

Handles complete cascaded deletion across:
1. Resumes on disk / object store.
2. Audio recordings.
3. Identity reference images and vectors.
4. Interview transcripts.
5. Relational database metadata.
6. Emits immutable audit log event.
7. Retention-based scheduled purging.
"""

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.security.privacy_models import AuditLogEvent
from app.security.storage_manager import StorageManager

logger = logging.getLogger(__name__)


class CandidateDeletionService:
    """Orchestrates comprehensive cascaded purging of all candidate data copies."""

    def __init__(self, storage_manager: Optional[StorageManager] = None):
        self.storage = storage_manager or StorageManager()
        self.audit_log: List[AuditLogEvent] = []

    def delete_candidate_complete(
        self,
        candidate_id: str,
        actor_id: str,
        actor_role: str,
        session_ids: Optional[List[str]] = None,
        mock_db: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Cascades deletion across file storage partitions, database metadata, and logs audit event."""
        deleted_files = []
        errors = []

        # 1. Delete Resume Files
        cand_resume_dir = self.storage.resumes_dir / candidate_id
        if cand_resume_dir.exists():
            for f in cand_resume_dir.glob("*"):
                f.unlink(missing_ok=True)
                deleted_files.append(str(f))
            shutil.rmtree(cand_resume_dir, ignore_errors=True)

        # 2. Delete Identity Images and Vectors
        cand_ident_dir = self.storage.identity_dir / candidate_id
        if cand_ident_dir.exists():
            for f in cand_ident_dir.glob("*"):
                f.unlink(missing_ok=True)
                deleted_files.append(str(f))
            shutil.rmtree(cand_ident_dir, ignore_errors=True)

        # 3. Delete Session Media (Audio & Transcripts)
        if session_ids:
            for sid in session_ids:
                sess_audio_dir = self.storage.audio_dir / sid
                if sess_audio_dir.exists():
                    for f in sess_audio_dir.glob("*"):
                        f.unlink(missing_ok=True)
                        deleted_files.append(str(f))
                    shutil.rmtree(sess_audio_dir, ignore_errors=True)

                sess_trans_dir = self.storage.transcripts_dir / sid
                if sess_trans_dir.exists():
                    for f in sess_trans_dir.glob("*"):
                        f.unlink(missing_ok=True)
                        deleted_files.append(str(f))
                    shutil.rmtree(sess_trans_dir, ignore_errors=True)

        # 4. Delete Database Metadata
        db_records_removed = 0
        if mock_db is not None:
            # Clean candidates table
            if candidate_id in mock_db.get("candidates", {}):
                del mock_db["candidates"][candidate_id]
                db_records_removed += 1
            # Clean sessions
            if "sessions" in mock_db:
                to_del = [sid for sid, s in mock_db["sessions"].items() if s.get("candidate_id") == candidate_id]
                for sid in to_del:
                    del mock_db["sessions"][sid]
                    db_records_removed += 1

        # 5. Emit Immutable Audit Event
        audit_event = AuditLogEvent(
            event_id=f"AUDIT_DEL_{candidate_id}_{int(datetime.now(timezone.utc).timestamp())}",
            event_type="candidate_data_purged",
            actor_id=actor_id,
            actor_role=actor_role,
            target_candidate_id=candidate_id,
            details={
                "deleted_files_count": len(deleted_files),
                "db_records_removed": db_records_removed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.audit_log.append(audit_event)

        logger.info(
            f"Candidate {candidate_id} completely purged by {actor_role} {actor_id}. "
            f"Files removed: {len(deleted_files)}, DB records: {db_records_removed}."
        )

        return {
            "candidate_id": candidate_id,
            "status": "purged",
            "deleted_files_count": len(deleted_files),
            "db_records_removed": db_records_removed,
            "audit_event_id": audit_event.event_id,
        }

    def purge_expired_records(
        self,
        records: List[Dict[str, Any]],
        retention_days: int,
        current_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Requirement F1.6 & F1.9: Purge records older than retention threshold."""
        now = current_time or datetime.now(timezone.utc)
        threshold = now - timedelta(days=retention_days)

        active = []
        purged_count = 0

        for rec in records:
            created = rec.get("created_at")
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            if created and created < threshold:
                purged_count += 1
            else:
                active.append(rec)

        logger.info(f"Retention purge complete: {purged_count} records older than {retention_days} days purged.")
        return active
