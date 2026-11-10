from app.stages.stage4_interview.graph.interview_graph import (
    build_interview_graph,
)

from tests.fixtures.mock_llm import (
    MockInterviewLLM,
)


def make_state():

    return {
        "session_id": "SESSION001",
        "candidate_id": "C001",

        "candidate": {},

        "target_competencies": [
            "technical_skills",
            "leadership",
            "databases",
        ],

        "current_competency":
            "technical_skills",

        "explored_competencies": [
            "technical_skills"
        ],

        "discovered_competencies": [],

        "conversation_history": [],

        "current_question": (
            "Tell me about your backend experience."
        ),

        "candidate_answer": (
            "I built a FastAPI backend and "
            "I also mentored two junior developers."
        ),

        "trigger_phrase": None,

        "extracted_signals": [],

        "reasoning": None,

        "reasoning_confidence": 0.0,

        "decision": None,

        "next_question": None,

        "evidence": {},

        "competency_scores": {},

        "identity_verified": True,
        "identity_failure_reason": None,
        "last_identity_confidence": 1.0,
        "identity_check_count": 0,
        "current_live_frame": None,

        "turn_number": 1,
        "interview_complete": False,
    }


def test_agent_pivots_to_new_competency():

    graph = build_interview_graph(
        MockInterviewLLM()
    )

    result = graph.invoke(
        make_state()
    )

    assert (
        result["decision"]
        == "pivot"
    )

    assert (
        result["trigger_phrase"]
        == "mentored two junior developers"
    )

    assert (
        "leadership"
        in result[
            "discovered_competencies"
        ]
    )

    assert (
        result["next_question"]
        is not None
    )

    assert (
        "mentored"
        in result["next_question"]
    )


def test_turn_is_recorded():

    graph = build_interview_graph(
        MockInterviewLLM()
    )

    result = graph.invoke(
        make_state()
    )

    assert len(
        result["conversation_history"]
    ) == 1

    turn = (
        result["conversation_history"][0]
    )

    assert turn["turn_id"] == 1
    assert turn["decision"] == "pivot"
    assert (
        turn["trigger_phrase"]
        == "mentored two junior developers"
    )


def test_interview_concludes_when_limits_reached():

    graph = build_interview_graph(
        MockInterviewLLM()
    )

    state = make_state()
    state["turn_number"] = 15

    result = graph.invoke(state)

    assert result["decision"] == "conclude"
    assert result["interview_complete"] is True
    assert result["next_question"] is None


def test_interview_halts_on_identity_failure():

    class MockFailedCheckpoint:
        def check(self, session_id):
            from app.schemas.identity import IdentityResult
            return IdentityResult(
                candidate_id="C001",
                session_id=session_id,
                verified=False,
                confidence=0.25,
                failure_reason="Multiple faces detected in live camera frame.",
            )

    graph = build_interview_graph(
        MockInterviewLLM(),
        identity_checkpoint=MockFailedCheckpoint(),
    )

    state = make_state()
    result = graph.invoke(state)

    assert result["identity_verified"] is False
    assert result["interview_complete"] is True
    assert result["decision"] is None
    assert result.get("workflow_condition") == "identity_failure"
    assert "Multiple faces" in result["identity_failure_reason"]
    assert result["next_question"] is None

