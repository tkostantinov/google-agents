# Blog Agent (ADK + local Ollama)

A small multi-agent pipeline built on [Google's Agent Development Kit](https://github.com/google/adk-python) that takes a blog topic and produces an outline, a full draft, three alternative titles, and two tweet-length hooks.

It runs entirely against a **local Ollama server** (no Gemini API key, no cloud calls, no rate limits) via [LiteLLM](https://github.com/BerriAI/litellm).

## Project layout

```
google-agents/
├── docker-compose.yml     # runs Ollama in Docker
├── requirements.txt
├── .env                    # OLLAMA_MODEL / OLLAMA_API_BASE
└── blog_agent/
    └── agent.py            # root_agent + sub-agents live here
```

`agent.py` lives inside the `blog_agent/` subfolder (not the repo root) on purpose: ADK's loader derives the agent's name from its folder name, and that name must be a valid Python identifier. The repo folder itself (`google-agents`) has a hyphen, so it can't be the agent — `blog_agent` is.

## 1. Prerequisites

- Python 3.12
- Docker (Docker Desktop, or the Docker Engine + CLI)
- ~5 GB free disk space for the Ollama model

## 2. Start Ollama in Docker

```bash
docker compose up -d
```

This starts an `ollama/ollama` container, publishes it on `localhost:11434`, and persists downloaded models in a named volume (`ollama_data`) so you don't re-download them on restart.

Pull a model that supports **tool/function calling** — the root agent calls the planner and writer as tools, so this is required, not optional. Good options: `llama3.1`, `qwen2.5`, `mistral-nemo`.

```bash
docker exec -it ollama ollama pull llama3.1
```

Verify it's up:

```bash
curl http://localhost:11434/api/tags
```

> **Have an NVIDIA GPU?** Add a `deploy.resources.reservations.devices` GPU block to the `ollama` service in `docker-compose.yml` (requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)) — otherwise Ollama runs on CPU, which is noticeably slower for anything beyond small models.

## 3. Python environment

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

(If you use [uv](https://github.com/astral-sh/uv) instead: `uv venv && uv pip install -r requirements.txt`.)

## 4. Configure

`.env` at the repo root already has sensible defaults:

```
OLLAMA_MODEL=llama3.1
OLLAMA_API_BASE=http://localhost:11434
```

Change `OLLAMA_MODEL` to whatever you pulled in step 2. If Ollama runs somewhere other than `localhost:11434` (e.g. a remote box), update `OLLAMA_API_BASE` accordingly.

## 5. Run it

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

## Performance

This pipeline makes several sequential model calls per request (plan → validate → write → validate → synthesize) — up to 8 with the default `max_iterations=3` loops. On CPU-only inference with an 8B model (`llama3.1`), a full run took **~8 minutes** in testing. If that's too slow:

- **Lower `max_iterations`** in `blog_agent/agent.py`'s two `LoopAgent`s (default 3) — this is the biggest lever. Each retry re-runs a full model call, and weaker/smaller models retry *more* often (they fail their own validation more), which can cancel out any speed gained from a smaller model. Setting `max_iterations=1` removes retries entirely.
- Give Ollama a GPU (see the GPU note in step 2) — the most reliable way to actually speed things up without changing behavior.
- Smaller models were tested (`qwen2.5:0.5b`, `qwen2.5:1.5b`, `qwen2.5:3b`) as an alternative to `llama3.1` (8B) and are **not recommended** for this project: 0.5B and 1.5B never actually invoked the planner/writer tools (they just answered directly or described calling the tool in prose), and 3B did call the tools correctly but needed more validation retries, ending up roughly as slow as `llama3.1` while producing weaker output. If you want to experiment anyway, `AgentTool`'s default schema expects tool calls shaped like `{"request": "<string>"}` — smaller models are prone to inventing a different key name, which crashes the call; the fix is already baked into `root_agent`'s instruction in this repo.

## How it works

- `BlogPlanner` drafts a Markdown outline; `OutlineValidationChecker` checks it and asks for a retry if incomplete. These two are wrapped in a `LoopAgent` (`RobustBlogPlanner`, up to 3 iterations).
- `BlogWriter` expands the outline into a full article; `BlogPostValidationChecker` checks it the same way, wrapped in `RobustBlogWriter`.
- Both loops are exposed to `root_agent` as callable tools (`AgentTool`), so the root agent explicitly calls "plan" then "write" rather than delegating via handoff.

## Troubleshooting

- **"Connection refused" / timeouts calling the model** — Ollama isn't running or isn't reachable at `OLLAMA_API_BASE`. Check `docker compose ps` and `curl http://localhost:11434/api/tags`.
- **Model never calls the planner/writer tools** — the model you pulled doesn't support tool calling. Switch `OLLAMA_MODEL` to one that does (see step 2).
- **Nothing happens when you submit a prompt in `adk web`** — check the terminal running `adk web` for a traceback; the web UI itself doesn't always surface backend errors.
