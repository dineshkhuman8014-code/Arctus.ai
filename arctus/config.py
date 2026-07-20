"""Configuration for Arctus.ai.

Keys live in the user's environment (or ~/.config/arctus-ai/config.json),
never in the code. Nothing is hardcoded, nothing leaves the machine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Any


CONFIG_DIR = Path.home() / ".config" / "arctus-ai"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_DIR = CONFIG_DIR / "sessions"


@dataclass
class Tier:
    """One model tier.

    Works against any OpenAI-compatible /chat/completions endpoint:
    OpenAI, OpenRouter, Ollama (/v1), LM Studio, vLLM, etc.
    """
    base_url: str
    model: str
    api_key: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096


@dataclass
class Config:
    # Lightweight tier: formatting, syntax checks, summaries, linting.
    fast: Tier = field(default_factory=lambda: Tier(
        base_url=os.environ.get("ARCTUS_FAST_BASE_URL", "http://localhost:11434/v1"),
        model=os.environ.get("ARCTUS_FAST_MODEL", "llama3.2"),
        api_key=os.environ.get("ARCTUS_FAST_API_KEY", "ollama"),
        temperature=0.2,
    ))
    # Primary tier: refactors, design decisions, multi-file changes.
    strong: Tier = field(default_factory=lambda: Tier(
        base_url=os.environ.get("ARCTUS_STRONG_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("ARCTUS_STRONG_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("ARCTUS_STRONG_API_KEY", ""),
        temperature=0.4,
    ))
    # Planner uses the strong tier by default.
    planner_uses: str = "strong"
    # Complexity routing threshold (words in prompt).
    complexity_threshold_words: int = 40
    # 80% context-handoff rule.
    agent_context_limit: int = 128_000
    handoff_threshold_ratio: float = 0.80


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """Load from JSON file; fall back to env-derived defaults."""
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            tiers = {}
            for name in ("fast", "strong"):
                if name in raw:
                    tiers[name] = Tier(**raw[name])
            rest = {k: v for k, v in raw.items() if k not in ("fast", "strong")}
            return Config(**tiers, **rest)
        except Exception:
            pass
    return Config()


def save_config(cfg: Config) -> Path:
    ensure_dirs()
    data = asdict(cfg)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return CONFIG_FILE


def tier_for(cfg: Config, name: str) -> Tier:
    return getattr(cfg, name)
