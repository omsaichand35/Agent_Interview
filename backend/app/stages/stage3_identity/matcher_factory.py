from app.config import settings
from app.core.paths import resolve_path
from app.stages.stage3_identity.face_matcher import (
    HistogramFaceMatcher,
)
from app.stages.stage3_identity.sface_model import (
    SFaceEmbeddingModel,
)
from app.stages.stage3_identity.yunet_detector import (
    YuNetDetector,
)


_cached_matcher_pair = None
_cached_matcher_type = None


def create_face_matcher(force_new: bool = False):
    global _cached_matcher_pair, _cached_matcher_type

    matcher_type = settings.identity_matcher
    if not force_new and _cached_matcher_pair is not None and _cached_matcher_type == matcher_type:
        return _cached_matcher_pair

    if matcher_type == "prototype":
        from app.stages.stage3_identity.face_detector import (
            FaceDetector,
        )

        detector = FaceDetector()
        pair = (
            detector,
            HistogramFaceMatcher(detector),
        )
        _cached_matcher_pair = pair
        _cached_matcher_type = matcher_type
        return pair

    if matcher_type == "sface":

        detector = YuNetDetector(
            model_path=str(resolve_path(settings.yunet_model_path)),
        )

        embedding_model = SFaceEmbeddingModel(
            model_path=str(resolve_path(settings.sface_model_path)),
        )

        from app.stages.stage3_identity.face_matcher import (
            SFaceMatcher,
        )

        matcher = SFaceMatcher(
            detector=detector,
            embedding_model=embedding_model,
        )

        pair = (detector, matcher)
        _cached_matcher_pair = pair
        _cached_matcher_type = matcher_type
        return pair

    raise ValueError(
        f"Unsupported identity matcher: "
        f"{settings.identity_matcher}"
    )