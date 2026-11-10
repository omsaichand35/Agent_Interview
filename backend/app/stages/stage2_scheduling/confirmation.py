import json
from pathlib import Path

from app.schemas.schedule import Schedule


class ConfirmationGenerator:

    def generate(
        self,
        schedule: Schedule,
        output_dir: str,
    ) -> str:

        output_path = Path(output_dir)

        output_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        confirmation = {
            "candidate_id": schedule.candidate_id,
            "slot_id": schedule.slot_id,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat(),
            "status": schedule.status,
            "message": (
                "Your interview has been scheduled."
            ),
        }

        file_path = (
            output_path
            / f"{schedule.candidate_id}_confirmation.json"
        )

        with open(
            file_path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                confirmation,
                file,
                indent=4,
            )

        return str(file_path)