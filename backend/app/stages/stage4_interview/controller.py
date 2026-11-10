from app.stages.stage4_interview.identity_checkpoint import normalized_identity_status


class SessionState(dict):
    """Dictionary subclass supporting attribute-style access for session state."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'SessionState' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value

class InterviewController:

    def __init__(
        self,
        session_manager,
        voice_service=None,
        identity_checkpoint=None,
        workflow_resumer=None,
        identity_check_interval: int = 3,
    ):
        self.session_manager = session_manager
        self.voice_service = voice_service
        self.identity_checkpoint = identity_checkpoint
        self.workflow_resumer = workflow_resumer
        self.identity_check_interval = identity_check_interval

    def start(
        self,
        session_id=None,
        candidate_id=None,
        candidate=None,
        competencies=None,
        first_question=None,
        **kwargs,
    ):
        # Support both positional and keyword argument orders
        sess_id = session_id or kwargs.get("session_id")
        cand_id = candidate_id or kwargs.get("candidate_id")
        cand = candidate or kwargs.get("candidate") or {"candidate_id": cand_id, "name": "Candidate"}
        comps = competencies or kwargs.get("competencies") or ["technical_skills", "problem_solving"]
        comps = list(dict.fromkeys(str(item).strip() for item in comps if str(item).strip()))
        starts_with_introduction = not first_question
        if not first_question:
            from app.stages.stage4_interview.questions.question_generator import generate_opening_question
            first_question = generate_opening_question(cand.get("program_title"))

        state = self.session_manager.create_state(
            session_id=sess_id,
            candidate_id=cand_id,
            candidate=cand,
            competencies=comps,
        )

        state["current_question"] = first_question
        state["next_question"] = first_question
        if starts_with_introduction:
            state["coverage_phase"] = "introduction"
            state["current_competency"] = None

        return SessionState(state)

    def _verify_identity(self, state, live_image=None):

        if self.identity_checkpoint is None:
            raise RuntimeError(
                "Identity checkpoint is not configured."
            )

        if live_image is not None:
            state["current_live_frame"] = live_image

        try:
            result = self.identity_checkpoint.check(
                candidate_id=state["candidate_id"],
                session_id=state["session_id"],
                live_image=live_image,
            )
        except TypeError:
            try:
                result = self.identity_checkpoint.check(
                    candidate_id=state["candidate_id"],
                    session_id=state["session_id"],
                )
            except TypeError:
                result = self.identity_checkpoint.check(
                    session_id=state["session_id"],
                )

        state["identity_check_count"] = state.get("identity_check_count", 0) + 1
        state["last_identity_confidence"] = getattr(result, "confidence", None)
        state["face_match_score"] = getattr(result, "face_match_score", getattr(result, "confidence", None))
        state["liveness_status"] = getattr(result, "liveness_status", "not_implemented")
        state["identity_reason_code"] = getattr(result, "reason_code", None)

        status = normalized_identity_status(result)

        if status == "passed":
            state["identity_verified"] = True
            state["identity_status"] = "verified"
            state["identity_failure_reason"] = None
            state["_identity_checkpoint_passed_for_turn"] = True
            return True

        if status == "review":
            state["identity_verified"] = False
            state["identity_status"] = "review"
            state["identity_failure_reason"] = (
                getattr(result, "failure_reason", None) or "Identity verification under recruiter review."
            )
            return False

        state["identity_verified"] = False
        state["identity_status"] = "failed"
        state["identity_failure_reason"] = (
            getattr(result, "failure_reason", "Face verification failed.")
        )

        if hasattr(self.session_manager, "persistence") and hasattr(
            self.session_manager.persistence, "save_state"
        ):
            self.session_manager.persistence.save_state(state)

        return False

    def submit_text(self, state, answer, live_image=None):

        if state.get("interview_complete", False):
            raise RuntimeError(
                "Interview is already complete."
            )

        if not self._verify_identity(state, live_image=live_image):
            return SessionState(state)

        result = self.session_manager.submit_answer(
            state,
            answer,
        )

        return SessionState(result)

    def submit_audio(self, state, audio_path, live_image=None):

        if state.get("interview_complete", False):
            raise RuntimeError(
                "Interview is already complete."
            )

        if self.voice_service is None:
            raise RuntimeError(
                "Voice service is not configured."
            )

        # Identity MUST happen before STT.
        if not self._verify_identity(state, live_image=live_image):
            return {
                "state": SessionState(state),
                "transcript": None,
                "next_question": None,
                "audio_path": None,
            }

        answer = self.voice_service.transcribe(
            audio_path
        )

        result = self.session_manager.submit_answer(
            state,
            answer,
        )

        next_question = result.get(
            "next_question"
        )

        output_audio = None

        if next_question:

            output_audio = self.voice_service.speak(
                next_question,
                (
                    f"data/outputs/interviews/"
                    f"{result['session_id']}_"
                    f"turn_{result['turn_number']}.wav"
                ),
            )

        return {
            "state": SessionState(result),
            "transcript": answer,
            "next_question": next_question,
            "audio_path": output_audio,
        }

    def complete(self, state):
        """Finalizes the interview, builds the InterviewResult, and triggers workflow resumer."""
        state["interview_complete"] = True
        result = self.session_manager.build_result(state)

        if hasattr(self.session_manager, "persistence") and hasattr(
            self.session_manager.persistence, "save_state"
        ):
            self.session_manager.persistence.save_state(state)

        if self.workflow_resumer is not None:
            job_id = state.get("job_id")
            if job_id and hasattr(self.workflow_resumer, "resume_interview"):
                try:
                    self.workflow_resumer.resume_interview(job_id, result)
                except Exception:
                    pass
            elif job_id and hasattr(self.workflow_resumer, "resume_after_interview"):
                try:
                    self.workflow_resumer.resume_after_interview(state, result)
                except Exception:
                    pass

        return result
