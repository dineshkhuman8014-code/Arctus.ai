"""Arctus.ai — local-first multi-agent orchestrator (Python).

Public surface for programmatic use:
    from arctus import Config, QueenAgent, TaskResult, run
"""
from .config import Config, Tier, load_config, save_config  # noqa: F401
from .orchestrator import QueenAgent, TaskResult, Step  # noqa: F401
from .rate_limit import RateLimitConfig, RateLimitError  # noqa: F401
from . import session  # noqa: F401

__version__ = "0.1.0"
__all__ = [
    "Config", "Tier", "load_config", "save_config",
    "QueenAgent", "TaskResult", "Step",
    "RateLimitConfig", "RateLimitError",
    "session", "__version__",
]
