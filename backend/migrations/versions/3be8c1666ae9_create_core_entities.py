"""create_core_entities

Revision ID: 3be8c1666ae9
Revises: 
Create Date: 2026-09-25 00:36:11.307925

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3be8c1666ae9'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. jobs
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('department', sa.String(length=128), nullable=False, server_default='Engineering'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('required_skills', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='OPEN'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_jobs_id'), 'jobs', ['id'], unique=False)

    # 2. candidates
    op.create_table(
        'candidates',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=64), nullable=True),
        sa.Column('photo_path', sa.String(length=512), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='APPLIED'),
        sa.Column('resume_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_candidates_id'), 'candidates', ['id'], unique=False)
    op.create_index(op.f('ix_candidates_job_id'), 'candidates', ['job_id'], unique=False)

    # 3. resumes
    op.create_table(
        'resumes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('file_path', sa.String(length=512), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('parsed_skills', sa.JSON(), nullable=True),
        sa.Column('experience_years', sa.Float(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('analysis', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_resumes_candidate_id'), 'resumes', ['candidate_id'], unique=False)

    # 4. interview_sessions
    op.create_table(
        'interview_sessions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='pending'),
        sa.Column('identity_verified', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('identity_status', sa.String(length=64), nullable=True, server_default='pending'),
        sa.Column('identity_failure_reason', sa.String(length=255), nullable=True),
        sa.Column('interview_score', sa.Float(), nullable=True),
        sa.Column('turn_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('current_question', sa.Text(), nullable=True),
        sa.Column('competency_scores', sa.JSON(), nullable=True),
        sa.Column('conversation_history', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_interview_sessions_candidate_id'), 'interview_sessions', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_interview_sessions_id'), 'interview_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_interview_sessions_job_id'), 'interview_sessions', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_table('interview_sessions')
    op.drop_table('resumes')
    op.drop_table('candidates')
    op.drop_table('jobs')
