import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stages.stage4_interview.dependencies import registry


from app.core.security import create_access_token
from app.stages.stage4_interview.dependencies import create_interview_controller, registry
from app.stages.stage4_interview.persistence import InterviewPersistence
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM


def test_interview_pipeline_live(monkeypatch, tmp_path):
    registry.sessions.clear()
    import app.api.interview_routes as routes
    test_controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    test_controller.session_manager.persistence = InterviewPersistence(
        output_dir=str(tmp_path / "interviews")
    )
    monkeypatch.setattr(routes, "controller", test_controller)
    monkeypatch.setattr(
        registry,
        "persistence",
        InterviewPersistence(output_dir=str(tmp_path / "interviews")),
        raising=False,
    )
    token = create_access_token(user_id="U_TEST", role="recruiter")
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        start_payload = {
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {
                "name": "Rahul Kumar",
                "email": "rahul@example.com",
            },
            "competencies": [
                "technical_skills",
                "problem_solving",
                "databases",
                "leadership",
            ],
            "first_question": "Tell me about your backend engineering experience.",
        }

        # 1. Start interview
        response = client.post("/interview/start", json=start_payload)
        assert response.status_code == 200, f"Start failed: {response.text}"
        start_data = response.json()

        assert start_data["session_id"] == "SESSION001"
        assert start_data["candidate_id"] == "C001"
        assert start_data["next_question"] == "Tell me about your backend engineering experience."
        assert start_data["interview_complete"] is False
        assert start_data["identity_verified"] is False

        # 2. Submit text answer
        answer_payload = {
            "answer": "I built REST APIs using FastAPI and PostgreSQL. I also optimized several slow SQL queries."
        }

        response = client.post("/interview/SESSION001/answer", json=answer_payload)
        assert response.status_code == 200, f"Answer failed: {response.text}"
        answer_data = response.json()

        assert answer_data["transcript"] == answer_payload["answer"]
        assert answer_data["next_question"] is not None
        assert len(answer_data["next_question"]) > 0
        assert answer_data["decision"] in ["deepen", "pivot", "conclude", "continue"]
        assert len(answer_data["competency_scores"]) > 0
        assert answer_data["interview_score"] > 0.0

        # 3. Check current session status
        get_res = client.get("/interview/SESSION001")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["turn_number"] == 2
