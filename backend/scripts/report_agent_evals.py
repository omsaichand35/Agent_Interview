"""Create a Markdown snapshot from an app's aggregate production eval metrics."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "agent_evals" / "production_report.md"
SAFETY_CHECKS = {
    "prompt_injection_handling",
    "evidence_grounding",
    "decision_trace",
    "question_policy",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/metrics", help="Application /metrics URL")
    parser.add_argument("--metrics-file", type=Path, help="Use a previously captured /metrics JSON response")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.metrics_file:
        payload = json.loads(args.metrics_file.read_text(encoding="utf-8"))
        source = f"metrics snapshot `{args.metrics_file.name}`"
    else:
        with urlopen(args.url, timeout=10) as response:
            payload = json.load(response)
        host = urlsplit(args.url).hostname or "configured endpoint"
        source = f"live metrics endpoint on `{host}`"

    checks = payload.get("agent_evals", {}).get("checks", {})
    total = sum(int(row.get("total", 0)) for row in checks.values())
    failures = sum(int(row.get("failed", 0)) for row in checks.values())
    safety_observations = sum(int(checks.get(name, {}).get("total", 0)) for name in SAFETY_CHECKS)
    safety_failures = sum(int(checks.get(name, {}).get("failed", 0)) for name in SAFETY_CHECKS)
    if safety_observations == 0:
        status = "INSUFFICIENT SAFETY DATA"
    else:
        status = "ACTION REQUIRED" if safety_failures else "NO SAFETY FAILURES OBSERVED"

    lines = [
        "# Production Agent Eval Snapshot",
        "",
        f"**Source:** {source}  ",
        f"**Observed checks:** {total}  ",
        f"**Failed checks:** {failures}  ",
        f"**Safety status:** {status}",
        "",
        "| Check | Passed | Failed | Observations | Pass rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in sorted(checks.items()):
        observed = int(row.get("total", 0))
        passed = int(row.get("passed", 0))
        failed = int(row.get("failed", 0))
        rate = f"{passed / observed:.1%}" if observed else "—"
        lines.append(f"| `{name}` | {passed} | {failed} | {observed} | {rate} |")
    lines.extend([
        "",
        "Checks run on actual interview graph turns and cover reasoning contracts, question policy, direct evidence grounding, evaluation fallbacks, decision trace consistency, and prompt-injection handling when detected.",
        "",
        "This snapshot contains aggregates only; it does not retain candidate answers, prompts, evidence quotes, or candidate identifiers. Metrics are in-process counters and reset when a worker restarts. For multi-worker deployments, scrape each worker and aggregate the counters in the monitoring system. A zero-observation snapshot is not evidence of quality.",
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Production eval report saved: {args.output}")
    return 0 if total else 2


if __name__ == "__main__":
    raise SystemExit(main())
