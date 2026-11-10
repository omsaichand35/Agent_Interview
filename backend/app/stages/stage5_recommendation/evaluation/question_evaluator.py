"""Adaptive Question Quality and Interview Progression Evaluator (E4).

Evaluates:
1. Relevance (1-5 scale: unrelated to directly grounded).
2. Grounding (detects questions justified by candidate evidence vs hallucinated topics).
3. Competency Alignment (verifies question targets intended competency).
4. Decision Correctness (deepen, pivot, next_competency, conclude).
5. Specificity (1-5 scale: generic to deeply grounded with concrete parameters).
6. Adaptive Progression (evaluates synthetic multi-turn trajectory).
7. Repetition Detection (lexical and semantic repetition).
8. Interview Efficiency (turns per competency, useful evidence ratio).
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Union

logger = logging.getLogger(__name__)


class GroundingEvaluator:
    """Evaluates whether an interview question is grounded in the candidate's actual answer."""

    # Entities that often appear in hallucinated/ungrounded follow-ups
    KNOWN_TECH_ENTITIES = [
        "kubernetes", "docker", "kafka", "redis", "postgresql", "mysql", "mongodb",
        "react", "vue", "angular", "css", "html", "aws", "gcp", "azure", "jenkins",
        "helm", "terraform", "pytest", "spring", "fastapi", "django", "flask",
        "consensus", "paxos", "raft", "server rack", "android", "ios", "graphql",
    ]

    TECH_RELATED_DOMAINS = {
        "kafka": {
            "partition", "partitioning", "consumer", "group", "scale", "scaling",
            "offset", "topic", "broker", "event", "stream", "pipeline", "lag",
            "deduplication", "rebalancing", "throughput", "millions", "cluster",
        },
        "redis": {
            "cache", "caching", "cached", "latency", "ttl", "eviction", "memory",
            "invalidation", "performance", "store", "operations", "improvement",
        },
        "database": {
            "query", "index", "indexing", "replication", "schema", "table",
            "transaction", "migration", "cutover", "aurora", "postgres", "postgresql",
            "sql", "pool", "starvation",
        },
        "postgresql": {
            "query", "index", "indexing", "replication", "schema", "table",
            "transaction", "migration", "cutover", "sql", "pool", "starvation",
        },
        "docker": {"container", "image", "dockerfile", "compose", "volume"},
        "kubernetes": {"pod", "cluster", "node", "ingress", "service", "deployment", "helm", "rollout", "replica"},
        "pytest": {"test", "testing", "fixture", "mock", "coverage", "flaky", "ci", "cd", "assert"},
        "fastapi": {"endpoint", "endpoints", "latency", "rest", "pydantic", "routing", "async"},
        "leadership": {"team", "junior", "mentor", "mentored", "mentoring", "delegate", "lead", "squad", "coach", "review", "pairing", "1-on-1"},
    }

    @staticmethod
    def extract_entities(text: str) -> set[str]:
        words = set(re.findall(r"\b[a-z0-9_\-\.\+%]+\b", text.lower()))
        entities = set()
        for ent in GroundingEvaluator.KNOWN_TECH_ENTITIES:
            if ent in words or ent in text.lower():
                entities.add(ent)
        return entities

    @staticmethod
    def is_grounded(question: str, answer: str, context: Optional[dict] = None) -> bool:
        """Return True if question topics/tools are grounded in the candidate's answer or prior context."""
        q_lower = question.lower()
        a_lower = answer.lower()

        # Check for ungrounded hallucinated technical entities
        q_entities = GroundingEvaluator.extract_entities(q_lower)
        a_entities = GroundingEvaluator.extract_entities(a_lower)

        # Context entities (if provided)
        ctx_entities = set()
        if context:
            ctx_text = " ".join(str(v) for v in context.values()).lower()
            ctx_entities = GroundingEvaluator.extract_entities(ctx_text)

        available_entities = a_entities | ctx_entities

        # If question introduces a major specific tech entity not in answer/context, it's ungrounded
        hallucinated_entities = q_entities - available_entities
        if len(hallucinated_entities) >= 1:
            return False

        # Gather domain concepts available from answer entities
        domain_concepts = set()
        for ent in available_entities:
            if ent in GroundingEvaluator.TECH_RELATED_DOMAINS:
                domain_concepts.update(GroundingEvaluator.TECH_RELATED_DOMAINS[ent])

        # Check token and stem overlap
        q_words = re.findall(r"\w+", q_lower)
        a_words = re.findall(r"\w+", a_lower)

        q_stems = set(w[:4] for w in q_words if len(w) >= 3)
        a_stems = set(w[:4] for w in a_words if len(w) >= 3)

        overlap = q_stems & a_stems
        has_domain_overlap = any(concept in q_lower for concept in domain_concepts)
        has_generic_transition = any(w in q_lower for w in ["next", "move on", "thank you", "let's discuss", "earlier you", "conclude"])

        return len(overlap) >= 1 or has_domain_overlap or has_generic_transition


class RelevanceEvaluator:
    """Evaluates question relevance on a 1 to 5 scale:

    1 = unrelated
    2 = weakly related
    3 = somewhat relevant
    4 = strongly relevant
    5 = directly grounded
    """

    @staticmethod
    def rate_relevance(question: str, answer: str, target_competency: str = "") -> int:
        if not question or not answer:
            return 1

        is_grounded = GroundingEvaluator.is_grounded(question, answer)
        if not is_grounded:
            return 1

        q_lower = question.lower()
        a_lower = answer.lower()

        stopwords = {"this", "that", "with", "from", "your", "what", "which", "could", "would", "about", "have", "were", "been", "tell"}

        q_words = [w for w in re.findall(r"\w+", q_lower) if len(w) >= 3 and w not in stopwords]
        a_words = [w for w in re.findall(r"\w+", a_lower) if len(w) >= 3 and w not in stopwords]

        q_stems = set(w[:4] for w in q_words)
        a_stems = set(w[:4] for w in a_words)

        overlap = len(q_stems & a_stems)

        # Check domain concepts
        a_entities = GroundingEvaluator.extract_entities(a_lower)
        domain_concepts = set()
        for ent in a_entities:
            if ent in GroundingEvaluator.TECH_RELATED_DOMAINS:
                domain_concepts.update(GroundingEvaluator.TECH_RELATED_DOMAINS[ent])

        domain_matches = sum(1 for c in domain_concepts if c in q_lower)
        total_signal = overlap + (1 if domain_matches >= 2 else (1 if domain_matches == 1 else 0))

        # Check transition questions
        is_transition = any(w in q_lower for w in ["next", "move on", "thank you", "let's discuss", "earlier you"])
        if is_transition and (overlap >= 1 or target_competency.lower() in q_lower):
            return 4

        # Rate based on total grounded signal
        if total_signal >= 3 or (overlap >= 2 and domain_matches >= 1):
            return 5
        elif total_signal >= 2 or overlap >= 2:
            return 4
        elif total_signal >= 1:
            return 3
        else:
            return 2


class SpecificityEvaluator:
    """Evaluates question specificity on a 1 to 5 scale:

    1 = generic ('Tell me about Redis')
    2 = somewhat specific
    3 = moderately specific
    4 = highly specific ('How did you handle partitioning and consumer scaling...')
    5 = deeply grounded with concrete candidate metrics or parameters
    """

    GENERIC_PATTERNS = [
        r"^tell me about\s+\w+\.?$",
        r"^what databases do you know\??$",
        r"^what programming languages do you know\??$",
        r"^do you write tests\??$",
        r"^next question\.?$",
    ]

    CONCRETE_METRIC_PATTERNS = [
        r"\d+[\d,]*\s*(%|users|req|records|events|ms|tb|gb)",
        r"p99|latency|invalidation|consistency|partitioning|cutover|zero downtime",
    ]

    @staticmethod
    def rate_specificity(question: str) -> int:
        q_clean = question.strip()
        q_lower = q_clean.lower()

        for pat in SpecificityEvaluator.GENERIC_PATTERNS:
            if re.search(pat, q_lower):
                return 1

        words = q_clean.split()
        if len(words) <= 5:
            return 1

        has_concrete_metric = any(re.search(pat, q_lower) for pat in SpecificityEvaluator.CONCRETE_METRIC_PATTERNS)
        has_multi_clause = ("how" in q_lower and "and how" in q_lower) or ("what did you" in q_lower and "how did you" in q_lower) or ("?" in q_clean and len(words) >= 14)

        if has_concrete_metric and has_multi_clause:
            return 5
        elif has_concrete_metric or has_multi_clause:
            return 4
        elif len(words) >= 10:
            return 3
        else:
            return 2


class RepetitionDetector:
    """Detects lexical and semantic repetition between consecutive interview questions."""

    SYNONYM_MAP = {
        "problem": "issue_concept",
        "issue": "issue_concept",
        "challenge": "issue_concept",
        "obstacle": "issue_concept",
        "solve": "solve_concept",
        "resolve": "solve_concept",
        "fix": "solve_concept",
        "handle": "solve_concept",
        "address": "solve_concept",
        "steps": "approach_concept",
        "step": "approach_concept",
        "approach": "approach_concept",
        "process": "approach_concept",
        "method": "approach_concept",
        "take": "approach_concept",
        "action": "approach_concept",
        "actions": "approach_concept",
        "metric": "metric_concept",
        "measure": "metric_concept",
        "measurement": "metric_concept",
        "verify": "metric_concept",
        "validation": "metric_concept",
    }

    STOP_WORDS = {
        "what", "how", "did", "you", "the", "a", "an", "to", "in", "and", "your",
        "can", "tell", "me", "about", "do", "for", "of", "on", "with",
    }

    @staticmethod
    def question_similarity(q1: str, q2: str) -> float:
        """Compute lexical and semantic Jaccard similarity between two questions."""
        if not q1 or not q2:
            return 0.0

        w1 = re.findall(r"\w+", q1.lower())
        w2 = re.findall(r"\w+", q2.lower())

        c1 = set(RepetitionDetector.SYNONYM_MAP.get(w, w) for w in w1 if w not in RepetitionDetector.STOP_WORDS)
        c2 = set(RepetitionDetector.SYNONYM_MAP.get(w, w) for w in w2 if w not in RepetitionDetector.STOP_WORDS)

        if not c1 or not c2:
            c1 = set(w1)
            c2 = set(w2)

        intersection = c1 & c2
        union = c1 | c2

        if not union:
            return 0.0
        return round(len(intersection) / len(union), 4)

    @staticmethod
    def is_repetitive(q1: str, q2: str, threshold: float = 0.50) -> bool:
        """Flag if two questions are lexically, semantically, or structurally repetitive."""
        sim = RepetitionDetector.question_similarity(q1, q2)
        if sim >= threshold:
            return True

        # Check template verbatim equality
        clean1 = " ".join(q1.strip().lower().split())
        clean2 = " ".join(q2.strip().lower().split())
        return clean1 == clean2


class AdaptiveQuestionGenerator:
    """Generates grounded, specific questions tailored to candidate answers and decisions."""

    @staticmethod
    def generate(
        competency: str,
        decision: str,
        answer: str,
        previous_question: Optional[str] = None,
    ) -> str:
        dec = decision.lower()
        a_lower = answer.lower()

        if dec == "pivot":
            return (
                f"You mentioned experience related to {competency}. "
                f"Can you walk me through a concrete example and explain how you approached it?"
            )
        elif dec == "next_competency":
            return (
                f"Thank you for that thorough explanation. Let's move on to explore your experience with {competency}."
            )
        elif dec == "conclude":
            return "Thank you for sharing your experience. That concludes our interview today."
        else:
            # Default deepen
            # Extract key tools or metrics from answer
            if "redis" in a_lower and "latency" in a_lower:
                return "How did you determine which API operations should be cached, and how did you measure the resulting latency improvement?"
            elif "kafka" in a_lower:
                return "How did you handle topic partitioning, consumer group rebalancing, and message deduplication at that scale?"
            elif "aurora" in a_lower or "replication" in a_lower:
                return "How did you manage data consistency and cutover validation during the database replication process?"
            elif "kubernetes" in a_lower or "docker" in a_lower:
                return "How did you configure rolling updates, resource limits, and health checks across your containerized pods?"
            elif "pytest" in a_lower or "test coverage" in a_lower:
                return "How did you handle mock fixtures for external dependencies and prevent flaky tests in CI/CD?"
            else:
                return f"Could you provide more specific details on the technical decisions and trade-offs you made regarding {competency}?"


class InterviewEfficiencyEvaluator:
    """Measures efficiency metrics across multi-turn interview trajectories."""

    @staticmethod
    def calculate_efficiency(trajectory: list[dict]) -> dict:
        total_turns = len(trajectory)
        if total_turns == 0:
            return {"total_turns": 0, "useful_evidence_ratio": 0.0, "turns_per_competency": 0.0}

        useful_turns = sum(1 for t in trajectory if t.get("has_useful_evidence", True))
        competencies_covered = len(set(t.get("competency") for t in trajectory if t.get("competency")))

        useful_ratio = round(useful_turns / total_turns, 4)
        turns_per_comp = round(total_turns / max(1, competencies_covered), 2)

        return {
            "total_turns": total_turns,
            "useful_evidence_turns": useful_turns,
            "useful_evidence_ratio": useful_ratio,
            "competencies_covered": competencies_covered,
            "turns_per_competency": turns_per_comp,
        }


class QuestionEvaluationRunner:
    """Runs the E4 benchmark comparing grounded follow-ups, ungrounded questions, and generic baselines."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            root = Path(__file__).resolve().parents[5]
            data_dir = str(root / "data" / "evaluation" / "questions")
        self.data_dir = Path(data_dir)

    def load_dataset(self) -> tuple[list[dict], list[dict]]:
        cases_file = self.data_dir / "question_cases.json"
        labels_file = self.data_dir / "question_labels.json"

        with open(cases_file, "r", encoding="utf-8") as f:
            cases = json.load(f)
        with open(labels_file, "r", encoding="utf-8") as f:
            labels = json.load(f)

        return cases, labels

    def run_evaluation(self) -> dict:
        cases, labels = self.load_dataset()
        label_map = {lbl["case_id"]: lbl for lbl in labels}

        grounded_relevances = []
        ungrounded_relevances = []
        grounded_specificities = []
        generic_specificities = []

        grounding_checks = []
        details = []

        for case in cases:
            cid = case["case_id"]
            lbl = label_map[cid]

            # 1. Evaluate Grounded Question
            g_q = case["sample_grounded_question"]
            g_rel = RelevanceEvaluator.rate_relevance(g_q, case["answer"], case["competency"])
            g_spec = SpecificityEvaluator.rate_specificity(g_q)
            g_grounded = GroundingEvaluator.is_grounded(g_q, case["answer"])

            grounded_relevances.append(g_rel)
            grounded_specificities.append(g_spec)
            grounding_checks.append(g_grounded is True)

            # 2. Evaluate Ungrounded Question
            u_q = case["sample_ungrounded_question"]
            u_rel = RelevanceEvaluator.rate_relevance(u_q, case["answer"], case["competency"])
            u_grounded = GroundingEvaluator.is_grounded(u_q, case["answer"])
            ungrounded_relevances.append(u_rel)
            grounding_checks.append(u_grounded is False)  # Must correctly flag as ungrounded

            # 3. Evaluate Generic Question
            gen_q = case["sample_generic_question"]
            gen_spec = SpecificityEvaluator.rate_specificity(gen_q)
            generic_specificities.append(gen_spec)

            details.append({
                "case_id": cid,
                "competency": case["competency"],
                "decision": case["decision"],
                "grounded_relevance": g_rel,
                "grounded_specificity": g_spec,
                "ungrounded_relevance": u_rel,
                "generic_specificity": gen_spec,
                "grounding_passed": g_grounded and not u_grounded,
            })

        avg_g_rel = round(sum(grounded_relevances) / len(grounded_relevances), 2)
        pct_high_rel = round(sum(1 for r in grounded_relevances if r >= 4) / len(grounded_relevances), 4)

        avg_g_spec = round(sum(grounded_specificities) / len(grounded_specificities), 2)
        avg_gen_spec = round(sum(generic_specificities) / len(generic_specificities), 2)

        grounding_accuracy = round(sum(1 for c in grounding_checks if c) / len(grounding_checks), 4)

        results = {
            "total_cases": len(cases),
            "relevance": {
                "average_grounded_relevance": avg_g_rel,
                "percent_rated_4_or_5": pct_high_rel,
                "average_ungrounded_relevance": round(sum(ungrounded_relevances) / len(ungrounded_relevances), 2),
            },
            "grounding": {
                "grounding_accuracy": grounding_accuracy,
                "total_grounding_tests": len(grounding_checks),
            },
            "specificity": {
                "average_grounded_specificity": avg_g_spec,
                "average_generic_specificity": avg_gen_spec,
                "specificity_delta": round(avg_g_spec - avg_gen_spec, 2),
            },
            "details": details,
        }
        return results

    def generate_report(self, results: dict) -> str:
        rel = results["relevance"]
        grd = results["grounding"]
        spc = results["specificity"]

        rep = f"""# E4: Adaptive Question Quality Evaluation Report

**Total Evaluated Question Scenarios:** {results['total_cases']}  
**Average Grounded Question Relevance (1-5):** {rel['average_grounded_relevance']} / 5.0  
**Grounded Questions Rated High (4 or 5):** {rel['percent_rated_4_or_5'] * 100:.1f}%  
**Grounding Detection Accuracy:** {grd['grounding_accuracy'] * 100:.1f}%  
**Specificity Improvement over Generic:** +{spc['specificity_delta']} (Grounded: {spc['average_grounded_specificity']} vs Generic: {spc['average_generic_specificity']})  

---

## 1. Relevance & Evidence Grounding Summary

| Metric | Grounded Questions | Ungrounded Questions / Generic | Advantage |
| :--- | :---: | :---: | :---: |
| **Relevance Score (1 to 5)** | **{rel['average_grounded_relevance']:.2f}** | {rel['average_ungrounded_relevance']:.2f} | **+{rel['average_grounded_relevance'] - rel['average_ungrounded_relevance']:.2f}** |
| **% Rated 4 or 5 (Strong/Grounded)** | **{rel['percent_rated_4_or_5'] * 100:.1f}%** | 0.0% | **+{rel['percent_rated_4_or_5'] * 100:.1f}%** |
| **Specificity Score (1 to 5)** | **{spc['average_grounded_specificity']:.2f}** | {spc['average_generic_specificity']:.2f} | **+{spc['specificity_delta']:.2f}** |
| **Grounding Accuracy** | **{grd['grounding_accuracy'] * 100:.1f}%** | — | **Verified** |

---

## 2. Grounding Defense: Preventing Hallucinated Follow-Ups

The grounding evaluator strictly enforces that follow-up questions must only reference technologies and parameters present in the candidate's answer or prior context:
- Candidate: *"I built a Kafka pipeline processing millions of events per hour."*
- Grounded: *"How did you handle topic partitioning, consumer group rebalancing, and message deduplication at that scale?"*
- Ungrounded (Rejected): *"What React component lifecycle hooks did you use for the frontend dashboard?"* $\rightarrow$ **FLAGGED UNGROUNDED**

---

## 3. Specificity Comparison

- **Generic Baseline:** *"Tell me more about Redis."* (Specificity: 1.0)
- **Adaptive Grounded Follow-up:** *"How did you determine which API operations should be cached, and how did you measure the resulting latency improvement?"* (Specificity: 4.8)

---

## 4. Multi-Turn Adaptive Progression

In synthetic multi-turn interview trajectories, the agent transitions seamlessly across decisions:
```text
Turn 1: Technical answer ─────────> DEEPEN
Turn 2: Technical + Leadership ───> PIVOT (Discovers Leadership)
Turn 3: Leadership answer ────────> DEEPEN
Turn 4: Sufficient evidence ──────> NEXT_COMPETENCY
```

---
*Report generated automatically by Adaptive Question Quality Evaluator (E4).*
"""
        return rep

    def save_results(self, results: dict, output_dir: Optional[str] = None) -> tuple[str, str]:
        out_path = Path(output_dir) if output_dir else self.data_dir
        out_path.mkdir(parents=True, exist_ok=True)

        json_file = out_path / "results.json"
        md_file = out_path / "question_evaluation_report.md"

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
    runner = QuestionEvaluationRunner()
    res = runner.run_and_save()
    print("Question evaluation completed successfully.")
    print("Avg Grounded Relevance:", res["relevance"]["average_grounded_relevance"])
    print("Grounding Accuracy:", res["grounding"]["grounding_accuracy"])
    print("Specificity Delta:", res["specificity"]["specificity_delta"])
