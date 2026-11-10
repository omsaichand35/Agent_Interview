import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]

RESULT_PATH = (
    BASE_DIR
    / "data"
    / "processed"
    / "identity"
    / "identity_calibration.json"
)


def main():

    with RESULT_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        results = json.load(file)

    genuine = [
        item["score"]
        for item in results["genuine"]
    ]

    impostor = [
        item["score"]
        for item in results["impostor"]
    ]

    if not genuine or not impostor:
        raise ValueError(
            "Need both genuine and impostor samples."
        )

    print("Genuine scores:")
    print(
        "  min:",
        f"{min(genuine):.4f}",
    )
    print(
        "  max:",
        f"{max(genuine):.4f}",
    )
    print(
        "  average:",
        f"{sum(genuine) / len(genuine):.4f}",
    )

    print()

    print("Impostor scores:")
    print(
        "  min:",
        f"{min(impostor):.4f}",
    )
    print(
        "  max:",
        f"{max(impostor):.4f}",
    )
    print(
        "  average:",
        f"{sum(impostor) / len(impostor):.4f}",
    )

    print()
    print("Threshold analysis")

    for threshold in [
        0.50,
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        0.85,
        0.90,
    ]:

        false_rejections = sum(
            score < threshold
            for score in genuine
        )

        false_acceptances = sum(
            score >= threshold
            for score in impostor
        )

        print(
            f"{threshold:.2f} | "
            f"false_rejections="
            f"{false_rejections}/{len(genuine)} | "
            f"false_acceptances="
            f"{false_acceptances}/{len(impostor)}"
        )


if __name__ == "__main__":
    main()