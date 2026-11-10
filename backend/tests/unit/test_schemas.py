from app.schemas import (
    Candidate,
    Competency,
    JobDescription,
    InterviewSession,
    InterviewTurn,
)


def test_candidate_creation():

    candidate = Candidate(
        candidate_id="C001",
        name="Test Candidate",
        email="test@example.com"
    )

    assert candidate.candidate_id == "C001"
    assert candidate.name == "Test Candidate"


def test_job_description_creation():

    competency = Competency(
        id="python",
        name="Python",
        description="Strong Python programming",
        weight=1.0
    )

    job = JobDescription(
        job_id="JOB001",
        title="Python Developer",
        description="Backend developer",
        competencies=[competency]
    )

    assert job.title == "Python Developer"
    assert len(job.competencies) == 1


def test_interview_turn():

    turn = InterviewTurn(
        turn_id=1,
        question="Tell me about a difficult problem you solved.",
        answer="I optimized our API."
    )

    assert turn.turn_id == 1
    assert turn.answer == "I optimized our API."


def test_interview_session():

    session = InterviewSession(
        session_id="INT001",
        candidate_id="C001"
    )

    assert session.status == "created"
    assert session.turns == []