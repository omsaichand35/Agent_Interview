"""Evaluation components with lazy exports to keep focused runners lightweight."""

from importlib import import_module


_EXPORTS = {
    "EndToEndDatasetLoader": ("app.evaluation.dataset_loader", "EndToEndDatasetLoader"),
    "CriticalInvariantsVerifier": ("app.evaluation.error_analysis", "CriticalInvariantsVerifier"),
    "ErrorPropagationAnalyzer": ("app.evaluation.error_analysis", "ErrorPropagationAnalyzer"),
    "PipelineEvaluationMetrics": ("app.evaluation.metrics", "PipelineEvaluationMetrics"),
    "AIReportGenerator": ("app.evaluation.report", "AIReportGenerator"),
    "EndToEndPipelineRunner": ("app.evaluation.end_to_end_runner", "EndToEndPipelineRunner"),
    "AgentEvalRunner": ("app.evaluation.agent_evals", "AgentEvalRunner"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Load legacy package-level exports only when a caller requests them."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    attribute = getattr(import_module(module_name), attribute_name)
    globals()[name] = attribute
    return attribute


def __dir__():
    return sorted(set(globals()) | set(__all__))
