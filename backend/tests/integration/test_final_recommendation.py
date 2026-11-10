"""
C8 integration test: final recommendation validation.

Verifies that Stage 5 produces correct, evidence-backed recommendations
and that the identity gate is a HARD BLOCK — not a score of zero that
accidentally flows through to an automatic recommendation.

Decision boundary
-----------------
                   IDENTITY
                  /         \
               PASS         FAIL
                |              |
                v              v
          Interview       Human Review
                |          final_score = 0.0
                v          status = "human_review"
        Recommendation
        status = "completed"
        final_score = resume*0.40 + interview*0.60
"""

from app.stages.stage5_recommendation.recommendation_service import (
    RecommendationService,
)
from app.config import settings


# Fresh instance for each import -- no shared state between test runs.
def _service():
    return RecommendationService()


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

CANDIDATE_C001 = {
    "candidate_id": "C001",
    "name": "Alex Smith",
    "resume_score": 0.71,
}

INTERVIEW_C001 = {
    "candidate_id": "C001",
    "interview_score": 0.78,
    "competency_scores": {
        "technical_skills": 0.80,
        "problem_solving": 0.76,
        "leadership": 0.68,
    },
}

IDENTITY_PASS = {"verified": True, "confidence": 0.95}
IDENTITY_FAIL = {"verified": False, "confidence": 0.12}

# Expected final score: 0.71*0.40 + 0.78*0.60
_EXPECTED_FINAL = round(
    0.71 * settings.resume_weight + 0.78 * settings.interview_weight, 2
)


# ---------------------------------------------------------------------------
# Case A: identity PASS + valid resume + valid interview
# ---------------------------------------------------------------------------


def test_valid_candidate_gets_recommendation():
    """
    A candidate who passes identity and has solid scores must receive a
    completed recommendation with the correct weighted final_score.
    """
    svc = _service()

    rec = svc.generate(
        candidate=CANDIDATE_C001,
        interview_result=INTERVIEW_C001,
        identity_result=IDENTITY_PASS,
    )

    assert rec is not None
    assert rec.candidate_id == "C001"
    assert rec.status == "completed"
    assert rec.identity_verified is True


def test_final_score_matches_weighted_formula():
    """
    final_score must equal resume_score * 0.40 + interview_score * 0.60,
    rounded to 2 dp, using the weights defined in settings.
    """
    svc = _service()

    rec = svc.generate(
        candidate=CANDIDATE_C001,
        interview_result=INTERVIEW_C001,
        identity_result=IDENTITY_PASS,
    )

    assert abs(rec.final_score - _EXPECTED_FINAL) < 0.001, (
        f"Expected final_score={_EXPECTED_FINAL}, got {rec.final_score}. "
        f"Formula: {CANDIDATE_C001['resume_score']}*{settings.resume_weight} "
        f"+ {INTERVIEW_C001['interview_score']}*{settings.interview_weight}"
    )


def test_resume_and_interview_scores_are_preserved():
    """
    The individual component scores must survive into the recommendation
    so the recruiter can see how the final score was derived.
    """
    svc = _service()

    rec = svc.generate(
        candidate=CANDIDATE_C001,
        interview_result=INTERVIEW_C001,
        identity_result=IDENTITY_PASS,
    )

    assert rec.resume_score == CANDIDATE_C001["resume_score"]
    assert rec.interview_score == INTERVIEW_C001["interview_score"]


def test_strengths_and_gaps_are_derived_from_competencies():
    """
    Strengths = competencies >= 0.75.
    Gaps      = competencies <  0.50.
    Leadership (0.68) is neither a strength nor a gap.
    """
    svc = _service()

    rec = svc.generate(
        candidate=CANDIDATE_C001,
        interview_result=INTERVIEW_C001,
        identity_result=IDENTITY_PASS,
    )

    # technical_skills (0.80) and problem_solving (0.76) are strengths.
    assert "technical_skills" in rec.strengths
    assert "problem_solving" in rec.strengths
    # leadership (0.68) is below 0.75 but above 0.50 -- neither.
    assert "leadership" not in rec.strengths
    assert "leadership" not in rec.gaps


def test_evidence_trail_is_populated():
    """
    The evidence list must contain strings referencing resume_score,
    interview_score, and each competency so the recruiter has a full
    audit trail without reading raw state.
    """
    svc = _service()

    rec = svc.generate(
        candidate=CANDIDATE_C001,
        interview_result=INTERVIEW_C001,
        identity_result=IDENTITY_PASS,
    )

    assert rec.evidence, "evidence list must not be empty"

    evidence_text = " ".join(rec.evidence)
    assert "resume" in evidence_text.lower() or "0.71" in evidence_text
    assert "interview" in evidence_text.lower() or "0.78" in evidence_text
    # At least one competency must appear in the evidence.
    assert any(
        c in evidence_text
        for c in ("technical_skills", "problem_solving", "leadership")
    ), "At least one competency must appear in evidence"


# ---------------------------------------------------------------------------
# Case B: identity FAIL -- the hard gate
# ---------------------------------------------------------------------------


def test_identity_failure_triggers_human_review():
    """
    HARD GATE: A failed identity check must produce status='human_review',
    regardless of how strong the resume or interview scores are.
    An impostor with a 0.90 interview score must never get a recommendation.
    """
    svc = _service()

    high_scoring_impostor = {
        "candidate_id": "C002",
        "resume_score": 0.90,
    }
    strong_interview = {
        "candidate_id": "C002",
        "interview_score": 0.90,
        "competency_scores": {"technical_skills": 0.95},
    }

    rec = svc.generate(
        candidate=high_scoring_impostor,
        interview_result=strong_interview,
        identity_result=IDENTITY_FAIL,
    )

    assert rec.status == "human_review", (
        f"Identity failure must produce 'human_review', got '{rec.status}'"
    )
    assert rec.identity_verified is False


def test_identity_failure_produces_zero_final_score():
    """
    When identity fails, final_score must be 0.0 -- not a weighted
    combination of the (unverified) interview scores.  The schema does
    not permit None, so 0.0 is the sentinel for 'not calculated'.
    """
    svc = _service()

    rec = svc.generate(
        candidate={"candidate_id": "C002", "resume_score": 0.80},
        interview_result={"candidate_id": "C002", "interview_score": 0.90},
        identity_result=IDENTITY_FAIL,
    )

    assert rec.final_score == 0.0, (
        f"Identity failure must set final_score=0.0, got {rec.final_score}. "
        "An impostor's scores must never produce an automatic recommendation."
    )


def test_identity_failure_gaps_explain_why():
    """
    The gaps list for a human_review recommendation must explain that
    identity verification failed, so the recruiter knows why it was blocked.
    """
    svc = _service()

    rec = svc.generate(
        candidate={"candidate_id": "C002", "resume_score": 0.50},
        interview_result={"candidate_id": "C002", "interview_score": 0.60},
        identity_result=IDENTITY_FAIL,
    )

    assert rec.gaps, "gaps must be non-empty when identity fails"
    gaps_text = " ".join(rec.gaps).lower()
    assert "identity" in gaps_text, (
        "gaps must mention identity so the recruiter understands the block"
    )


# ---------------------------------------------------------------------------
# Case C: identity PASS + weak scores
# ---------------------------------------------------------------------------


def test_weak_candidate_gets_recommendation_from_scoring_rules():
    """
    A verified candidate with weak scores must still get a 'completed'
    recommendation (not hard-coded to any outcome).  Stage 5 simply
    applies its scoring formula -- it does not apply a hiring threshold.
    That decision belongs to the recruiter.
    """
    svc = _service()

    weak_candidate = {
        "candidate_id": "C003",
        "resume_score": 0.30,
    }
    weak_interview = {
        "candidate_id": "C003",
        "interview_score": 0.25,
        "competency_scores": {"technical_skills": 0.20, "problem_solving": 0.30},
    }

    rec = svc.generate(
        candidate=weak_candidate,
        interview_result=weak_interview,
        identity_result=IDENTITY_PASS,
    )

    # Must be completed (not human_review) since identity passed.
    assert rec.status == "completed"
    assert rec.identity_verified is True

    # Score must follow the formula, not be hard-coded.
    expected = round(
        0.30 * settings.resume_weight + 0.25 * settings.interview_weight, 2
    )
    assert abs(rec.final_score - expected) < 0.001, (
        f"Weak candidate score must equal {expected}, got {rec.final_score}"
    )

    # Gaps must reflect the weak competencies.
    assert "technical_skills" in rec.gaps
    assert "problem_solving" in rec.gaps


# ---------------------------------------------------------------------------
# Full decision-boundary matrix
# ---------------------------------------------------------------------------


def test_recommendation_decision_boundary():
    """
    Validates all three branches of the decision tree in a single test:

        Identity PASS + valid scores   → completed
        Identity FAIL + excellent scores → human_review
        Identity PASS + weak scores    → completed (scoring rules apply)
    """
    svc = _service()

    # Case A: PASS + good scores
    rec_a = svc.generate(
        candidate={"candidate_id": "A001", "resume_score": 0.71},
        interview_result={"candidate_id": "A001", "interview_score": 0.78, "competency_scores": {}},
        identity_result={"verified": True, "confidence": 0.95},
    )
    assert rec_a.status == "completed"
    assert rec_a.final_score > 0.0

    # Case B: FAIL + excellent scores → hard gate blocks
    rec_b = svc.generate(
        candidate={"candidate_id": "B001", "resume_score": 0.95},
        interview_result={"candidate_id": "B001", "interview_score": 0.95, "competency_scores": {}},
        identity_result={"verified": False, "confidence": 0.10},
    )
    assert rec_b.status == "human_review"
    assert rec_b.final_score == 0.0        # never calculated for impostors
    assert rec_b.identity_verified is False

    # Case C: PASS + weak scores → scoring rules, not a hard rejection
    rec_c = svc.generate(
        candidate={"candidate_id": "C003", "resume_score": 0.20},
        interview_result={"candidate_id": "C003", "interview_score": 0.15, "competency_scores": {}},
        identity_result={"verified": True, "confidence": 0.88},
    )
    assert rec_c.status == "completed"
    assert rec_c.identity_verified is True
    # Score must be mathematically derivable (not zero just because it is weak).
    expected_c = round(
        0.20 * settings.resume_weight + 0.15 * settings.interview_weight, 2
    )
    assert abs(rec_c.final_score - expected_c) < 0.001


# ---------------------------------------------------------------------------
# get_recommendation hard gate
# ---------------------------------------------------------------------------


def test_get_recommendation_blocks_failed_identity():
    """
    get_recommendation() must return None for a candidate whose stored
    recommendation has status='human_review'.  The UI must never be able
    to display an automatic recommendation for an unverified candidate.
    """
    svc = _service()

    # Generate and store a human_review recommendation.
    svc.generate(
        candidate={"candidate_id": "C_FAIL", "resume_score": 0.80},
        interview_result={"candidate_id": "C_FAIL", "interview_score": 0.85},
        identity_result={"verified": False, "confidence": 0.05},
    )

    # The public API must gate it out.
    result = svc.get_recommendation("C_FAIL")
    assert result is None, (
        "get_recommendation() must return None when identity failed -- "
        "the hard gate must be enforced at the API layer too"
    )


def test_get_recommendation_returns_completed_rec():
    """
    get_recommendation() must return the stored recommendation when identity
    passed and status is 'completed'.
    """
    svc = _service()

    svc.generate(
        candidate={"candidate_id": "C_PASS", "resume_score": 0.71},
        interview_result={
            "candidate_id": "C_PASS",
            "interview_score": 0.78,
            "competency_scores": {},
        },
        identity_result={"verified": True, "confidence": 0.95},
    )

    result = svc.get_recommendation("C_PASS")
    assert result is not None
    assert result.candidate_id == "C_PASS"
    assert result.status == "completed"
