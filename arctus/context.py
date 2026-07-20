"""Agent state: isolated context windows, sandbox checkpoints, handoff.

This is the safe kernel of the "hive-mind" idea: each agent gets its own
token budget with an 80% handoff rule, and state is checkpointed to a
session-local directory (not /tmp) so a handoff can resume cleanly.

NOTE on "sandbox": this is a state directory, not an OS-level filesystem
jail. If you need true isolation (separate mount namespace, restricted
syscalls), run each agent in a container or use your OS's sandboxing.
The naming is honest here — it's a state dir, not a jail.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import SESSIONS_DIR

logger = logging.getLogger("arctus.context")

HANDOFF_THRESHOLD_RATIO = 0.80


@dataclass
class IsolatedContextWindow:
    """Token budget for one agent. Independent. No cross-agent bleeding."""
    agent_id: str
    max_tokens: int = 128_000
    used_tokens: int = 0
    handoff_limit: int = field(init=False)

    def __post_init__(self) -> None:
        self.handoff_limit = int(self.max_tokens * HANDOFF_THRESHOLD_RATIO)

    def consume(self, token_count: int) -> bool:
        self.used_tokens += token_count
        pct = (self.used_tokens / self.max_tokens) * 100.0
        logger.info(
            "Agent [%s] context: %d/%d tokens (%.1f%%)",
            self.agent_id, self.used_tokens, self.max_tokens, pct,
        )
        return self.used_tokens >= self.handoff_limit

    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "max_tokens": self.max_tokens,
            "used_tokens": self.used_tokens,
            "handoff_limit": self.handoff_limit,
        }


class StateDir:
    """Per-agent state directory under the user's config dir.

    Replaces the original spec's '/tmp/arctus_sandboxes' — using a path under
    the user's own config dir is safer and more predictable than /tmp.
    """

    def __init__(self, agent_id: str, session_id: str = "default") -> None:
        self.agent_id = agent_id
        self.path = SESSIONS_DIR / "agent-state" / session_id / agent_id
        self.path.mkdir(parents=True, exist_ok=True)
        self.state_file = self.path / "state_log.json"

    def write_checkpoint(
        self, done: str, next_steps: str, context: Dict[str, Any]
    ) -> Path:
        payload = {
            "timestamp": time.time(),
            "agent_id": self.agent_id,
            "what_has_been_done": done,
            "what_needs_to_be_completed_next": next_steps,
            "saved_context": context,
        }
        self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self.state_file

    def read_checkpoint(self) -> Optional[Dict[str, Any]]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None


@dataclass
class HandoffPayload:
    """Carrier for the 80% rule: A pauses, B resumes with a fresh budget."""
    paused_agent: str
    target_agent: str
    state_dir: StateDir
    reason: str
    context_snapshot: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paused_agent": self.paused_agent,
            "target_agent": self.target_agent,
            "state_dir": str(self.state_dir.state_file),
            "reason": self.reason,
            "context_snapshot": self.context_snapshot,
        }
