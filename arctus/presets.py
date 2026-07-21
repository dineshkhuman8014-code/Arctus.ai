"""Tier presets for common providers.

These are OpenAI-compatible endpoints. The thing I refused earlier was the
*header-forwarding* design — NOT these providers. OpenRouter and OmniRoute
are perfectly fine when used the normal way: your local config holds your
key, the orchestrator calls the endpoint directly. No tunnels, no forwarding.

Usage:
    from arctus.presets import apply_preset
    apply_preset("openrouter")           # sets strong tier to OpenRouter
    apply_preset("omniroute_local")      # fast tier -> local OmniRoute
    apply_preset("ollama")               # fast tier -> local Ollama
    apply_preset("openai")               # strong tier -> OpenAI

Env vars take precedence; presets only fill in defaults if the env var is unset.
"""
from __future__ import annotations

import os
from typing import Dict

from .config import Config, Tier, load_config, save_config


PRESETS: Dict[str, Dict[str, str]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-3.5-sonnet",
        "api_key_env": "OPENROUTER_API_KEY",
        "applies_to": "strong",
    },
    "omniroute_local": {
        "base_url": "http://localhost:20128/v1",
        "model": "llama3.2",
        "api_key_env": "ARCTUS_OMNIROUTE_KEY",
        "applies_to": "fast",
    },
    "omniroute_remote": {
        # OmniRoute cloud endpoint (OpenAI-compatible). User supplies key.
        "base_url": "https://api.omniroute.ai/v1",
        "model": "llama3.2",
        "api_key_env": "OMNIROUTE_API_KEY",
        "applies_to": "fast",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "api_key_env": "",          # Ollama ignores keys
        "applies_to": "fast",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "builder_model": "gpt-4o-mini",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "applies_to": "strong",
    },
    "anthropic_via_openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-3.5-sonnet",
        "api_key_env": "OPENROUTER_API_KEY",
        "applies_to": "strong",
    },
}


def apply_preset(name: str, cfg: Config | None = None) -> Config:
    """Apply a named preset to the relevant tier. Returns the updated config."""
    if name not in PRESETS:
        raise KeyError(f"Unknown preset {name!r}. Known: {list(PRESETS)}")
    p = PRESETS[name]
    cfg = cfg or load_config()
    api_key = os.environ.get(p["api_key_env"], "") if p["api_key_env"] else ""
    new_tier = Tier(
        base_url=p["base_url"],
        model=p["model"],
        api_key=api_key,
        temperature=0.3,
    )
    setattr(cfg, p["applies_to"], new_tier)
    save_config(cfg)
    return cfg


def list_presets() -> Dict[str, Dict[str, str]]:
    return PRESETS
