from datetime import datetime, timezone
from app.core.logging import log_event
from app.evaluation.production_agent_monitor import observe_production_agent_turn


def record_turn(state):
    # Observe the actual completed agent output in production. This records
    # aggregate quality counters only and does not affect candidate decisions.
    observe_production_agent_turn(state)

    turn_num = state.get("turn_number", 1)
    state["turn_number"] = turn_num
    session_id = state.get("session_id")
    candidate_id = state.get("candidate_id")

    decision_trace = {
        "session_id": session_id,
        "turn": turn_num,
        "current_competency": state.get("answered_competency") or state.get("current_competency"),
        "coverage_phase": state.get("answered_coverage_phase", state.get("coverage_phase")),
        "trigger": state.get("trigger_phrase"),
        "decision": state.get("decision"),
        "reasoning_confidence": state.get("reasoning_confidence", 0.85),
        "question_generated": bool(state.get("next_question")),
    }

    turn = {
        "turn_id": turn_num,
        "question": state.get("current_question"),
        "answer": state.get("candidate_answer"),
        "trigger_phrase": state.get("trigger_phrase"),
        "extracted_signals": state.get("extracted_signals", []),
        "reasoning": state.get("reasoning"),
        "decision": state.get("decision"),
        "competency": state.get("answered_competency") or state.get("current_competency"),
        "coverage_phase": state.get("answered_coverage_phase", state.get("coverage_phase")),
        "next_question": state.get("next_question"),
        "trace": decision_trace,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if "conversation_history" not in state:
        state["conversation_history"] = []
    state["conversation_history"].append(turn)

    if "decision_traces" not in state:
        state["decision_traces"] = []
    state["decision_traces"].append(decision_trace)

    state["turn_number"] += 1

    # Emit structured event for observability
    log_event(
        "reasoning_completed",
        session_id=session_id,
        candidate_id=candidate_id,
        turn=turn_num,
        decision=state.get("decision"),
        trigger=state.get("trigger_phrase"),
        current_competency=state.get("current_competency"),
        question_generated=bool(state.get("next_question")),
    )

    return state
