from app.schemas.interview import InterviewResult
from app.stages.stage4_interview.evaluation.interview_scorer import (
    InterviewScorer,
)
from app.stages.stage4_interview.persistence import (
    InterviewPersistence,
)
from app.stages.stage4_interview.graph.coverage import target_criteria


class InterviewSessionManager:

    def __init__(
        self,
        graph,
        persistence: InterviewPersistence,
    ):
        self.graph = graph
        self.persistence = persistence
        self.scorer = InterviewScorer()

    def create_state(
        self,
        session_id,
        candidate_id,
        candidate,
        competencies,
    ):

        initial_state = {
            "session_id": session_id,
            "candidate_id": candidate_id,
            "candidate": candidate,

            "target_competencies": list(dict.fromkeys(str(item).strip() for item in (competencies or []) if str(item).strip())),
            "current_competency": (
                competencies[0]
                if competencies
                else None
            ),

            "explored_competencies": [],
            "discovered_competencies": [],

            "conversation_history": [],

            "current_question": None,
            "candidate_answer": None,

            "trigger_phrase": None,
            "extracted_signals": [],

            "reasoning": None,
            "reasoning_confidence": 0.0,

            "decision": None,
            "next_question": None,

            "evidence": {},
            "evaluation": None,
            "competency_scores": {},

            "identity_verified": False,
            "identity_status": "pending",
            "identity_failure_reason": None,
            "last_identity_confidence": None,
            "identity_check_count": 0,
            "current_live_frame": None,
            "_identity_checkpoint_passed_for_turn": False,
            "gaze_warning_count": 0,
            "gaze_flagged": False,
            "gaze_events": [],
            "coverage_phase": "horizontal",
            "answered_competency": None,
            "answered_coverage_phase": None,

            "turn_number": 1,
            "interview_complete": False,
            "bad_answer_count": 0,
            "recovery_attempted": False,
        }
        targets = target_criteria(initial_state)
        initial_state["current_competency"] = targets[0] if targets else None
        return initial_state

    def submit_answer(
        self,
        state,
        answer,
    ):

        state["candidate_answer"] = answer

        result = self.graph.invoke(state)

        result["interview_score"] = (
            self.scorer.score(
                result["competency_scores"]
            )
        )

        if result.get("next_question"):
            result["current_question"] = (
                result["next_question"]
            )

        self.persistence.save_state(
            result
        )

        return result

    def build_result(
        self,
        state,
    ) -> InterviewResult:

        if not state.get("interview_complete", False):
            raise RuntimeError(
                "Cannot build result before interview completion."
            )

        status = (
            "identity_failed"
            if not state.get("identity_verified", True)
            else "completed"
        )

        score = self.scorer.score(
            state.get("competency_scores", {})
        )

        return InterviewResult(
            session_id=state["session_id"],
            candidate_id=state["candidate_id"],
            status=status,
            identity_verified=(
                state.get("identity_verified", True)
            ),
            interview_score=score,
            competency_scores=(
                state.get("competency_scores", {})
            ),
            turn_count=(
                state.get("turn_number", 1) - 1
            ),
        )

    def _verify_identity(self, state):

        if self.identity_checkpoint is None:
            raise RuntimeError(
                "Identity checkpoint is not configured."
            )

        result = self.identity_checkpoint.check(
            candidate_id=state["candidate_id"],
            session_id=state["session_id"],
        )

        state["identity_check_count"] += 1
        state["last_identity_confidence"] = result.confidence

        if result.verified:
            state["identity_verified"] = True
            state["identity_status"] = "verified"
            state["identity_failure_reason"] = None
            return True

        state["identity_verified"] = False
        state["identity_status"] = "failed"
        state["identity_failure_reason"] = (
            result.failure_reason
        )

        self.session_manager.persistence.save_state(
            state
        )

        return False
