import json
from pathlib import Path
from app.stages.stage4_interview.persistence import InterviewPersistence


def test_interview_persistence_save_state(tmp_path: Path):
    output_dir = tmp_path / "interviews"
    persistence = InterviewPersistence(output_dir=str(output_dir))

    sample_state = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_count": 3,
        "interview_complete": False,
        "identity_verified": True,
        "competency_scores": {"Python": 0.85},
    }

    saved_path_str = persistence.save_state(sample_state)
    saved_path = Path(saved_path_str)

    assert saved_path.exists()
    assert saved_path.name == "SESSION001.json"

    with saved_path.open("r", encoding="utf-8") as f:
        loaded_data = json.load(f)

    assert loaded_data == sample_state
