from io import BytesIO

import cv2
import numpy as np


def valid_live_frame_upload():
    """Return a decodable frame for API tests that require multipart media."""
    ok, encoded = cv2.imencode(".jpg", np.full((300, 300, 3), 128, dtype=np.uint8))
    if not ok:
        raise RuntimeError("Could not create test frame")
    return ("live-frame.jpg", BytesIO(encoded.tobytes()), "image/jpeg")
