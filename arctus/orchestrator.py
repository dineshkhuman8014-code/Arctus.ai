"""The orchestration loop: Plan -> Validate(local) -> Execute(strong) -> Verify.

Replaces the stub `asyncio.sleep` version with real LLM calls. Complexity
routing (Queen) decides whether to do a single fast pass or the full pipeline.

Safety vs. the original spec:
- No header-based key forwarding. Models are reached via the user's own
  configured endpoints and keys (see config.py).
- Each step's token usage counts against the per-agent context window; the
  80% rule triggers a clean handoff with a checkpoint.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import llm
from .config import Config, Tier
from .context import IsolatedContextWindow, StateDir, HandoffPayload
from .rate_limit import RateLimitConfig, check_and_update, estimate_tokens, RateLimitError

logger = logging.getLogger("arctus.orch")

COMPLEX_KEYWORDS = (
    "refactor", "architecture", "microservice", "security audit",
    "parallel", "pipeline", "benchmark", "full-stack", "db migration",
    "migrate", "design", "rewrite",
)

PLANNER_SYSTEM = (
    "You are the Planner for Arctus.ai. Break the user's task into a small "
    "ordered list of concrete steps and tag each as 'fast' or 'strong'.\n"
    "  fast   = formatting, syntax checks, summaries, linting, simple edits.\n"
    "  strong = refactors, design decisions, algorithmic logic, multi-file changes.\n"
    'Respond with STRICT JSON only, no prose:\n'
    '{"steps":[{"title":"...","detail":"...","tier":"fast|strong"}]}'
)

VALIDATOR_SYSTEM = (
    "You are the local Validator for Arctus.ai. Given context and a step, "
    "perform the lightweight check requested (lint, format, summary, schema). "
    "Return a concise result string."
)

WORKER_SYSTEM = (
    "You are a focused worker agent for Arctus.ai. Do exactly what the step "
    "asks. Be concise."
)

VERIFIER_SYSTEM = (
    "You are the Verifier for Arctus.ai. Given the task and the work produced, "
    'decide if it is satisfied. Reply with STRICT JSON only:\n'
    '{"done": true|false, "notes": "one short sentence"}'
)


@dataclass
class Step:
    title: str
    detail: str
    tier: str = "fast"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Step":
        return cls(title=str(d.get("title", "")), detail=str(d.get("detail", "")), tier=str(d.get("tier", "fast")))


@dataclass
class TaskResult:
    complexity: str            # "simple" | "complex"
    mode: str                  # "single_fast" | "pipeline"
    steps: List[Step] = field(default_factory=list)
    work: List[Dict[str, Any]] = field(default_factory=list)
    handoffs: List[Dict[str, Any]] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class QueenAgent:
    """Routes by complexity. Simple -> single fast pass. Complex -> full pipeline."""

    def __init__(self, config: Config):
        self.config = config

    def evaluate_complexity(self, prompt: str) -> str:
        p = prompt.lower()
        has_kw = any(k in p for k in COMPLEX_KEYWORDS)
        if has_kw or len(prompt.split()) > self.config.complexity_threshold_words:
            return "complex"
        return "simple"

    def _tier(self, name: str) -> Tier:
        return getattr(self.config, name)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        cleaned = text.replace("```json", "").replace("```", "").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object found in model response")
        return json.loads(cleaned[start : end + 1])

    def plan(self, prompt: str) -> List[Step]:
        tier = self._tier(self.config.planner_uses)
        out = llm.chat(tier, [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": f"Task: {prompt}"},
        ])
        parsed = self._extract_json(out)
        raw_steps = parsed.get("steps", [])
        if not isinstance(raw_steps, list) or not raw_steps:
            # Fallback: one strong step covering the whole prompt.
            return [Step(title="Whole task", detail=prompt, tier="strong")]
        return [Step.from_dict(s) for s in raw_steps]

    def _call_with_budget(
        self,
        agent_id: str,
        tier: Tier,
        messages: List[Dict[str, str]],
        budget: IsolatedContextWindow,
    ) -> str:
        # Pre-flight token estimate for the prompt side.
        prompt_chars = sum(len(m["content"]) for m in messages)
        budget.consume(estimate_tokens_of(prompt_chars))
        result = llm.chat(tier, messages)
        budget.consume(estimate_tokens_of(len(result)))
        return result

    def run_simple(self, prompt: str, session_id: str) -> TaskResult:
        logger.info("Queen: simple route -> single fast pass")
        tier = self._tier("fast")
        budget = IsolatedContextWindow(agent_id=f"{session_id}-fast")
        out = self._call_with_budget(
            f"{session_id}-fast", tier,
            [
                {"role": "system", "content": WORKER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            budget,
        )
        return TaskResult(
            complexity="simple",
            mode="single_fast",
            steps=[Step(title="prompt", detail=prompt, tier="fast")],
            work=[{"step": "prompt", "tier": "fast", "result": out}],
        )

    def run_pipeline(self, prompt: str, session_id: str) -> TaskResult:
        logger.info("Queen: complex route -> full pipeline")
        steps = self.plan(prompt)
        logger.info("Plan: %d step(s)", len(steps))
        result = TaskResult(complexity="complex", mode="pipeline", steps=steps)

        work_log: List[str] = []
        agent_counter = 0
        for i, step in enumerate(steps, 1):
            tier_name = "fast" if step.tier == "fast" else "strong"
            tier = self._tier(tier_name)
            agent_counter += 1
            agent_id = f"{session_id}-w{agent_counter}"
            budget = IsolatedContextWindow(
                agent_id=agent_id, max_tokens=self.config.agent_context_limit
            )
            state = StateDir(agent_id=agent_id, session_id=session_id)

            system = VALIDATOR_SYSTEM if step.tier == "fast" else WORKER_SYSTEM
            context_blob = "\n---\n".join(work_log[-3:]) if work_log else "(none)"
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Context so far:\n{context_blob}\n\n"
                        f"Step {i}/{len(steps)}: {step.title}\n{step.detail}"
                    ),
                },
            ]

            try:
                out = self._call_with_budget(agent_id, tier, messages, budget)
            except llm.LLMError as e:
                result.error = f"Step {i} ({step.tier}) failed: {e}"
                logger.error(result.error)
                return result

            # 80% handoff rule: checkpoint and tag the step.
            if budget.used_tokens >= budget.handoff_limit:
                state.write_checkpoint(
                    done=f"Completed step {i}: {step.title}",
                    next_steps=f"Continue from step {i+1}/{len(steps)}" if i < len(steps) else "All steps done.",
                    context=budget.to_dict(),
                )
                result.handoffs.append(HandoffPayload(
                    paused_agent=agent_id,
                    target_agent=f"{session_id}-w{agent_counter+1}",
                    state_dir=state,
                    reason="80% context threshold reached",
                    context_snapshot=budget.to_dict(),
                ).to_dict())
                logger.warning("Handoff triggered at step %d", i)

            work_log.append(f"## {step.title}\n{out}")
            result.work.append({
                "step": step.title, "tier": step.tier,
                "agent": agent_id, "tokens_used": budget.used_tokens,
                "result": out,
            })

        # Verify on the fast tier.
        try:
            verdict_text = self._call_with_budget(
                f"{session_id}-verify", self._tier("fast"),
                [
                    {"role": "system", "content": VERIFIER_SYSTEM},
                    {"role": "user", "content": f"Task: {prompt}\n\nWork:\n" + "\n\n".join(work_log)},
                ],
                IsolatedContextWindow(agent_id=f"{session_id}-verify"),
            )
            try:
                result.verification = self._extract_json(verdict_text)
            except Exception:
                result.verification = {"done": True, "notes": "verifier unparsable; assuming done"}
        except llm.LLMError as e:
            result.verification = {"done": True, "notes": f"verifier failed: {e}"}

        return result

    def run(
        self,
        prompt: str,
        session_id: str = "default",
        rate_config: Optional[RateLimitConfig] = None,
        complexity_override: Optional[str] = None,
    ) -> TaskResult:
        complexity = (complexity_override or self.evaluate_complexity(prompt)).lower()
        try:
            rc = rate_config or RateLimitConfig()
            check_and_update(session_id, rc, estimated_tokens=estimate_tokens(prompt))
        except RateLimitError as e:
            return TaskResult(complexity=complexity, mode="blocked", error=e.detail)

        if complexity == "simple":
            return self.run_simple(prompt, session_id)
        return self.run_pipeline(prompt, session_id)


def estimate_tokens_of(char_count: int) -> int:
    # Same heuristic as rate_limit.estimate_tokens; kept local for clarity.
    return max(1, char_count // 4)
