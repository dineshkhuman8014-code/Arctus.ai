#!/usr/bin/env python3
"""Opt-in clone of the 12 third-party reference repos.

Run once locally:
    python scripts/clone_repos.py

Pulls each repo in repos.yaml into ./repos/<name> (shallow clone, depth 1).
Existing dirs are skipped. Agents can then read from ./repos as grounding.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
REPOS_YAML = ROOT / "repos.yaml"
DEST = ROOT / "repos"


def parse_yaml_simple(text: str):
    """Fallback minimal YAML parser for THIS file's shape (no PyYAML needed)."""
    repos = []
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped == "repos:":
            continue
        if line.startswith("  - "):
            if cur:
                repos.append(cur)
            cur = {}
            stripped2 = stripped[2:].strip()
            if stripped2.startswith("name:"):
                cur["name"] = stripped2.split(":", 1)[1].strip()
        elif cur is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            cur[k.strip()] = v.strip().strip('"').strip("'")
    if cur:
        repos.append(cur)
    return repos


def main() -> int:
    if not REPOS_YAML.exists():
        print(f"missing {REPOS_YAML}", file=sys.stderr)
        return 1
    text = REPOS_YAML.read_text(encoding="utf-8")
    if yaml:
        data = yaml.safe_load(text)
        repos = data.get("repos", []) if data else []
    else:
        repos = parse_yaml_simple(text)

    DEST.mkdir(parents=True, exist_ok=True)
    print(f"Cloning {len(repos)} repos into {DEST} (shallow)…\n")

    ok, fail = 0, 0
    for r in repos:
        name = r.get("name")
        url = r.get("url")
        if not name or not url:
            continue
        target = DEST / name
        if target.exists():
            print(f"  skip  {name} (exists)")
            ok += 1
            continue
        print(f"  clone {name} <- {url}")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(target)],
                check=True,
                capture_output=True,
            )
            ok += 1
        except FileNotFoundError:
            print("    git not installed — aborting.", file=sys.stderr)
            return 2
        except subprocess.CalledProcessError as e:
            print(f"    FAILED: {e.stderr.decode(errors='ignore').strip()}")
            fail += 1
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)

    print(f"\nDone. ok={ok} fail={fail}")
    print("Agents can read from ./repos (mounted read-only in docker-compose).")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
