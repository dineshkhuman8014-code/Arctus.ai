"""Agent roster — 60 to 100 specialized agents.

Composition (100 agents):
  - 2 coders              (primary, multi-file refactors)
  - 7 testers             (unit/integration/e2e/security/perf/fuzz/property)
  - 1 security reviewer
  - 5 planners / coordinators
  - 10 validators         (lint, types, format, schema, contract)
  - 10 researchers        (web, docs, repo mining, dep analysis)
  - 10 engineers          (frontend, backend, infra, db, ml, data, ...)
  - 8 analysts            (perf, cost, risk, requirements, root-cause)
  - 5 reviewers           (code review, design review, PR review)
  - 4 docs writers
  - 3 devops              (CI/CD, release, monitoring)
  - 2 data engineers
  - 2 ml engineers
  - 2 sre
  - 2 product
  - 2 qa leads
  - 5 federation peers    (cross-instance work, see federation.py)
  - 10 swarm workers      (generic parallel capacity)
  - 10 spares / on-call

Each agent is a typed slot, not a free-form LLM call. Roster is generated
deterministically so the same config always yields the same team.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import Config, Tier

logger = logging.getLogger("arctus.agents")


@dataclass
class AgentSpec:
    id: str
    role: str
    category: str
    tier: str = "fast"        # "fast" | "strong"
    system_prompt: str = ""
    tools: List[str] = field(default_factory=list)  # MCP tool names this agent may call


CODER_SYSTEM = (
    "You are a Coder agent for Arctus.ai. You make focused, minimal, correct "
    "code changes. You never invent APIs. You read before you write. You "
    "prefer small diffs. When done, you state exactly what you changed."
)

TESTER_SYSTEM = (
    "You are a Tester agent for Arctus.ai. You write tests that fail on the "
    "bug and pass on the fix. You prefer behavior over coverage numbers."
)

SECURITY_SYSTEM = (
    "You are the Security Reviewer for Arctus.ai. You look for injection, "
    "auth bypass, secret leakage, unsafe deserialization, SSRF, and path "
    "traversal. You report findings by severity with file:line references."
)


def _expand(prefix: str, count: int, category: str, tier: str = "fast",
            system: str = "", tools: Optional[List[str]] = None) -> List[AgentSpec]:
    out = []
    for i in range(1, count + 1):
        out.append(AgentSpec(
            id=f"{prefix}-{i:02d}",
            role=prefix,
            category=category,
            tier=tier,
            system_prompt=system,
            tools=list(tools or []),
        ))
    return out


def build_roster() -> List[AgentSpec]:
    """Build the default 100-agent roster."""
    roster: List[AgentSpec] = []
    roster += _expand("coder", 2, "primary", "strong", CODER_SYSTEM)
    roster += _expand("tester", 7, "test", "fast", TESTER_SYSTEM, tools=["run_tests"])
    roster += _expand("security-reviewer", 1, "security", "strong", SECURITY_SYSTEM, tools=["scan"])
    roster += _expand("planner", 5, "planning", "strong")
    roster += _expand("validator", 10, "validation", "fast", tools=["lint", "typecheck", "format"])
    roster += _expand("researcher", 10, "research", "fast", tools=["web_search", "read_repo"])
    roster += _expand("engineer", 10, "engineering", "strong")
    roster += _expand("analyst", 8, "analysis", "fast")
    roster += _expand("reviewer", 5, "review", "strong")
    roster += _expand("docs", 4, "docs", "fast")
    roster += _expand("devops", 3, "devops", "strong")
    roster += _expand("data-engineer", 2, "data", "strong")
    roster += _expand("ml-engineer", 2, "ml", "strong")
    roster += _expand("sre", 2, "sre", "strong")
    roster += _expand("product", 2, "product", "fast")
    roster += _expand("qa-lead", 2, "qa", "fast")
    roster += _expand("federation-peer", 5, "federation", "fast")
    roster += _expand("swarm-worker", 10, "swarm", "fast")
    roster += _expand("oncall", 10, "spare", "fast")
    return roster


def roster_summary(roster: List[AgentSpec]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for a in roster:
        counts[a.role] = counts.get(a.role, 0) + 1
    return counts


def pick(roster: List[AgentSpec], role: str) -> Optional[AgentSpec]:
    """Return the first available agent of a role."""
    for a in roster:
        if a.role == role:
            return a
    return None


def tier_for_agent(cfg: Config, agent: AgentSpec) -> Tier:
    return getattr(cfg, agent.tier)
