import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_workflow_default_job(client):
    response = client.get("/workflow/JOB001")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "JOB001"
    assert "status" in data
    assert "candidate_ids" in data
    assert "shortlist" in data
    assert "current_candidate_id" in data


def test_list_workflows(client):
    response = client.get("/workflow")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(job["job_id"] == "JOB001" for job in data)


def test_get_workflow_not_found(client):
    response = client.get("/workflow/NON_EXISTENT_JOB_999")
    assert response.status_code == 404
    assert "Workflow not found" in response.json()["detail"]


def test_create_and_start_workflow_job(client):
    job_payload = {
        "job_id": "JOB_TEST_200",
        "job_title": "AI Research Engineer",
        "department": "AI Lab",
        "candidates": [
            {"candidate_id": "C_TEST_1", "name": "Elena Rostova", "resume_score": 88.0},
            {"candidate_id": "C_TEST_2", "name": "Marcus Vance", "resume_score": 52.0},
        ],
    }

    create_res = client.post("/workflow/create", json=job_payload)
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["job_id"] == "JOB_TEST_200"
    assert created["status"] == "SHORTLISTED"
    assert len(created["shortlist"]) == 1

    # Start pipeline
    start_res = client.post("/workflow/JOB_TEST_200/start")
    assert start_res.status_code == 200
    started = start_res.json()
    assert started["status"] == "INTERVIEW_IN_PROGRESS"

    # Fetch to verify persistence
    get_res = client.get("/workflow/JOB_TEST_200")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "INTERVIEW_IN_PROGRESS"
