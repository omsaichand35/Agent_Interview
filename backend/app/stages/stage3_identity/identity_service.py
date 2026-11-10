import time
from pathlib import Path
from typing import Optional, Union

from app.core.logging import log_event
from app.core.metrics import get_metrics_collector
from app.schemas.identity import IdentityResult
from app.stages.stage3_identity.identity_checker import IdentityChecker
from app.stages.stage3_identity.identity_logger import IdentityLogger
from app.stages.stage3_identity.matcher_factory import create_face_matcher


class IdentityService:

    def __init__(
        self,
        logger: Optional[IdentityLogger] = None,
        log_dir: str = "data/outputs/identity_logs",
        checker: Optional[IdentityChecker] = None,
    ):
        if isinstance(logger, (str, Path)):
            log_dir = str(logger)
            logger = None

        detector, matcher = create_face_matcher()

        self.checker = checker or IdentityChecker(
            detector=detector,
            matcher=matcher,
            face_detector=detector,
            face_matcher=matcher,
        )

        self.logger = logger or IdentityLogger()
        if logger is not None and hasattr(logger, "output_dir") and log_dir == "data/outputs/identity_logs":
            self.log_dir = logger.output_dir
        else:
            self.log_dir = log_dir

    def verify(
        self,
        candidate_id: str,
        session_id: str,
        reference_image: str,
        live_image: str,
        log_dir: Optional[str] = None,
    ) -> IdentityResult:

        start_time = time.perf_counter()
        result = self.checker.verify(
            candidate_id=candidate_id,
            session_id=session_id,
            reference_path=reference_image,
            live_path=live_image,
        )
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        log_event(
            event="identity_completed",
            candidate_id=candidate_id,
            session_id=session_id,
            verified=result.verified,
            confidence=result.confidence,
            duration_ms=duration_ms,
        )
        get_metrics_collector().record_identity_check(passed=result.verified)

        output_dir = log_dir or self.log_dir
        try:
            self.logger.log(
                result=result,
                output_dir=output_dir,
            )
        except TypeError:
            self.logger.log(result)

        return result

    def verify_candidate(
        self,
        candidate_id: str,
        session_id: str,
        reference_path: str,
        live_path: str,
        log_dir: str = "data/outputs/identity_logs",
    ):
        result = self.verify(
            candidate_id=candidate_id,
            session_id=session_id,
            reference_image=reference_path,
            live_image=live_path,
            log_dir=log_dir,
        )

        log_path = Path(log_dir) / f"identity_log_{result.session_id}.json"

        return {
            "result": result,
            "log_path": str(log_path),
        }