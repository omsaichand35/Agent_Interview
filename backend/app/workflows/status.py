from enum import Enum


class HiringStatus(str, Enum):

    CREATED = "created"

    SHORTLISTED = "shortlisted"

    SCHEDULED = "scheduled"

    IDENTITY_CHECK = "identity_check"

    INTERVIEW_READY = "interview_ready"

    INTERVIEW_IN_PROGRESS = "interview_in_progress"

    INTERVIEW_COMPLETED = "interview_completed"

    HUMAN_REVIEW = "human_review"

    RECOMMENDATION_READY = "recommendation_ready"

    COMPLETED = "completed"