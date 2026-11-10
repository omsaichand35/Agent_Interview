# E3: Competency Detection & Discovery Quality Evaluation Report

**Total Evaluated Cases:** 20  
**Overall Detection F1-Score:** 0.9655  
**Unexpected Discovery F1-Score:** 0.8276  
**False Discovery Rate:** 0.0% (Noise Rejection: 100.0%)  
**Taxonomy Normalization Accuracy:** 100.0%  
**Turn Latency:** 0.22 ms (Same-turn: True)  

---

## 1. Quantitative Performance Summary

| Metric | Precision | Recall | F1-Score | TP / FP / FN |
| :--- | :---: | :---: | :---: | :---: |
| **All Competency Detection** | **0.9655** | **0.9655** | **0.9655** | 28 / 1 / 1 |
| **Unexpected Competency Discovery** | **0.7059** | **1.0000** | **0.8276** | 12 / 5 / 0 |

---

## 2. Unexpected Discovery Capabilities (E3.4)

When a candidate introduces an unexpected competency during an interview (e.g., revealing mentorship during a technical problem solving question):
- Initial Target: `["problem_solving", "technical_skills"]`
- Candidate: *"I optimized our API and mentored two junior developers."*
- State Transition: `discovered_competencies` <- `["leadership"]`
- Adaptive Graph Decision: `pivot` or `deepen` triggered immediately.

---

## 3. False Discovery Prevention (E3.5)

To prevent arbitrary nouns or locations from polluting the competency model:
- Tested Entities: `10` noise instances (e.g. *Bangalore*, *London*, *Jira*, *Confluence*, *Slack*, *Zoom*, *lunch*).
- **False Discovery Rate:** `0.0%`
- **Noise Rejection Rate:** `100.0%`

---

## 4. Competency Normalization (E3.6)

Natural language variations are unified into standard taxonomy keys:
- *"led developers"*, *"mentored engineers"*, *"team leadership"* -> **`leadership`**
- *"Postgres"*, *"relational database"*, *"mysql"* -> **`databases`**
- *"AWS EKS"*, *"container orchestration"*, *"k8s"* -> **`cloud_devops`**
- *"Pytest"*, *"unit testing"*, *"code reviews"* -> **`software_engineering`**

**Normalization Accuracy:** **100.0%** (38 / 38 phrases mapped).

---

## 5. Discovery Latency & Turn Turnaround (E3.8)

- **Execution Latency:** `0.22 ms` per answer turn.
- **Turn Turnaround Delay:** `0 turns` (the graph identifies discovered competencies and triggers `pivot` in the exact same turn cycle).

---
*Report generated automatically by Competency Detection Quality Evaluator (E3).*
