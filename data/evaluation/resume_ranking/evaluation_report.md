# E1: Resume Ranking Quality Evaluation Report

**Job ID:** `JOB001`  
**Candidate Count:** 30  
**Human Reference Relevant Candidates:** 10  
**Evaluation Cutoff (K):** 10

---

## 1. Executive Summary

This experiment compares a standard **Keyword Matching Baseline** against our **Semantic Competency + Evidence-Reasoning AI System**.

- **Precision@10**: AI achieved **100.0%** vs Baseline **90.0%** (Δ +0.10).
- **Recall@10**: AI retrieved **100.0%** of suitable candidates vs Baseline **90.0%** (Δ +0.10).
- **NDCG@10**: AI ranking achieved **0.9875** vs Baseline **0.8938** (Δ +0.0937).
- **Evidence Validity**: AI maintains **99.0%** verifiable evidence grounding, catching 2 unsupported or fabricated claims.

---

## 2. Quantitative Comparison Table

| Metric | Baseline (Keyword Matching) | AI System (Semantic + Evidence) | Delta / Improvement |
| :--- | :---: | :---: | :---: |
| **Precision@10** | 0.90 | **1.00** | **+0.10** |
| **Recall@10** | 0.90 | **1.00** | **+0.10** |
| **NDCG@10** | 0.8938 | **0.9875** | **+0.0937** |
| **Spearman Correlation (ρ)** | 0.8114 | **0.9502** | **+0.1388** |
| **Kendall Tau (τ)** | 0.7532 | **0.8535** | **+0.1003** |
| **Evidence Validity Rate** | 0.00 | **0.99** | **+0.99** |

---

## 3. Shortlist Comparison

- **Baseline Top 10 Shortlist:** `C001, C029, C005, C003, C002, C010, C004, C009, C007, C008`
- **AI System Top 10 Shortlist:** `C003, C001, C007, C002, C008, C004, C010, C005, C006, C009`

---

## 4. Unsupported Claims & Hallucination Resistance

The AI system features the `EvidenceValidator` pipeline:
```text
LLM / Extracted Evidence Quote ──> EvidenceValidator ──> Directly Supported?
                                                             ├── YES: keep score & evidence
                                                             └── NO:  cap score at 0.2 & reject
```

**Detected & Filtered Unsupported Claims:** 2

- **Candidate C029**: Claim `"Led a team of 10 engineers."` -> **REJECTED** (Direct evidence quote not found in candidate resume text).
- **Candidate C030**: Claim `"Architected petabyte scale distributed streaming platform with 99.999% availability."` -> **REJECTED** (Direct evidence quote not found in candidate resume text).

---
*Report generated automatically by Stage 1 Resume Ranking Quality Evaluator (E1).*
