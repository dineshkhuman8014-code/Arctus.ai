"""Arctus.ai FastAPI server.

Runs on port 7860 (Hugging Face Spaces / Docker / cloud). Keys come from
the environment (HF Spaces Secrets), NEVER from forwarded client headers.

Endpoints:
  GET  /                          -> dashboard
  GET  /api/health                -> health
  POST /api/orchestrate           -> run a task (JSON body)
  POST /api/mcp/connect           -> add an MCP connector
  GET  /api/mcp/list              -> list MCP connectors
  DELETE /api/mcp/{name}          -> remove an MCP connector
  GET  /api/agents                -> list the agent roster
  GET  /api/federation/peers      -> list federation peers
  POST /api/federation/peers      -> add a peer (https or localhost only)
  POST /api/federation/submit     -> receive a federated task from a peer
  GET  /api/federation/result/{id} -> fetch a result for a peer

Safety vs. the refused design:
  - No x-omniroute-url / x-omniroute-key forwarding. Provider keys are read
    from env vars on the server (HF Spaces Secrets). Clients send prompts,
    not credentials.
  - MCP stdio connectors are defined in config, not spawned from request bodies.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from arctus import load_config
from arctus.agents import build_roster, roster_summary
from arctus.federation import FederationHub, Peer, FederatedTask
from arctus.mcp import REGISTRY, MCPConnector, add_connector as _add_mcp
from arctus.orchestrator import QueenAgent

logger = logging.getLogger("arctus.server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Arctus.ai Orchestrator", version="1.0.0")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# Singletons
_hub = FederationHub()
_roster = build_roster()


# ---------- models ----------
class OrchestrateRequest(BaseModel):
    prompt: str
    session_id: str = "default"
    complexity_override: Optional[str] = None


class MCPConnectRequest(BaseModel):
    name: str
    config: Dict[str, Any]


class PeerRequest(BaseModel):
    name: str
    base_url: str
    shared_secret: str


# ---------- routes ----------
@app.get("/")
async def dashboard():
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"name": "Arctus.ai", "status": "ok", "dashboard": "missing"})


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/orchestrate")
async def orchestrate(req: OrchestrateRequest):
    cfg = load_config()
    queen = QueenAgent(cfg)
    result = queen.run(
        req.prompt,
        session_id=req.session_id,
        complexity_override=req.complexity_override,
    )
    return {
        "complexity": result.complexity,
        "mode": result.mode,
        "steps": [s.__dict__ for s in result.steps],
        "work": result.work,
        "verification": result.verification,
        "error": result.error,
    }


@app.get("/api/agents")
async def agents():
    return {
        "total": len(_roster),
        "summary": roster_summary(_roster),
        "agents": [a.__dict__ for a in _roster],
    }


# ---- MCP ----
@app.post("/api/mcp/connect")
async def mcp_connect(req: MCPConnectRequest):
    try:
        c = _add_mcp(req.name, req.config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "connected", "server": c.name, "tools": c.tools}


@app.get("/api/mcp/list")
async def mcp_list():
    return {"connectors": [c.__dict__ for c in REGISTRY.list_connectors()]}


@app.delete("/api/mcp/{name}")
async def mcp_delete(name: str):
    ok = REGISTRY.remove_connector(name)
    return {"removed": ok}


# ---- Federation ----
@app.get("/api/federation/peers")
async def fed_peers():
    return {"peers": [p.__dict__ for p in _hub.list_peers()]}


@app.post("/api/federation/peers")
async def fed_add_peer(req: PeerRequest):
    try:
        _hub.add_peer(Peer(name=req.name, base_url=req.base_url,
                           shared_secret=req.shared_secret))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "added", "peer": req.name}


@app.post("/api/federation/submit")
async def fed_submit(req: Request):
    """A peer pushes a task to us. Auth via shared secret."""
    auth = req.headers.get("authorization", "")
    body = await req.json()
    # find the peer whose secret matches
    peer = next((p for p in _hub.list_peers()
                 if f"Bearer {p.shared_secret}" == auth), None)
    if not peer:
        raise HTTPException(status_code=401, detail="unknown peer")
    task = FederatedTask(
        task_id=body["task_id"], prompt=body["prompt"],
        origin=body.get("origin", peer.name),
        submitted_at=__import__("time").time(),
    )
    _hub.submit_local(task)
    return {"status": "queued", "task_id": task.task_id}


@app.get("/api/federation/result/{task_id}")
async def fed_result(task_id: str, request: Request):
    auth = request.headers.get("authorization", "")
    peer = next((p for p in _hub.list_peers()
                 if f"Bearer {p.shared_secret}" == auth), None)
    if not peer:
        raise HTTPException(status_code=401, detail="unknown peer")
    t = _hub.results.get(task_id)
    if not t:
        return {"status": "pending"}
    return {"status": t.status, "result": t.result}


def main() -> None:
    """Run with uvicorn. Port 7860 = HF Spaces default."""
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
