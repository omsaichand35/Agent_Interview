from abc import ABC, abstractmethod
from pathlib import Path
import cv2


class Camera(ABC):

    @abstractmethod
    def capture_frame(self) -> str:
        pass


class OpenCVCamera(Camera):

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.camera = cv2.VideoCapture(0)

        if not self.camera.isOpened():
            raise RuntimeError(
                "Unable to open webcam."
            )

    def capture_frame(self) -> str:

        success, frame = self.camera.read()

        if not success:
            raise RuntimeError(
                "Unable to capture webcam frame."
            )

        frame_number = len(
            list(self.output_dir.glob("*.jpg"))
        ) + 1

        output_path = (
            self.output_dir
            / f"check_{frame_number:03d}.jpg"
        )

        cv2.imwrite(
            str(output_path),
            frame,
        )

        return str(output_path)

    def release(self):
        self.camera.release()
