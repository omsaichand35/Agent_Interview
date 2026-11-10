from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(
    0,
    str(BACKEND_DIR)
)


from app.stages.stage1_resume.stage1_pipeline import (
    Stage1Pipeline,
)


CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "competencies.yaml"
)

JD_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "job_descriptions"
    / "backend_engineer.txt"
)

RESUMES = [
    {
        "candidate_id": "C001",
        "resume_path": str(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "resumes"
            / "test_candidate.txt"
        ),
    },
    {
        "candidate_id": "C002",
        "resume_path": str(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "resumes"
            / "test_candidate_002.txt"
        ),
    },
    {
        "candidate_id": "C003",
        "resume_path": str(
            PROJECT_ROOT
            / "data"
            / "raw"
            / "resumes"
            / "test_candidate_003.txt"
        ),
    },
]


def main():

    pipeline = Stage1Pipeline(
        competency_config=str(
            CONFIG_PATH
        )
    )

    result = pipeline.run(
        job_id="JOB001",
        jd_path=str(JD_PATH),
        candidates=RESUMES,
        shortlist_size=2,
    )

    job = result["job"]

    print("\n")
    print("=" * 60)
    print("           AI HIRING PIPELINE")
    print("              STAGE 1")
    print("=" * 60)

    print(f"\nJob: {job.title}")

    print("\nCompetencies:")

    for competency in job.competencies:
        print(
            f"  - {competency.name}"
        )

    print("\nCandidate Scores:")

    for candidate_result in result[
        "candidates"
    ]:

        candidate = (
            candidate_result["candidate"]
        )

        score = (
            candidate_result["resume_score"]
        )

        print(
            f"\n{candidate.candidate_id}"
            f" | {candidate.name}"
            f" | {score.overall_score:.2f}"
        )

    print("\n")
    print("=" * 60)
    print("              SHORTLIST")
    print("=" * 60)

    for index, candidate in enumerate(
        result["shortlist"],
        start=1,
    ):

        print(
            f"{index}. "
            f"{candidate.candidate_id} "
            f"-> "
            f"{candidate.overall_score:.2f}"
        )

    print("\n")


if __name__ == "__main__":
    main()