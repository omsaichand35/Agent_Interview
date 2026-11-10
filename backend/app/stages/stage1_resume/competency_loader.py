from pathlib import Path

import yaml

from app.schemas.job import Competency


class CompetencyLoader:

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)

    def load(self) -> list[Competency]:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Competency configuration not found: {self.config_path}"
            )

        with open(self.config_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        competencies = data.get("competencies", [])

        return [
            Competency(
                id=item.get("id", item["name"].lower().replace(" ", "_")),
                name=item["name"],
                description=item["description"],
                weight=item["weight"],
            )
            for item in competencies
        ]
