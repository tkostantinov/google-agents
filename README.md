# Blog Agent (ADK + Mistral API)

A small multi-agent pipeline built on [Google's Agent Development Kit](https://github.com/google/adk-python) that takes a blog topic and produces an outline, a full draft, three alternative titles, and two tweet-length hooks.

It calls the **Mistral API** via [LiteLLM](https://github.com/BerriAI/litellm). A local-only setup using Ollama in Docker is also documented at the bottom if you'd rather not use a cloud API.

## Project layout

```
google-agents/
├── docker-compose.yml     # optional: runs Ollama in Docker (local alternative)
├── requirements.txt
├── .env                    # MISTRAL_API_KEY / MISTRAL_MODEL
└── blog_agent/
    └── agent.py            # root_agent + sub-agents live here
```

`agent.py` lives inside the `blog_agent/` subfolder (not the repo root) on purpose: ADK's loader derives the agent's name from its folder name, and that name must be a valid Python identifier. The repo folder itself (`google-agents`) has a hyphen, so it can't be the agent — `blog_agent` is.

## 1. Prerequisites

- Python 3.12
- A [Mistral API key](https://console.mistral.ai/api-keys)

## 2. Python environment

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

(If you use [uv](https://github.com/astral-sh/uv) instead: `uv venv && uv pip install -r requirements.txt`.)

## 3. Configure

Set your key in `.env` at the repo root:

```
MISTRAL_API_KEY=your-key-here
MISTRAL_MODEL=mistral-large-latest
```

## 4. Run it

> **`adk` only exists inside the virtual environment** (it's installed to `.venv/bin/adk`, not system-wide). Every new terminal needs `source .venv/bin/activate` first, or you'll get `Command 'adk' not found`. If your prompt doesn't start with `(.venv)`, run this from the repo root before anything below:
> ```bash
> source .venv/bin/activate      # Windows: .venv\Scripts\activate
> ```

### Web UI

From the repo root:

```bash
adk web
```

Open the printed URL (default `http://127.0.0.1:8000`) and select **blog_agent** from the app dropdown. Enter a topic (e.g. "benefits of using type hints in Python") and send it.

### CLI

From the repo root:

```bash
adk run blog_agent
```

Type a topic at the prompt and press enter.

> If you pipe a single message in non-interactively (`echo "topic" | adk run blog_agent`), the CLI prints `Aborted!` and exits non-zero once stdin closes after your line — that's expected, not a pipeline failure. Check the printed conversation above it for the actual result.

## Performance and rate limits

This pipeline makes several sequential model calls per request (plan → validate → write → validate → synthesize) — up to 8 with the default `max_iterations=3` loops. A full run against the Mistral API took **~3 minutes** in testing.

Free/trial Mistral API keys are commonly capped at a low requests-per-minute limit (check the `x-ratelimit-limit-req-minute` response header — a key in testing here was capped at **4 req/min**), which this pipeline can exceed on its own. `agent.py` sets `num_retries=10` with `retry_strategy="exponential_backoff_retry"` on the model so 429s are absorbed automatically rather than crashing the run — no action needed, but expect the pipeline to pause and retry rather than fail outright if you're on a low-tier key. If it's still too slow:

- Lower `max_iterations` in `blog_agent/agent.py`'s two `LoopAgent`s (default 3) — fewer validation retries means fewer total calls.
- Upgrade your Mistral API tier for a higher requests-per-minute limit.

## How it works

- `BlogPlanner` drafts a Markdown outline; `OutlineValidationChecker` checks it and asks for a retry if incomplete. These two are wrapped in a `LoopAgent` (`RobustBlogPlanner`, up to 3 iterations).
- `BlogWriter` expands the outline into a full article; `BlogPostValidationChecker` checks it the same way, wrapped in `RobustBlogWriter`.
- Both loops are exposed to `root_agent` as callable tools (`AgentTool`), so the root agent explicitly calls "plan" then "write" rather than delegating via handoff. `root_agent`'s instruction explicitly spells out the tool call argument shape (`{"request": "<string>"}`) since `AgentTool`'s default schema has no field description, and weaker models are prone to guessing a wrong key name.

## Troubleshooting

- **`Command 'adk' not found`** — the virtual environment isn't active in this terminal. Run `source .venv/bin/activate` from the repo root first (see step 4).
- **`AuthenticationError`** — check `MISTRAL_API_KEY` in `.env`.
- **`RateLimitError` after many retries** — your key's requests-per-minute quota is too low for this pipeline's call volume even with backoff. Lower `max_iterations`, or upgrade your Mistral tier.
- **Model never calls the planner/writer tools** — `MISTRAL_MODEL` doesn't support tool calling, or the instruction in `agent.py` describing the tool call shape was removed/changed.
- **Nothing happens when you submit a prompt in `adk web`** — check the terminal running `adk web` for a traceback; the web UI itself doesn't always surface backend errors.

---

## Alternative: run fully locally with Ollama (no cloud API)

If you'd rather not send data to a cloud API, `docker-compose.yml` runs [Ollama](https://ollama.com) in Docker instead.

1. Start it: `docker compose up -d` — runs `ollama/ollama`, published on `localhost:11434`, with models persisted in a Docker volume.
2. Pull a model that supports **tool/function calling** (required — the root agent calls the planner and writer as tools): `docker exec -it ollama ollama pull llama3.1`. Smaller models (`qwen2.5:0.5b`/`1.5b`/`3b`) were tested here and are **not recommended** — they either skip the tool calls entirely or call them unreliably; `llama3.1` (8B) was the smallest model that worked correctly in testing.
3. In `.env`, set:
   ```
   OLLAMA_MODEL=llama3.1
   OLLAMA_API_BASE=http://localhost:11434
   ```
4. In `blog_agent/agent.py`, swap the `MODEL` definition back to:
   ```python
   OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
   os.environ.setdefault("OLLAMA_API_BASE", os.getenv("OLLAMA_API_BASE", "http://localhost:11434"))
   MODEL = LiteLlm(model=f"ollama_chat/{OLLAMA_MODEL}")
   ```

Expect a full run to take **~8 minutes** on CPU-only inference with `llama3.1` (no rate limits, but much slower than the cloud API). A GPU passthrough in `docker-compose.yml` (via the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)) speeds this up significantly. Docker Desktop's VM memory limit must also be large enough to load the model (`llama3.1` needs ~5GB) — check `docker info | grep "Total Memory"` and increase it via Docker Desktop → Settings → Resources if the container gets OOM-killed (`signal: killed` in `docker logs ollama`).
