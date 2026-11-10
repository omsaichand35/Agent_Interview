from typing import Dict, List


class EvidenceAggregator:

    def aggregate(
        self,
        evidence: Dict[str, List[dict]],
    ) -> Dict[str, float]:

        scores = {}

        for competency, items in evidence.items():

            values = [
                float(item["score"])
                for item in items
                if "score" in item
            ]

            if not values:
                continue

            average = sum(values) / len(values)
            strongest = max(values)

            final_score = (
                average * 0.7
                + strongest * 0.3
            )

            scores[competency] = round(
                final_score,
                3,
            )

        return scores
