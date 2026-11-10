"""
D1 Integration Test: Database Layer and SQLAlchemy Repositories.

Verifies:
1. Engine connection & SessionLocal lifecycle
2. JobRepository operations (create, query, update, relationships)
3. CandidateRepository operations (create, update, resume parsing attachment)
4. InterviewRepository operations (create session, append turns, identity checks)
5. RecommendationRepository operations (final recommendations, recruiter review records)
6. Dual persistence compatibility (JSON persistence + DB persistence operational together)
"""

import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database.base import Base
from app.database import (
    JobRepository,
    CandidateRepository,
    InterviewRepository,
    RecommendationRepository,
)
from app.stages.stage4_interview.persistence import InterviewPersistence
from app.workflows.persistence import HiringWorkflowPersistence


@pytest.fixture
def db_session(tmp_path):
    """Use an isolated SQLite database so tests never pollute local app data."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'integration.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_database_connection(db_session):
    """Verifies that the database connection is live and queryable."""
    result = db_session.execute(__import__("sqlalchemy").text("SELECT 1")).scalar()
    assert result == 1


def test_job_and_candidate_repository_lifecycle(db_session):
    """
    Tests Job and Candidate CRUD operations and relational integrity.
    """
    job_repo = JobRepository(db_session)
    cand_repo = CandidateRepository(db_session)

    job_id = f"JOB_DB_{uuid.uuid4().hex[:6].upper()}"
    cand_id = f"CAND_DB_{uuid.uuid4().hex[:6].upper()}"

    # 1. Create Job
    job = job_repo.create(
        job_id=job_id,
        title="Staff AI Engineer",
        department="Autonomous Systems",
        description="Lead research and implementation of agentic architectures.",
        required_skills=["Python", "FastAPI", "PyTorch", "Distributed Systems"],
    )
    assert job.id == job_id
    assert job.department == "Autonomous Systems"

    # 2. Create Candidate attached to Job
    cand = cand_repo.create(
        candidate_id=cand_id,
        name="Elena Rostova",
        email="elena.r@example.com",
        job_id=job_id,
        resume_score=88.5,
        status="SHORTLISTED",
    )
    assert cand.id == cand_id
    assert cand.job_id == job_id

    # 3. Attach Resume to Candidate
    resume = cand_repo.save_resume(
        candidate_id=cand_id,
        raw_text="Experienced in Python, PyTorch, and distributed microservices.",
        parsed_skills=["Python", "PyTorch", "FastAPI"],
        experience_years=7.5,
        score=88.5,
        analysis={"fit_score": 0.88, "tier": "A"},
    )
    assert resume.id is not None
    assert resume.candidate_id == cand_id
    assert resume.score == 88.5

    # 4. Query relationships
    fetched_cand = cand_repo.get_by_id(cand_id)
    assert fetched_cand is not None
    assert fetched_cand.job.title == "Staff AI Engineer"
    assert len(fetched_cand.resumes) >= 1
    assert fetched_cand.resumes[0].experience_years == 7.5


def test_interview_repository_lifecycle(db_session):
    """
    Tests InterviewSession, Turns, and IdentityChecks in the database.
    """
    cand_repo = CandidateRepository(db_session)
    interview_repo = InterviewRepository(db_session)

    cand_id = f"CAND_INT_{uuid.uuid4().hex[:6].upper()}"
    sess_id = f"SESS_INT_{uuid.uuid4().hex[:6].upper()}"

    cand_repo.create(
        candidate_id=cand_id,
        name="Marcus Vance",
        email="marcus.v@example.com",
    )

    # 1. Create Session
    session = interview_repo.create_session(
        session_id=sess_id,
        candidate_id=cand_id,
        status="in_progress",
        identity_verified=False,
        current_question="Explain your approach to concurrency.",
    )
    assert session.id == sess_id
    assert session.turn_count == 0

    # 2. Record Identity Check
    check = interview_repo.record_identity_check(
        candidate_id=cand_id,
        session_id=sess_id,
        verified=True,
        confidence=0.94,
    )
    assert check.verified is True
    assert check.confidence == 0.94

    refreshed_sess = interview_repo.get_session(sess_id)
    assert refreshed_sess.identity_verified is True
    assert refreshed_sess.identity_status == "verified"

    # 3. Record Turns
    turn1 = interview_repo.record_turn(
        session_id=sess_id,
        turn_number=1,
        question="Explain your approach to concurrency.",
        answer="I use asyncio event loops for I/O bound tasks and multiprocessing for CPU bound tasks.",
        scores={"technical_skills": 0.82},
    )
    assert turn1.turn_number == 1
    assert turn1.scores["technical_skills"] == 0.82

    # 4. Finalize Session
    interview_repo.update_session(
        session_id=sess_id,
        status="completed",
        interview_score=0.85,
        competency_scores={"technical_skills": 0.85, "problem_solving": 0.80},
    )

    completed_sess = interview_repo.get_session(sess_id)
    assert completed_sess.status == "completed"
    assert completed_sess.interview_score == 0.85
    assert len(completed_sess.turns) == 1


def test_recommendation_and_review_repository(db_session):
    """
    Tests Recommendation and RecruiterReview persistence.
    """
    cand_repo = CandidateRepository(db_session)
    rec_repo = RecommendationRepository(db_session)

    cand_id = f"CAND_REC_{uuid.uuid4().hex[:6].upper()}"
    cand_repo.create(candidate_id=cand_id, name="Sophia Chen")

    # 1. Save Recommendation
    rec = rec_repo.save_recommendation(
        candidate_id=cand_id,
        resume_score=0.82,
        interview_score=0.86,
        final_score=0.84,
        strengths=["technical_skills", "architecture"],
        gaps=[],
        evidence=[{"observation": "Strong domain knowledge"}],
        status="completed",
    )
    assert rec.final_score == 0.84
    assert "technical_skills" in rec.strengths

    # 2. Save Recruiter Review
    review = rec_repo.save_review(
        candidate_id=cand_id,
        reviewer_id="lead_recruiter",
        decision="APPROVE",
        status="approved",
        notes="Strong hire recommendation.",
    )
    assert review.decision == "APPROVE"
    assert review.status == "approved"

    # 3. Retrieve
    fetched_rec = rec_repo.get_recommendation(cand_id)
    assert fetched_rec is not None
    assert fetched_rec.final_score == 0.84

    fetched_rev = rec_repo.get_review(cand_id)
    assert fetched_rev is not None
    assert fetched_rev.reviewer_id == "lead_recruiter"


def test_dual_persistence_coexistence(db_session, tmp_path):
    """
    Verifies that existing JSON persistence and new Database persistence
    can run side-by-side without interference.
    """
    wf_persistence = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    interview_persistence = InterviewPersistence(output_dir=str(tmp_path / "interviews"))
    cand_repo = CandidateRepository(db_session)

    unique_id = uuid.uuid4().hex[:6].upper()
    job_id = f"JOB_DUAL_{unique_id}"
    sess_id = f"SESS_DUAL_{unique_id}"
    cand_id = f"CAND_DUAL_{unique_id}"

    # JSON persistence operations
    wf_dict = {
        "job_id": job_id,
        "status": "SHORTLISTED",
        "candidate_ids": [cand_id],
    }
    wf_persistence.save(job_id, wf_dict)
    assert wf_persistence.exists(job_id) is True

    interview_dict = {
        "session_id": sess_id,
        "candidate_id": cand_id,
        "interview_complete": True,
    }
    interview_persistence.save(sess_id, interview_dict)
    assert interview_persistence.exists(sess_id) is True

    # Database operations simultaneously
    cand = cand_repo.create(
        candidate_id=cand_id,
        name="Dual Persistence Test",
        job_id=job_id,
    )
    assert cand.id == cand_id

    # Verify both sources can read their respective states
    loaded_wf = wf_persistence.load(job_id)
    loaded_int = interview_persistence.load(sess_id)
    loaded_db_cand = cand_repo.get_by_id(cand_id)

    assert loaded_wf["job_id"] == job_id
    assert loaded_int["session_id"] == sess_id
    assert loaded_db_cand.name == "Dual Persistence Test"
