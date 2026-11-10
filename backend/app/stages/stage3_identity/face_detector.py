import cv2


class FaceDetector:

    def __init__(self):
        try:
            cascade_path = getattr(cv2, "data", None) and getattr(cv2.data, "haarcascades", "") + (
                "haarcascade_frontalface_default.xml"
            )
            classifier_cls = getattr(cv2, "CascadeClassifier", None)
            self.detector = classifier_cls(cascade_path) if classifier_cls else None
        except Exception:
            self.detector = None

    def detect(self, image_path):
        import numpy as np
        if isinstance(image_path, np.ndarray):
            image = image_path
        else:
            image = cv2.imread(image_path)

        if image is None:
            raise ValueError(
                f"Could not read image: {image_path}"
            )

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        if self.detector is None or not hasattr(self.detector, "detectMultiScale"):
            return []

        faces = self.detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(80, 80),
        )

        return faces