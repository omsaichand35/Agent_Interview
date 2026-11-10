"""Dataset loader for the End-to-End AI Hiring Pipeline Evaluation (E8)."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class EndToEndDatasetLoader:
    """Loads hiring cases, shortlists, interview expectations, and recommendation labels."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            # Resolves from backend/app/evaluation to project_root/data/evaluation/end_to_end
            root = Path(__file__).resolve().parents[3]
            data_dir = str(root / "data" / "evaluation" / "end_to_end")
        self.data_dir = Path(data_dir)

    def load_all(self) -> Dict[str, Any]:
        with open(self.data_dir / "hiring_cases.json", "r", encoding="utf-8") as f:
            cases = json.load(f)
        with open(self.data_dir / "expected_shortlists.json", "r", encoding="utf-8") as f:
            shortlists = json.load(f)
        with open(self.data_dir / "expected_interviews.json", "r", encoding="utf-8") as f:
            interviews = json.load(f)
        with open(self.data_dir / "expected_recommendations.json", "r", encoding="utf-8") as f:
            recommendations = json.load(f)

        return {
            "cases": cases,
            "shortlists": {s["case_id"]: s for s in shortlists},
            "interviews": {i["case_id"]: i for i in interviews},
            "recommendations": {r["case_id"]: r for r in recommendations},
        }
