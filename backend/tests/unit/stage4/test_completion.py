from app.stages.stage4_interview.graph.completion import (
    should_conclude,
)


def make_state():

    return {
        "turn_number": 6,
        "target_competencies": [
            "technical_skills",
            "leadership",
            "databases",
        ],
        "explored_competencies": [
            "technical_skills",
            "leadership",
            "databases",
        ],
        "competency_scores": {
            "technical_skills": 0.8,
            "leadership": 0.9,
            "databases": 0.75,
        },
    }


def test_interview_concludes_with_enough_evidence():

    state = make_state()

    assert should_conclude(state) is True


def test_interview_does_not_end_too_early():

    state = make_state()

    state["turn_number"] = 2
    state["explored_competencies"] = [
        "technical_skills"
    ]

    assert should_conclude(state) is False


def test_interview_has_hard_maximum():

    state = make_state()

    state["turn_number"] = 15

    assert should_conclude(state) is True
