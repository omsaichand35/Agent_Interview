def normalized_identity_status(result):
    """Resolve status without allowing a contradictory status to bypass verification."""
    status = getattr(result, "identity_status", None)
    if status == "review":
        return "review"
    if bool(getattr(result, "verified", False)) and status in (None, "passed", "verified"):
        return "passed"
    return "failed"


class IdentityCheckpoint:

    def __init__(
        self,
        camera=None,
        identity_monitor=None,
        reference_image=None,
    ):
        self.camera = camera
        self.identity_monitor = identity_monitor
        self.reference_image = reference_image

    def check(
        self,
        candidate_id,
        session_id,
        live_image=None,
    ):
        # Browser-provided frame
        if live_image is not None:
            live_frame = live_image

        # Local camera fallback
        elif self.camera is not None:
            live_frame = self.camera.capture_frame()

        else:
            raise RuntimeError(
                "No live image or camera is available."
            )

        return self.identity_monitor.verify(
            reference_image=self.reference_image,
            live_image=live_frame,
            candidate_id=candidate_id,
            session_id=session_id,
        )


def apply_identity_result(state, result):
    state["identity_verified"] = bool(result.verified)
    state["last_identity_confidence"] = getattr(result, "confidence", None)
    state["face_match_score"] = getattr(result, "face_match_score", getattr(result, "confidence", None))
    state["liveness_status"] = getattr(result, "liveness_status", "not_implemented")
    state["identity_check_count"] = state.get("identity_check_count", 0) + 1
    state["identity_reason_code"] = getattr(result, "reason_code", None)

    status = normalized_identity_status(result)

    if status == "passed":
        state["identity_status"] = "passed"
        state["identity_verified"] = True
        state["identity_failure_reason"] = None
        state["workflow_condition"] = "identity_pass"
        return state

    if status == "review":
        state["identity_status"] = "review"
        state["identity_verified"] = False
        state["identity_failure_reason"] = getattr(result, "failure_reason", None) or "Identity under recruiter review."
        state["workflow_condition"] = "identity_review"
        return state

    state["identity_status"] = "failed"
    state["identity_verified"] = False
    state["identity_failure_reason"] = getattr(result, "failure_reason", None)
    state["workflow_condition"] = "identity_failure"
    return state
