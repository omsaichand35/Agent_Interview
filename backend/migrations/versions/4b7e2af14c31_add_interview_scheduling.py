"""add persistent interview scheduling batches and placements

Revision ID: 4b7e2af14c31
Revises: 8612b5e8fd49, 9af13b6c2d41
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b7e2af14c31"
down_revision: Union[str, Sequence[str], None] = ("8612b5e8fd49", "9af13b6c2d41")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_schedule_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("program_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("first_slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("people_per_slot", sa.Integer(), nullable=False),
        sa.Column("number_of_slots", sa.Integer(), nullable=False),
        sa.Column("selection_rule", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_schedule_batches_id", "interview_schedule_batches", ["id"], unique=False)
    op.create_index("ix_interview_schedule_batches_program_id", "interview_schedule_batches", ["program_id"], unique=False)
    op.create_index("ix_interview_schedule_batches_created_by", "interview_schedule_batches", ["created_by"], unique=False)

    op.create_table(
        "interview_schedules",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reminder_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["interview_schedule_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "application_id", name="uq_schedule_batch_application"),
    )
    for column in ("id", "batch_id", "application_id", "session_id", "scheduled_start", "status"):
        op.create_index(f"ix_interview_schedules_{column}", "interview_schedules", [column], unique=False)


def downgrade() -> None:
    op.drop_table("interview_schedules")
    op.drop_table("interview_schedule_batches")
