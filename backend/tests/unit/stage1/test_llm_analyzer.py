from app.schemas.resume import LLMResumeAnalysis


def test_llm_resume_analysis_schema():

    data = {
        "candidate_name": "Rahul Kumar",
        "candidate_email": "rahul@example.com",
        "assessments": [
            {
                "competency_id": "technical_skills",
                "competency_name": "Technical Skills",
                "score": 0.9,
                "evidence": [
                    {
                        "quote": "Developed REST APIs using Python and FastAPI.",
                        "relevance": 0.95,
                    }
                ],
                "reasoning": (
                    "The candidate demonstrates direct backend "
                    "development experience using Python and FastAPI."
                ),
            }
        ],
        "strengths": [
            "Python backend development",
            "REST APIs",
        ],
        "gaps": [],
    }

    result = LLMResumeAnalysis.model_validate(data)

    assert result.candidate_name == "Rahul Kumar"
    assert result.assessments[0].score == 0.9