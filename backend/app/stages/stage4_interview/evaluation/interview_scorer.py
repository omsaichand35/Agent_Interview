from typing import Optional


class InterviewScorer:

    def calculate(
        self,
        competency_scores: dict[str, float],
        weights: Optional[dict[str, float]] = None,
    ) -> float:
        """Calculate aggregated interview score in range [0.0, 1.0]."""
        if not competency_scores:
            return 0.0

        if weights:
            total_weight = sum(weights.get(k, 1.0) for k in competency_scores)
            weighted_sum = sum(v * weights.get(k, 1.0) for k, v in competency_scores.items())
            val = weighted_sum / max(1e-6, total_weight)
        else:
            val = sum(competency_scores.values()) / len(competency_scores)

        # Normalize if passed as 0-100 scale
        if val > 1.0:
            val = val / 100.0

        return round(min(1.0, max(0.0, val)), 3)

    def score(
        self,
        competency_scores: dict[str, float],
    ) -> float:
        """Calculate aggregated interview score on a 0-100 scale for backwards compatibility."""
        calc = self.calculate(competency_scores)
        return round(calc * 100, 2)