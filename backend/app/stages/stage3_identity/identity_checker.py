from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.schemas.identity import (
    IdentityCheck,
    IdentityResult,
)
from app.stages.stage3_identity.threshold_config import (
    IdentityThresholdConfig,
    get_threshold_config,
)


class IdentityChecker:

    def __init__(
        self,
        face_detector=None,
        face_matcher=None,
        detector=None,
        matcher=None,
        threshold: Optional[float] = None,
        review_threshold: Optional[float] = None,
        threshold_config: Optional[IdentityThresholdConfig] = None,
    ):
        self.face_detector = face_detector if face_detector is not None else detector
        self.face_matcher = face_matcher if face_matcher is not None else matcher
        self.detector = self.face_detector
        self.matcher = self.face_matcher

        self.threshold_config = threshold_config or get_threshold_config()
        self.pass_threshold = (
            threshold
            if threshold is not None
            else self.threshold_config.pass_threshold
        )
        self.threshold = self.pass_threshold
        self.review_threshold = (
            review_threshold
            if review_threshold is not None
            else self.threshold_config.review_threshold
        )

    def verify(
        self,
        candidate_id: str,
        session_id: str,
        reference_path: str,
        live_path: str,
    ) -> IdentityResult:

        checks = []

        # ------------------------------------------------
        # 1. Reference image
        # ------------------------------------------------
        try:
            reference_faces = self.face_detector.detect(reference_path)
            reference_count = len(reference_faces) if reference_faces is not None else 0
        except Exception as exc:
            return IdentityResult(
                candidate_id=candidate_id,
                session_id=session_id,
                verified=False,
                face_detected=False,
                identity_status="failed",
                reason_code="IMAGE_INVALID",
                failure_reason="Invalid reference image format or unreadable.",
                checks=[],
                threshold=self.pass_threshold,
                review_threshold=self.review_threshold,
                matcher=self.threshold_config.model_name,
                face_detector=self.threshold_config.detector_name,
                model_version=self.threshold_config.model_version,
                threshold_version=self.threshold_config.threshold_version,
            )

        if reference_count != 1:
            reason_code = "NO_FACE" if reference_count == 0 else "MULTIPLE_FACES"
            checks.append(
                IdentityCheck(
                    timestamp=datetime.now(timezone.utc),
                    check_type="reference_face_count",
                    face_detected=(reference_count > 0),
                    face_count=reference_count,
                    result="fail",
                    reason_code=reason_code,
                    reason=(
                        "Reference image must contain "
                        "exactly one face."
                    ),
                )
            )

            return IdentityResult(
                candidate_id=candidate_id,
                session_id=session_id,
                verified=False,
                face_detected=(reference_count > 0),
                identity_status="failed",
                reason_code=reason_code,
                checks=checks,
                failure_reason="Invalid reference image.",
                threshold=self.pass_threshold,
                review_threshold=self.review_threshold,
                matcher=self.threshold_config.model_name,
                face_detector=self.threshold_config.detector_name,
                model_version=self.threshold_config.model_version,
                threshold_version=self.threshold_config.threshold_version,
            )

        # ------------------------------------------------
        # 2. Live image
        # ------------------------------------------------
        try:
            live_faces = self.face_detector.detect(live_path)
            live_count = len(live_faces) if live_faces is not None else 0
        except Exception as exc:
            return IdentityResult(
                candidate_id=candidate_id,
                session_id=session_id,
                verified=False,
                face_detected=False,
                identity_status="failed",
                reason_code="IMAGE_INVALID",
                failure_reason="Invalid live frame image.",
                checks=[],
                threshold=self.pass_threshold,
                review_threshold=self.review_threshold,
                matcher=self.threshold_config.model_name,
                face_detector=self.threshold_config.detector_name,
                model_version=self.threshold_config.model_version,
                threshold_version=self.threshold_config.threshold_version,
            )

        if live_count != 1:
            reason_code = "NO_FACE" if live_count == 0 else "MULTIPLE_FACES"
            identity_status = "failed" if live_count == 0 else "review"
            check_result = "fail" if live_count == 0 else "review"
            reason_text = (
                "No face detected in live camera frame."
                if live_count == 0
                else "Multiple faces detected in live camera frame."
            )

            checks.append(
                IdentityCheck(
                    timestamp=datetime.now(timezone.utc),
                    check_type="live_face_count",
                    face_detected=(live_count > 0),
                    face_count=live_count,
                    result=check_result,
                    reason_code=reason_code,
                    reason=reason_text,
                )
            )

            return IdentityResult(
                candidate_id=candidate_id,
                session_id=session_id,
                verified=False,
                face_detected=(live_count > 0),
                identity_status=identity_status,
                reason_code=reason_code,
                checks=checks,
                failure_reason="Invalid live face state.",
                threshold=self.pass_threshold,
                review_threshold=self.review_threshold,
                matcher=self.threshold_config.model_name,
                face_detector=self.threshold_config.detector_name,
                model_version=self.threshold_config.model_version,
                threshold_version=self.threshold_config.threshold_version,
            )

        # ------------------------------------------------
        # 3. Face matching & Liveness Separation
        # ------------------------------------------------
        try:
            if hasattr(self.face_matcher, "compare"):
                confidence = float(self.face_matcher.compare(
                    reference_path=reference_path,
                    live_path=live_path,
                    reference_face=reference_faces[0],
                    live_face=live_faces[0],
                ))
            elif hasattr(self.face_matcher, "match"):
                confidence = float(self.face_matcher.match(
                    reference_image=reference_path,
                    live_image=live_path,
                ))
            else:
                raise AttributeError("Matcher has neither compare nor match method.")
        except Exception as exc:
            return IdentityResult(
                candidate_id=candidate_id,
                session_id=session_id,
                verified=False,
                face_detected=True,
                identity_status="failed",
                reason_code="MODEL_ERROR",
                failure_reason=f"Face matching pipeline error: {exc}",
                checks=checks,
                threshold=self.pass_threshold,
                review_threshold=self.review_threshold,
                matcher=self.threshold_config.model_name,
                face_detector=self.threshold_config.detector_name,
                model_version=self.threshold_config.model_version,
                threshold_version=self.threshold_config.threshold_version,
            )

        # F4.3: Uncertainty calibration (PASS / REVIEW / FAIL)
        if confidence >= self.pass_threshold:
            status = "passed"
            verified = True
            check_result = "pass"
            reason_code = None
            reason_msg = None
            failure_reason = None
        elif confidence >= self.review_threshold:
            status = "review"
            verified = False
            check_result = "review"
            reason_code = "LOW_CONFIDENCE"
            reason_msg = "Borderline face match confidence requires recruiter review."
            failure_reason = "Face match confidence is borderline. Recruiter review required."
        else:
            status = "failed"
            verified = False
            check_result = "fail"
            reason_code = "FACE_NOT_MATCHED"
            reason_msg = "Face confidence is below the configured threshold."
            failure_reason = "Face verification failed."

        checks.append(
            IdentityCheck(
                timestamp=datetime.now(timezone.utc),
                check_type="face_match",
                face_detected=True,
                face_count=1,
                confidence=confidence,
                result=check_result,
                reason=reason_msg,
                reason_code=reason_code,
                liveness_status=self.threshold_config.liveness_status,
            )
        )

        return IdentityResult(
            candidate_id=candidate_id,
            session_id=session_id,
            verified=verified,
            confidence=confidence,
            face_detected=True,
            face_match_score=confidence,
            liveness_status=self.threshold_config.liveness_status,
            identity_status=status,
            reason_code=reason_code,
            matcher=self.threshold_config.model_name,
            face_detector=self.threshold_config.detector_name,
            model_version=self.threshold_config.model_version,
            threshold_version=self.threshold_config.threshold_version,
            threshold=self.pass_threshold,
            review_threshold=self.review_threshold,
            checks=checks,
            failure_reason=failure_reason,
        )

    def check(
        self,
        reference_image: str,
        live_image: str,
        candidate_id: str,
        session_id: str,
    ) -> IdentityResult:
        return self.verify(
            candidate_id=candidate_id,
            session_id=session_id,
            reference_path=reference_image,
            live_path=live_image,
        )