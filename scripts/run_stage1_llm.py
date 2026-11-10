from pathlib import Path
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.stages.stage1_resume.stage1_pipeline import Stage1Pipeline


ROOT = Path(__file__).resolve().parents[1]

JD_PATH = (
    ROOT
    / "data"
    / "raw"
    / "job_descriptions"
    / "backend_engineer.txt"
)

RESUME_DIR = (
    ROOT
    / "data"
    / "raw"
    / "resumes"
)

OUTPUT_DIR = (
    ROOT
    / "data"
    / "outputs"
    / "shortlists"
)


def main():

    resume_paths = [
        RESUME_DIR / "test_candidate.txt",
        RESUME_DIR / "test_candidate_002.txt",
        RESUME_DIR / "test_candidate_003.txt",
    ]

    pipeline = Stage1Pipeline()

    result = pipeline.run(
        jd_path=str(JD_PATH),
        resume_paths=[
            str(path)
            for path in resume_paths
        ],
        top_n=3,
    )

    print("\n" + "=" * 70)
    print("STAGE 1 - AI RESUME SHORTLIST")
    print("=" * 70)

    for rank, item in enumerate(
        result["shortlist"],
        start=1,
    ):
        print(
            f"\n#{rank}"
            f" | Candidate: {item.candidate_id}"
            f" | Score: {item.overall_score:.2f}"
        )

        print("-" * 70)

        for assessment in item.competency_scores:

            print(
                f"\n{assessment.competency}: "
                f"{assessment.score:.2f}"
            )

            print(
                f"Reasoning: {assessment.reasoning}"
            )

            if assessment.evidence:
                print("Evidence:")

                for evidence in assessment.evidence:
                    print(
                        f'  - "{evidence.text}"'
                    )

            else:
                print("Evidence: None")

        print("\nStrengths:")
        for strength in item.strengths:
            print(f"  + {strength}")

        print("Gaps:")
        for gap in item.gaps:
            print(f"  - {gap}")

    save_result(result)


def save_result(result):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIR
        / "backend_engineer_shortlist.json"
    )

    output = {
        "job": result["job"].model_dump(
            mode="json"
        ),

        "candidates": [
            {
                "candidate":
                    candidate_result[
                        "candidate"
                    ].model_dump(mode="json"),

                "resume_score":
                    candidate_result[
                        "resume_score"
                    ].model_dump(mode="json"),
            }
            for candidate_result
            in result["candidates"]
        ],

        "shortlist": [
            score.model_dump(mode="json")
            for score in result["shortlist"]
        ],
    }

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            indent=4,
        )

    print("\n" + "=" * 70)

    print(
        f"Results saved to:\n{output_path}"
    )


if __name__ == "__main__":
    main()