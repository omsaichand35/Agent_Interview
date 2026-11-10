import numpy as np

from app.stages.stage3_identity.face_matcher import (
    EmbeddingFaceMatcher,
)


def test_cosine_similarity_identical_vectors():
    vector = np.array([1.0, 2.0, 3.0])

    result = EmbeddingFaceMatcher._cosine_similarity(
        vector,
        vector,
    )

    assert result == 1.0


def test_cosine_similarity_is_bounded():
    first = np.array([1.0, 0.0, 0.0])
    second = np.array([0.0, 1.0, 0.0])

    result = EmbeddingFaceMatcher._cosine_similarity(
        first,
        second,
    )

    assert 0.0 <= result <= 1.0