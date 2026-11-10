"""Run the offline interview reasoning agent evaluation suite."""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.agent_evals import AgentEvalRunner  # noqa: E402


def main() -> int:
    runner = AgentEvalRunner(PROJECT_ROOT)
    results = runner.run()
    print(f"Agent evals: {results['passed_cases']}/{results['total_cases']} passed ({results['pass_rate']:.1%})")
    print(f"Report: {runner.report_path}")
    print(f"Results: {runner.results_path}")
    return 0 if results["failed_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
