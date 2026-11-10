from math import ceil
import re


MIN_TURNS = 5
MAX_TURNS = 15


def target_criteria(state) -> list[str]:
    """Return the ordered, unique rubric criteria for this interview."""
    result = []
    for item in state.get("target_competencies") or []:
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return result


def criterion_label(value: str) -> str:
    """Remove rubric weights from a criterion before asking or evaluating it."""
    label = str(value or "").strip()
    label = re.sub(r"\s*(?:[-–—]\s*)?[\[(]?\s*\d+(?:\.\d+)?\s*%\s*[\])]?$", "", label)
    return label.strip(" \t-–—:;,.()[]")


def required_evidence_per_criterion(targets: list[str]) -> int:
    """Keep the interview near five turns while requiring breadth and depth."""
    if not targets:
        return 2
    return max(2, ceil(MIN_TURNS / len(targets)))


def evidence_counts(state, targets: list[str]) -> dict[str, int]:
    evidence = state.get("evidence") or {}
    return {criterion: len(evidence.get(criterion) or []) for criterion in targets}
