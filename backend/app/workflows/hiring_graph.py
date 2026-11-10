from typing import TypedDict, List, Dict, Optional

class HiringState(TypedDict):

    job_id: str
    job_description: Dict

    candidate_ids: List[str]
    candidates: List[Dict]

    shortlist: List[Dict]
    schedules: List[Dict]

    current_candidate_id: Optional[str]

    identity_results: Dict[str, Dict]

    interview_sessions: Dict[str, Dict]
    interview_results: Dict[str, Dict]

    recommendations: List[Dict]
    human_review: List[Dict]

    status: str
    error: Optional[str]

def run_stage1(state: HiringState, services):

    result = services.resume_service.run(
        job_description=state["job_description"],
        candidates=state["candidates"],
    )

    state["shortlist"] = result["shortlist"]
    state["status"] = "shortlisted"

    return state

def run_stage2(state: HiringState, services):

    result = services.scheduling_service.schedule(
        shortlist=state["shortlist"],
    )

    state["schedules"] = result["schedules"]
    state["status"] = "scheduled"

    return state

def select_next_candidate(
    state: HiringState,
):

    processed = set(
        state["identity_results"].keys()
    )

    for schedule in state["schedules"]:

        candidate_id = schedule["candidate_id"]

        if candidate_id not in processed:
            state["current_candidate_id"] = candidate_id
            return state

    state["current_candidate_id"] = None

    return state

def run_stage3(
    state: HiringState,
    services,
):

    candidate_id = state[
        "current_candidate_id"
    ]

    candidate = next(
        c
        for c in state["candidates"]
        if c["candidate_id"] == candidate_id
    )

    result = services.identity_service.verify(
        candidate_id=candidate_id,
        session_id=f"INTERVIEW_{candidate_id}",
        reference_image=candidate["photo_path"],
        live_image=candidate["live_image_path"],
    )

    state["identity_results"][candidate_id] = (
        result.model_dump()
    )

    return state

run_identity_check = run_stage3

def route_after_identity(state):

    candidate_id = state[
        "current_candidate_id"
    ]

    result = state[
        "identity_results"
    ][candidate_id]

    if result["verified"]:
        return "interview"

    return "human_review"

def send_to_human_review(
    state: HiringState,
):

    candidate_id = state[
        "current_candidate_id"
    ]

    identity_result = state[
        "identity_results"
    ][candidate_id]

    state["human_review"].append({
        "candidate_id": candidate_id,
        "reason": identity_result.get(
            "failure_reason",
            "Identity verification failed.",
        ),
        "identity_result": identity_result,
    })

    return state

def run_stage4(
    state,
    services,
):

    candidate_id = state[
        "current_candidate_id"
    ]

    candidate = next(
        c
        for c in state["candidates"]
        if c["candidate_id"] == candidate_id
    )

    session_id = (
        f"INTERVIEW_{candidate_id}"
    )

    interview_state = (
        services.interview_controller.start(
            session_id=session_id,
            candidate_id=candidate_id,
            candidate=candidate,
            competencies=candidate.get(
                "target_competencies",
                candidate.get("competencies", []),
            ),
            first_question=(
                "Tell me about your most "
                "relevant engineering experience."
            ),
        )
    )

    state["interview_sessions"][
        candidate_id
    ] = interview_state

    state["status"] = "interview_ready"

    if hasattr(services, "persistence") and services.persistence is not None:
        services.persistence.save(state)

    return state

def run_stage5(
    state: HiringState,
    services,
):

    candidate_id = state[
        "current_candidate_id"
    ]

    candidate = next(
        candidate
        for candidate in state["candidates"]
        if candidate["candidate_id"] == candidate_id
    )

    interview = state[
        "interview_results"
    ][candidate_id]

    recommendation = (
        services.recommendation_service.generate(
            candidate=candidate,
            interview_result=interview,
            identity_result=state[
                "identity_results"
            ][candidate_id],
        )
    )

    state["recommendations"].append(
        recommendation.model_dump()
    )

    return state

from langgraph.graph import StateGraph, END


def build_hiring_graph(services):

    graph = StateGraph(HiringState)

    graph.add_node(
        "stage1_resume",
        lambda state: run_stage1(
            state,
            services,
        ),
    )

    graph.add_node(
        "stage2_schedule",
        lambda state: run_stage2(
            state,
            services,
        ),
    )

    graph.add_node(
        "select_candidate",
        select_next_candidate,
    )

    graph.add_node(
        "stage3_identity",
        lambda state: run_stage3(
            state,
            services,
        ),
    )

    graph.add_node(
        "human_review",
        send_to_human_review,
    )

    graph.add_node(
        "stage4_interview",
        lambda state: run_stage4(
            state,
            services,
        ),
    )

    graph.add_node(
        "stage5_recommendation",
        lambda state: run_stage5(
            state,
            services,
        ),
    )

    graph.set_entry_point(
        "stage1_resume"
    )

    graph.add_edge(
        "stage1_resume",
        "stage2_schedule",
    )

    graph.add_edge(
        "stage2_schedule",
        "select_candidate",
    )

    graph.add_conditional_edges(
        "stage3_identity",
        route_after_identity,
        {
            "interview": "stage4_interview",
            "human_review": "human_review",
        },
    )

    graph.add_edge(
        "human_review",
        "select_candidate",
    )

    graph.add_edge(
        "stage4_interview",
        END,
    )

    graph.add_edge(
        "stage5_recommendation",
        "select_candidate",
    )

    graph.add_conditional_edges(
        "select_candidate",
        route_after_candidate_selection,
        {
            "identity": "stage3_identity",
            "done": END,
        },
    )

    return graph.compile()

def route_after_candidate_selection(
    state: HiringState,
):

    if state["current_candidate_id"] is None:
        return "done"

    return "identity"

def create_hiring_state(
    job_id,
    job_description,
    candidates,
):

    return {
        "job_id": job_id,

        "job_description": (
            job_description
        ),

        "candidate_ids": [
            candidate["candidate_id"]
            for candidate in candidates
        ],

        "candidates": candidates,

        "shortlist": [],

        "schedules": [],

        "current_candidate_id": None,

        "identity_results": {},

        "interview_sessions": {},

        "interview_results": {},

        "recommendations": [],

        "human_review": [],

        "status": "created",

        "error": None,
    }