from app.config import settings
from app.stages.stage3_identity.face_matcher import (
    HistogramFaceMatcher,
)
from app.stages.stage3_identity.matcher_factory import (
    create_face_matcher,
)


def test_prototype_matcher_factory(monkeypatch):

    monkeypatch.setattr(
        settings,
        "identity_matcher",
        "prototype",
    )

    detector, matcher = create_face_matcher()

    assert detector is not None
    assert isinstance(
        matcher,
        HistogramFaceMatcher,
    )