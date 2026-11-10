from pathlib import Path

import cv2
import numpy as np


class SFaceEmbeddingModel:
    """
    OpenCV SFace embedding backend.

    Uses FaceRecognizerSF to align a detected face and
    generate its feature embedding.
    """

    def __init__(self, model_path: str):
        from app.core.paths import resolve_path
        model = resolve_path(model_path)

        if not model.exists():
            candidate = Path(__file__).resolve().parents[3] / "models" / "face" / Path(model_path).name
            if candidate.exists():
                model = candidate
            else:
                candidate_root = Path(__file__).resolve().parents[4] / "models" / "face" / Path(model_path).name
                if candidate_root.exists():
                    model = candidate_root
                else:
                    raise FileNotFoundError(
                        f"SFace model not found: {model_path}"
                    )

        self.recognizer = cv2.FaceRecognizerSF.create(
            str(model),
            "",
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )

    def embed(self, image, face):
        """
        Generate an SFace embedding.

        `face` must contain the YuNet detection result,
        including the five facial landmarks.
        """

        aligned = self.recognizer.alignCrop(
            image,
            face,
        )

        feature = self.recognizer.feature(
            aligned,
        )

        feature = np.asarray(
            feature,
            dtype=np.float32,
        )

        return feature.flatten()