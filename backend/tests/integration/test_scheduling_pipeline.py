import json
from pathlib import Path

from app.stages.stage1_resume.stage1_pipeline import (
    Stage1Pipeline,
)

from app.stages.stage2_scheduling.scheduling_service import (
    SchedulingService,
)


def test_scheduling_pipeline(tmp_path):

    root = Path(__file__).resolve().parents[3]

    jd_path = (
        root
        / "data"
        / "raw"
        / "job_descriptions"
        / "backend_engineer.txt"
    )

    resume_dir = (
        root
        / "data"
        / "raw"
        / "resumes"
    )

    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"slots": [
        {
            "slot_id": f"test-slot-{index}",
            "start_time": f"2026-10-01T{9 + index:02d}:00:00",
            "end_time": f"2026-10-01T{9 + index:02d}:30:00",
            "available": True,
        }
        for index in range(3)
    ]}), encoding="utf-8")

    confirmation_dir = (
        root
        / "data"
        / "outputs"
        / "confirmations"
    )

    stage1 = Stage1Pipeline()

    result = stage1.run(
        jd_path=str(jd_path),
        resume_paths=[
            str(
                resume_dir
                / "test_candidate.txt"
            ),
            str(
                resume_dir
                / "test_candidate_002.txt"
            ),
            str(
                resume_dir
                / "test_candidate_003.txt"
            ),
        ],
        top_n=3,
    )

    shortlist = result["shortlist"]

    scheduling = SchedulingService(calendar_path=str(calendar_path))

    result = scheduling.schedule_candidates(
        shortlist=shortlist,
        calendar_path=str(calendar_path),
        confirmation_dir=str(
            confirmation_dir
        ),
    )

    schedules = result["schedules"]

    assert len(schedules) == 3

    slot_ids = [
        schedule.slot_id
        for schedule in schedules
    ]

    assert len(slot_ids) == len(set(slot_ids))

    assert all(
        schedule.status == "scheduled"
        for schedule in schedules
    )

    assert len(
        result["confirmations"]
    ) == 3
