from app.stages.stage5_recommendation.recommendation_service import (
    RecommendationService,
)
from app.stages.stage5_recommendation.scorer import FinalScorer


def test_final_score():

    service = RecommendationService()

    result = service.generate(
        candidate={
            "candidate_id": "C001",
            "resume_score": 71.3,
        },
        interview_result={
            "interview_score": 82.5,
            "competency_scores": {
                "technical_skills": 0.85,
                "leadership": 0.80,
                "databases": 0.45,
            },
        },
        identity_result={
            "verified": True,
        },
    )

    assert result.final_score == 78.02
    assert result.identity_verified is True

    assert (
        "technical_skills"
        in result.strengths
    )

    assert (
        "databases"
        in result.gaps
    )


def test_identity_failure():

    service = RecommendationService()

    result = service.generate(
        candidate={
            "candidate_id": "C001",
            "resume_score": 90.0,
        },
        interview_result={
            "interview_score": 95.0,
        },
        identity_result={
            "verified": False,
        },
    )

    assert result.identity_verified is False
    assert result.status == "human_review"
    assert result.final_score == 0.0


def test_final_scorer():
    scorer = FinalScorer()
    assert scorer.score(71.3, 82.5) == 78.02
