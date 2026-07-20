# Arctus.ai (Python)

A **local-first** multi-agent orchestrator. Standard library only — zero
runtime third-party dependencies.

Runs the loop you wanted — **Plan → Validate (local/fast) → Execute (strong) → Verify** —
entirely on your machine. No tunnels, no Hugging Face relay, no `x-omniroute-key`
header forwarding, no `connect.sh` opening public tunnels to your machine. Your
API keys stay in your own environment.

## What it keeps from the original spec

The genuinely good parts of the pasted Python are here, fixed and wired to real
LLM calls instead of `asyncio.sleep` stubs:

- **Queen complexity routing** — short/simple prompts get a single fast pass;
  complex prompts get the full pipeline.
- **Planner agent** — decomposes a task into ordered steps tagged `fast`/`strong`.
- **Isolated context windows** — each agent gets its own token budget; no
  cross-agent bleeding.
- **80% handoff rule** — when an agent crosses 80% of its budget, it writes a
  checkpoint and hands off to a fresh agent.
- **Rate limiting** — per-session rolling 60s window (requests + tokens).
- **Session state** — JSON files under `~/.config/arctus-ai/sessions/`.

## What it intentionally drops

- **Header-based key forwarding.** No `x-omniroute-url` / `x-omniroute-key`
  headers. The orchestrator reaches models via endpoints you configured, with
  keys you set in your env. Nothing is forwarded to a remote server.
- **`connect.sh` + localtunnel.** No public tunnel is opened to your machine.
- **`/tmp/arctus_sandboxes`.** State lives under your own config dir, not `/tmp`.

## Requirements

- Python 3.8+
- At least one reachable model endpoint. Defaults:
  - `fast` tier → local Ollama at `http://localhost:11434/v1`, model `llama3.2`
  - `strong` tier → OpenAI, model `gpt-4o-mini` (set `ARCTUS_STRONG_API_KEY`)

## Setup — 3 commands

```bash
# 1. From this folder, make the package importable + the CLI runnable
pip install -e .          # if you add the provided pyproject.toml; or just run main.py directly
# Or skip install entirely and run:
python main.py --help

# 2. (optional) point the strong tier at your key
export ARCTUS_STRONG_API_KEY=sk-...        # macOS/Linux
setx ARCTUS_STRONG_API_KEY "sk-..."        # Windows (new shell)

# 3. Run it
python main.py "refactor my parser into a class and add a test plan"
```

Fully local (no OpenAI key):

```bash
ollama pull llama3.2
python main.py config-set '{"strong":{"base_url":"http://localhost:11434/v1","model":"llama3.2","api_key":"ollama"}}'
```

## Usage

```bash
python main.py                       # interactive REPL
python main.py "do something"        # one-shot task, then exit
python main.py config                # show config + file path
python main.py config-set '<json>'   # merge JSON into config
python main.py show <session-id>     # print a saved session
python main.py reset <session-id> --scope all
python main.py -v "..."              # verbose logging
```

In the REPL, type a task and press Enter. Use `:quit` to exit, `:reset` to clear.

## Programmatic use

```python
from arctus import Config, QueenAgent, RateLimitConfig

cfg = Config()              # reads env / ~/.config/arctus-ai/config.json
queen = QueenAgent(cfg)
result = queen.run(
    prompt="Refactor the auth module and add type hints",
    session_id="job-1",
    rate_config=RateLimitConfig(max_requests_per_minute=10),
)
print(result.complexity, result.mode)
for w in result.work:
    print(w["step"], "->", w["result"][:80])
```

## Layout

```
arctus-ai-python/
├── arctus/
│   ├── __init__.py        # public API
│   ├── config.py          # Config, Tier, load/save (env + JSON)
│   ├── llm.py             # OpenAI-compatible client (stdlib urllib)
│   ├── session.py         # file-backed session state + reset
│   ├── rate_limit.py      # per-session rolling 60s window
│   ├── context.py         # IsolatedContextWindow, StateDir, 80% handoff
│   └── orchestrator.py    # QueenAgent: Plan -> Validate -> Execute -> Verify
├── main.py                # CLI + REPL
├── requirements.txt       # empty (stdlib only)
└── README.md
```

## Safety

- No network listener is opened. The tool only makes **outbound** calls to the
  model endpoints you configured.
- The only files it reads from your home directory are its own config + session
  files under `~/.config/arctus-ai/`.
- No credential ever leaves your machine except to the model endpoint you
  explicitly configured.

## License

MIT.
