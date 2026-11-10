# Higher Studies Interview Admissions Prototype

This repository contains a FastAPI interview workflow adapted for higher-studies admissions. Departments publish programs and criteria, students apply with a resume and consented face reference, and the project scores resume evidence against the selected program before an identity-gated interview.

## Local pages

The public homepage at `/` includes a scripted product preview; student and admissions-team authentication remains available at `/student/signin` and `/recruiter/signin`.

From the repository root, install the backend requirements into the included local virtual environment (or your own environment):

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

For a new local recruiter account, provision it from the repository root; the script prompts for a password without echoing or printing it:

```powershell
.\.venv\Scripts\python.exe scripts\create_recruiter.py --email recruiter@company.com
```

The script defaults only the email and rejects passwords shorter than 12 characters. Public `/auth/register` is candidate-only; recruiter/admin roles and candidate IDs cannot be self-assigned.

- Portal home (the two entry points): http://localhost:8000/
- Recruiter workspace: http://localhost:8000/recruiter
- Student portal: http://localhost:8000/student
- API docs: http://localhost:8000/docs

Candidate sign-up/sign-in is available on the student portal. Recruiter access requires an existing recruiter/admin account; create one locally with `scripts\create_recruiter.py`. The application does not ship demo credentials.

## Batch interview scheduling

Recruiters can select a program and either the top-scoring applicants or everyone above a resume-score threshold, then set the first start time, slot duration, number of slots, and people per slot. The service assigns applicants in score order, saves the batch roster, issues/reissues interview codes where needed, and emails each student their slot. The recruiter also receives the complete roster as a CSV email attachment; it is available in the portal and can be downloaded again. Students see a flip-style countdown in the student portal; the join button appears at the slot start, and the interview API also rejects early joins. The running backend checks for due reminders every 30 seconds and sends the 10-minute reminder once per scheduled interview.

Configure SMTP to enable invitation and reminder delivery. Set `SMTP_HOST`, `SMTP_FROM_EMAIL`, optional SMTP credentials/TLS settings, and `PUBLIC_BASE_URL` in `backend/.env`. Keep the backend running for reminders to be sent.

The focused sample suite exercises a five-student schedule with two people per slot and a 101-applicant batch filling 10 slots of 10 seats, plus score-threshold capacity handling, student code redemption, early-join rejection, one-time reminders, recruiter roster email/CSV contents, SMTP chunking, and role restrictions:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_interview_scheduling.py backend\tests\unit\stage2\test_calendar_loader.py backend\tests\unit\stage2\test_slot_manager.py backend\tests\unit\stage2\test_scheduler.py backend\tests\unit\stage2\test_scheduling_service_standardized.py backend\tests\security\test_api_security.py::test_unauthenticated_access_returns_401 backend\tests\security\test_api_security.py::test_wrong_role_returns_403 -q
```

## Email notifications

The app uses email and password for sign-in. Public registration creates candidate accounts only; recruiter and admin roles must be provisioned by an administrator.

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, and the optional SMTP credentials/TLS settings in `backend/.env` to enable transactional email. The app sends a welcome message for new accounts, an application receipt after submission, and an interview invitation containing the one-time code when a recruiter issues it. Email is skipped when SMTP is not configured; delivery failures are logged and do not block application or interview workflows.

The app does not seed candidate or job records at startup. A fresh database has no open opportunities until a recruiter creates one. Existing local application and interview history is retained; a job with history is closed instead of deleting its records. New opportunities are assigned to the recruiter who creates them. Legacy unassigned opportunities must be claimed; their applications then belong to that recruiter workspace. Recruiters see only applications for programs assigned to them (admins can review all programs). Students apply from a candidate account; each application is linked to that account and one program, and duplicate applications to the same program are rejected. Resume files are stored under an application-specific name so uploading the same filename again cannot replace an earlier application. Recruiters review program-specific scores and evidence, then issue a one-time interview code. The applying student redeems it in the student portal before starting the identity-checked interview. The browser uses one active role session; sign out before switching between candidate and recruiter accounts. Existing local output files are retained across code changes; remove them only when intentionally resetting local history.

## Architecture and privacy

See [the complete application flow, API, scoring limits, privacy controls and production follow-ups](docs/architecture/higher_studies_application_flow.md). When the configured NVIDIA LLM is available, resume compatibility uses its criterion-by-criterion analysis and only accepts evidence quotes present in the resume. If unavailable, the recorded method says `keyword_evidence` and the system uses the transparent lexical fallback. Scores support human review only. Face references are private local files, but this prototype does not yet enforce a purge schedule or provide production-grade liveness verification. Do not enroll real applicants until retention, deletion, encryption, consent and manual review processes are implemented for the institution.

## Existing project documentation

- [System architecture](docs/architecture/system_architecture.md)
- [Interview agent](docs/architecture/interview_agent.md)
- [Security access matrix](docs/security/access_matrix.md)
- [Candidate data inventory](docs/security/data_inventory.md)

## Interview agent evaluations

The suite has two layers. Run the labeled offline regression suite before release:

```powershell
.\.venv\Scripts\python.exe backend\scripts\run_agent_evals.py
```

The labeled scenarios cover prompt injection, unsupported claims, contradictions, irrelevant answers, missing metrics, and resume evidence grounding. GitHub Actions runs this suite on pull requests and pushes that affect the interview agent or eval data. The suite is deterministic and does not require API credentials.

During real interviews, the LangGraph turn recorder also runs privacy-preserving checks on the actual agent outputs: reasoning schema/range, next-question policy, direct evidence-quote grounding, evaluator fallback use, decision trace consistency, and prompt-injection handling when detected. Aggregated counters are available from the existing `/metrics` endpoint; candidate answers, prompts, evidence quotes, and candidate IDs are not stored by this monitor. The checks observe behavior without changing the interview outcome.

To create a production snapshot report from a running instance (or from a saved `/metrics` JSON file):

```powershell
.\.venv\Scripts\python.exe backend\scripts\report_agent_evals.py --url http://localhost:8000/metrics
.\.venv\Scripts\python.exe backend\scripts\report_agent_evals.py --metrics-file .\metrics-snapshot.json
```

Production counters are per process and reset when a worker restarts. Scrape each worker and aggregate them in your metrics backend for durable multi-worker monitoring. A report with no observations is labeled insufficient data. See the [offline regression report](data/evaluation/agent_evals/agent_eval_report.md).
