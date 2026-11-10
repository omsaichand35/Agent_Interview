class InterviewSessionRegistry:

    def __init__(self, persistence=None):
        self.sessions = {}
        self.persistence = persistence

    def _get_persistence(self):
        if self.persistence is None:
            from app.stages.stage4_interview.persistence import InterviewPersistence
            self.persistence = InterviewPersistence()
        return self.persistence

    def create(self, session_id, state):
        self.sessions[session_id] = state
        # Persist initial state immediately so a backend restart right after
        # /start doesn't lose the session before the first answer is submitted.
        try:
            persistence = self._get_persistence()
            state_dict = dict(state) if isinstance(state, dict) else state
            persistence.save(session_id, state_dict)
        except Exception:
            pass

    def get(self, session_id):
        if session_id not in self.sessions:
            from app.stages.stage4_interview.controller import SessionState
            persistence = self._get_persistence()
            disk_data = persistence.load(session_id)
            if disk_data is not None:
                # Wrap in SessionState so attribute access works throughout
                # the app (state.turn_number etc.) after a backend restart.
                disk_state = SessionState(disk_data)
                self.sessions[session_id] = disk_state
                return disk_state

            raise KeyError(
                f"Interview session not found: {session_id}"
            )
        return self.sessions[session_id]

    def get_by_candidate(self, candidate_id: str):
        # 1. Check in-memory sessions
        for state in self.sessions.values():
            if isinstance(state, dict) and state.get("candidate_id") == candidate_id:
                return state

        # 2. Check disk persisted sessions
        import json
        from pathlib import Path
        output_dir = (
            self._get_persistence().output_dir
            if self.persistence is not None
            else Path("data/outputs/interviews")
        )
        if output_dir.exists():
            json_files = sorted(
                output_dir.glob("*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            for path in json_files:
                try:
                    with path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and data.get("candidate_id") == candidate_id:
                            return data
                except Exception:
                    continue
        return None

    def update(self, session_id, state):
        self.sessions[session_id] = state
        # Auto-persist every state change so the disk is always the
        # source of truth. This covers both browser reconnects (C4) and
        # backend restart recovery (C5) without extra save() calls in routes.
        try:
            persistence = self._get_persistence()
            state_dict = dict(state) if isinstance(state, dict) else state
            persistence.save(session_id, state_dict)
        except Exception:
            pass  # Never let persistence failure break the interview

    def delete(self, session_id):
        self.sessions.pop(session_id, None)
        try:
            persistence = self._get_persistence()
            p = persistence._path(session_id)
            if p.exists():
                p.unlink()
        except Exception:
            pass


    def __getitem__(self, session_id):
        return self.get(session_id)

    def __setitem__(self, session_id, state):
        self.update(session_id, state)

    def __contains__(self, session_id):
        return session_id in self.sessions
