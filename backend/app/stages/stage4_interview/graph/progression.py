from app.stages.stage4_interview.graph.coverage import (
    evidence_counts,
    required_evidence_per_criterion,
    target_criteria,
)


def update_competency_progress(state):
    if state.get("decision") == "recover" or state.get("interview_complete"):
        return state

    targets = target_criteria(state)
    if not targets:
        return state

    if state.get("coverage_phase") == "introduction":
        state["coverage_phase"] = "horizontal"
        state["current_competency"] = targets[0]
        state["decision"] = "next_competency"
        return state

    counts = evidence_counts(state, targets)
    explored = state.setdefault("explored_competencies", [])
    for criterion, count in counts.items():
        if count and criterion not in explored:
            explored.append(criterion)

    # First pass is horizontal: one answer on every configured rubric criterion.
    horizontal = [criterion for criterion in targets if counts[criterion] == 0]
    if horizontal:
        state["coverage_phase"] = "horizontal"
        state["current_competency"] = horizontal[0]
        state["decision"] = "next_competency"
        return state

    # Second pass is vertical: require deeper evidence for every criterion,
    # choosing in rubric order so the interview plan is predictable.
    required = required_evidence_per_criterion(targets)
    vertical = [criterion for criterion in targets if counts[criterion] < required]
    if vertical:
        state["coverage_phase"] = "vertical"
        state["current_competency"] = min(vertical, key=lambda criterion: counts[criterion])
        state["decision"] = "deepen"
    else:
        state["coverage_phase"] = "complete"
        state["decision"] = "conclude"
        state["interview_complete"] = True

    return state
