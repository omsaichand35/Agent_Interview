import pytest

from app.llm.provider import get_llm_client

pytestmark = pytest.mark.live_llm
pytestmark = pytest.mark.live_llm


def test_nvidia_connection():

    client = get_llm_client()

    response = client.generate_structured(
        prompt="""
Return this JSON exactly:

{
    "candidate_name": "Test Candidate",
    "candidate_email": "test@example.com",
    "assessments": [],
    "strengths": [],
    "gaps": []
}
""",
        response_model=__import__(
            "app.schemas.resume",
            fromlist=["LLMResumeAnalysis"],
        ).LLMResumeAnalysis,
    )

    assert response.candidate_name == "Test Candidate"
