# E2: Evidence Extraction Quality Evaluation Report

**Total Evaluated Evidence Cases:** 37  
**Overall Accuracy:** 97.3%  
**Macro F1-Score:** 0.9752  
**Hallucination Catch Rate:** 100.0%  
**Adversarial Passive Detection Accuracy:** 100.0%  

---

## 1. Classification Performance by Category

| Evidence Category | Precision | Recall | F1-Score | Support |
| :--- | :---: | :---: | :---: | :---: |
| **SUPPORTED** | 1.0000 | 1.0000 | **1.0000** | 10 |
| **WEAKLY_SUPPORTED** | 1.0000 | 0.9333 | **0.9655** | 15 |
| **UNSUPPORTED** | 0.9231 | 1.0000 | **0.9600** | 12 |
| **MACRO AVERAGE** | — | — | **0.9752** | 37 |

---

## 2. Hallucination Detection & Verification Integrity

- **Hallucinated Evidence Rate:** `10.8%`
- **Total Injected Hallucinations:** 4
- **Hallucinations Caught & Rejected:** 4 / 4 (100.0%)

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

**Result:** The evaluator successfully distinguished active technical ownership (`Architected`, `Designed`, `Built`) from passive observation or intent, correctly penalizing 6 / 6 adversarial cases (100.0% accuracy).

---

## 4. Verification Chain: Evidence ➔ Competency Score Contract

When evidence fails validation or is unsupported:
1. `is_valid` is set to `False`.
2. Evidence list is pruned.
3. The competency score is capped at `0.20`.
4. High scores require concrete specificity (`> 0.80`) and active ownership directness (`> 0.80`).

---
*Report generated automatically by Evidence Extraction Quality Evaluator (E2).*
