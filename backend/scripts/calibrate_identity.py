import json
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.stages.stage3_identity.face_matcher import SFaceMatcher
from app.stages.stage3_identity.sface_model import SFaceEmbeddingModel
from app.stages.stage3_identity.yunet_detector import YuNetDetector


BASE_DIR = Path(__file__).resolve().parents[2]

VALIDATION_DIR = (
    BASE_DIR
    / "data"
    / "raw"
    / "identity_validation"
)
if not VALIDATION_DIR.exists() and (BACKEND_DIR / "data" / "raw" / "identity_validation").exists():
    VALIDATION_DIR = BACKEND_DIR / "data" / "raw" / "identity_validation"


def load_pairs(directory: Path):
    if not directory.exists():
        return []

    files = sorted(directory.glob("*"))

    pairs = []

    references = {
        path.stem.replace("_reference", ""): path
        for path in files
        if "_reference" in path.stem
    }

    lives = {
        path.stem.replace("_live", ""): path
        for path in files
        if "_live" in path.stem
    }

    for pair_id in sorted(references.keys() & lives.keys()):
        pairs.append(
            (
                pair_id,
                references[pair_id],
                lives[pair_id],
            )
        )

    return pairs


def main():

    detector = YuNetDetector(
        model_path=settings.yunet_model_path,
    )

    embedding_model = SFaceEmbeddingModel(
        model_path=settings.sface_model_path,
    )

    matcher = SFaceMatcher(
        detector=detector,
        embedding_model=embedding_model,
    )

    genuine_pairs = load_pairs(
        VALIDATION_DIR / "genuine"
    )

    impostor_pairs = load_pairs(
        VALIDATION_DIR / "impostor"
    )

    if not genuine_pairs and not impostor_pairs:
        print(f"Notice: No validation pairs found in: {VALIDATION_DIR}")
        print("To run calibration, place pairs in:")
        print(f"  {VALIDATION_DIR / 'genuine'}/*_reference.* and *_live.*")
        print(f"  {VALIDATION_DIR / 'impostor'}/*_reference.* and *_live.*")

    results = {
        "genuine": [],
        "impostor": [],
    }

    for pair_id, reference, live in genuine_pairs:

        score = matcher.match(
            reference_image=str(reference),
            live_image=str(live),
        )

        results["genuine"].append(
            {
                "pair_id": pair_id,
                "score": score,
                "reference": str(reference),
                "live": str(live),
            }
        )

        print(
            f"[GENUINE] {pair_id}: "
            f"{score:.4f}"
        )

    for pair_id, reference, live in impostor_pairs:

        score = matcher.match(
            reference_image=str(reference),
            live_image=str(live),
        )

        results["impostor"].append(
            {
                "pair_id": pair_id,
                "score": score,
                "reference": str(reference),
                "live": str(live),
            }
        )

        print(
            f"[IMPOSTOR] {pair_id}: "
            f"{score:.4f}"
        )

    output_dir = (
        BASE_DIR
        / "data"
        / "processed"
        / "identity"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / "identity_calibration.json"
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            results,
            file,
            indent=2,
        )

    print()
    print(
        f"Saved calibration results to: "
        f"{output_path}"
    )


if __name__ == "__main__":
    main()