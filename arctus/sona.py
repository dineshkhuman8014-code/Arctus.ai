"""SONA — Sparse Optimized Neural Attention (lightweight local proxy).

A small in-process optimizer that ranks candidate steps/agents/models by
expected cost/latency before dispatch. Pure heuristic, no external deps.

Why this exists: when you have 200 MCP tools and 100 agents, the Planner
needs a cheap way to decide "which 3 of these 200 tools are actually relevant
for this step?" SONA scores candidates by keyword + recency + cost, then
returns the top-k.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger("arctus.sona")


@dataclass
class Sonacandidate:
    id: str
    description: str
    base_cost: float = 1.0       # relative cost (tokens or ms)
    keywords: List[str] = field(default_factory=list)
    last_used: float = 0.0       # epoch seconds
    use_count: int = 0


@dataclass
class Sonarank:
    id: str
    score: float
    parts: Dict[str, float]


class Sonaptimizer:
    """Scores candidates for a given step.

    score = w_text * text_overlap + w_recency * recency + w_cost * cost_norm
    All weights are configurable.
    """

    def __init__(
        self,
        w_text: float = 0.6,
        w_recency: float = 0.2,
        w_cost: float = 0.2,
        recency_half_life_s: float = 3600.0,
    ):
        self.w_text = w_text
        self.w_recency = w_recency
        self.w_cost = w_cost
        self.recency_half_life_s = recency_half_life_s

    def _tokenize(self, s: str) -> set:
        return {w for w in s.lower().split() if len(w) > 2}

    def _text_overlap(self, step_words: set, c: Sonacandidate) -> float:
        if not c.keywords:
            return 0.0
        kw = {k.lower() for k in c.keywords}
        if not step_words:
            return 0.0
        return len(step_words & kw) / max(1, len(kw))

    def _recency(self, c: Sonacandidate, now: float) -> float:
        if c.last_used == 0.0:
            return 0.0
        age = max(0.0, now - c.last_used)
        return math.exp(-age / self.recency_half_life_s)

    def _cost_norm(self, c: Sonacandidate, max_cost: float) -> float:
        # cheaper -> higher score
        if max_cost <= 0:
            return 1.0
        return 1.0 - (c.base_cost / max_cost)

    def rank(
        self, step_text: str, candidates: List[Sonacandidate], top_k: int = 5
    ) -> List[Sonarank]:
        now = time.time()
        step_words = self._tokenize(step_text)
        max_cost = max((c.base_cost for c in candidates), default=1.0)
        results: List[Sonarank] = []
        for c in candidates:
            text = self._text_overlap(step_words, c)
            rec = self._recency(c, now)
            cost = self._cost_norm(c, max_cost)
            score = (
                self.w_text * text
                + self.w_recency * rec
                + self.w_cost * cost
            )
            results.append(Sonarank(id=c.id, score=score, parts={
                "text": text, "recency": rec, "cost": cost,
            }))
        results.sort(key=lambda r: r.score, reverse=True)
        for r in results[:top_k]:
            logger.debug("SONA rank %s = %.3f %s", r.id, r.score, r.parts)
        return results[:top_k]


# A registry of MCP tools / agent capabilities that SONA can rank.
# Populated by mcp.py and agents.py at startup.
_CAPABILITY_REGISTRY: List[Sonacandidate] = []


def register_capability(c: Sonacandidate) -> None:
    _CAPABILITY_REGISTRY.append(c)


def rank_for_step(step_text: str, top_k: int = 5) -> List[Sonarank]:
    """Convenience: rank global capability registry for a step."""
    opt = Sonaptimizer()
    return opt.rank(step_text, _CAPABILITY_REGISTRY, top_k=top_k)
