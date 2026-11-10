from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np


class FaceMatcher(ABC):
    """Interface for comparing a reference face with a live face."""

    @abstractmethod
    def match(
        self,
        reference_image: str,
        live_image: str,
    ) -> float:
        """
        Return a similarity score in the range [0, 1].
        """
        raise NotImplementedError

    def compare(
        self,
        reference_path: str,
        live_path: str,
        reference_face=None,
        live_face=None,
    ) -> float:
        """
        Compare interface compatible with IdentityChecker.
        """
        return self.match(
            reference_image=reference_path,
            live_image=live_path,
        )


class HistogramFaceMatcher(FaceMatcher):
    """
    Prototype face matcher.

    This keeps the existing histogram-based implementation behind
    the FaceMatcher interface so the rest of the pipeline does not
    depend on the matching algorithm.
    """

    def __init__(self, detector):
        self.detector = detector

    def match(
        self,
        reference_image: str,
        live_image: str,
    ) -> float:

        reference_face = self._extract_face(reference_image)
        live_face = self._extract_face(live_image)

        reference_hist = self._histogram(reference_face)
        live_hist = self._histogram(live_face)

        similarity = cv2.compareHist(
            reference_hist,
            live_hist,
            cv2.HISTCMP_CORREL,
        )

        # Correlation can be [-1, 1].
        # Normalize to [0, 1].
        similarity = (similarity + 1.0) / 2.0

        return float(np.clip(similarity, 0.0, 1.0))

    def _extract_face(self, image_path) -> np.ndarray:
        if isinstance(image_path, np.ndarray):
            image = image_path
        else:
            path = Path(image_path)
            if not path.exists():
                raise FileNotFoundError(
                    f"Image not found: {image_path}"
                )

            image = cv2.imread(str(path))

            if image is None:
                raise ValueError(
                    f"Unable to read image: {image_path}"
                )

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        faces = self.detector.detect(image_path)

        if len(faces) != 1:
            raise ValueError(
                "Expected exactly one face for matching."
            )

        x, y, w, h = faces[0]

        face = gray[y:y + h, x:x + w]

        if face.size == 0:
            raise ValueError(
                "Detected face region is empty."
            )

        return cv2.resize(
            face,
            (128, 128),
            interpolation=cv2.INTER_AREA,
        )

    @staticmethod
    def _histogram(face: np.ndarray) -> np.ndarray:
        histogram = cv2.calcHist(
            [face],
            [0],
            None,
            [256],
            [0, 256],
        )

        cv2.normalize(
            histogram,
            histogram,
            alpha=0,
            beta=1,
            norm_type=cv2.NORM_MINMAX,
        )

        return histogram

class EmbeddingFaceMatcher(FaceMatcher):

    def __init__(self, detector, embedding_model):
        self.detector = detector
        self.embedding_model = embedding_model

    def match(
        self,
        reference_image,
        live_image,
    ) -> float:
        reference_faces = self.detector.detect(
            reference_image
        )

        live_faces = self.detector.detect(
            live_image
        )

        if len(reference_faces) != 1:
            raise ValueError(
                "Reference image must contain exactly one face."
            )

        if len(live_faces) != 1:
            raise ValueError(
                "Live image must contain exactly one face."
            )

        if isinstance(reference_image, np.ndarray):
            reference_image_data = reference_image
        else:
            ref_path = str(reference_image).strip().strip("\"'")
            reference_image_data = cv2.imread(ref_path)

        if isinstance(live_image, np.ndarray):
            live_image_data = live_image
        else:
            live_path = str(live_image).strip().strip("\"'")
            live_image_data = cv2.imread(live_path)

        reference_embedding = (
            self.embedding_model.embed(
                reference_image_data,
                reference_faces[0],
            )
        )

        live_embedding = (
            self.embedding_model.embed(
                live_image_data,
                live_faces[0],
            )
        )

        sim = self._cosine_similarity(
            reference_embedding,
            live_embedding,
        )

        # If already a clear match or clear mismatch, return directly
        if sim >= 0.75 or sim < 0.35:
            return sim

        # -------------------------------------------------------------------
        # Illumination Invariance Adaptation:
        # In the borderline band (0.35 <= sim < 0.75), real-time lighting
        # differences (shadows, backlight, auto-exposure) can degrade raw
        # cosine similarity. Evaluate multiple lighting-normalized variants
        # of BOTH reference and live images to find the best score.
        # -------------------------------------------------------------------
        best_sim = sim

        def _try_normalized(ref_img, live_img):
            """Run detection + embedding on a pair and return cosine similarity, or None."""
            try:
                rf = self.detector.detect(ref_img)
                lf = self.detector.detect(live_img)
                if rf is not None and len(rf) == 1 and lf is not None and len(lf) == 1:
                    emb_r = self.embedding_model.embed(ref_img, rf[0])
                    emb_l = self.embedding_model.embed(live_img, lf[0])
                    return self._cosine_similarity(emb_r, emb_l)
            except Exception:
                pass
            return None

        try:
            # --- Helper: CLAHE on YCrCb luminance ---
            def _clahe_ycrcb(img, clip=2.5):
                ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
                y, cr, cb = cv2.split(ycrcb)
                clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
                return cv2.cvtColor(cv2.merge((clahe.apply(y), cr, cb)), cv2.COLOR_YCrCb2BGR)

            # --- Helper: Gamma LUT ---
            def _gamma(img, g):
                inv = 1.0 / g
                table = np.array([((i / 255.0) ** inv) * 255 for i in range(256)]).astype("uint8")
                return cv2.LUT(img, table)

            # 1. CLAHE-normalize BOTH reference and live
            norm_ref = _clahe_ycrcb(reference_image_data)
            norm_live = _clahe_ycrcb(live_image_data)
            s = _try_normalized(norm_ref, norm_live)
            if s is not None and s > best_sim:
                best_sim = s

            # 2. Gamma-brighten live (dark room) – two strengths
            for gamma_val in (0.55, 0.70):
                if best_sim >= 0.75:
                    break
                s = _try_normalized(reference_image_data, _gamma(live_image_data, gamma_val))
                if s is not None and s > best_sim:
                    best_sim = s

            # 3. Gamma-darken live (overexposed / bright window behind candidate)
            if best_sim < 0.75:
                s = _try_normalized(reference_image_data, _gamma(live_image_data, 1.40))
                if s is not None and s > best_sim:
                    best_sim = s

            # 4. CLAHE live + gamma-brightened reference
            # (reference photo may itself have been taken in poor light)
            if best_sim < 0.75:
                s = _try_normalized(_gamma(reference_image_data, 0.70), norm_live)
                if s is not None and s > best_sim:
                    best_sim = s

            # 5. Histogram-equalized grayscale → BGR of live
            if best_sim < 0.75:
                gray_eq = cv2.cvtColor(
                    cv2.equalizeHist(cv2.cvtColor(live_image_data, cv2.COLOR_BGR2GRAY)),
                    cv2.COLOR_GRAY2BGR,
                )
                s = _try_normalized(reference_image_data, gray_eq)
                if s is not None and s > best_sim:
                    best_sim = s

        except Exception:
            pass

        return float(np.clip(best_sim, 0.0, 1.0))

    @staticmethod
    def _cosine_similarity(a, b) -> float:

        a_norm = np.linalg.norm(a)
        b_norm = np.linalg.norm(b)

        if a_norm == 0 or b_norm == 0:
            raise ValueError(
                "Cannot compare zero-length embeddings."
            )

        similarity = np.dot(a, b) / (
            a_norm * b_norm
        )

        return float(
            np.clip(similarity, 0.0, 1.0)
        )


SFaceMatcher = EmbeddingFaceMatcher