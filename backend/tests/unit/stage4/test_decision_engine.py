from app.stages.stage4_interview.reasoning.decision_engine import InterviewDecision
from app.stages.stage4_interview.graph.routing import WorkflowCondition


def test_interview_decision_enum_values():
    expected_decisions = {"deepen", "pivot", "next_competency", "recover", "conclude"}
    actual_decisions = {d.value for d in InterviewDecision}

    assert actual_decisions == expected_decisions
    assert "identity_failure" not in actual_decisions


def test_workflow_condition_enum_values():
    expected_conditions = {"identity_pass", "identity_failure"}
    actual_conditions = {c.value for c in WorkflowCondition}

    assert actual_conditions == expected_conditions
    assert actual_conditions.isdisjoint({d.value for d in InterviewDecision})
