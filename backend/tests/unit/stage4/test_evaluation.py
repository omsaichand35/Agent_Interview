from app.stages.stage4_interview.evaluation.evidence import (
    build_evidence,
)
from app.stages.stage4_interview.evaluation.competency_scorer import (
    CompetencyScorer,
)
from app.stages.stage4_interview.evaluation.interview_scorer import (
    InterviewScorer,
)


def test_evidence_is_created():

    evidence = build_evidence(
        competency="leadership",
        answer="I mentored two junior developers.",
        extracted_signals=["leadership"],
    )

    assert evidence.competency == "leadership"
    assert evidence.evidence_strength > 0


def test_competency_score():

    evidence = [
        build_evidence(
            competency="leadership",
            answer="I mentored two junior developers.",
            extracted_signals=["leadership"],
        ),
        build_evidence(
            competency="leadership",
            answer="I led the project team.",
            extracted_signals=["leadership"],
        ),
    ]

    scorer = CompetencyScorer()

    scores = scorer.score(evidence)

    assert "leadership" in scores
    assert scores["leadership"] > 0


def test_interview_score():

    scorer = InterviewScorer()

    score = scorer.score(
        {
            "technical_skills": 0.8,
            "leadership": 0.9,
            "databases": 0.7,
        }
    )

    assert score == 80.0