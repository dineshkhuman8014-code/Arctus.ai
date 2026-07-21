"""Sandbox + handoff cycle.

Implements the loop you described:

  1. Agent works in its own isolated state dir ("sandbox").
  2. When it crosses 80% of its context budget, it pauses.
  3. It fires up a SMALL local-model call to summarize:
        - what it has done
        - what the next agent must do
  4. It writes that summary into the sandbox state file.
  5. It clears its OWN in-memory history (frees tokens) and WAITS.
  6. The next agent starts with a FRESH budget, reads the sandbox summary,
     and continues. When IT hands off, the cycle repeats.

This is a clean cycle, not a leak: only the summary crosses the boundary,
never the full raw history. "Sandbox" here is a state directory + memory
clear, not an OS-level jail. If you need OS-level isolation, run each agent
in its own container.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import llm
from .config import Config, Tier
from .context import IsolatedContextWindow, StateDir

logger = logging.getLogger("arctus.sandbox")

HANDOFF_RATIO = 0.80


@dataclass
class HandoffSummary:
    done: str
    next_steps: str
    paused_agent: str
    target_agent: str
    at: float = field(default_factory=time.time)


SUMMARY_SYSTEM = (
    "You are the Handoff Summarizer for Arctus.ai. Given an agent's raw work "
    "log, produce a tight handoff note in STRICT JSON:\n"
    '{"done": "<what was completed, bullets>", '
    '"next": "<what the next agent must do, bullets>"}'
)


def summarize_for_handoff(
    cfg: Config, agent_id: str, work_log: List[str]
) -> Dict[str, str]:
    """Call the fast/local tier to compress a work log into a handoff note."""
    blob = "\n---\n".join(work_log[-6:]) if work_log else "(no work yet)"
    tier = cfg.fast
    try:
        out = llm.chat(tier, [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": f"Agent {agent_id} work log:\n{blob}"},
        ])
        cleaned = out.replace("```json", "").replace("```", "").strip()
        s = cleaned.find("{")
        e = cleaned.rfind("}")
        if s != -1 and e != -1:
            return json.loads(cleaned[s : e + 1])
    except Exception as e:
        logger.warning("handoff summarize failed (%s); using raw tail", e)
    # Fallback: crude tail-based summary, no model call.
    tail = work_log[-1] if work_log else "(none)"
    return {"done": tail[:500], "next": "continue from where the log ends"}


class SandboxCycle:
    """Drives the plan -> execute -> (handoff?) -> resume loop.

    Usage:
        cycle = SandboxCycle(cfg, session_id="job-1")
        cycle.run(steps_from_planner)
    """

    def __init__(self, cfg: Config, session_id: str = "default") -> None:
        self.cfg = cfg
        self.session_id = session_id
        self.agent_seq = 0
        self.handoffs: List[HandoffSummary] = []

    def _next_agent_id(self) -> str:
        self.agent_seq += 1
        return f"{self.session_id}-agent-{self.agent_seq:02d}"

    def _execute_step(
        self,
        agent_id: str,
        tier: Tier,
        system: str,
        step_text: str,
        context_summary: str,
        budget: IsolatedContextWindow,
        history: List[Dict[str, str]],
    ) -> str:
        messages = [{"role": "system", "content": system}]
        # Carry only the compact summary forward, not the full raw history.
        if context_summary:
            messages.append({"role": "user", "content": f"Prior handoff note:\n{context_summary}"})
        messages.append({"role": "user", "content": step_text})

        # Pre-flight estimate.
        prompt_chars = sum(len(m["content"]) for m in messages)
        budget.consume(max(1, prompt_chars // 4))

        result = llm.chat(tier, messages)
        budget.consume(max(1, len(result) // 4))
        history.append({"role": "assistant", "content": result, "agent": agent_id})
        return result

    def run(self, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run the full step list with the 80% handoff cycle."""
        results: List[Dict[str, Any]] = []
        context_summary = ""
        work_log: List[str] = []
        history: List[Dict[str, str]] = []

        for i, step in enumerate(steps, 1):
            tier_name = step.get("tier", "fast")
            tier = getattr(self.cfg, tier_name)
            system = (
                "You are a focused worker agent for Arctus.ai. "
                "Do exactly what the step asks. Be concise."
            )
            agent_id = self._next_agent_id()
            budget = IsolatedContextWindow(
                agent_id=agent_id,
                max_tokens=self.cfg.agent_context_limit,
            )
            state = StateDir(agent_id=agent_id, session_id=self.session_id)

            step_text = f"Step {i}/{len(steps)}: {step.get('title','')}\n{step.get('detail','')}"
            logger.info("Cycle: step %d -> agent %s (tier=%s)", i, agent_id, tier_name)

            try:
                out = self._execute_step(
                    agent_id, tier, system, step_text, context_summary,
                    budget, history,
                )
            except llm.LLMError as e:
                results.append({"step": i, "error": str(e)})
                logger.error("step %d failed: %s", i, e)
                break

            work_log.append(f"[{agent_id}] {out}")
            results.append({
                "step": i, "title": step.get("title", ""),
                "agent": agent_id, "tier": tier_name,
                "tokens_used": budget.used_tokens,
                "result": out,
            })

            # ---- 80% handoff rule ----
            if budget.used_tokens >= budget.handoff_limit:
                logger.warning("Agent %s hit 80%% (%d/%d) — handing off",
                               agent_id, budget.used_tokens, budget.max_tokens)

                # 3. small local-model summary
                note = summarize_for_handoff(self.cfg, agent_id, work_log)
                h = HandoffSummary(
                    done=note.get("done", ""),
                    next_steps=note.get("next", ""),
                    paused_agent=agent_id,
                    target_agent=self._next_agent_id(),  # reserve next id
                )
                self.handoffs.append(h)

                # 4. write summary into sandbox state
                state.write_checkpoint(
                    done=h.done, next_steps=h.next_steps,
                    context={
                        "tokens_used": budget.used_tokens,
                        "max_tokens": budget.max_tokens,
                        "step_index": i,
                        "total_steps": len(steps),
                        "raw_tail": work_log[-1][-1000:],
                    },
                )

                # 5. clear THIS agent's memory and wait for next
                context_summary = (
                    f"Previous agent ({h.paused_agent}) handed off.\n"
                    f"DONE: {h.done}\nNEXT: {h.next_steps}"
                )
                history = []  # cleared
                work_log = []  # cleared
                logger.info("Agent %s memory cleared; next agent continues from summary",
                            agent_id)

        return {
            "session_id": self.session_id,
            "steps_run": len(results),
            "results": results,
            "handoffs": [h.__dict__ for h in self.handoffs],
        }
