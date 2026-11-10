from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np


class YuNetDetector:
    """
    Robust Face detector that returns bounding boxes plus
    five facial landmarks required by SFace.

    Includes multi-tier adaptive detection:
    1. Primary pass with standard confidence (0.60)
    2. Adaptive contrast enhancement (CLAHE) for dim or backlit webcams
    3. Multi-scale retry for high-res / wide-angle camera feeds
    """

    def __init__(
        self,
        model_path: str,
        input_size=(320, 320),
        confidence_threshold: float = 0.60,
        nms_threshold: float = 0.30,
        top_k: int = 5000,
    ):
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
                        f"YuNet model not found: {model_path}"
                    )

        self.model_path = str(model)
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        self.input_size = input_size

        self.detector = cv2.FaceDetectorYN.create(
            self.model_path,
            "",
            input_size,
            self.confidence_threshold,
            self.nms_threshold,
            self.top_k,
        )

        # Fallback detector with relaxed confidence for low-light or angled faces
        self._relaxed_detector = None

    def _get_relaxed_detector(self, size: Tuple[int, int]):
        if self._relaxed_detector is None:
            self._relaxed_detector = cv2.FaceDetectorYN.create(
                self.model_path,
                "",
                size,
                0.30,  # Very relaxed: catches faces in extreme lighting
                self.nms_threshold,
                self.top_k,
            )
        else:
            self._relaxed_detector.setInputSize(size)
        return self._relaxed_detector

    def detect(self, image_path: Union[str, Path, np.ndarray]) -> np.ndarray:
        if isinstance(image_path, np.ndarray):
            image = image_path
        else:
            image_path_str = str(image_path).strip().strip("\"'")
            image = cv2.imread(image_path_str)

        if image is None:
            raise ValueError(
                f"Unable to read image: {image_path}"
            )

        height, width = image.shape[:2]
        if height < 10 or width < 10:
            return []

        # -------------------------------------------------------------------
        # Pass 1: Standard detection at native resolution
        # -------------------------------------------------------------------
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)

        if faces is not None and len(faces) > 0:
            return faces

        # -------------------------------------------------------------------
        # Pass 2: Contrast-enhanced detection (handles indoor/backlit webcams)
        # -------------------------------------------------------------------
        try:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l_channel, a_channel, b_channel = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            cl = clahe.apply(l_channel)
            enhanced = cv2.cvtColor(cv2.merge((cl, a_channel, b_channel)), cv2.COLOR_LAB2BGR)

            _, e_faces = self.detector.detect(enhanced)
            if e_faces is not None and len(e_faces) > 0:
                return e_faces
        except Exception:
            pass

        # -------------------------------------------------------------------
        # Pass 3: Multi-scale detection (standard 320x320 or 640x480 scale)
        # -------------------------------------------------------------------
        scales = [0.5, 0.75, 1.25]
        for s in scales:
            sw, sh = int(width * s), int(height * s)
            if sw >= 80 and sh >= 80:
                resized = cv2.resize(image, (sw, sh), interpolation=cv2.INTER_LINEAR)
                self.detector.setInputSize((sw, sh))
                _, s_faces = self.detector.detect(resized)
                if s_faces is not None and len(s_faces) > 0:
                    # Rescale coordinates & landmarks back to original dimensions
                    rescaled = []
                    for f in s_faces:
                        rf = f.copy()
                        rf[0:4] = rf[0:4] / s
                        rf[4:14] = rf[4:14] / s
                        rescaled.append(rf)
                    return np.array(rescaled)

        # -------------------------------------------------------------------
        # Pass 4: Histogram-equalized grayscale → back to BGR
        # Handles severe underexposure or harsh directional lighting.
        # -------------------------------------------------------------------
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            eq = cv2.equalizeHist(gray)
            eq_bgr = cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR)
            self.detector.setInputSize((width, height))
            _, eq_faces = self.detector.detect(eq_bgr)
            if eq_faces is not None and len(eq_faces) > 0:
                return eq_faces
        except Exception:
            pass

        # -------------------------------------------------------------------
        # Pass 5: Bilateral-filter denoised image (low-light noise reduction)
        # -------------------------------------------------------------------
        try:
            denoised = cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)
            self.detector.setInputSize((width, height))
            _, dn_faces = self.detector.detect(denoised)
            if dn_faces is not None and len(dn_faces) > 0:
                return dn_faces
        except Exception:
            pass

        # -------------------------------------------------------------------
        # Pass 6: Relaxed confidence threshold (0.30) fallback
        # -------------------------------------------------------------------
        try:
            rel_det = self._get_relaxed_detector((width, height))
            _, r_faces = rel_det.detect(image)
            if r_faces is not None and len(r_faces) > 0:
                return r_faces
            # Also try relaxed on CLAHE-enhanced for the hardest cases
            try:
                lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
                l_channel, a_channel, b_channel = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                cl = clahe.apply(l_channel)
                enhanced2 = cv2.cvtColor(cv2.merge((cl, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
                rel_det.setInputSize((width, height))
                _, re_faces = rel_det.detect(enhanced2)
                if re_faces is not None and len(re_faces) > 0:
                    return re_faces
            except Exception:
                pass
        except Exception:
            pass

        return []