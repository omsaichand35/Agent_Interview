from typing import Dict, List, Optional
from app.schemas.candidate import Candidate


class CandidateRepository:

    def __init__(self, candidates: Optional[Dict[str, Candidate]] = None):
        self._candidates: Dict[str, Candidate] = dict(candidates or {})

    def list_all(self) -> List[Candidate]:
        return list(self._candidates.values())

    def get_by_id(self, candidate_id: str) -> Optional[Candidate]:
        return self._candidates.get(candidate_id)

    def save(self, candidate: Candidate):
        self._candidates[candidate.candidate_id] = candidate

    def create_or_update(
        self,
        candidate_id: str,
        name: str = "",
        email: str = "",
        photo_path: Optional[str] = None,
        **kwargs,
    ) -> Candidate:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            candidate = Candidate(
                candidate_id=candidate_id,
                name=name,
                email=email,
                photo_path=photo_path,
                **kwargs,
            )
        else:
            if photo_path is not None:
                candidate.photo_path = photo_path
            if name:
                candidate.name = name
            if email:
                candidate.email = email
            for k, v in kwargs.items():
                if hasattr(candidate, k) and v is not None:
                    setattr(candidate, k, v)
        self._candidates[candidate_id] = candidate
        return candidate

