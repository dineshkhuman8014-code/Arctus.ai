# Arctus.ai

A **local-first** multi-agent orchestration platform.

- **100 specialized agents** (2 coders, 7 testers, 1 security reviewer, planners, validators, researchers, engineers, federation peers, swarm workers, and more)
- **Up to 200 MCP connectors** (HTTP + stdio transports)
- **80% context handoff cycle** — agent summarizes → writes sandbox checkpoint → clears its memory → waits → next agent resumes from summary
- **SONA** — sparse attention optimizer that ranks tools/agents per step
- **Federation** — peer-to-peer task sharing between trusted Arctus instances
- **Glassmorphism dashboard** — FastAPI + HTML/CSS/JS, runs on port 7860
- **Docker** — public container for Hugging Face Spaces + user compose with reference repo volume
- **Provider presets** — OpenRouter, OmniRoute (local/remote), Ollama, OpenAI, Anthropic-via-OpenRouter
- **Zero runtime deps** for the core; FastAPI only for the server

Runs the loop: **Plan → Validate (local) → Execute (strong) → Verify**.

> **Safety note.** This project deliberately does NOT include the `connect.sh` +
> `localtunnel` + `x-omniroute-key` header-forwarding design. Provider keys live
> in your environment (or HF Spaces Secrets), not in forwarded client headers.
> OpenRouter and OmniRoute are fully supported — the normal way: your local
> config holds your key, the orchestrator calls the endpoint directly.

---

## Quick start (3 commands)

```bash
git clone https://github.com/YOUR_USERNAME/arctus-ai.git arctus.ai
cd arctus.ai
pip install -e ".[server]" && python main.py --help
```

Then set a provider key and run:

```bash
# Strong tier (OpenAI default). Use any preset instead — see below.
export ARCTUS_STRONG_API_KEY=sk-...           # macOS/Linux
setx ARCTUS_STRONG_API_KEY "sk-..."           # Windows (new shell after)

python main.py "refactor my parser into a class and add a test plan"
```

---

## Setup commands (full)

### 1. CLI only (local-first)

```bash
git clone https://github.com/YOUR_USERNAME/arctus-ai.git arctus.ai
cd arctus.ai
pip install -e .
export ARCTUS_STRONG_API_KEY=sk-...
python main.py "your task"
```

### 2. Local + dashboard (FastAPI on :7860)

```bash
pip install -e ".[server]"
python -m server.app
# open http://localhost:7860
```

### 3. Docker (with OmniRoute bundled)

```bash
docker build -t arctus-ai .
docker run -p 7860:7860 -p 20128:20128 -e OPENAI_API_KEY=sk-... arctus-ai
# :7860  = Arctus dashboard / API
# :20128 = OmniRoute (local 160+ provider router, pre-installed)
# open http://localhost:7860
```

OmniRoute is installed from npm (`omniroute`) at build time and auto-starts
inside the container. The fast tier points at `http://localhost:20128/v1` by
default. Configure OmniRoute providers via `~/.config/omniroute/config.json`.

### 4. Docker Compose (OmniRoute + reference repos)

```bash
# Once: fetch the 12 reference repos into ./repos (opt-in)
python scripts/clone_repos.py

# Your keys in .env (see docker-compose.yml)
echo "OPENAI_API_KEY=sk-..." > .env

docker compose up
# :7860  = Arctus dashboard
# :20128 = OmniRoute
```

### 5. Hugging Face Spaces

Push this repo to a HF Space (Docker SDK type). In **Settings → Secrets** add:

```
OPENAI_API_KEY        = sk-...
OPENROUTER_API_KEY    = sk-or-...     (if using OpenRouter)
ARCTUS_OMNIROUTE_KEY  = ...           (if using OmniRoute)
```

The server reads them from env. **No client headers carry keys.**

---

## Provider presets

```bash
python -c "from arctus import presets; presets.apply_preset('openrouter')"
python -c "from arctus import presets; presets.apply_preset('omniroute_local')"
python -c "from arctus import presets; presets.apply_preset('ollama')"
python -c "from arctus import presets; presets.apply_preset('openai')"
```

Env vars (take precedence): `OPENROUTER_API_KEY`, `OMNIROUTE_API_KEY`,
`ARCTUS_OMNIROUTE_KEY`, `OPENAI_API_KEY`, `ARCTUS_FAST_*`, `ARCTUS_STRONG_*`.

---

## CLI usage

```bash
python main.py                       # interactive REPL
python main.py "do something"        # one-shot task
python main.py config                # show config
python main.py config-set '<json>'   # merge settings
python main.py show <session-id>     # view saved session
python main.py reset <session-id> --scope all
python main.py -v "task"             # verbose logging
```

REPL keys: type a task + Enter · `:reset` to clear · `:quit` to exit.

---

## Programmatic use

```python
from arctus import Config, QueenAgent, build_roster, mcp, presets

presets.apply_preset("openrouter")          # strong tier -> OpenRouter
cfg = Config()
roster = build_roster()                      # 100 agents
print(len(roster), "agents available")

# Add an MCP connector (HTTP transport)
mcp.add_connector("github", {
    "transport": "http",
    "url": "https://mcp.example.com/jsonrpc",
    "tools": ["search", "read"],
})

queen = QueenAgent(cfg)
result = queen.run("refactor auth + add tests", session_id="job-1")
for w in result.work:
    print(w["step"], "->", w["result"][:80])
```

---

## The 80% handoff cycle

```
Agent A runs steps… crosses 80% of its context budget
   ├─ fires a small local-model call to summarize (done / next)
   ├─ writes the summary into the sandbox state file
   ├─ clears its OWN in-memory history (frees tokens)
   └─ WAITS
Agent B starts with a FRESH budget, reads the summary, continues.
   When B crosses 80%, the cycle repeats.
```

Only the summary crosses the boundary — never the full raw history. "Sandbox"
here = a state directory + memory clear, not an OS-level jail. For OS-level
isolation, run each agent in its own container.

---

## Federation

```python
from arctus.federation import FederationHub, Peer, FederatedTask
import time

hub = FederationHub()
# https only (or http://localhost). No plain http over the internet.
hub.add_peer(Peer(
    name="lab-box",
    base_url="https://lab.example.com",
    shared_secret="long-random-secret",
))
hub.push_to_peer("lab-box", FederatedTask(
    task_id="t1", prompt="summarize this repo", origin="me",
    submitted_at=time.time(),
))
```

---

## Layout

```
arctus.ai/
├── arctus/
│   ├── __init__.py        # public API
│   ├── config.py          # Config, Tier (env + JSON)
│   ├── llm.py             # OpenAI-compatible client (stdlib urllib)
│   ├── orchestrator.py    # QueenAgent: Plan -> Validate -> Execute -> Verify
│   ├── agents.py          # 100-agent roster
│   ├── mcp.py             # up to 200 MCP connectors
│   ├── sona.py            # sparse attention optimizer (tool/agent ranking)
│   ├── federation.py      # peer-to-peer task sharing
│   ├── sandbox.py         # 80% handoff cycle with summarization
│   ├── context.py         # IsolatedContextWindow, StateDir
│   ├── session.py         # file-backed sessions
│   ├── rate_limit.py      # per-session rolling 60s window
│   └── presets.py         # OpenRouter / OmniRoute / Ollama / OpenAI
├── server/
│   └── app.py             # FastAPI on :7860, MCP + federation endpoints
├── web/
│   ├── index.html         # glassmorphism dashboard
│   ├── style.css
│   └── app.js
├── scripts/
│   └── clone_repos.py     # opt-in fetch of the 12 reference repos
├── repos.yaml             # the 12 third-party repos (opt-in)
├── Dockerfile             # public non-root container (port 7860)
├── docker-compose.yml     # user compose with reference repo volume
├── main.py                # CLI + REPL
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Reference repos (opt-in)

12 third-party repos are listed in `repos.yaml`. They are NOT cloned
automatically. Run once:

```bash
python scripts/clone_repos.py
```

They land in `./repos/` and are mounted **read-only** into the Docker container
so agents can read them as grounding material. You are responsible for
respecting each repo's license.

---

## Safety

- No network listener is opened by the CLI. The CLI only makes **outbound**
  calls to the model endpoints you configured.
- The FastAPI server listens on port 7860 (you opted into it by running it).
- Provider keys come from your env (or HF Spaces Secrets). No client-supplied
  key headers are read or forwarded.
- MCP stdio connectors run commands YOU listed in config — never commands
  derived from HTTP request bodies.
- Federation peers must be explicitly added by URL (https or localhost only)
  with a shared secret. No anonymous discovery.

---

## License

MIT.
