from app.stages.stage4_interview.graph.coverage import (
    MAX_TURNS,
    evidence_counts,
    required_evidence_per_criterion,
    target_criteria,
)


def should_conclude(state) -> bool:
    """Finish only after the rubric has breadth and depth, or at the hard cap."""
    if state.get("turn_number", 1) >= MAX_TURNS:
        return True

    targets = target_criteria(state)
    if not targets:
        return False

    required = required_evidence_per_criterion(targets)
    counts = evidence_counts(state, targets)
    return all(counts[criterion] >= required for criterion in targets)
