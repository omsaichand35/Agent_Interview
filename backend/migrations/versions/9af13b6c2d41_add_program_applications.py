"""add program applications

Revision ID: 9af13b6c2d41
Revises: d5d6383ea4a7
Create Date: 2026-10-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9af13b6c2d41"
down_revision: Union[str, Sequence[str], None] = "d5d6383ea4a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("program_id", sa.String(length=64), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=True),
        sa.Column("face_reference_path", sa.String(length=512), nullable=False),
        sa.Column("biometric_consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("biometric_consent_version", sa.String(length=64), nullable=False, server_default="admissions-face-consent-v1"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="submitted"),
        sa.Column("resume_score", sa.Float(), nullable=True),
        sa.Column("interview_score", sa.Float(), nullable=True),
        sa.Column("score_details", sa.JSON(), nullable=True),
        sa.Column("identity_status", sa.String(length=64), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "program_id", name="uq_application_candidate_program"),
    )
    op.create_index(op.f("ix_applications_id"), "applications", ["id"], unique=False)
    op.create_index(op.f("ix_applications_candidate_id"), "applications", ["candidate_id"], unique=False)
    op.create_index(op.f("ix_applications_program_id"), "applications", ["program_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_program_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_candidate_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_id"), table_name="applications")
    op.drop_table("applications")
