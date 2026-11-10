import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.stages.stage3_identity.face_matcher import (
    SFaceMatcher,
)
from app.stages.stage3_identity.sface_model import (
    SFaceEmbeddingModel,
)
from app.stages.stage3_identity.yunet_detector import (
    YuNetDetector,
)


def main():

    detector = YuNetDetector(
        settings.yunet_model_path
    )

    embedding_model = SFaceEmbeddingModel(
        settings.sface_model_path
    )

    matcher = SFaceMatcher(
        detector=detector,
        embedding_model=embedding_model,
    )

    reference = input(
        "Reference image path: "
    ).strip().strip("\"'")

    live = input(
        "Live image path: "
    ).strip().strip("\"'")

    similarity = matcher.match(
        reference_image=reference,
        live_image=live,
    )

    print()
    print("SFace similarity:", similarity)


if __name__ == "__main__":
    main()
