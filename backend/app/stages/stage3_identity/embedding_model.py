from abc import ABC, abstractmethod


class FaceEmbeddingModel(ABC):

    @abstractmethod
    def embed(self, face_image):
        """
        Convert a detected face into a numeric embedding.
        """
        raise NotImplementedError