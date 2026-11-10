import threading
import time
from typing import Any, Dict, List


class MetricsCollector:
    """Thread-safe application metrics collector for requests, interviews, identity, STT, and LLM."""

    def __init__(self):
        self._lock = threading.Lock()

        # Requests
        self.requests_total: int = 0
        self.requests_successful: int = 0
        self.requests_failed: int = 0

        # Interview
        self.interview_sessions_started: int = 0
        self.interview_sessions_completed: int = 0
        self.interview_sessions_abandoned: int = 0
        self.interview_durations: List[float] = []

        # Identity
        self.identity_checks_total: int = 0
        self.identity_checks_passed: int = 0
        self.identity_checks_failed: int = 0

        # STT
        self.stt_requests_total: int = 0
        self.stt_failures: int = 0
        self.stt_latencies_ms: List[float] = []

        # LLM
        self.llm_requests_total: int = 0
        self.llm_failures: int = 0
        self.llm_latencies_ms: List[float] = []

        # Aggregate production agent quality observations. These counters never
        # retain prompts, answers, evidence quotes, or candidate identifiers.
        self.agent_eval_checks: Dict[str, Dict[str, int]] = {}

    def record_request(self, status_code: int) -> None:
        with self._lock:
            self.requests_total += 1
            if status_code < 400:
                self.requests_successful += 1
            else:
                self.requests_failed += 1

    def record_interview_start(self) -> None:
        with self._lock:
            self.interview_sessions_started += 1

    def record_interview_complete(self, duration_seconds: float = 0.0) -> None:
        with self._lock:
            self.interview_sessions_completed += 1
            if duration_seconds > 0:
                self.interview_durations.append(duration_seconds)

    def record_interview_abandoned(self) -> None:
        with self._lock:
            self.interview_sessions_abandoned += 1

    def record_identity_check(self, passed: bool) -> None:
        with self._lock:
            self.identity_checks_total += 1
            if passed:
                self.identity_checks_passed += 1
            else:
                self.identity_checks_failed += 1

    def record_stt(self, success: bool, latency_ms: float) -> None:
        with self._lock:
            self.stt_requests_total += 1
            if not success:
                self.stt_failures += 1
            self.stt_latencies_ms.append(latency_ms)

    def record_llm(self, success: bool, latency_ms: float) -> None:
        with self._lock:
            self.llm_requests_total += 1
            if not success:
                self.llm_failures += 1
            self.llm_latencies_ms.append(latency_ms)

    def record_agent_eval(self, check_name: str, passed: bool) -> None:
        """Record a fixed-name live quality check without persisting user content."""
        with self._lock:
            counters = self.agent_eval_checks.setdefault(
                check_name, {"total": 0, "passed": 0, "failed": 0}
            )
            counters["total"] += 1
            counters["passed" if passed else "failed"] += 1

    def _percentile(self, values: List[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c < len(sorted_vals):
            d0 = sorted_vals[f] * (c - k)
            d1 = sorted_vals[c] * (k - f)
            return round(d0 + d1, 2)
        return round(sorted_vals[f], 2)

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            avg_duration = 0.0
            if self.interview_durations:
                avg_duration = round(sum(self.interview_durations) / len(self.interview_durations), 2)

            return {
                "requests": {
                    "total": self.requests_total,
                    "successful": self.requests_successful,
                    "failed": self.requests_failed,
                },
                "interview": {
                    "sessions": self.interview_sessions_started,
                    "completed": self.interview_sessions_completed,
                    "abandoned": self.interview_sessions_abandoned,
                    "average_duration_seconds": avg_duration,
                },
                "identity": {
                    "checks": self.identity_checks_total,
                    "passed": self.identity_checks_passed,
                    "failed": self.identity_checks_failed,
                },
                "stt": {
                    "requests": self.stt_requests_total,
                    "failures": self.stt_failures,
                    "latency": {
                        "p50_ms": self._percentile(self.stt_latencies_ms, 50),
                        "p95_ms": self._percentile(self.stt_latencies_ms, 95),
                    },
                },
                "llm": {
                    "requests": self.llm_requests_total,
                    "failures": self.llm_failures,
                    "latency": {
                        "p50_ms": self._percentile(self.llm_latencies_ms, 50),
                        "p95_ms": self._percentile(self.llm_latencies_ms, 95),
                    },
                },
                "agent_evals": {
                    "source": "live_interview_turns",
                    "checks": {
                        name: dict(values)
                        for name, values in sorted(self.agent_eval_checks.items())
                    },
                },
            }

    def reset(self) -> None:
        with self._lock:
            self.requests_total = 0
            self.requests_successful = 0
            self.requests_failed = 0
            self.interview_sessions_started = 0
            self.interview_sessions_completed = 0
            self.interview_sessions_abandoned = 0
            self.interview_durations.clear()
            self.identity_checks_total = 0
            self.identity_checks_passed = 0
            self.identity_checks_failed = 0
            self.stt_requests_total = 0
            self.stt_failures = 0
            self.stt_latencies_ms.clear()
            self.llm_requests_total = 0
            self.llm_failures = 0
            self.llm_latencies_ms.clear()
            self.agent_eval_checks.clear()


_metrics_instance = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _metrics_instance
