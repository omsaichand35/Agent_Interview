from app.config import settings

from app.llm.provider import get_llm_client

from app.stages.stage4_interview.graph.interview_graph import (
    build_interview_graph,
)

from app.stages.stage4_interview.persistence import (
    InterviewPersistence,
)

from app.stages.stage4_interview.session import (
    InterviewSessionManager,
)

from app.stages.stage4_interview.controller import (
    InterviewController,
)

from app.stages.stage4_interview.registry import (
    InterviewSessionRegistry,
)


registry = InterviewSessionRegistry()


class DefaultLiveIdentityCheckpoint:
    """Compare each submitted live frame with the application's enrolled face."""

    def check(self, candidate_id=None, session_id=None, live_image=None, **kwargs):
        from app.api.dependencies import get_identity_service

        state = registry.get(session_id) if session_id in registry else {}
        candidate = state.get("candidate", {})
        reference_path = candidate.get("photo_path") if isinstance(candidate, dict) else None
        if not reference_path or not live_image:
            from app.schemas.identity import IdentityResult
            return IdentityResult(
                candidate_id=candidate_id or "unknown",
                session_id=session_id or "unknown",
                verified=False,
                identity_status="failed",
                failure_reason="A live frame and enrolled face reference are required.",
                reason_code="REFERENCE_OR_FRAME_MISSING",
            )

        return get_identity_service().verify(
            candidate_id=candidate_id,
            session_id=session_id,
            reference_image=reference_path,
            live_image=live_image,
        )



def create_interview_controller(
    workflow_resumer=None,
    identity_checkpoint=None,
    llm_client=None,
):

    llm_client = llm_client or get_llm_client()

    if identity_checkpoint is None:
        identity_checkpoint = DefaultLiveIdentityCheckpoint()

    graph = build_interview_graph(
        llm_client=llm_client,
        identity_checkpoint=identity_checkpoint,
    )

    persistence = InterviewPersistence(
        output_dir="data/outputs/interviews"
    )

    session_manager = InterviewSessionManager(
        graph=graph,
        persistence=persistence,
    )

    return InterviewController(
        session_manager=session_manager,
        workflow_resumer=workflow_resumer,
        identity_checkpoint=identity_checkpoint,
    )
