"""OpenAI-compatible LLM client.

Talks to whatever endpoints the user configured (fast / strong tiers).
Pure outbound HTTP, no listeners, no tunneling. Uses urllib from the stdlib
so the package has zero third-party runtime dependencies.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Dict, Any, Optional

from .config import Tier


class LLMError(RuntimeError):
    pass


def chat(tier: Tier, messages: List[Dict[str, str]], *, timeout: int = 120) -> str:
    """Call POST {base_url}/chat/completions and return the assistant message."""
    url = tier.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": tier.model,
        "messages": messages,
        "temperature": tier.temperature,
        "max_tokens": tier.max_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if tier.api_key:
        headers["Authorization"] = f"Bearer {tier.api_key}"

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        text = ""
        try:
            text = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        raise LLMError(f"{tier.model} HTTP {e.code}: {text[:400]}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"{tier.model} unreachable: {e.reason}") from None

    content: Optional[str] = (
        payload.get("choices", [{}])[0].get("message", {}).get("content")
    )
    if not content:
        raise LLMError(f"{tier.model} returned no content: {json.dumps(payload)[:400]}")
    return content.strip()
