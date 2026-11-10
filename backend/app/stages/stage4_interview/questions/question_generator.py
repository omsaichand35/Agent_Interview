def _label(competency: str) -> str:
    return " ".join(str(competency or "the evaluation criterion").replace("_", " ").split())


def generate_opening_question(program_title: str | None = None) -> str:
    return "To start, please introduce yourself."


def generate_criterion_question(competency: str, phase: str, answer: str = "") -> str:
    """Generate a simple textbook-style question for the exact criterion."""
    criterion = _label(competency)
    if phase == "vertical":
        return f"Could you explain one part of {criterion} a little more?"
    return f"Could you explain {criterion} in your own words?"


def generate_recovery_question(
    competency: str | None,
    phase: str = "horizontal",
    answer: str = "",
) -> str:
    if not competency:
        return "No problem. Could you briefly introduce yourself?"

    # Rephrase the same configured criterion in plain, textbook-style language.
    return f"No problem. Could you explain {_label(competency)} in your own words?"
