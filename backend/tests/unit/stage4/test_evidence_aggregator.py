from app.stages.stage4_interview.evaluation.evidence_aggregator import (
    EvidenceAggregator,
)


def test_multiple_answers_are_aggregated():

    aggregator = EvidenceAggregator()

    result = aggregator.aggregate(
        {
            "technical_skills": [
                {"score": 0.6},
                {"score": 0.9},
                {"score": 0.8},
            ]
        }
    )

    assert "technical_skills" in result

    assert abs(
        result["technical_skills"] - 0.807
    ) < 0.001
