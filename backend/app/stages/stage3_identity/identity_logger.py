import json
from pathlib import Path
from typing import Optional

from app.schemas.identity import IdentityResult


class IdentityLogger:

    def __init__(self, output_dir: str = "data/outputs/identity_logs"):
        self.output_dir = output_dir

    def log(
        self,
        result: IdentityResult,
        output_dir: Optional[str] = None,
    ) -> str:

        directory = Path(output_dir or self.output_dir)

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            directory
            / f"identity_log_{result.session_id}.json"
        )

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                result.model_dump(mode="json"),
                file,
                indent=4,
            )

        return str(path)