"""Evidence quality and unsupported claim detection metrics for Stage 1 evaluation.

Implements:
- 5-point Evidence Correctness scale:
    1: unsupported
    2: weakly supported
    3: partially supported
    4: strongly supported
    5: directly supported
- Direct and fuzzy evidence verification against resume text
- Unsupported claims detector
- Evidence validity rate metric
- EvidenceValidator penalty filter (rejection / capping score at 0.2)
"""

import re
from enum import IntEnum
from typing import Any, Optional, Union


class EvidenceCorrectness(IntEnum):
    UNSUPPORTED = 1
    WEAKLY_SUPPORTED = 2
    PARTIALLY_SUPPORTED = 3
    STRONGLY_SUPPORTED = 4
    DIRECTLY_SUPPORTED = 5


def normalize_text(text: str) -> str:
    """Normalize text by stripping whitespace and converting to lowercase."""
    if not text:
        return ""
    return " ".join(text.split()).lower()


def _is_token_match(q_token: str, resume_tokens: set[str]) -> bool:
    """Check if quote token matches any resume token (exact or common stem/prefix)."""
    if q_token in resume_tokens:
        return True
    for r_token in resume_tokens:
        if len(q_token) >= 4 and len(r_token) >= 4:
            if q_token.startswith(r_token) or r_token.startswith(q_token):
                return True
        # Plural/singular s check
        if q_token.rstrip("s") == r_token.rstrip("s"):
            return True
    return False


def verify_evidence_quote(quote: str, resume_text: str) -> bool:
    """Check if the evidence quote is directly present in the resume text."""
    if not quote or not resume_text:
        return False
    norm_quote = normalize_text(quote)
    norm_resume = normalize_text(resume_text)
    return norm_quote in norm_resume


def score_evidence_support(quote: str, resume_text: str) -> EvidenceCorrectness:
    """Grade evidence support on the 1 to 5 scale:

    1 -> unsupported
    2 -> weakly supported
    3 -> partially supported
    4 -> strongly supported
    5 -> directly supported
    """
    if not quote or not resume_text:
        return EvidenceCorrectness.UNSUPPORTED

    norm_quote = normalize_text(quote)
    norm_resume = normalize_text(resume_text)

    # 5: Directly supported (verbatim normalized substring)
    if norm_quote in norm_resume:
        return EvidenceCorrectness.DIRECTLY_SUPPORTED

    # Token-level overlap analysis
    quote_tokens = [w for w in re.findall(r"\w+", norm_quote) if len(w) > 2]
    if not quote_tokens:
        return EvidenceCorrectness.UNSUPPORTED

    resume_tokens = set(re.findall(r"\w+", norm_resume))
    matched_count = sum(1 for q in quote_tokens if _is_token_match(q, resume_tokens))
    overlap_ratio = matched_count / len(quote_tokens)

    # Check for sliding window / sequential match
    token_str = " ".join(quote_tokens)
    if token_str in " ".join(re.findall(r"\w+", norm_resume)):
        return EvidenceCorrectness.DIRECTLY_SUPPORTED

    if overlap_ratio >= 0.70:
        return EvidenceCorrectness.STRONGLY_SUPPORTED
    elif overlap_ratio >= 0.45:
        return EvidenceCorrectness.PARTIALLY_SUPPORTED
    elif overlap_ratio >= 0.20:
        return EvidenceCorrectness.WEAKLY_SUPPORTED
    else:
        return EvidenceCorrectness.UNSUPPORTED


def detect_unsupported_claims(
    evidence_items: list[Union[dict, Any]],
    resume_text: str,
    strict: bool = True,
) -> list[dict]:
    """Detect evidence claims that fail verification against resume text.

    Args:
        evidence_items: List of evidence items (dict with 'quote' or 'text', or Evidence objects).
        resume_text: Raw candidate resume text.
        strict: If True, requires exact substring containment (score == 5).
                If False, requires at least partially supported (score >= 3).

    Returns:
        List of unsupported evidence details.
    """
    unsupported = []
    norm_resume = normalize_text(resume_text)

    for item in evidence_items:
        quote = (
            item.get("quote") or item.get("text")
            if isinstance(item, dict)
            else getattr(item, "quote", getattr(item, "text", str(item)))
        )
        if not quote:
            continue

        norm_quote = normalize_text(str(quote))
        is_direct = norm_quote in norm_resume
        score = score_evidence_support(str(quote), resume_text)

        failed = not is_direct if strict else (score < EvidenceCorrectness.PARTIALLY_SUPPORTED)

        if failed:
            unsupported.append({
                "quote": quote,
                "support_score": int(score),
                "support_level": score.name,
                "reason": "Direct evidence quote not found in candidate resume text",
            })

    return unsupported


def calculate_evidence_validity_rate(
    evidence_evaluations: list[dict],
    min_level: EvidenceCorrectness = EvidenceCorrectness.DIRECTLY_SUPPORTED,
) -> float:
    """Calculate the fraction of evidence claims that satisfy the support threshold.

    Args:
        evidence_evaluations: List of evaluations, each containing 'support_score' or 'is_valid'.
        min_level: Minimum acceptable correctness level (defaults to DIRECTLY_SUPPORTED = 5).

    Returns:
        Validity rate as float in [0.0, 1.0].
    """
    if not evidence_evaluations:
        return 0.0

    valid_count = 0
    for eval_item in evidence_evaluations:
        if "is_valid" in eval_item:
            if eval_item["is_valid"]:
                valid_count += 1
        elif "support_score" in eval_item:
            if eval_item["support_score"] >= int(min_level):
                valid_count += 1

    return round(valid_count / len(evidence_evaluations), 4)


def validate_and_penalize_competency(
    assessment: dict,
    resume_text: str,
    penalty_cap: float = 0.2,
) -> dict:
    """Enforce EvidenceValidator rules on an assessment dict:

    If evidence quote is not found in the resume, filter it out.
    If no valid evidence remains, cap the score at penalty_cap (0.2)
    and set reasoning indicating insufficient verifiable evidence.
    """
    ass = dict(assessment)
    raw_evidence = ass.get("evidence", [])
    valid_evidence = []

    for ev in raw_evidence:
        quote = ev.get("quote") or ev.get("text") if isinstance(ev, dict) else getattr(ev, "quote", getattr(ev, "text", ""))
        if verify_evidence_quote(str(quote), resume_text):
            valid_evidence.append(ev)

    ass["evidence"] = valid_evidence
    if not valid_evidence:
        ass["score"] = min(float(ass.get("score", 0.0)), penalty_cap)
        ass["reasoning"] = "Insufficient directly verifiable resume evidence."
        ass["is_supported"] = False
    else:
        ass["is_supported"] = True

    return ass
