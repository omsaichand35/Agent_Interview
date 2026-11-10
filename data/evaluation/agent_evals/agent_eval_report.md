# Interview Reasoning Agent Evals

**Run:** 2026-11-10T09:39:55.829870+00:00  
**Mode:** `offline_deterministic_no_live_llm`  
**Cases passed:** 13/13 (100.0%)  
**Cases failed:** 0

## Category results

| Category | Passed | Cases | Pass rate |
|---|---:|---:|---:|
| `contradiction` | 2 | 2 | 100.0% |
| `evidence_grounding` | 2 | 2 | 100.0% |
| `irrelevant_answer` | 2 | 2 | 100.0% |
| `missing_metric` | 2 | 2 | 100.0% |
| `normal_answer` | 1 | 1 | 100.0% |
| `prompt_injection` | 2 | 2 | 100.0% |
| `unsupported_claim` | 2 | 2 | 100.0% |

## Case results

| Case | Category | Result | Failed checks |
|---|---|---:|---|
| `AGENT_001` | `unsupported_claim` | PASS | — |
| `AGENT_002` | `contradiction` | PASS | — |
| `AGENT_003` | `irrelevant_answer` | PASS | — |
| `AGENT_004` | `missing_metric` | PASS | — |
| `AGENT_005` | `prompt_injection` | PASS | — |
| `AGENT_006` | `evidence_grounding` | PASS | — |
| `AGENT_007` | `normal_answer` | PASS | — |
| `AGENT_008` | `unsupported_claim` | PASS | — |
| `AGENT_009` | `contradiction` | PASS | — |
| `AGENT_010` | `irrelevant_answer` | PASS | — |
| `AGENT_011` | `missing_metric` | PASS | — |
| `AGENT_012` | `prompt_injection` | PASS | — |
| `AGENT_013` | `evidence_grounding` | PASS | — |

## Production monitoring

The live interview graph records aggregate checks for reasoning contracts, next-question policy, evidence quote grounding, evaluation fallback use, decision trace consistency, and prompt-injection handling. This offline run does not contain production traffic; capture `/metrics` from a running deployment and use `backend/scripts/report_agent_evals.py` for a production snapshot.

## Scope and limitations

This suite runs the repository's deterministic reasoning analyzer and evidence validator against labeled, synthetic scenarios. It does not call a hosted model, assess production latency, or establish that the behavior generalizes to real candidate interviews. Passing scores describe only these cases; expand and independently review the dataset before using results as a deployment gate.

Machine-readable details, including expected and observed checks, are in `results.json`.
