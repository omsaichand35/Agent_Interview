"""create_supporting_entities

Revision ID: d5d6383ea4a7
Revises: 3be8c1666ae9
Create Date: 2026-09-25 00:36:33.400000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5d6383ea4a7'
down_revision: Union[str, Sequence[str], None] = '3be8c1666ae9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. interview_turns
    op.create_table(
        'interview_turns',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('audio_path', sa.String(length=512), nullable=True),
        sa.Column('scores', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_interview_turns_session_id'), 'interview_turns', ['session_id'], unique=False)

    # 2. identity_checks
    op.create_table(
        'identity_checks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('failure_reason', sa.String(length=255), nullable=True),
        sa.Column('live_frame_path', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_identity_checks_candidate_id'), 'identity_checks', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_identity_checks_session_id'), 'identity_checks', ['session_id'], unique=False)

    # 3. recommendations
    op.create_table(
        'recommendations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=True),
        sa.Column('resume_score', sa.Float(), nullable=True),
        sa.Column('interview_score', sa.Float(), nullable=True),
        sa.Column('final_score', sa.Float(), nullable=True),
        sa.Column('strengths', sa.JSON(), nullable=True),
        sa.Column('gaps', sa.JSON(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=True, server_default='completed'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recommendations_candidate_id'), 'recommendations', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_recommendations_job_id'), 'recommendations', ['job_id'], unique=False)

    # 4. recruiter_reviews
    op.create_table(
        'recruiter_reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=True),
        sa.Column('reviewer_id', sa.String(length=128), nullable=False),
        sa.Column('decision', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recruiter_reviews_candidate_id'), 'recruiter_reviews', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_recruiter_reviews_job_id'), 'recruiter_reviews', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_table('recruiter_reviews')
    op.drop_table('recommendations')
    op.drop_table('identity_checks')
    op.drop_table('interview_turns')
