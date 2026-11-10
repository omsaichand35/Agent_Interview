import json
from pathlib import Path


class InterviewPersistence:
    """
    Durable, file-backed store for interview session state.

    Design
    ------
    * save()   -- writes <session_id>.json atomically (write to .tmp, rename).
    * load()   -- returns a plain dict. Returns None when session doesn't exist.
    * exists() -- lightweight check without a full load.

    The registry treats disk as the authoritative source of truth.
    In-memory (registry.sessions) is a fast-access cache only.
    """

    def __init__(self, output_dir: str = "data/outputs/interviews"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        return self.output_dir / f"{session_id}.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def exists(self, session_id: str) -> bool:
        """Return True if a persisted session file exists on disk."""
        return self._path(session_id).exists()

    def save(self, session_id: str, state) -> None:
        """
        Persist *state* to disk under *session_id*.

        Accepts a plain dict, a SessionState (dict subclass), or any
        object with a .model_dump() / .dict() method (Pydantic).

        The caller's dict is never mutated -- a shallow copy is made first.
        Writes atomically: write to .tmp then rename, so a crash mid-write
        never leaves a corrupt JSON file on disk.
        """
        if hasattr(state, "model_dump"):
            data = state.model_dump()
        elif hasattr(state, "dict") and callable(state.dict):
            data = state.dict()
        elif isinstance(state, dict):
            data = dict(state)      # shallow copy -- do not mutate the caller
        else:
            data = dict(state)

        data["session_id"] = session_id    # guarantee key is always present

        path = self._path(session_id)
        tmp = path.with_suffix(".tmp")

        tmp.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
        return str(path)

    def load(self, session_id: str):
        """
        Load a session from disk and return it as a plain dict.

        Returns None if the session file does not exist.
        Callers that need SessionState attribute access should wrap:
            SessionState(persistence.load(sid))
        The registry.get() does this automatically.
        """
        path = self._path(session_id)

        if not path.exists():
            return None

        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Legacy shim -- kept so existing call sites don't break
    # ------------------------------------------------------------------

    def save_state(self, state: dict) -> str:
        """Deprecated: use save(session_id, state) instead."""
        return self.save(state["session_id"], state)

