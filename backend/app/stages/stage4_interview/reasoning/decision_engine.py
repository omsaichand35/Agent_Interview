from enum import Enum


class InterviewDecision(str, Enum):

    DEEPEN = "deepen"

    PIVOT = "pivot"

    NEXT_COMPETENCY = "next_competency"

    RECOVER = "recover"

    CONCLUDE = "conclude"