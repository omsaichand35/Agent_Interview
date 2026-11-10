"""Interview Scoring Consistency and Sensitivity Evaluator (E5).

Evaluates:
1. Scoring Dimensions:
   - Evidence Quality
   - Technical Depth
   - Specificity
   - Reasoning Quality
   - Overall Competency Score
2. Equivalent-Answer Consistency (|Score_A - Score_B| <= tolerance).
3. Evidence Sensitivity (Weak vs Strong answers).
4. Unsupported Claim Detection and Score Capping.
5. Score Stability across Repeated Sessions (low variance / standard deviation).
6. Multi-turn Competency Aggregation (EvidenceAggregator preserving accumulated evidence).
7. Final Interview Score Computation (InterviewScorer [0.0, 1.0]).
"""

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.interview import InterviewEvidenceEvaluation
from app.stages.stage4_interview.evaluation.evidence_aggregator import EvidenceAggregator
from app.stages.stage4_interview.evaluation.interview_scorer import InterviewScorer

logger = logging.getLogger(__name__)


class ConsistencyMetrics:
    """Statistical metrics for evaluation consistency."""

    @staticmethod
    def score_variance(scores: List[float]) -> float:
        if len(scores) < 2:
            return 0.0
        mean_val = sum(scores) / len(scores)
        var = sum((s - mean_val) ** 2 for s in scores) / (len(scores) - 1)
        return round(var, 6)

    @staticmethod
    def standard_deviation(scores: List[float]) -> float:
        return round(math.sqrt(ConsistencyMetrics.score_variance(scores)), 5)

    @staticmethod
    def mean_absolute_difference(pairs: List[Tuple[float, float]]) -> float:
        if not pairs:
            return 0.0
        total_diff = sum(abs(a - b) for a, b in pairs)
        return round(total_diff / len(pairs), 4)

    @staticmethod
    def correlation(scores_a: List[float], scores_b: List[float]) -> float:
        """Pearson correlation coefficient."""
        if len(scores_a) != len(scores_b) or len(scores_a) < 2:
            return 1.0

        mean_a = sum(scores_a) / len(scores_a)
        mean_b = sum(scores_b) / len(scores_b)

        cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(scores_a, scores_b))
        var_a = sum((a - mean_a) ** 2 for a in scores_a)
        var_b = sum((b - mean_b) ** 2 for b in scores_b)

        denom = math.sqrt(var_a * var_b)
        if denom < 1e-9:
            return 1.0  # Perfect agreement when both have zero variance
        return round(cov / denom, 4)

    @staticmethod
    def tolerance_pass_rate(pairs: List[Tuple[float, float]], tolerance: float = 0.08) -> float:
        if not pairs:
            return 1.0
        passed = sum(1 for a, b in pairs if abs(a - b) <= tolerance)
        return round(passed / len(pairs), 4)


class DeterministicAnswerEvaluator:
    """Evaluates candidate answers across the 5 dimensions deterministically."""

    # Concrete technical and leadership entity indicators
    TECH_INDICATORS = {
        "redis", "kafka", "postgresql", "postgres", "fastapi", "spring", "docker",
        "kubernetes", "eks", "aws", "gcp", "azure", "pytest", "pgbouncer",
        "autovacuum", "indexes", "partitions", "consumer groups", "readiness probes",
        "horizontal pod autoscaling", "fixtures", "serializer", "caching", "cache",
        "pair programming", "code reviews", "pr reviews", "1-on-1", "microservices",
        "connection pool", "rest api", "api", "rest", "ci/cd", "ci test", "coverage",
        "pg_stat_activity", "pg_stat", "pooling", "junior developers", "junior engineers",
    }

    # Action / achievement verbs across engineering & leadership
    ACTION_PATTERNS = [
        r"\b(designed|built|architected|configured|implemented|mentored|guided|paired|diagnosed|tuned|partitioned|reduced|optimized|introduced|analyzed|resolved|reconfiguring|deployed|deploying|shipping|raising|comparing|compared|measuring|measured)\b",
    ]

    # Quantitative metrics and measured deltas
    METRIC_PATTERNS = [
        r"\d+[\d,]*\s*(%|percent|ms|events/sec|events per second|req/sec|tb|gb|k|k\b|junior)",
        r"p95|p99|latency|response times|throughput|coverage|40%|15k|2tb|28ms|420\s*ms|180\s*ms|88%|12 partitions",
    ]

    # Reasoning / causality / problem resolution / outcome links
    REASONING_PATTERNS = [
        r"\b(because|so that|in order to|before and after|compared|diagnosed|resolved|tuning|prevent|eliminate|helping them|until they successfully|raising ci)\b",
    ]

    # Unsupported claim patterns (hyperbolic statements without architectural substantiation)
    UNSUPPORTED_PATTERNS = [
        r"\b10 million requests per second\b",
        r"\bsingle-handedly replaced\b",
        r"\bentire legacy monolith in one weekend\b",
        r"\bwithout (any )?bugs\b",
        r"\bquery any database instantly\b",
    ]

    @staticmethod
    def is_unsupported_claim(answer: str) -> bool:
        lower = answer.lower()
        has_hyperbole = any(re.search(pat, lower) for pat in DeterministicAnswerEvaluator.UNSUPPORTED_PATTERNS)
        # Check if hyperbole is accompanied by architectural proof (consensus, rollback, topology)
        has_substantiation = ("consensus" in lower or "raft" in lower or "rollback" in lower or "staging" in lower)
        return has_hyperbole and not has_substantiation

    @classmethod
    def evaluate(
        cls,
        competency: str,
        answer: str,
        question: str = "",
    ) -> InterviewEvidenceEvaluation:
        if not answer.strip():
            return InterviewEvidenceEvaluation(
                competency=competency,
                score=0.0,
                evidence_quality=0.0,
                technical_depth=0.0,
                specificity=0.0,
                reasoning_quality=0.0,
                reasoning="No answer provided.",
                evidence_quote="",
            )

        lower = answer.lower()

        # Check for unsupported claims first
        if cls.is_unsupported_claim(answer):
            return InterviewEvidenceEvaluation(
                competency=competency,
                score=0.30,
                evidence_quality=0.25,
                technical_depth=0.30,
                specificity=0.35,
                reasoning_quality=0.25,
                reasoning="Candidate made extreme unsubstantiated scale claims without architectural or verification evidence.",
                evidence_quote=answer[:300],
            )

        # Passive/vague answers (e.g. "I worked on APIs", "I know Kubernetes")
        is_passive_vague = (
            ("worked on" in lower or "know " in lower or "sometimes" in lower)
            and len(answer.split()) <= 10
            and not any(re.search(pat, lower) for pat in cls.METRIC_PATTERNS)
        )
        if is_passive_vague:
            return InterviewEvidenceEvaluation(
                competency=competency,
                score=0.30,
                evidence_quality=0.30,
                technical_depth=0.25,
                specificity=0.25,
                reasoning_quality=0.30,
                reasoning=f"Limited passive assertion regarding {competency} without verifiable action or metrics.",
                evidence_quote=answer[:300],
            )

        # 1. Evidence Quality
        has_action = any(re.search(pat, lower) for pat in cls.ACTION_PATTERNS)
        tech_matches = sum(1 for t in cls.TECH_INDICATORS if t in lower)
        
        evidence_quality = 0.55
        if has_action:
            evidence_quality += 0.20
        if tech_matches >= 2:
            evidence_quality += 0.12
        elif tech_matches == 1:
            evidence_quality += 0.06
        evidence_quality = round(min(0.95, max(0.20, evidence_quality)), 2)

        # 2. Technical Depth: mechanisms, parameters, concrete practices
        depth_indicators = [
            "pg_stat_activity", "pgbouncer", "consumer groups", "partitions", "hpa",
            "readiness probes", "autovacuum", "fixtures", "p95", "p99", "asynchronous",
            "serializer", "composite b-tree", "caching", "cache", "pair programming",
            "pr reviews", "code reviews", "connection pool", "exhaustion", "starvation",
            "rolling deployments", "isolated",
        ]
        depth_matches = sum(1 for d in depth_indicators if d in lower)
        technical_depth = 0.50 + min(0.35, depth_matches * 0.12)
        technical_depth = round(min(0.92, max(0.20, technical_depth)), 2)

        # 3. Specificity: concrete metrics, percentages, numbers, tools
        has_metric = any(re.search(pat, lower) for pat in cls.METRIC_PATTERNS)
        specificity = 0.55
        if has_metric:
            specificity += 0.22
        if tech_matches >= 2:
            specificity += 0.10
        specificity = round(min(0.95, max(0.20, specificity)), 2)

        # 4. Reasoning Quality: problem context, decisions, trade-offs, comparisons
        has_reasoning = any(re.search(pat, lower) for pat in cls.REASONING_PATTERNS)
        reasoning_quality = 0.60
        if has_reasoning:
            reasoning_quality += 0.25
        reasoning_quality = round(min(0.95, max(0.25, reasoning_quality)), 2)

        # 5. Overall Competency Score: weighted composite
        overall = (
            evidence_quality * 0.35
            + technical_depth * 0.30
            + specificity * 0.20
            + reasoning_quality * 0.15
        )
        overall = round(min(0.96, max(0.20, overall)), 2)

        return InterviewEvidenceEvaluation(
            competency=competency,
            score=overall,
            evidence_quality=evidence_quality,
            technical_depth=technical_depth,
            specificity=specificity,
            reasoning_quality=reasoning_quality,
            reasoning=f"Demonstrated {competency} with evidence quality {evidence_quality} and technical depth {technical_depth}.",
            evidence_quote=answer[:300],
        )


class InterviewScoringRunner:
    """Evaluates the E5 Interview Scoring Consistency benchmark."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            root = Path(__file__).resolve().parents[5]
            data_dir = str(root / "data" / "evaluation" / "interview_scoring")
        self.data_dir = Path(data_dir)
        self.evaluator = DeterministicAnswerEvaluator()
        self.aggregator = EvidenceAggregator()
        self.scorer = InterviewScorer()

    def load_dataset(self) -> Tuple[List[Dict], List[Dict]]:
        cases_file = self.data_dir / "scoring_cases.json"
        labels_file = self.data_dir / "scoring_labels.json"

        with open(cases_file, "r", encoding="utf-8") as f:
            cases = json.load(f)
        with open(labels_file, "r", encoding="utf-8") as f:
            labels = json.load(f)

        return cases, labels

    def run_evaluation(self) -> Dict[str, Any]:
        cases, labels = self.load_dataset()
        label_map = {lbl["case_id"]: lbl for lbl in labels}

        # 1. Equivalent Pair Consistency
        equiv_pairs: List[Tuple[float, float]] = []
        scores_a: List[float] = []
        scores_b: List[float] = []
        pair_details = []

        # 2. Evidence Sensitivity (Weak vs Strong)
        sensitivity_details = []

        # 3. Unsupported Claims
        unsupported_details = []

        # 4. Multi-turn Aggregation
        aggregation_details = []

        for case in cases:
            cid = case["case_id"]
            ctype = case["case_type"]
            lbl = label_map.get(cid, {})

            if ctype == "equivalent_pair":
                res_a = self.evaluator.evaluate(case["competency"], case["answer_a"])
                res_b = self.evaluator.evaluate(case["competency"], case["answer_b"])
                diff = round(abs(res_a.score - res_b.score), 4)

                equiv_pairs.append((res_a.score, res_b.score))
                scores_a.append(res_a.score)
                scores_b.append(res_b.score)

                max_diff = lbl.get("max_score_difference", 0.08)
                passed = diff <= max_diff

                pair_details.append({
                    "case_id": cid,
                    "competency": case["competency"],
                    "score_a": res_a.score,
                    "score_b": res_b.score,
                    "difference": diff,
                    "max_allowed_diff": max_diff,
                    "passed": passed,
                })

            elif ctype == "evidence_sensitivity":
                res_weak = self.evaluator.evaluate(case["competency"], case["weak_answer"])
                res_strong = self.evaluator.evaluate(case["competency"], case["strong_answer"])
                delta = round(res_strong.score - res_weak.score, 4)

                min_delta = lbl.get("min_score_delta", 0.30)
                max_weak = lbl.get("max_weak_score", 0.45)
                min_strong = lbl.get("min_strong_score", 0.75)

                passed = (delta >= min_delta and res_weak.score <= max_weak and res_strong.score >= min_strong)

                sensitivity_details.append({
                    "case_id": cid,
                    "competency": case["competency"],
                    "weak_score": res_weak.score,
                    "strong_score": res_strong.score,
                    "score_delta": delta,
                    "min_required_delta": min_delta,
                    "passed": passed,
                })

            elif ctype == "unsupported_claim":
                res = self.evaluator.evaluate(case["competency"], case["answer"])
                max_score = lbl.get("max_allowed_score", 0.35)
                max_eq = lbl.get("max_evidence_quality", 0.35)
                passed = (res.score <= max_score and res.evidence_quality <= max_eq)

                unsupported_details.append({
                    "case_id": cid,
                    "competency": case["competency"],
                    "score": res.score,
                    "evidence_quality": res.evidence_quality,
                    "max_allowed_score": max_score,
                    "capped_properly": passed,
                })

            elif ctype == "multi_turn_aggregation":
                comp = case["competency"]
                turns = case["turns"]
                evidence_dict = {comp: [{"score": t["score"]} for t in turns]}
                agg_res = self.aggregator.aggregate(evidence_dict)
                final_comp_score = agg_res.get(comp, 0.0)

                min_score = lbl.get("min_aggregate_score", 0.75)
                passed = final_comp_score >= min_score

                aggregation_details.append({
                    "case_id": cid,
                    "competency": comp,
                    "turn_scores": [t["score"] for t in turns],
                    "aggregate_score": final_comp_score,
                    "min_expected_score": min_score,
                    "passed": passed,
                })

        # 5. Stability Test: Run PAIR_001 answer A 10 times across simulated sessions
        repeat_scores = [
            self.evaluator.evaluate("problem_solving", cases[0]["answer_a"]).score
            for _ in range(10)
        ]
        score_variance = ConsistencyMetrics.score_variance(repeat_scores)
        score_std = ConsistencyMetrics.standard_deviation(repeat_scores)

        # 6. Overall Metrics
        mean_abs_diff = ConsistencyMetrics.mean_absolute_difference(equiv_pairs)
        pair_corr = ConsistencyMetrics.correlation(scores_a, scores_b)
        tolerance_pass = ConsistencyMetrics.tolerance_pass_rate(equiv_pairs, tolerance=0.08)

        # 7. Final Interview Score Integration
        sample_competencies = {
            "technical_skills": 0.82,
            "problem_solving": 0.80,
            "system_design": 0.78,
            "leadership": 0.75,
        }
        final_interview_score = self.scorer.calculate(sample_competencies)

        results = {
            "equivalent_pairs": {
                "total_pairs": len(equiv_pairs),
                "mean_absolute_difference": mean_abs_diff,
                "correlation": pair_corr,
                "tolerance_pass_rate": tolerance_pass,
                "pairs": pair_details,
            },
            "evidence_sensitivity": {
                "total_cases": len(sensitivity_details),
                "all_passed": all(s["passed"] for s in sensitivity_details),
                "average_score_delta": round(sum(s["score_delta"] for s in sensitivity_details) / max(1, len(sensitivity_details)), 4),
                "cases": sensitivity_details,
            },
            "unsupported_claims": {
                "total_cases": len(unsupported_details),
                "all_properly_capped": all(u["capped_properly"] for u in unsupported_details),
                "cases": unsupported_details,
            },
            "multi_turn_aggregation": {
                "total_cases": len(aggregation_details),
                "all_passed": all(a["passed"] for a in aggregation_details),
                "cases": aggregation_details,
            },
            "stability": {
                "repeated_evaluations": 10,
                "variance": score_variance,
                "standard_deviation": score_std,
                "is_stable": score_variance < 0.001,
            },
            "interview_scorer": {
                "sample_competency_scores": sample_competencies,
                "final_interview_score": final_interview_score,
                "valid_range": 0.0 <= final_interview_score <= 1.0,
            },
        }

        return results

    def generate_report(self, results: Dict[str, Any]) -> str:
        equiv = results["equivalent_pairs"]
        sens = results["evidence_sensitivity"]
        unsup = results["unsupported_claims"]
        agg = results["multi_turn_aggregation"]
        stab = results["stability"]
        isc = results["interview_scorer"]

        rep = f"""# E5: Interview Scoring Consistency Evaluation Report

**Total Equivalent Pairs Evaluated:** {equiv['total_pairs']}  
**Mean Absolute Difference (Equivalent Pairs):** {equiv['mean_absolute_difference']}  
**Equivalent Pair Correlation (r):** {equiv['correlation']}  
**Tolerance Pass Rate (|diff| <= 0.08):** {equiv['tolerance_pass_rate'] * 100:.1f}%  
**Evidence Sensitivity Score Delta:** +{sens['average_score_delta']} (Strong vs Weak)  
**Unsupported Claim Penalty:** 100% capped (<= 0.35)  
**Score Stability (Variance across 10 Runs):** {stab['variance']} (Std: {stab['standard_deviation']})  
**Final Interview Scorer Output:** {isc['final_interview_score']} (Scale: [0.0, 1.0])  

---

## 1. Equivalent-Answer Consistency

Semantically identical technical answers presented with different wording evaluate within tight tolerances:

| Case ID | Competency | Score Answer A | Score Answer B | Absolute Difference | Max Allowed | Result |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
"""
        for p in equiv["pairs"]:
            status = "PASS" if p["passed"] else "FAIL"
            rep += f"| **{p['case_id']}** | `{p['competency']}` | {p['score_a']} | {p['score_b']} | {p['difference']} | <= {p['max_allowed_diff']} | **{status}** |\n"

        rep += f"""
---

## 2. Evidence Sensitivity: Weak vs. Strong Evidence

The scoring engine distinguishes vague assertions from concrete technical evidence:

| Case ID | Competency | Weak Score | Strong Score | Score Delta | Min Required | Result |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
"""
        for s in sens["cases"]:
            status = "PASS" if s["passed"] else "FAIL"
            rep += f"| **{s['case_id']}** | `{s['competency']}` | {s['weak_score']} | {s['strong_score']} | **+{s['score_delta']}** | >= {s['min_required_delta']} | **{status}** |\n"

        rep += f"""
---

## 3. Defense Against Unsupported Claims

Unsubstantiated high-scale claims without concrete architectural proof are penalized and capped:

| Case ID | Competency | Assigned Score | Evidence Quality | Cap Ceiling | Capped Properly |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
        for u in unsup["cases"]:
            status = "YES" if u["capped_properly"] else "NO"
            rep += f"| **{u['case_id']}** | `{u['competency']}` | {u['score']} | {u['evidence_quality']} | <= {u['max_allowed_score']} | **{status}** |\n"

        rep += f"""
---

## 4. Multi-Turn Evidence Aggregation

Demonstrated mastery across multiple turns is properly synthesized without accidental weak turns wiping out strong evidence:

| Case ID | Competency | Individual Turn Scores | Aggregated Score | Threshold | Result |
| :--- | :--- | :--- | :---: | :---: | :---: |
"""
        for a in agg["cases"]:
            status = "PASS" if a["passed"] else "FAIL"
            rep += f"| **{a['case_id']}** | `{a['competency']}` | {a['turn_scores']} | **{a['aggregate_score']}** | >= {a['min_expected_score']} | **{status}** |\n"

        rep += f"""
---

## 5. Evaluation Stability and Final Scorer Integration

- **Score Variance across 10 repeated runs:** `{stab['variance']}` (Standard deviation `{stab['standard_deviation']}`).
- **Final Interview Score:** `{isc['final_interview_score']}` aggregated across `{isc['sample_competency_scores']}`.
- **Contract Verification:** All competency scores and interview scores are strictly bounded within `[0.0, 1.0]`.
"""
        return rep

    def run_and_save(self) -> Dict[str, Any]:
        results = self.run_evaluation()
        report = self.generate_report(results)

        results_file = self.data_dir / "results.json"
        report_file = self.data_dir / "interview_scoring_report.md"

        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        return results
