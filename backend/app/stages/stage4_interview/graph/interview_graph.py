from langgraph.graph import StateGraph, END

from app.stages.stage4_interview.graph.state import InterviewState
from app.stages.stage4_interview.graph.nodes import (
    create_nodes,
    check_completion,
)
from app.stages.stage4_interview.graph.trace import record_turn
from app.stages.stage4_interview.graph.progression import (
    update_competency_progress,
)
from app.stages.stage4_interview.identity_checkpoint import (
    apply_identity_result,
)


def build_interview_graph(
    llm_client,
    identity_checkpoint=None,
):
    (
        reason_about_answer,
        evaluate_answer,
        generate_next_question,
    ) = create_nodes(llm_client)

    def identity_checkpoint_node(state):

        # The controller has just verified the live frame before this graph
        # invocation (and, for audio, before transcription). Consume that
        # server-only one-turn marker instead of checking again without the
        # original frame. Direct graph invocations still pass through the gate.
        if state.pop("_identity_checkpoint_passed_for_turn", False):
            state["current_live_frame"] = None
            return state

        if identity_checkpoint is None:
            state["identity_verified"] = True
            state["last_identity_confidence"] = 1.0
            state["current_live_frame"] = None
            return state

        try:
            result = identity_checkpoint.check(
                candidate_id=state.get("candidate_id"),
                session_id=state.get("session_id"),
                live_image=state.get("current_live_frame"),
            )
        except TypeError:
            result = identity_checkpoint.check(
                session_id=state.get("session_id")
            )

        state = apply_identity_result(state, result)
        state["current_live_frame"] = None
        return state


    def route_after_identity(state):

        if not state.get("identity_verified", True):
            return "stop"

        return "continue"

    graph = StateGraph(InterviewState)

    graph.add_node(
        "identity_checkpoint",
        identity_checkpoint_node,
    )

    graph.add_node(
        "reason",
        reason_about_answer,
    )

    graph.add_node(
        "evaluate_answer",
        evaluate_answer,
    )

    graph.add_node(
        "update_competency",
        update_competency_progress,
    )

    graph.add_node(
        "check_completion",
        check_completion,
    )

    graph.add_node(
        "generate_question",
        generate_next_question,
    )

    graph.add_node(
        "record_turn",
        record_turn,
    )

    graph.set_entry_point("identity_checkpoint")

    graph.add_conditional_edges(
        "identity_checkpoint",
        route_after_identity,
        {
            "stop": "record_turn",
            "continue": "reason",
        },
    )

    graph.add_edge(
        "reason",
        "evaluate_answer",
    )

    graph.add_edge(
        "evaluate_answer",
        "update_competency",
    )

    graph.add_edge(
        "update_competency",
        "check_completion",
    )

    graph.add_edge(
        "check_completion",
        "generate_question",
    )

    graph.add_edge(
        "generate_question",
        "record_turn",
    )

    graph.add_edge(
        "record_turn",
        END,
    )

    return graph.compile()
