def test_identity_failure_prevents_reasoning():

    events = []

    class FakeIdentityResult:
        verified = False
        confidence = 0.20
        failure_reason = "Face mismatch"
        checks = []

    class FakeCheckpoint:

        def check(self, candidate_id, session_id):
            events.append("identity")
            return FakeIdentityResult()

    class FakeReasoner:

        def analyze(self, **kwargs):
            events.append("reasoning")
            raise AssertionError(
                "Reasoning must not run after identity failure."
            )

    def checkpoint_node(state):
        result = FakeCheckpoint().check(
            state["candidate_id"],
            state["session_id"],
        )

        state["identity_verified"] = result.verified
        state["identity_failure_reason"] = (
            result.failure_reason
        )

        return state

    state = {
        "candidate_id": "C001",
        "session_id": "S001",
        "identity_verified": False,
        "identity_failure_reason": None,
    }

    checkpoint_node(state)

    assert state["identity_verified"] is False
    assert state["identity_failure_reason"] == "Face mismatch"
    assert events == ["identity"]