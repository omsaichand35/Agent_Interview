from enum import Enum


class WorkflowCondition(str, Enum):
    IDENTITY_PASS = "identity_pass"
    IDENTITY_FAILURE = "identity_failure"


def route_after_identity(state) -> str:

    if not state.get("identity_verified", True):
        return WorkflowCondition.IDENTITY_FAILURE.value

    return WorkflowCondition.IDENTITY_PASS.value