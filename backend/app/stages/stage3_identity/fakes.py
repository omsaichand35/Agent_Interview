import numpy as np


class FakeEmbeddingModel:

    def embed(self, face_image):
        """
        Deterministic embedding for unit tests.
        """
        flattened = face_image.astype(np.float32).flatten()

        if len(flattened) < 128:
            flattened = np.pad(
                flattened,
                (0, 128 - len(flattened)),
            )

        return flattened[:128]