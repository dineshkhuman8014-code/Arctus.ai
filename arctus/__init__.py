"""Arctus.ai — local-first multi-agent orchestrator (Python).

Public surface for programmatic use:
    from arctus import Config, QueenAgent, TaskResult, build_roster, ...
"""
from .config import Config, Tier, load_config, save_config  # noqa: F401
from .orchestrator import QueenAgent, TaskResult, Step  # noqa: F401
from .rate_limit import RateLimitConfig, RateLimitError  # noqa: F401
from .agents import AgentSpec, build_roster, roster_summary, pick  # noqa: F401
from . import session  # noqa: F401
from . import mcp  # noqa: F401
from . import federation  # noqa: F401
from . import sona  # noqa: F401
from . import sandbox  # noqa: F401
from . import presets  # noqa: F401

__version__ = "1.0.0"
__all__ = [
    "Config", "Tier", "load_config", "save_config",
    "QueenAgent", "TaskResult", "Step",
    "RateLimitConfig", "RateLimitError",
    "AgentSpec", "build_roster", "roster_summary", "pick",
    "session", "mcp", "federation", "sona", "sandbox", "presets",
    "__version__",
]
