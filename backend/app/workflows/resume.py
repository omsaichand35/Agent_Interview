class HiringWorkflowResumer:
    """
    Resumes a hiring workflow from any persisted status.

    resume(job_id)
    --------------
    Loads the workflow from disk, inspects its current status, and
    dispatches to the appropriate next stage.  Completed stages are
    NOT re-run -- the status field is the single source of truth for
    where the pipeline left off.

    Status dispatch table
    ---------------------
    CREATED               -> shortlisting
    SHORTLISTED           -> scheduling
    SCHEDULED             -> (no-op: waits for candidate to arrive)
    IDENTITY_CHECK        -> (no-op: waits for identity result)
    INTERVIEW_READY       -> (no-op: waits for interview start)
    INTERVIEW_IN_PROGRESS -> resume_interview (restore interview session)
    INTERVIEW_COMPLETED   -> generate_recommendation
    RECOMMENDATION_READY  -> mark completed
    COMPLETED / other     -> return as-is
    """

    def __init__(
        self,
        persistence=None,
        recommendation_service=None,
        workflow_session_manager=None,
    ):
        if persistence is None:
            from app.workflows.persistence import HiringWorkflowPersistence
            persistence = HiringWorkflowPersistence()
        if recommendation_service is None:
            from app.stages.stage5_recommendation.recommendation_service import (
                RecommendationService,
            )
            recommendation_service = RecommendationService()
        self.persistence = persistence
        self.recommendation_service = recommendation_service
        self.workflow_session_manager = workflow_session_manager


    # ------------------------------------------------------------------
    # Top-level resume dispatcher
    # ------------------------------------------------------------------

    def resume(self, job_id: str) -> dict:
        """
        Load the workflow for *job_id* and advance it from its current
        status.  Returns the (possibly updated) workflow state dict.

        Raises ValueError if the workflow does not exist on disk.
        """
        workflow = self.persistence.load(job_id)

        if workflow is None:
            raise ValueError(
                f"Workflow not found: {job_id}. "
                "It may not have been persisted yet."
            )

        status = (workflow.get("status") or "").upper()

        mgr = self.workflow_session_manager

        if status == "CREATED":
            if mgr:
                return mgr.run_shortlisting(workflow)
            return workflow

        if status == "SHORTLISTED":
            if mgr:
                return mgr.run_scheduling(workflow)
            return workflow

        # SCHEDULED / IDENTITY_CHECK / INTERVIEW_READY:
        # The pipeline is waiting for an external event (candidate arrival,
        # camera frame, interview start).  Nothing to advance automatically.
        if status in ("SCHEDULED", "IDENTITY_CHECK", "INTERVIEW_READY"):
            return workflow

        if status in ("INTERVIEW_IN_PROGRESS", "INTERVIEW_COMPLETED"):
            # The interview session itself handles its own persistence.
            # Return the workflow as-is so the route handler can display
            # the current state without accidentally re-starting anything.
            return workflow

        if status == "RECOMMENDATION_READY":
            if mgr:
                candidate_id = workflow.get("current_candidate_id")
                if candidate_id and candidate_id not in workflow.get("recommendations", {}):
                    return mgr.generate_recommendation(workflow, candidate_id)
            return workflow

        # COMPLETED or unknown status: nothing to do.
        return workflow

    # ------------------------------------------------------------------
    # Post-interview callback (called by the interview route on completion)
    # ------------------------------------------------------------------

    def resume_after_interview(
        self,
        state,
        interview_result,
    ):
        candidate_id = state["current_candidate_id"]

        if hasattr(interview_result, "model_dump"):
            stored_result = interview_result.model_dump()
        else:
            stored_result = interview_result

        state["interview_results"][candidate_id] = stored_result
        state["status"] = "interview_completed"

        recommendation = self.recommendation_service.generate(
            candidate=self._get_candidate(state, candidate_id),
            interview_result=stored_result,
            identity_result=state["identity_results"][candidate_id],
        )

        if hasattr(recommendation, "model_dump"):
            recommendation = recommendation.model_dump()

        state["recommendations"].append(recommendation)
        state["status"] = "recommendation_ready"

        self.persistence.save(state["job_id"], state)

        return state

    # ------------------------------------------------------------------
    # Aliases kept for backwards compatibility
    # ------------------------------------------------------------------

    resume_interview = resume_after_interview

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_candidate(state, candidate_id):
        return next(
            candidate
            for candidate in state["candidates"]
            if candidate["candidate_id"] == candidate_id
        )
