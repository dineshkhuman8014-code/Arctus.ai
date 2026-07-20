#!/usr/bin/env python3
"""Arctus.ai CLI.

Usage:
    python main.py                       # interactive REPL
    python main.py "do something"        # one-shot task
    python main.py config                # show config
    python main.py config-set '{"strong":{"model":"gpt-4o"}}'
    python main.py show <session-id>
    python main.py reset <session-id> [--scope all|history]
    python main.py --help | -h

Everything runs locally. No tunnels, no header forwarding, no remote servers.
Keys come from your environment or ~/.config/arctus-ai/config.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from typing import List, Optional

from arctus import Config, Tier, QueenAgent, RateLimitConfig, load_config, save_config
from arctus import session as session_store


HELP_TEXT = """\
Arctus.ai — local-first multi-agent orchestrator (Plan -> Route -> Execute -> Verify)

Runs entirely on YOUR machine. No tunnels, no remote servers, no credential
forwarding. Your API key stays in your environment.

Commands:
  arctus                      interactive REPL
  arctus "do something"       run a single task and exit
  arctus config               print config + config file path
  arctus config-set '<json>'  merge JSON into config
  arctus show <session-id>    print a saved session
  arctus reset <session-id>   clear a session (--scope all|history)
  arctus --help | -h          this help

Config:  ~/.config/arctus-ai/config.json
Sessions: ~/.config/arctus-ai/sessions/*.json

Tier defaults:
  fast   -> http://localhost:11434/v1   model llama3.2  (Ollama, local)
  strong -> https://api.openai.com/v1   model gpt-4o-mini (set ARCTUS_STRONG_API_KEY)
"""


def _stamp(msg: str) -> str:
    import datetime
    return f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"


def _run_task(prompt: str, cfg: Config, session_id: str) -> None:
    print(_stamp(f"Task: {prompt!r}"))
    queen = QueenAgent(cfg)
    result = queen.run(prompt, session_id=session_id)
    print(_stamp(f"Complexity: {result.complexity} | mode: {result.mode}"))

    if result.error:
        print(_stamp(f"Error: {result.error}"))
        return

    sess = session_store.load(session_id)
    sess["steps"] = [asdict(s) if hasattr(s, "__dataclass_fields__") else s for s in result.steps]
    sess["log"].append({
        "prompt": prompt,
        "complexity": result.complexity,
        "mode": result.mode,
        "work": result.work,
        "verification": result.verification,
        "handoffs": result.handoffs,
    })
    sess["history"].append({"role": "user", "content": prompt})
    for w in result.work:
        sess["history"].append({"role": "assistant", "content": w.get("result", "")})
    session_store.save(sess)

    for w in result.work:
        print(_stamp(f"  [{w.get('tier')}] {w.get('step')} ({w.get('tokens_used', 0)} tok)"))
    if result.verification:
        print(_stamp(f"Verify: done={result.verification.get('done')} — {result.verification.get('notes')}"))
    print("\n=== RESULT ===")
    print("\n\n".join(w.get("result", "") for w in result.work))
    print("==============\n")


def _repl(cfg: Config) -> None:
    print("Arctus.ai REPL. Type a task, or :quit to exit.\n")
    session_id = f"repl-{int(__import__('time').time())}"
    while True:
        try:
            line = input("arctus> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return
        if not line:
            continue
        if line in (":quit", ":q"):
            print("bye.")
            return
        if line == ":reset":
            session_store.reset(session_id, scope="all")
            print(_stamp("session reset"))
            continue
        try:
            _run_task(line, cfg, session_id)
        except Exception as e:
            print(_stamp(f"Error: {e}"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arctus",
        description="Local-first multi-agent orchestrator.",
        add_help=False,
    )
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.help or args.command in (None, "-h", "--help"):
        print(HELP_TEXT)
        return 0

    cfg = load_config()

    if args.command == "config":
        from arctus.config import CONFIG_FILE
        print(f"Config file: {CONFIG_FILE}")
        print(json.dumps(asdict(cfg), indent=2))
        return 0

    if args.command == "config-set":
        if not args.rest:
            print("usage: arctus config-set '<json>'", file=sys.stderr)
            return 2
        try:
            patch = json.loads(" ".join(args.rest))
        except json.JSONDecodeError as e:
            print(f"invalid JSON: {e}", file=sys.stderr)
            return 2
        merged = asdict(cfg)
        for k, v in patch.items():
            if k in ("fast", "strong") and isinstance(v, dict):
                merged[k].update(v)
            else:
                merged[k] = v
        # Re-build dataclasses from merged dict.
        new_cfg = Config(
            fast=Tier(**merged["fast"]),
            strong=Tier(**merged["strong"]),
            **{k: v for k, v in merged.items() if k not in ("fast", "strong")},
        )
        path = save_config(new_cfg)
        print(f"Saved to {path}")
        return 0

    if args.command == "show":
        if not args.rest:
            print("usage: arctus show <session-id>", file=sys.stderr)
            return 2
        print(json.dumps(session_store.load(args.rest[0]), indent=2))
        return 0

    if args.command == "reset":
        if not args.rest:
            print("usage: arctus reset <session-id> [--scope all|history]", file=sys.stderr)
            return 2
        sid = args.rest[0]
        scope = "all"
        if "--scope" in args.rest:
            i = args.rest.index("--scope")
            scope = args.rest[i + 1] if i + 1 < len(args.rest) else "all"
        print(json.dumps(session_store.reset(sid, scope=scope), indent=2))
        return 0

    if args.command == "repl":
        _repl(cfg)
        return 0

    # Anything else = one-shot task (joined).
    prompt = " ".join([args.command] + args.rest).strip()
    _run_task(prompt, cfg, session_id=f"task-{int(__import__('time').time())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
