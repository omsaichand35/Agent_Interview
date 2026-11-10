import json
from pathlib import Path


class HiringWorkflowPersistence:
    """
    Durable, file-backed store for hiring workflow state.

    Design
    ------
    * save(job_id, state)  -- writes <job_id>_workflow.json atomically.
    * load(job_id)         -- returns plain dict or None (never raises).
    * exists(job_id)       -- lightweight presence check.
    * list_all()           -- enumerate all persisted workflows.

    The workflow session manager auto-persists after every transition so
    a backend restart at any stage loses at most the current incomplete
    operation (never an entire stage).
    """

    def __init__(self, output_dir: str = "data/outputs/workflows"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path(self, job_id: str) -> Path:
        return self.output_dir / f"{job_id}_workflow.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def exists(self, job_id: str) -> bool:
        """Return True if a persisted workflow file exists on disk."""
        return self._path(job_id).exists()

    def save(self, job_id_or_state, state=None) -> str:
        """
        Persist workflow state to disk.

        Two call styles are supported so both old and new callers work:
            save(state)          -- state must contain 'job_id' key
            save(job_id, state)  -- explicit job_id (preferred)

        State may be a plain dict, WorkflowState (dict subclass), or any
        object with .model_dump() / .dict().

        Writes atomically: .tmp then rename, so a crash mid-write never
        leaves a corrupt file on disk.
        """
        if state is None:
            # Old-style: save(state_dict)
            raw = job_id_or_state
            job_id = raw["job_id"] if isinstance(raw, dict) else getattr(raw, "job_id")
        else:
            job_id = job_id_or_state
            raw = state

        if hasattr(raw, "model_dump"):
            data = raw.model_dump()
        elif hasattr(raw, "dict") and callable(raw.dict):
            data = raw.dict()
        elif isinstance(raw, dict):
            data = dict(raw)    # shallow copy -- do not mutate caller
        else:
            data = dict(raw)

        data["job_id"] = job_id   # guarantee key is always present

        path = self._path(job_id)
        tmp = path.with_suffix(".tmp")

        tmp.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
        return str(path)

    def load(self, job_id: str):
        """
        Load a workflow from disk and return it as a plain dict.

        Returns None when the workflow file does not exist.
        Never raises FileNotFoundError -- callers should check for None.
        """
        path = self._path(job_id)

        if not path.exists():
            return None

        return json.loads(path.read_text(encoding="utf-8"))

    def list_all(self) -> list:
        """Return all persisted workflows as plain dicts."""
        workflows = []
        for path in self.output_dir.glob("*_workflow.json"):
            try:
                workflows.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return workflows
