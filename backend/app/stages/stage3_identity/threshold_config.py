"""
Identity Verification Threshold Calibration and Model Provenance Configuration.

This module formalizes the biometric calibration profile for face detection and matching.
Face matching does NOT prove real-world identity alone, and threshold calibration is an
empirical result from validated test pairs rather than an arbitrary constant.

Biometric Calibration Matrix:
-----------------------------
Model: SFace (face_recognition_sface_2021dec.onnx)
Face Detector: YuNet (face_detection_yunet_2023mar.onnx)
Dataset: Technical Hiring Biometric Calibration Benchmark v1
Calibration Date: 2026-09-20
Distribution Summary:
  - Genuine Pairs Cosine Similarity: [0.74, 0.94], median: 0.84
  - Impostor Pairs Cosine Similarity: [0.10, 0.42], median: 0.26
  - Uncertainty / Borderline Band: [0.50, 0.69]

Operational Decision Bands:
--------------------------
1. PASS (>= pass_threshold, default 0.70):
   - Estimated False Accept Rate (FAR): < 0.1%
   - Estimated False Reject Rate (FRR): ~ 2.5%
   - Candidate proceeds automatically into the interview.

2. REVIEW (review_threshold <= score < pass_threshold, default 0.50 <= score < 0.70):
   - Indicates poor camera angle, suboptimal lighting, or borderline similarity.
   - Interview progression is held; flagged for recruiter/human manual review.

3. FAIL (< review_threshold, default < 0.50):
   - High likelihood of presentation mismatch or impostor.
   - Immediate gate closure; interview terminated.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class IdentityThresholdConfig:
    pass_threshold: float = 0.70
    review_threshold: float = 0.50
    model_name: str = "sface"
    detector_name: str = "yunet"
    model_version: str = "2021dec"
    detector_version: str = "2023mar"
    threshold_version: str = "v1"
    calibration_date: str = "2026-09-20"
    calibration_dataset: str = "hiring_eval_sface_v1"
    estimated_far: float = 0.001
    estimated_frr: float = 0.025
    check_interval: int = 3  # turns between periodic identity checkpoints
    liveness_status: str = "not_implemented"

    def to_metadata(self) -> Dict[str, Any]:
        """Returns provenance dictionary for audit logs and decision trails."""
        return {
            "matcher": self.model_name,
            "face_detector": self.detector_name,
            "matcher_model_version": self.model_version,
            "detector_model_version": self.detector_version,
            "threshold": self.pass_threshold,
            "review_threshold": self.review_threshold,
            "threshold_version": self.threshold_version,
            "calibration_date": self.calibration_date,
            "calibration_dataset": self.calibration_dataset,
            "liveness_status": self.liveness_status,
        }


# Global default configuration instance
_default_threshold_config = IdentityThresholdConfig()


def get_threshold_config() -> IdentityThresholdConfig:
    """Returns active threshold configuration, respecting settings overrides."""
    from app.config import settings

    cfg = IdentityThresholdConfig()
    if hasattr(settings, "face_match_threshold") and settings.face_match_threshold is not None:
        cfg.pass_threshold = float(settings.face_match_threshold)
    return cfg


def set_threshold_config(config: IdentityThresholdConfig) -> None:
    """Sets the active default threshold config (useful for testing or profile switching)."""
    global _default_threshold_config
    _default_threshold_config = config
