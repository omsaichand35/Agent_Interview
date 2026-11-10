from typing import Optional, Dict, Any

from app.schemas.recommendation import (
    FinalRecommendation,
)

from app.stages.stage5_recommendation.scorer import (
    FinalScorer,
)

from app.stages.stage5_recommendation.evidence_builder import (
    RecommendationEvidenceBuilder,
)


class RecommendationService:

    def __init__(self, candidate_repo=None, interview_registry=None):
        self.scorer = FinalScorer()
        self.evidence_builder = (
            RecommendationEvidenceBuilder()
        )
        self.candidate_repo = candidate_repo
        self.interview_registry = interview_registry
        self._recommendations: Dict[str, FinalRecommendation] = {}
        self._reviews: Dict[str, Dict[str, Any]] = {}

    def set_dependencies(self, candidate_repo=None, interview_registry=None):
        if candidate_repo is not None:
            self.candidate_repo = candidate_repo
        if interview_registry is not None:
            self.interview_registry = interview_registry

    def save_recommendation(self, recommendation: FinalRecommendation):
        self._recommendations[recommendation.candidate_id] = recommendation

    def save_human_review(self, candidate_id: str, review: Dict[str, Any]):
        self._reviews[candidate_id] = review

    def generate(
        self,
        candidate=None,
        interview_result=None,
        identity_result=None,
        candidate_id: Optional[str] = None,
        resume_score: Optional[float] = None,
        interview_score: Optional[float] = None,
        identity_verified: Optional[bool] = None,
        identity_confidence: Optional[float] = None,
        competency_scores: Optional[dict] = None,
        **kwargs,
    ):
        if candidate is None and candidate_id is not None:
            candidate = {
                "candidate_id": candidate_id,
                "resume_score": resume_score,
            }
        if interview_result is None and interview_score is not None:
            c_id = candidate_id or (
                candidate["candidate_id"]
                if isinstance(candidate, dict)
                else getattr(candidate, "candidate_id", None)
            )
            if not c_id:
                raise ValueError("A candidate_id is required to generate a recommendation")
            interview_result = {
                "candidate_id": c_id,
                "interview_score": interview_score,
                "competency_scores": competency_scores or {},
            }
        if identity_result is None and identity_verified is not None:
            identity_result = {
                "verified": identity_verified,
                "confidence": identity_confidence,
            }

        identity_verified = (
            identity_result.get("verified", False)
            if isinstance(identity_result, dict)
            else getattr(identity_result, "verified", False)
        )

        candidate_id = (
            candidate["candidate_id"]
            if isinstance(candidate, dict)
            else getattr(candidate, "candidate_id")
        )

        if not identity_verified:
            rec = FinalRecommendation(
                candidate_id=candidate_id,
                resume_score=(
                    candidate.get("resume_score", 0.0)
                    if isinstance(candidate, dict)
                    else getattr(candidate, "resume_score", 0.0) or 0.0
                ),
                interview_score=0.0,
                final_score=0.0,
                strengths=[],
                gaps=[
                    "Identity verification failed."
                ],
                evidence=[],
                identity_verified=False,
                status="human_review",
            )
            self._recommendations[candidate_id] = rec
            self._reviews[candidate_id] = {
                "candidate_id": candidate_id,
                "requires_review": True,
                "reason": "Identity verification did not pass.",
                "identity_failure_reason": "Face match confidence below threshold or no live face detected.",
            }
            return rec

        resume_score = (
            candidate.get("resume_score")
            if isinstance(candidate, dict)
            else getattr(candidate, "resume_score", None)
        )

        if resume_score is None:
            raise ValueError("A scored resume is required before generating a recommendation.")

        interview_score = (
            interview_result.get("interview_score")
            if isinstance(interview_result, dict)
            else getattr(interview_result, "interview_score", None)
        )

        if interview_score is None:
            raise ValueError("A completed interview score is required before generating a recommendation.")

        final_score = self.scorer.score(
            resume_score=resume_score,
            interview_score=interview_score,
        )

        competency_scores = (
            interview_result.get("competency_scores", {})
            if isinstance(interview_result, dict)
            else getattr(interview_result, "competency_scores", {}) or {}
        )

        strengths = [
            competency
            for competency, score
            in competency_scores.items()
            if score >= 0.75
        ]

        gaps = [
            competency
            for competency, score
            in competency_scores.items()
            if score < 0.50
        ]

        evidence = (
            self.evidence_builder.build(
                candidate,
                interview_result,
            )
        )

        rec = FinalRecommendation(
            candidate_id=candidate_id,
            resume_score=resume_score,
            interview_score=interview_score,
            final_score=final_score,
            strengths=strengths,
            gaps=gaps,
            evidence=evidence,
            identity_verified=True,
            status="completed",
        )
        self._recommendations[candidate_id] = rec
        # Identity verified and completed -> no review required
        self._reviews[candidate_id] = {
            "candidate_id": candidate_id,
            "requires_review": False,
        }
        return rec

    def get_recommendation(self, candidate_id: str) -> Optional[FinalRecommendation]:
        """
        Retrieves final recommendation for candidate.
        HARD GATE: If identity verification failed, DO NOT recommend automatically.
        """
        if candidate_id in self._recommendations:
            rec = self._recommendations[candidate_id]
            if not rec.identity_verified or rec.status == "human_review":
                return None
            return rec

        # Dynamic retrieval from pipeline state
        repo = self.candidate_repo
        if repo is None:
            from app.api.dependencies import get_candidate_repository
            repo = get_candidate_repository()

        reg = self.interview_registry
        if reg is None:
            from app.stages.stage4_interview.dependencies import registry as interview_reg
            reg = interview_reg

        candidate = repo.get_by_id(candidate_id) if repo else None
        interview = reg.get_by_candidate(candidate_id) if reg else None

        if candidate is None or interview is None:
            return None

        # Hard gate: check identity status
        identity_verified = interview.get("identity_verified", False)
        identity_status = interview.get("identity_status", "pending")
        if not identity_verified or identity_status == "failed":
            return None

        resume_score = (
            candidate.get("resume_score")
            if isinstance(candidate, dict)
            else getattr(candidate, "resume_score", None)
        )
        interview_score = (
            interview.get("interview_score")
            if isinstance(interview, dict)
            else getattr(interview, "interview_score", None)
        )
        if resume_score is None or interview_score is None:
            return None

        candidate_dict = candidate.model_dump() if hasattr(candidate, "model_dump") else dict(candidate)
        return self.generate(
            candidate=candidate_dict,
            interview_result=interview,
            identity_result={"verified": True},
        )

    def get_human_review(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns human review requirement if candidate cannot be automatically recommended.
        Identity failure triggers human review = True.
        """
        if candidate_id in self._reviews:
            return self._reviews[candidate_id]

        repo = self.candidate_repo
        if repo is None:
            from app.api.dependencies import get_candidate_repository
            repo = get_candidate_repository()

        reg = self.interview_registry
        if reg is None:
            from app.stages.stage4_interview.dependencies import registry as interview_reg
            reg = interview_reg

        candidate = repo.get_by_id(candidate_id) if repo else None
        interview = reg.get_by_candidate(candidate_id) if reg else None

        if interview:
            identity_status = interview.get("identity_status")
            identity_verified = interview.get("identity_verified", False)
            if identity_status == "failed" or (identity_status is not None and not identity_verified):
                review = {
                    "candidate_id": candidate_id,
                    "requires_review": True,
                    "reason": "Identity verification did not pass.",
                    "identity_failure_reason": (
                        interview.get("identity_failure_reason")
                        or "Face match confidence below threshold or no live face detected."
                    ),
                }
                self._reviews[candidate_id] = review
                return review

        if candidate_id in self._recommendations:
            rec = self._recommendations[candidate_id]
            if rec.status == "human_review" or not rec.identity_verified:
                review = {
                    "candidate_id": candidate_id,
                    "requires_review": True,
                    "reason": "Identity verification failed or candidate flagged for review.",
                    "identity_failure_reason": "Identity verification did not pass.",
                }
                self._reviews[candidate_id] = review
                return review

        return {
            "candidate_id": candidate_id,
            "requires_review": False,
        }
