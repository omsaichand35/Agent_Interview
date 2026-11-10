import json

from app.schemas.identity import IdentityResult

from app.stages.stage3_identity.identity_logger import (
    IdentityLogger,
)


def test_identity_log_is_created(tmp_path):

    result = IdentityResult(
        candidate_id="C001",
        session_id="SESSION001",
        verified=True,
        confidence=0.91,
    )

    logger = IdentityLogger()

    path = logger.log(
        result=result,
        output_dir=str(tmp_path),
    )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(file)

    assert data["candidate_id"] == "C001"
    assert data["session_id"] == "SESSION001"
    assert data["verified"] is True
    assert data["confidence"] == 0.91