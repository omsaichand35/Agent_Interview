from dataclasses import dataclass


@dataclass
class InterviewEvidence:
    competency: str
    answer: str
    evidence_strength: float
    notes: str

def build_evidence(
    competency: str,
    answer: str,
    extracted_signals: list[str],
) -> InterviewEvidence:

    if not answer.strip():
        return InterviewEvidence(
            competency=competency,
            answer=answer,
            evidence_strength=0.0,
            notes="No answer provided.",
        )

    normalized = answer.lower()

    matching_signals = [
        signal
        for signal in extracted_signals
        if signal.lower() in normalized
    ]

    if matching_signals:
        strength = min(1.0, 0.5 + 0.1 * len(matching_signals))
        notes = (
            f"Answer contains evidence related to: "
            f"{', '.join(matching_signals)}."
        )
    else:
        strength = 0.3
        notes = "Answer provides limited directly detectable evidence."

    return InterviewEvidence(
        competency=competency,
        answer=answer,
        evidence_strength=strength,
        notes=notes,
    )