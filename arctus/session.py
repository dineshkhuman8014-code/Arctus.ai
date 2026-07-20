"""File-backed session state.

Each session is a JSON file under ~/.config/arctus-ai/sessions/<id>.json.
State survives process restarts and is easy to inspect / clear by hand.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Dict, Any

from .config import SESSIONS_DIR


def _path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def load(session_id: str) -> Dict[str, Any]:
    p = _path(session_id)
    if not p.exists():
        return {
            "id": session_id,
            "created_at": time.time(),
            "steps": [],
            "log": [],
            "history": [],
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {
            "id": session_id,
            "created_at": time.time(),
            "steps": [],
            "log": [],
            "history": [],
        }


def save(session: Dict[str, Any]) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _path(session["id"]).write_text(
        json.dumps(session, indent=2), encoding="utf-8"
    )


def reset(session_id: str, scope: str = "all") -> Dict[str, Any]:
    """Drop session state. scope: 'all' | 'history'."""
    p = _path(session_id)
    if not p.exists():
        return {"status": "already_empty", "session_id": session_id, "scope": scope}
    if scope == "history":
        data = json.loads(p.read_text(encoding="utf-8"))
        data["history"] = []
        data["steps"] = []
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"status": "reset_history", "session_id": session_id, "scope": scope}
    # scope == "all"
    try:
        p.unlink()
    except OSError:
        pass
    return {"status": "reset_all", "session_id": session_id, "scope": scope}
