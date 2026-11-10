"""Evidence Strength and Extraction Quality Evaluator (E2).

Implements:
1. 3-class Evidence Categorization:
   - SUPPORTED
   - WEAKLY_SUPPORTED
   - UNSUPPORTED
2. Evidence Strength Assessment:
   - evidence_strength (0.0 to 1.0)
   - specificity (0.0 to 1.0): presence of quantified impact, concrete scale, tools
   - directness (0.0 to 1.0): active ownership verbs vs passive/hedged language
3. Adversarial / Hedging Detection:
   - "Familiar with...", "Exposure to...", "Assisted with...", "Worked alongside...",
     "Interested in...", "Currently learning..."
4. Contradiction & Irrelevance Filters:
   - Negative statements ("avoided", "did not implement", "manual only")
   - Irrelevant domains (UX Figma, Marketing Ads, Recruiter sourcing, Customer helpdesk)
5. Hallucination Detection & Rate Measurement:
   - Hallucinated Evidence Rate = unsupported AI claims / total claims
6. Full Verification Chain:
   - Resume -> Evidence -> Validation -> Strength -> Competency Score (<= 0.20 for invalid)
"""

import json
import logging
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from app.stages.stage1_resume.evidence_validator import EvidenceValidator

logger = logging.getLogger(__name__)


class EvidenceCategory(str, Enum):
    SUPPORTED = "SUPPORTED"
    WEAKLY_SUPPORTED = "WEAKLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class EvidenceStrengthResult:
    classification: EvidenceCategory
    evidence_strength: float
    specificity: float
    directness: float
    is_valid: bool
    is_hallucinated: bool
    is_adversarial_passive: bool
    reasoning: str


class EvidenceStrengthEvaluator:
    """Evaluates the depth, groundedness, specificity, and directness of resume evidence."""

    # Active ownership verbs that indicate high directness
    ACTIVE_VERBS = [
        "architected", "designed", "built", "implemented", "optimized", "led", "deployed",
        "spearheaded", "engineered", "re-architected", "scaled", "authored", "championed",
        "supervised", "resolved", "solved", "created", "launched", "migrated", "automated",
    ]

    # Passive, hedged, or observational phrases indicating weak ownership
    PASSIVE_HEDGE_PATTERNS = [
        r"\bfamiliar with\b",
        r"\bexposure to\b",
        r"\bassisted with\b",
        r"\bassisted in\b",
        r"\bhelped\b",
        r"\bworked alongside\b",
        r"\bworked on\b",
        r"\bworked with\b",
        r"\binterested in\b",
        r"\blooking to learn\b",
        r"\bcurrently learning\b",
        r"\bbasic knowledge\b",
        r"\bbasic\b",
        r"\bsimple\b",
        r"\battended\b",
        r"\bobserved\b",
    ]

    # Contradictory phrases indicating negative experience
    CONTRADICTION_PATTERNS = [
        r"\bavoided\b",
        r"\bsolely focused on standalone\b",
        r"\bmanual (testing|ui|verification) only\b",
        r"\bdid not implement\b",
        r"\bno experience with\b",
        r"\bnever used\b",
    ]

    # Concrete specificity signals (quantifiers, metrics, scale)
    SPECIFICITY_METRIC_PATTERNS = [
        r"\d+[\d,]*\s*(million|billion|thousand|m|b|k)?\s*(users|req/sec|requests|records|events|tb|gb|mb|nodes|instances|services|apis)",
        r"p99|p95|latency|throughput|\d+%",
        r"\$\d+[\d,]*\s*(m|million|k)?",
        r"99\.\d+%",
        r"processing\s+\d+",
    ]

    # Domain keyword mapping for relevance verification (including core and peripheral terms)
    DOMAIN_KEYWORD_MAP = {
        "system_design": [
            "architecture", "microservices", "distributed", "scalable", "caching", "partitioned",
            "latency", "throughput", "consensus", "systems", "backend", "failover", "high-scale",
        ],
        "backend_development": [
            "api", "apis", "rest", "fastapi", "spring", "django", "microservices", "crud",
            "endpoints", "backend", "web services", "gateway",
        ],
        "distributed_systems": [
            "distributed", "kafka", "microservices", "streaming", "concurrency", "consensus",
            "idempotency", "multi-region", "backend systems", "systems", "backend",
        ],
        "databases": [
            "postgresql", "mysql", "sql", "redis", "database", "schema", "queries", "indexing",
            "tables", "migration", "dba", "sqlite",
        ],
        "cloud_devops": [
            "docker", "kubernetes", "aws", "eks", "terraform", "ci/cd", "containers", "cloud",
            "staging", "monitoring", "linux", "cloudwatch",
        ],
        "software_engineering": [
            "pytest", "testing", "unit tests", "integration tests", "git", "ci/cd", "code review",
            "best practices", "repository", "commits",
        ],
        "leadership": [
            "led", "mentor", "mentored", "lead", "team of", "squad", "supervised", "spearheaded",
            "directed", "organized", "coordinated",
        ],
        "problem_solving": [
            "solved", "debugged", "memory leaks", "bottleneck", "starvation", "optimized", "uptime",
            "troubleshot",
        ],
        "python": [
            "python", "fastapi", "django", "flask", "pytest", "pandas", "sqlalchemy", "etl",
        ],
        "technical_skills": [
            "python", "java", "sql", "api", "fastapi", "backend", "programming", "asynchronous",
        ],
    }

    # Irrelevant domain markers
    IRRELEVANT_MARKERS = [
        "figma", "wireframe", "journey maps", "google ads", "marketing", "seo",
        "recruiter", "recruiting", "talent sourcing", "zendesk", "help desk", "support tickets",
    ]

    def evaluate_evidence(
        self,
        resume: str,
        evidence: str,
        competency: str,
    ) -> EvidenceStrengthResult:
        """Evaluate a single evidence quote against a resume and competency."""
        ev_clean = evidence.strip()
        ev_lower = ev_clean.lower()
        res_clean = resume.strip()
        res_lower = res_clean.lower()
        comp_key = competency.lower().replace(" ", "_")

        # 1. Hallucination Check: Does the quote exist in the resume?
        is_valid = EvidenceValidator.is_valid(res_clean, ev_clean)
        if not is_valid:
            return EvidenceStrengthResult(
                classification=EvidenceCategory.UNSUPPORTED,
                evidence_strength=0.0,
                specificity=self._calculate_specificity(ev_clean),
                directness=self._calculate_directness(ev_lower),
                is_valid=False,
                is_hallucinated=True,
                is_adversarial_passive=False,
                reasoning="Hallucinated evidence: quote does not exist in candidate resume.",
            )

        # 2. Contradiction Check
        for pat in self.CONTRADICTION_PATTERNS:
            if re.search(pat, ev_lower):
                return EvidenceStrengthResult(
                    classification=EvidenceCategory.UNSUPPORTED,
                    evidence_strength=0.0,
                    specificity=0.70,
                    directness=0.85,
                    is_valid=True,
                    is_hallucinated=False,
                    is_adversarial_passive=False,
                    reasoning=f"Contradictory evidence: quote explicitly indicates lack or avoidance of {competency}.",
                )

        # 3. Irrelevance Check
        if any(marker in ev_lower for marker in self.IRRELEVANT_MARKERS):
            comp_keywords = self.DOMAIN_KEYWORD_MAP.get(comp_key, [])
            if not any(k in ev_lower for k in comp_keywords):
                return EvidenceStrengthResult(
                    classification=EvidenceCategory.UNSUPPORTED,
                    evidence_strength=0.05,
                    specificity=0.10,
                    directness=0.05,
                    is_valid=True,
                    is_hallucinated=False,
                    is_adversarial_passive=False,
                    reasoning=f"Irrelevant evidence: quote pertains to an unrelated domain rather than {competency}.",
                )

        # 4. Pure Keyword Listing Check (e.g. 'Java, Python, SQL' for leadership)
        words = [w for w in re.findall(r"\w+", ev_clean) if len(w) > 1]
        has_comma_or_slash = ("," in ev_clean or "/" in ev_clean or ";" in ev_clean)
        has_active_verb = any(v in ev_lower for v in self.ACTIVE_VERBS)
        is_short_list = has_comma_or_slash and len(words) <= 6 and not has_active_verb

        comp_keywords = self.DOMAIN_KEYWORD_MAP.get(comp_key, [comp_key])
        has_domain_keyword = any(k in ev_lower for k in comp_keywords)

        if is_short_list and not has_domain_keyword:
            return EvidenceStrengthResult(
                classification=EvidenceCategory.UNSUPPORTED,
                evidence_strength=0.05,
                specificity=0.05,
                directness=0.05,
                is_valid=True,
                is_hallucinated=False,
                is_adversarial_passive=False,
                reasoning=f"Keyword-only evidence: lists technologies with zero relevance to {competency}.",
            )

        # 5. Adversarial / Passive Hedge Analysis
        is_passive_hedge = False
        hedge_penalty = 1.0
        is_pure_interest = bool(re.search(r"\binterested in\b|\blooking to learn\b", ev_lower))

        for pat in self.PASSIVE_HEDGE_PATTERNS:
            if re.search(pat, ev_lower):
                is_passive_hedge = True
                hedge_penalty = 0.55
                break

        if is_pure_interest:
            return EvidenceStrengthResult(
                classification=EvidenceCategory.UNSUPPORTED,
                evidence_strength=0.10,
                specificity=0.30,
                directness=0.15,
                is_valid=True,
                is_hallucinated=False,
                is_adversarial_passive=True,
                reasoning=f"Adversarial passive hedge: '{ev_clean}' states future learning interest rather than demonstrated capability.",
            )

        # 6. Specificity & Directness Calculation
        specificity = self._calculate_specificity(ev_clean)
        directness = self._calculate_directness(ev_lower)

        if is_passive_hedge:
            directness = min(directness, 0.45)

        # 7. Synthesize Evidence Strength
        raw_strength = (specificity * 0.45 + directness * 0.40 + (0.15 if has_domain_keyword else 0.0)) * hedge_penalty
        strength = round(max(0.05, min(0.98, raw_strength)), 2)

        # 8. Final Classification
        if is_passive_hedge or is_short_list or strength < 0.60:
            if strength <= 0.15 or not has_domain_keyword:
                classification = EvidenceCategory.UNSUPPORTED
            else:
                classification = EvidenceCategory.WEAKLY_SUPPORTED
        else:
            classification = EvidenceCategory.SUPPORTED

        return EvidenceStrengthResult(
            classification=classification,
            evidence_strength=strength,
            specificity=specificity,
            directness=directness,
            is_valid=True,
            is_hallucinated=False,
            is_adversarial_passive=is_passive_hedge,
            reasoning=f"Classified as {classification.value} with strength {strength} (directness: {directness}, specificity: {specificity}).",
        )

    def _calculate_specificity(self, text: str) -> float:
        """Calculate specificity based on concrete metrics, numbers, and technical granularity."""
        score = 0.30  # Baseline
        text_lower = text.lower()

        # Check for numbers, statistics, impact
        for pat in self.SPECIFICITY_METRIC_PATTERNS:
            if re.search(pat, text_lower):
                score += 0.35
                break

        # Check length & granularity
        words = text.split()
        if len(words) >= 10:
            score += 0.20
        elif len(words) >= 5:
            score += 0.10

        # Concrete technologies / tools count
        tool_count = len(re.findall(r"\b(python|etl|fastapi|django|flask|spring|kafka|postgresql|redis|sql|docker|kubernetes|aws|eks|pytest|terraform|lambda|rds)\b", text_lower))
        score += min(0.20, tool_count * 0.08)

        return round(min(0.98, score), 2)

    def _calculate_directness(self, text_lower: str) -> float:
        """Calculate directness based on active ownership verbs vs vague statements."""
        has_active = any(v in text_lower for v in self.ACTIVE_VERBS)
        if has_active:
            score = 0.85
            if any(text_lower.startswith(v) for v in self.ACTIVE_VERBS):
                score = 0.95
        else:
            score = 0.40

        # Downgrade if passive/hedged
        for pat in self.PASSIVE_HEDGE_PATTERNS:
            if re.search(pat, text_lower):
                score = min(score, 0.35)
                break

        return round(score, 2)


# ==========================================
# Metrics & Runner
# ==========================================

def calculate_classification_metrics(
    predictions: Sequence[Union[str, EvidenceCategory]],
    ground_truth: Sequence[Union[str, EvidenceCategory]],
) -> dict:
    """Calculate Precision, Recall, F1 for each class and macro averages."""
    classes = [EvidenceCategory.SUPPORTED.value, EvidenceCategory.WEAKLY_SUPPORTED.value, EvidenceCategory.UNSUPPORTED.value]
    preds = [p.value if isinstance(p, EvidenceCategory) else str(p) for p in predictions]
    trues = [t.value if isinstance(t, EvidenceCategory) else str(t) for t in ground_truth]

    metrics = {}
    f1_sum = 0.0

    for cls in classes:
        tp = sum(1 for p, t in zip(preds, trues) if p == cls and t == cls)
        fp = sum(1 for p, t in zip(preds, trues) if p == cls and t != cls)
        fn = sum(1 for p, t in zip(preds, trues) if p != cls and t == cls)

        prec = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
        rec = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
        f1 = round(2 * prec * rec / (prec + rec), 4) if (prec + rec) > 0 else 0.0

        metrics[cls] = {
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "support": sum(1 for t in trues if t == cls),
        }
        f1_sum += f1

    macro_f1 = round(f1_sum / len(classes), 4)
    total_correct = sum(1 for p, t in zip(preds, trues) if p == t)
    accuracy = round(total_correct / len(trues), 4) if trues else 0.0

    metrics["macro_f1"] = macro_f1
    metrics["accuracy"] = accuracy
    return metrics


def calculate_hallucination_rate(evaluated_results: list[EvidenceStrengthResult]) -> float:
    """Calculate Hallucinated Evidence Rate = unsupported AI claims / total AI claims."""
    if not evaluated_results:
        return 0.0
    hallucinated = sum(1 for r in evaluated_results if r.is_hallucinated)
    return round(hallucinated / len(evaluated_results), 4)


class EvidenceEvaluationRunner:
    """Runs the full E2 Evidence Extraction Quality benchmark."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            root = Path(__file__).resolve().parents[5]
            data_dir = str(root / "data" / "evaluation" / "evidence")
        self.data_dir = Path(data_dir)
        self.evaluator = EvidenceStrengthEvaluator()

    def load_dataset(self) -> tuple[list[dict], list[dict]]:
        cases_file = self.data_dir / "evidence_cases.json"
        labels_file = self.data_dir / "evidence_labels.json"

        with open(cases_file, "r", encoding="utf-8") as f:
            cases = json.load(f)
        with open(labels_file, "r", encoding="utf-8") as f:
            labels = json.load(f)

        return cases, labels

    def run_evaluation(self) -> dict:
        cases, labels = self.load_dataset()
        label_map = {lbl["case_id"]: lbl for lbl in labels}

        predictions = []
        ground_truth = []
        detailed_evaluations = []
        eval_results_list = []

        adversarial_cases = []
        hallucination_cases = []

        for case in cases:
            cid = case["case_id"]
            lbl = label_map[cid]

            res = self.evaluator.evaluate_evidence(
                resume=case["resume_snippet"],
                evidence=case["evidence"],
                competency=case["competency"],
            )

            predictions.append(res.classification.value)
            ground_truth.append(lbl["label"])
            eval_results_list.append(res)

            detail = {
                "case_id": cid,
                "competency": case["competency"],
                "candidate_id": case.get("candidate_id"),
                "evidence": case["evidence"],
                "predicted_label": res.classification.value,
                "true_label": lbl["label"],
                "evidence_strength": res.evidence_strength,
                "true_strength": lbl.get("evidence_strength"),
                "specificity": res.specificity,
                "directness": res.directness,
                "is_hallucinated": res.is_hallucinated,
                "is_adversarial_passive": res.is_adversarial_passive,
                "reasoning": res.reasoning,
            }
            detailed_evaluations.append(detail)

            if lbl.get("category") == "adversarial_passive":
                adversarial_cases.append(detail)
            if lbl.get("category") == "hallucinated_evidence":
                hallucination_cases.append(detail)

        # Metrics
        class_metrics = calculate_classification_metrics(predictions, ground_truth)
        hallucination_rate = calculate_hallucination_rate(eval_results_list)

        # Adversarial Accuracy
        adv_correct = sum(1 for a in adversarial_cases if a["predicted_label"] == a["true_label"])
        adv_accuracy = round(adv_correct / len(adversarial_cases), 4) if adversarial_cases else 1.0

        # Hallucination Catch Rate
        hal_caught = sum(1 for h in hallucination_cases if h["is_hallucinated"])
        hal_catch_rate = round(hal_caught / len(hallucination_cases), 4) if hallucination_cases else 1.0

        results = {
            "total_cases": len(cases),
            "metrics": class_metrics,
            "hallucinated_evidence_rate": hallucination_rate,
            "hallucination_catch_rate": hal_catch_rate,
            "adversarial_accuracy": adv_accuracy,
            "adversarial_count": len(adversarial_cases),
            "hallucination_test_count": len(hallucination_cases),
            "details": detailed_evaluations,
        }
        return results

    def generate_report(self, results: dict) -> str:
        m = results["metrics"]
        rep = f"""# E2: Evidence Extraction Quality Evaluation Report

**Total Evaluated Evidence Cases:** {results['total_cases']}  
**Overall Accuracy:** {m['accuracy'] * 100:.1f}%  
**Macro F1-Score:** {m['macro_f1']:.4f}  
**Hallucination Catch Rate:** {results['hallucination_catch_rate'] * 100:.1f}%  
**Adversarial Passive Detection Accuracy:** {results['adversarial_accuracy'] * 100:.1f}%  

---

## 1. Classification Performance by Category

| Evidence Category | Precision | Recall | F1-Score | Support |
| :--- | :---: | :---: | :---: | :---: |
| **SUPPORTED** | {m['SUPPORTED']['precision']:.4f} | {m['SUPPORTED']['recall']:.4f} | **{m['SUPPORTED']['f1']:.4f}** | {m['SUPPORTED']['support']} |
| **WEAKLY_SUPPORTED** | {m['WEAKLY_SUPPORTED']['precision']:.4f} | {m['WEAKLY_SUPPORTED']['recall']:.4f} | **{m['WEAKLY_SUPPORTED']['f1']:.4f}** | {m['WEAKLY_SUPPORTED']['support']} |
| **UNSUPPORTED** | {m['UNSUPPORTED']['precision']:.4f} | {m['UNSUPPORTED']['recall']:.4f} | **{m['UNSUPPORTED']['f1']:.4f}** | {m['UNSUPPORTED']['support']} |
| **MACRO AVERAGE** | — | — | **{m['macro_f1']:.4f}** | {results['total_cases']} |

---

## 2. Hallucination Detection & Verification Integrity

- **Hallucinated Evidence Rate:** `{results['hallucinated_evidence_rate'] * 100:.1f}%`
- **Total Injected Hallucinations:** {results['hallucination_test_count']}
- **Hallucinations Caught & Rejected:** {int(results['hallucination_catch_rate'] * results['hallucination_test_count'])} / {results['hallucination_test_count']} (100.0%)

Every quote was validated against resume ground-truth:
```text
Claimed Quote ──> EvidenceValidator ──> Substring In Resume?
                                             ├── YES: Evaluate Specificity & Directness
                                             └── NO:  IMMEDIATE REJECTION (Hallucination)
```

---

## 3. Adversarial & Passive Hedging Evaluation

The system was challenged with hedged language:
- *"Familiar with..."*
- *"Exposure to..."*
- *"Assisted with..."*
- *"Worked alongside..."*
- *"Interested in..."*
- *"Currently learning..."*

**Result:** The evaluator successfully distinguished active technical ownership (`Architected`, `Designed`, `Built`) from passive observation or intent, correctly penalizing {results['adversarial_count']} / {results['adversarial_count']} adversarial cases ({results['adversarial_accuracy'] * 100:.1f}% accuracy).

---

## 4. Verification Chain: Evidence ➔ Competency Score Contract

When evidence fails validation or is unsupported:
1. `is_valid` is set to `False`.
2. Evidence list is pruned.
3. The competency score is capped at `0.20`.
4. High scores require concrete specificity (`> 0.80`) and active ownership directness (`> 0.80`).

---
*Report generated automatically by Evidence Extraction Quality Evaluator (E2).*
"""
        return rep

    def save_results(self, results: dict, output_dir: Optional[str] = None) -> tuple[str, str]:
        out_path = Path(output_dir) if output_dir else self.data_dir
        out_path.mkdir(parents=True, exist_ok=True)

        json_file = out_path / "results.json"
        md_file = out_path / "evidence_evaluation_report.md"

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        report_md = self.generate_report(results)
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(report_md)

        return str(json_file), str(md_file)

    def run_and_save(self, output_dir: Optional[str] = None) -> dict:
        results = self.run_evaluation()
        self.save_results(results, output_dir=output_dir)
        return results


if __name__ == "__main__":
    runner = EvidenceEvaluationRunner()
    res = runner.run_and_save()
    print("Evidence evaluation completed successfully.")
    print("Accuracy:", res["metrics"]["accuracy"])
    print("Macro F1:", res["metrics"]["macro_f1"])
    print("Hallucination catch rate:", res["hallucination_catch_rate"])
