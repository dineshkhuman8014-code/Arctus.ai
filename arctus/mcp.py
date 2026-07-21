"""MCP (Model Context Protocol) connector registry.

Supports up to 200 MCP servers per orchestrator. Two transports:

  1. http:  a remote MCP-over-HTTP server (POST JSON-RPC to its URL).
  2. stdio: a local command (subprocess) speaking JSON-RPC over stdin/stdout.

This is a thin, dependency-free client. It does NOT spawn arbitrary commands
without explicit user opt-in: stdio connectors must be listed in config or
added via the explicit add_connector() API (and via /api/mcp/connect from the
dashboard). The server never auto-runs connector commands from request bodies.

A "connector" is a record. Calling a tool does a real JSON-RPC round-trip.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import sona

logger = logging.getLogger("arctus.mcp")

MAX_CONNECTORS = 200


@dataclass
class MCPConnector:
    name: str
    transport: str            # "http" | "stdio"
    # http:
    url: str = ""
    api_key: str = ""
    # stdio:
    command: str = ""         # exact command, user-provided
    env: Dict[str, str] = field(default_factory=dict)
    # runtime:
    tools: List[str] = field(default_factory=list)
    enabled: bool = True


class MCPRegistry:
    """Registry of MCP connectors with SONA-aware tool ranking."""

    def __init__(self) -> None:
        self._connectors: Dict[str, MCPConnector] = {}
        self._lock = threading.Lock()
        # one long-lived subprocess per stdio connector (lazy spawn)
        self._procs: Dict[str, subprocess.Popen] = {}

    def add_connector(self, c: MCPConnector) -> None:
        with self._lock:
            if len(self._connectors) >= MAX_CONNECTORS:
                raise RuntimeError(f"Max connectors reached ({MAX_CONNECTORS})")
            if c.transport not in ("http", "stdio"):
                raise ValueError(f"Unknown transport: {c.transport}")
            self._connectors[c.name] = c
            # Register each tool with SONA so the planner can rank it.
            for tool in c.tools:
                sona.register_capability(sona.Sonacandidate(
                    id=f"{c.name}.{tool}", description=tool,
                    base_cost=1.0, keywords=tool.split("_"),
                ))
            logger.info("MCP connector added: %s (%s, %d tools)",
                        c.name, c.transport, len(c.tools))

    def remove_connector(self, name: str) -> bool:
        with self._lock:
            c = self._connectors.pop(name, None)
            if c and c.transport == "stdio" and name in self._procs:
                try:
                    self._procs[name].terminate()
                except Exception:
                    pass
                self._procs.pop(name, None)
            return c is not None

    def list_connectors(self) -> List[MCPConnector]:
        with self._lock:
            return list(self._connectors.values())

    def get(self, name: str) -> Optional[MCPConnector]:
        return self._connectors.get(name)

    # ---- tool calling -----------------------------------------------------

    def call_tool(self, connector_name: str, tool_name: str,
                  arguments: Optional[Dict[str, Any]] = None) -> Any:
        c = self.get(connector_name)
        if not c or not c.enabled:
            raise KeyError(f"connector {connector_name!r} not found or disabled")
        if c.transport == "http":
            return self._call_http(c, tool_name, arguments or {})
        return self._call_stdio(c, tool_name, arguments or {})

    def _call_http(self, c: MCPConnector, tool_name: str, args: Dict[str, Any]) -> Any:
        payload = {
            "jsonrpc": "2.0", "id": uuid.uuid4().hex[:8],
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        headers = {"Content-Type": "application/json"}
        if c.api_key:
            headers["Authorization"] = f"Bearer {c.api_key}"
        req = urllib.request.Request(
            c.url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"MCP http {c.name} HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"MCP http {c.name} unreachable: {e.reason}") from None
        if "error" in data:
            raise RuntimeError(f"MCP {c.name}.{tool_name}: {data['error']}")
        return data.get("result")

    def _call_stdio(self, c: MCPConnector, tool_name: str, args: Dict[str, Any]) -> Any:
        # Spawn-on-demand; in production you'd keep a persistent proc and
        # newline-delimited JSON framing. This is a safe minimal version.
        if not c.command:
            raise RuntimeError(f"stdio connector {c.name} has no command")
        env = dict(os.environ)
        env.update(c.env)
        payload = {
            "jsonrpc": "2.0", "id": "1",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        try:
            proc = subprocess.run(
                c.command, shell=False, input=json.dumps(payload),
                capture_output=True, text=True, timeout=60, env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"MCP stdio {c.name} timed out") from None
        except FileNotFoundError:
            raise RuntimeError(f"MCP stdio {c.name}: command not found: {c.command}") from None
        if proc.returncode != 0:
            raise RuntimeError(
                f"MCP stdio {c.name} exited {proc.returncode}: {proc.stderr[:200]}"
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"MCP stdio {c.name}: non-JSON stdout") from None
        if "error" in data:
            raise RuntimeError(f"MCP {c.name}.{tool_name}: {data['error']}")
        return data.get("result")


# module-level singleton
REGISTRY = MCPRegistry()


def add_connector(name: str, config: Dict[str, Any]) -> MCPConnector:
    """Convenience for the FastAPI /api/mcp/connect endpoint."""
    transport = config.get("transport", "http")
    c = MCPConnector(
        name=name,
        transport=transport,
        url=config.get("url", ""),
        api_key=config.get("api_key", ""),
        command=config.get("command", ""),
        env=config.get("env", {}),
        tools=config.get("tools", []),
    )
    REGISTRY.add_connector(c)
    return c
