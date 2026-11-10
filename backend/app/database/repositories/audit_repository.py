"""
Audit Repository (Requirement F5.8).

Provides append-only persistence and query capabilities for system audit logs.
In accordance with tamper-resistance requirements (F5.5), this repository
does NOT provide single-row deletion or update methods for normal operations.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import AuditEvent, utc_now
from app.database.models import AuditEventModel


class AuditRepository:

    def __init__(self, db: Session):
        self.db = db

    def create(self, event: AuditEvent) -> AuditEventModel:
        """Appends a new audit event to the persistent audit table."""
        model = AuditEventModel(
            event_id=event.event_id,
            timestamp=event.timestamp,
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            result=event.result,
            request_id=event.request_id,
            event_metadata=event.metadata,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return model

    def get_by_event_id(self, event_id: str) -> Optional[AuditEventModel]:
        return self.db.query(AuditEventModel).filter(AuditEventModel.event_id == event_id).first()

    def list_events(
        self,
        candidate_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditEventModel]:
        """Queries audit records ordered chronologically by timestamp."""
        query = self.db.query(AuditEventModel)
        if candidate_id:
            query = query.filter(AuditEventModel.candidate_id == candidate_id)
        if actor_id:
            query = query.filter(AuditEventModel.actor_id == actor_id)
        if action:
            query = query.filter(AuditEventModel.action == action.upper())
        if resource_type:
            query = query.filter(AuditEventModel.resource_type == resource_type.upper())

        return query.order_by(AuditEventModel.timestamp.asc()).offset(offset).limit(limit).all()

    def purge_expired_events(self, retention_days: Optional[int] = None) -> int:
        """
        Compliance data retention operation (F5.9).
        Purges audit records older than the configured retention policy (e.g. settings.audit_retention_days).
        """
        days = retention_days if retention_days is not None else settings.audit_retention_days
        cutoff = utc_now() - timedelta(days=days)
        deleted = (
            self.db.query(AuditEventModel)
            .filter(AuditEventModel.timestamp < cutoff)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return deleted
