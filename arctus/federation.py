"""Federation — peer-to-peer work distribution across Arctus instances.

Lets multiple Arctus orchestrators (your laptop, a server, a friend's box)
share a work queue over HTTP. Designed for trusted peers only — peer URLs
are explicitly registered, no discovery, no anonymous join.

Security model:
  - Peers are added explicitly by URL.
  - All peer URLs must be https:// (or http://localhost) — never plain http
    over the internet.
  - Each peer shares a pre-shared secret in the Authorization header.
  - A peer can push tasks TO you and pull results FROM you, but cannot read
    your arbitrary local files — only the task results you choose to share.

This is NOT the localtunnel design. No public tunnel, no forwarded user key.
Each Arctus instance keeps its own keys local.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("arctus.federation")

MAX_PEERS = 32


@dataclass
class Peer:
    name: str
    base_url: str           # e.g. https://peer.example.com
    shared_secret: str
    enabled: bool = True


@dataclass
class FederatedTask:
    task_id: str
    prompt: str
    origin: str
    submitted_at: float
    status: str = "pending"   # pending | running | done | failed
    result: Optional[Any] = None


def _validate_peer_url(url: str) -> None:
    """Reject anything that isn't https or localhost http."""
    url_l = url.lower()
    if url_l.startswith("https://"):
        return
    if url_l.startswith("http://localhost") or url_l.startswith("http://127.0.0.1"):
        return
    raise ValueError(
        f"Peer URL must be https:// (or http://localhost). Got: {url!r}"
    )


class FederationHub:
    """In-process registry + queue for federated peers."""

    def __init__(self) -> None:
        self.peers: Dict[str, Peer] = {}
        self.queue: List[FederatedTask] = []
        self.results: Dict[str, FederatedTask] = {}
        self._lock = threading.Lock()

    def add_peer(self, peer: Peer) -> None:
        if len(self.peers) >= MAX_PEERS:
            raise RuntimeError(f"Max peers reached ({MAX_PEERS})")
        _validate_peer_url(peer.base_url)
        self.peers[peer.name] = peer
        logger.info("Federation peer added: %s -> %s", peer.name, peer.base_url)

    def remove_peer(self, name: str) -> bool:
        with self._lock:
            return self.peers.pop(name, None) is not None

    def list_peers(self) -> List[Peer]:
        return list(self.peers.values())

    def submit_local(self, task: FederatedTask) -> None:
        with self._lock:
            self.queue.append(task)

    def claim_next(self) -> Optional[FederatedTask]:
        with self._lock:
            for t in self.queue:
                if t.status == "pending":
                    t.status = "running"
                    return t
            return None

    def complete(self, task_id: str, result: Any, ok: bool = True) -> None:
        with self._lock:
            for t in self.queue:
                if t.task_id == task_id:
                    t.status = "done" if ok else "failed"
                    t.result = result
                    self.results[task_id] = t
                    return

    def push_to_peer(self, peer_name: str, task: FederatedTask) -> bool:
        """Push a task to a remote peer over HTTP."""
        peer = self.peers.get(peer_name)
        if not peer or not peer.enabled:
            return False
        url = peer.base_url.rstrip("/") + "/api/federation/submit"
        body = json.dumps({
            "task_id": task.task_id, "prompt": task.prompt, "origin": task.origin,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {peer.shared_secret}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            logger.info("Pushed task %s to peer %s", task.task_id, peer_name)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.warning("Push to %s failed: %s", peer_name, e)
            return False

    def pull_result_from_peer(self, peer_name: str, task_id: str) -> Optional[Any]:
        peer = self.peers.get(peer_name)
        if not peer or not peer.enabled:
            return None
        url = f"{peer.base_url.rstrip('/')}/api/federation/result/{task_id}"
        req = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": f"Bearer {peer.shared_secret}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("result")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.warning("Pull from %s failed: %s", peer_name, e)
            return None
