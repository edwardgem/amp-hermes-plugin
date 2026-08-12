from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path() -> Path:
    raw = os.environ.get("HERMES_HOME", "").strip()
    hermes_home = Path(raw).expanduser() if raw else Path.home() / ".hermes"
    if not str(raw):
        hermes_home = Path.home() / ".hermes"
    state_dir = hermes_home / "plugin_state" / "amp-governance"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "sessions.json"


@dataclass
class SessionRecord:
    session_id: str
    instance_id: str
    model: str = ""
    platform: str = ""
    created_at: str = ""
    last_seen_at: str = ""
    # Fingerprint of the AMP config (backend/org/agent/api key) active when
    # this record was created. A cached instance_id is only safe to reuse if
    # the plugin is still talking to the same AMP agent — without this, a
    # Hermes session that outlives an .env change (e.g. re-pointing at a new
    # agent during QSJ setup) keeps reusing the old agent's instance_id and
    # never calls init_instance() again, so AMP never records a fresh
    # connection for the new agent.
    agent_fingerprint: str = ""

    @classmethod
    def from_dict(cls, payload: Dict[str, str]) -> "SessionRecord":
        return cls(**payload)


class SessionStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _state_path()
        self._lock = threading.Lock()

    def _load_all(self) -> Dict[str, SessionRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, SessionRecord] = {}
        for session_id, payload in raw.items():
            if isinstance(payload, dict):
                out[session_id] = SessionRecord.from_dict(payload)
        return out

    def _save_all(self, data: Dict[str, SessionRecord]) -> None:
        serializable = {key: asdict(value) for key, value in data.items()}
        self._path.write_text(json.dumps(serializable, indent=2) + "\n")

    def get(self, session_id: str) -> Optional[SessionRecord]:
        with self._lock:
            return self._load_all().get(session_id)

    def put(self, record: SessionRecord) -> None:
        with self._lock:
            data = self._load_all()
            record.last_seen_at = _utc_now()
            if not record.created_at:
                record.created_at = record.last_seen_at
            data[record.session_id] = record
            self._save_all(data)

    def delete(self, session_id: str) -> None:
        with self._lock:
            data = self._load_all()
            if session_id in data:
                del data[session_id]
                self._save_all(data)
