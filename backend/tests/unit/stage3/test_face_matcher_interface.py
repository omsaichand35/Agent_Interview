from app.stages.stage3_identity.face_matcher import (
    FaceMatcher,
    HistogramFaceMatcher,
)


def test_histogram_matcher_implements_face_matcher():
    matcher = HistogramFaceMatcher(detector=None)

    assert isinstance(matcher, FaceMatcher)