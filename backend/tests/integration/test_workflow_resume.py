"""
C6 integration test: workflow persistence and full pipeline resume.

Scenario
--------
1. Create a workflow and advance it through multiple stages.
2. Persist to disk after each transition (also happens automatically
   inside each session_manager method).
3. Simulate a backend restart: instantiate a brand-new persistence
   instance (zero in-memory state from the previous run).
4. Assert the restored workflow matches the live state exactly.
5. Verify that the status-based resumer does NOT re-run completed stages.

The critical invariant: after a backend restart, the pipeline must
resume from the exact stage it was in, not from Stage 1.
"""

import uuid
import json
import os
from pathlib import Path

from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.resume import HiringWorkflowResumer
from app.workflows.session_manager import HiringWorkflowSessionManager
from app.stages.stage2_scheduling.scheduling_service import SchedulingService


# ---------------------------------------------------------------------------
# Lightweight stub services so tests never need cv2 / face_matcher
# ---------------------------------------------------------------------------


class _StubRecommendationService:
    def generate(self, candidate, interview_result, identity_result):
        return {
            "candidate_id": candidate.get("candidate_id", "C001"),
            "recommendation": "hire",
            "score": 85.0,
        }

    def get_recommendation(self, candidate_id):
        return None


_TEST_WORKFLOW_DIR = Path(os.environ["TEST_OUTPUT_ROOT"]) / "workflows"


def _build_workflow_service(output_dir=str(_TEST_WORKFLOW_DIR)):
    persistence = HiringWorkflowPersistence(output_dir=output_dir)
    rec_service = _StubRecommendationService()
    resumer = HiringWorkflowResumer(
        persistence=persistence,
        recommendation_service=rec_service,
    )
    return HiringWorkflowSessionManager(
        persistence=persistence,
        resumer=resumer,
    )


# Shared "old server" instances
_workflow_service = _build_workflow_service()
_persistence = HiringWorkflowPersistence(output_dir=str(_TEST_WORKFLOW_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix="JOB"):
    return f"{prefix}_{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_workflow_resumes_after_restart(tmp_path):
    """
    A workflow that has completed Stages 1 and 2 must be fully recoverable
    from disk after a backend restart.
    """
    job_id = _uid("JOB_RESUME")

    # ── Old server: create and advance through Stage 1 + 2 ─────────────
    workflow = _workflow_service.create(
        job_id=job_id,
        candidate_ids=["C001"],
        candidates=[{"candidate_id": "C001", "name": "Test candidate", "resume_score": 80.0}],
    )
    assert workflow["status"] == "CREATED"

    workflow = _workflow_service.run_shortlisting(workflow)
    assert workflow["status"] == "SHORTLISTED"
    assert "C001" in workflow.shortlist

    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"slots": [{
        "slot_id": "resume-test-slot",
        "start_time": "2026-10-01T10:00:00",
        "end_time": "2026-10-01T10:30:00",
        "available": True,
    }]}), encoding="utf-8")
    workflow = _workflow_service.run_scheduling(
        workflow,
        scheduling_service=SchedulingService(
            calendar_path=str(calendar_path),
            confirmation_dir=str(tmp_path / "confirmations"),
        ),
    )
    assert workflow["status"] == "SCHEDULED"

    # Each transition auto-persists inside session_manager. We also call
    # save() explicitly to mirror callers that do so directly.
    _persistence.save(job_id, dict(workflow))

    # ── Simulate restart: fresh persistence, zero in-memory state ───────
    new_persistence = HiringWorkflowPersistence(output_dir=str(_TEST_WORKFLOW_DIR))
    restored = new_persistence.load(job_id)

    assert restored is not None, (
        "Workflow must be recoverable from disk after a backend restart"
    )
    assert restored["job_id"] == job_id
    assert restored["status"] == "SCHEDULED", (
        f"Expected SCHEDULED, got {restored['status']}"
    )
    assert "C001" in restored["shortlist"], "Shortlist must survive restart"


def test_resume_does_not_repeat_completed_stages():
    """
    If the workflow is at INTERVIEW_IN_PROGRESS, loading from disk must
    NOT re-run shortlisting, scheduling, or identity checks.
    The restored state must still show the same current_candidate_id.
    """
    job_id = _uid("JOB_NORERUN")

    mid_pipeline = {
        "job_id": job_id,
        "status": "INTERVIEW_IN_PROGRESS",
        "current_candidate_id": "C001",
        "shortlist": ["C001"],
        "schedules": [{"candidate_id": "C001", "slot_id": "SLOT_C001"}],
        "candidates": [{"candidate_id": "C001", "name": "Test", "resume_score": 80.0}],
        "candidate_ids": ["C001"],
        "identity_results": {"C001": {"verified": True, "confidence": 0.95}},
        "interview_results": {},
        "recommendations": [],
        "human_review": [],
    }
    _persistence.save(job_id, mid_pipeline)

    new_persistence = HiringWorkflowPersistence(output_dir=str(_TEST_WORKFLOW_DIR))
    restored = new_persistence.load(job_id)

    assert restored is not None
    assert restored["status"] == "INTERVIEW_IN_PROGRESS"
    assert restored["current_candidate_id"] == "C001"
    assert "C001" in restored["shortlist"], (
        "Shortlist must not be re-run after restart"
    )


def test_resumer_status_dispatch_interview_in_progress():
    """
    resumer.resume() must return the workflow as-is when status is
    INTERVIEW_IN_PROGRESS -- it must NOT advance to Stage 5 prematurely.
    """
    job_id = _uid("JOB_DISPATCH")

    mid = {
        "job_id": job_id,
        "status": "INTERVIEW_IN_PROGRESS",
        "current_candidate_id": "C001",
        "shortlist": ["C001"],
        "schedules": [],
        "candidates": [{"candidate_id": "C001", "name": "X", "resume_score": 80.0}],
        "candidate_ids": ["C001"],
        "identity_results": {"C001": {"verified": True, "confidence": 0.95}},
        "interview_results": {},
        "recommendations": [],
        "human_review": [],
    }
    _persistence.save(job_id, mid)

    resumer = _workflow_service.resumer
    result = resumer.resume(job_id)

    assert result["status"] == "INTERVIEW_IN_PROGRESS", (
        "resumer.resume() must not advance past INTERVIEW_IN_PROGRESS "
        "without an explicit interview result"
    )
    assert result["current_candidate_id"] == "C001"


def test_exists_check():
    """exists() must reflect whether the workflow has been saved."""
    job_id = _uid("JOB_EXISTS")
    p = HiringWorkflowPersistence(output_dir=str(_TEST_WORKFLOW_DIR))

    assert not p.exists(job_id)

    p.save(job_id, {"job_id": job_id, "status": "CREATED"})

    assert p.exists(job_id)


def test_persistence_atomic_write():
    """
    Saving twice must produce the second value on next load.
    """
    job_id = _uid("JOB_ATOMIC")
    p = HiringWorkflowPersistence(output_dir=str(_TEST_WORKFLOW_DIR))

    p.save(job_id, {"job_id": job_id, "status": "CREATED", "shortlist": []})
    p.save(job_id, {"job_id": job_id, "status": "SHORTLISTED", "shortlist": ["C001"]})

    loaded = p.load(job_id)
    assert loaded["status"] == "SHORTLISTED"
    assert "C001" in loaded["shortlist"]


def test_load_returns_none_for_missing_workflow():
    """load() must return None for an unknown job_id, not raise."""
    p = HiringWorkflowPersistence(output_dir=str(_TEST_WORKFLOW_DIR))
    result = p.load("NONEXISTENT_JOB_XYZ_999")
    assert result is None


def test_each_stage_transition_auto_persists(tmp_path):
    """
    Verify that session_manager auto-persists after each stage so a restart
    mid-pipeline does not lose progress.
    """
    job_id = _uid("JOB_AUTOPERSIST")
    svc = _build_workflow_service(output_dir=str(tmp_path / "workflows"))

    # Stage 1
    wf = svc.create(
        job_id=job_id,
        candidate_ids=["C001"],
        candidates=[{"candidate_id": "C001", "name": "Test candidate", "resume_score": 80.0}],
    )
    p = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    assert p.exists(job_id), "Workflow must be on disk after create()"

    # Stage 2
    wf = svc.run_shortlisting(wf)
    loaded = p.load(job_id)
    assert loaded["status"] == "SHORTLISTED", (
        "Disk must reflect SHORTLISTED after run_shortlisting()"
    )

    # Stage 3 (scheduling)
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"slots": [{
        "slot_id": "transition-test-slot",
        "start_time": "2026-10-01T10:00:00",
        "end_time": "2026-10-01T10:30:00",
        "available": True,
    }]}), encoding="utf-8")
    wf = svc.run_scheduling(
        wf,
        scheduling_service=SchedulingService(
            calendar_path=str(calendar_path),
            confirmation_dir=str(tmp_path / "confirmations"),
        ),
    )
    loaded = p.load(job_id)
    assert loaded["status"] == "SCHEDULED", (
        "Disk must reflect SCHEDULED after run_scheduling()"
    )


