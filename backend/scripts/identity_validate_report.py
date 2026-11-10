import json
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]

INPUT_PATH = (
    BASE_DIR
    / "data"
    / "processed"
    / "identity"
    / "identity_calibration.json"
)

OUTPUT_PATH = (
    BASE_DIR
    / "data"
    / "processed"
    / "identity"
    / "identity_validation_report.json"
)


def calculate_metrics(genuine, impostor, threshold):
    false_rejections = sum(
        score < threshold for score in genuine
    )

    false_acceptances = sum(
        score >= threshold for score in impostor
    )

    return {
        "threshold": threshold,
        "genuine_count": len(genuine),
        "impostor_count": len(impostor),
        "false_rejections": false_rejections,
        "false_acceptances": false_acceptances,
        "false_rejection_rate": (
            false_rejections / len(genuine)
        ),
        "false_acceptance_rate": (
            false_acceptances / len(impostor)
        ),
    }


def main():
    with INPUT_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    genuine = [
        float(item["score"])
        for item in data["genuine"]
    ]

    impostor = [
        float(item["score"])
        for item in data["impostor"]
    ]

    if not genuine or not impostor:
        raise ValueError(
            "Both genuine and impostor pairs are required."
        )

    thresholds = [
        round(value / 100, 2)
        for value in range(40, 91, 5)
    ]

    results = [
        calculate_metrics(genuine, impostor, threshold)
        for threshold in thresholds
    ]

    report = {
        "model": "YuNet + SFace",
        "score_type": "raw_cosine_similarity",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "genuine_pairs": len(genuine),
            "impostor_pairs": len(impostor),
        },
        "observed_scores": {
            "genuine_min": min(genuine),
            "genuine_max": max(genuine),
            "impostor_min": min(impostor),
            "impostor_max": max(impostor),
        },
        "threshold_results": results,
        "deployment_ready": False,
        "limitations": [
            "Small validation dataset.",
            "Results may not represent actual interview conditions.",
            "Threshold requires independent validation.",
            "Presentation attacks and spoofing were not evaluated.",
        ],
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print(f"Report saved: {OUTPUT_PATH}")

    print()
    print("Threshold | FAR | FRR")

    for result in results:
        print(
            f"{result['threshold']:.2f} | "
            f"{result['false_acceptance_rate']:.2%} | "
            f"{result['false_rejection_rate']:.2%}"
        )


if __name__ == "__main__":
    main()