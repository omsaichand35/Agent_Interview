from datetime import datetime

import pytest

from app.stages.stage3_identity.identity_checker import (
    IdentityChecker,
)


class FakeDetector:

    def __init__(
        self,
        faces=None,
        reference_faces=None,
        live_faces=None,
    ):
        self.faces = faces
        self.reference_faces = reference_faces
        self.live_faces = live_faces

    def detect(self, image_path):
        if "reference" in str(image_path) and self.reference_faces is not None:
            return self.reference_faces
        if "live" in str(image_path) and self.live_faces is not None:
            return self.live_faces
        return self.faces if self.faces is not None else []


class FakeMatcher:

    def __init__(self, confidence):
        self.confidence = confidence

    def compare(
        self,
        reference_path,
        live_path,
        reference_face,
        live_face,
    ):
        return self.confidence


def test_identity_passes_with_one_face_and_high_confidence():

    detector = FakeDetector(
        faces=[(10, 10, 100, 100)]
    )

    matcher = FakeMatcher(
        confidence=0.90
    )

    checker = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
    )

    result = checker.verify(
        candidate_id="C001",
        session_id="S001",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is True
    assert result.confidence == 0.90
    assert result.failure_reason is None


def test_identity_fails_with_no_live_face():

    detector = FakeDetector(
        reference_faces=[(10, 10, 100, 100)],
        live_faces=[],
    )

    matcher = FakeMatcher(
        confidence=0.90
    )

    checker = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
    )

    result = checker.verify(
        candidate_id="C001",
        session_id="S002",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is False

    assert (
        result.failure_reason
        == "Invalid live face state."
    )

    assert result.confidence is None


def test_identity_fails_with_multiple_live_faces():

    detector = FakeDetector(
        reference_faces=[(10, 10, 100, 100)],
        live_faces=[
            (10, 10, 100, 100),
            (200, 10, 100, 100),
        ],
    )

    matcher = FakeMatcher(
        confidence=0.99
    )

    checker = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
    )

    result = checker.verify(
        candidate_id="C001",
        session_id="S003",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is False

    assert (
        result.failure_reason
        == "Invalid live face state."
    )


def test_identity_fails_with_low_confidence():

    detector = FakeDetector(
        faces=[
            (10, 10, 100, 100)
        ]
    )

    matcher = FakeMatcher(
        confidence=0.40
    )

    checker = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
    )

    result = checker.verify(
        candidate_id="C001",
        session_id="S004",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is False
    assert result.confidence == 0.40
    assert (
        result.failure_reason
        == "Face verification failed."
    )

def test_identity_fails_with_invalid_reference():

    detector = FakeDetector(
        faces=[]
    )

    matcher = FakeMatcher(
        confidence=0.99
    )

    checker = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
    )

    result = checker.verify(
        candidate_id="C001",
        session_id="S005",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is False

    assert (
        result.failure_reason
        == "Invalid reference image."
    )