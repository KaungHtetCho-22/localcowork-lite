# LocalCowork Lite

**A fully on-device AI agent with MCP tool-calling — runs entirely on a consumer GPU with 6GB VRAM.**

Inspired by [LiquidAI's LocalCowork](https://github.com/Liquid4All/cookbook/tree/main/examples/localcowork), rebuilt in Python for accessibility and scaled to fit consumer hardware. No cloud APIs, no data leaving your machine, no vendor lock-in.


![Python](https://img.shields.io/badge/python-3.11-blue)
![Tests](https://img.shields.io/badge/pytest-53%20passed-brightgreen?logo=pytest)
![Local](https://img.shields.io/badge/100%25%20local-no%20cloud-brightgreen)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![VRAM](https://img.shields.io/badge/VRAM-6GB%20RTX%203060-76B900?logo=nvidia&logoColor=white)
![Model](https://img.shields.io/badge/model-Qwen2.5--7B%20Q4__K__M-blueviolet)
![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9)
![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![Tauri](https://img.shields.io/badge/Tauri-2.0-FFC131?logo=tauri&logoColor=black)

---

![LocalCowork Lite](image.png)

## What Is This?

LocalCowork Lite is a **local AI agent** that takes natural language instructions and executes real actions on your machine — reading files, searching a knowledge base, processing documents, querying system info, and interacting with Gmail and Google Calendar — all through a chat interface running in your browser.

The key idea is **tool-calling**: instead of just generating text, the LLM decides which tool to call, calls it, observes the result, and synthesizes a response. Every tool call is logged to a local audit trail so you always know what the agent did.

```
You:   "Ingest all PDFs in my Research folder"
Agent: filesystem.search_files   → 6 PDFs found (12ms)
       knowledge.ingest_document → paper1.pdf indexed (380ms)
       knowledge.ingest_document → paper2.pdf indexed (360ms)
       ... × 6 total

You:   "What do these papers say about attention mechanisms?"
Agent: knowledge.search → top 5 relevant chunks retrieved (38ms)
       "Across your 6 papers, attention mechanisms are discussed in three contexts..."

You:   "Check my inbox and summarize any unread messages from recruiters"
Agent: google.list_emails → 10 emails fetched (1240ms)
       google.search_emails → query: 'from:recruiter OR subject:opportunity' → 3 matches (890ms)
       google.summarize_thread → thread 19ccb9c2 read (670ms)
       "You have 3 recruiter emails. The most recent is from abc@gmail.com
        asking you to visit the office to sign your offer letter."

You:   "Reply to the offer letter email and confirm I'll visit Thursday"
Agent: google.send_email → to: abc@gmail.com, subject: Re: Offer Letter (540ms)
       "Email sent. Confirmed your Thursday visit."

You:   "What's on my calendar this week? Find a free 2-hour slot for deep work"
Agent: google.list_events → 7 events found for next 7 days (820ms)
       google.find_free_slots → date: 2026-03-10, duration: 120min → 2 slots found (610ms)
       "You have 7 events this week. Two free 2-hour slots on Tuesday:
        10:00–12:00 and 15:00–17:00."

You:   "Block 10am–12pm Tuesday as Deep Work"
Agent: google.create_time_block → 'Deep Work' created on 2026-03-10T10:00 (490ms)
       "Done. Deep Work block added to your calendar for Tuesday 10:00–12:00
        with a 1-day reminder."

You:   "Show me the audit trail"
Agent: audit.get_summary → 12 tool calls, 100% success, avg 68ms
```

Everything — the model, the tools, your files — stays on your machine.

---

## Why Build This?

- **Privacy**: your documents, emails, and calendar never touch a third-party API
- **Cost**: no per-token billing — run it all day for free after setup
- **Learning**: a practical, end-to-end example of local LLM + tool-calling architecture
- **Portfolio**: demonstrates production ML engineering — RAG pipelines, agent loops, MCP servers, SQLite persistence, human-in-the-loop confirmation

---

## Architecture

```
┌─────────────────────────────────────────────┐
│           React + TypeScript (Vite)          │
│    Chat UI · Tool Trace Panel · Charts        │
│    HITL Confirmation Dialog                   │
└───────────────────┬─────────────────────────┘
                    │ WebSocket (ws://localhost:8000)
┌───────────────────▼─────────────────────────┐
│           FastAPI Backend (Python)            │
│                                               │
│  ConversationManager                          │
│    └─ agent loop · HITL pause/resume          │
│    └─ SQLite-backed history (persistent)      │
│                                               │
│  ToolRouter                                   │
│    └─ auto-discovers MCP servers at startup   │
│    └─ dispatches tool calls + audit logging   │
│    └─ risk classification per tool            │
│                                               │
│  InferenceClient                              │
│    └─ OpenAI-compat API → llama.cpp server    │
└───────────────────┬─────────────────────────┘
                    │ HTTP (localhost:8080/v1)
┌───────────────────▼─────────────────────────┐
│        llama.cpp server (model server)        │
│        Qwen2.5-7B-Instruct Q4_K_M            │
│        ~4.5GB VRAM · ~390ms/call              │
└─────────────────────────────────────────────┘

MCP Servers (Python modules, auto-discovered):
  knowledge  → ChromaDB RAG pipeline
  filesystem → sandboxed file access
  document   → PDF/DOCX processing
  audit      → tool call history
  system     → OS/CPU/RAM/disk info
  google     → Gmail + Google Calendar (OAuth2)
```

### Agent Loop

Each conversation turn works like this:

1. User message is appended to history and saved to SQLite
2. LLM is called with the full history + all tool schemas
3. If the LLM emits a `tool_call`:
   - If the tool is `write` or `destructive` risk → pause and ask user to confirm (HITL)
   - If approved (or `safe` risk) → dispatch → append result → call LLM again
4. Repeat up to `MAX_TOOL_CALLS` times (default: 10)
5. Stream final text response back to the frontend via WebSocket

### MCP Tool Registration

Each server module calls `register_tool()` at import time. The `ToolRouter` auto-discovers all servers by importing them, builds OpenAI-compatible tool schemas, and routes calls by name (`server.tool_name`). Adding a new tool requires no changes to the core agent — just register it in the server module and restart.

---

## Key Features

### Persistent Conversation Memory

Conversation history is saved to a local SQLite database (`.data/sessions.db`) after every message. If the backend restarts, all sessions are restored automatically — the agent remembers everything it was told and every tool it called.

```
# Monday session
You:   "Ingest all PDFs in ~/research"
Agent: 6 PDFs indexed into ChromaDB

# Backend restarted Tuesday morning

You:   "What did we ingest yesterday?"
Agent: "Yesterday we ingested 6 PDFs from your research folder:
        paper1.pdf, paper2.pdf..."   ← restored from SQLite
```

The `/sessions` REST endpoint lists all past sessions with message counts and timestamps, enabling a future conversation history sidebar.

### Human-in-the-Loop (HITL) Confirmation

Every tool is classified with a risk level. Before executing write or destructive actions, the agent pauses and shows a confirmation dialog in the frontend — the user must explicitly approve or reject before execution continues.

| Risk | Color | Examples | Behavior |
|---|---|---|---|
| `safe` | — | `search`, `list_dir`, `list_emails` | Executes immediately |
| `write` | 🟡 Yellow | `ingest_document`, `create_event`, `create_report` | Pauses — requires approval |
| `destructive` | 🔴 Red | `send_email`, `delete_source` | Pauses — requires approval |

If the user rejects a tool call, the agent records `"Rejected by user"` in the conversation history and synthesizes a response explaining what was cancelled — without crashing or losing context.

---

## Running with Docker (Recommended for Users)

Docker is the easiest way to run LocalCowork Lite. It packages all three services into isolated containers — no Python environment setup, no Node.js, no manual dependency management.

### Requirements

- Docker Engine 24+ and Docker Compose V2
- NVIDIA GPU with 6GB+ VRAM
- [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed

Verify your GPU is accessible to Docker before starting:

```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

You should see your GPU listed. If not, install nvidia-container-toolkit first.

### Step 1 — Clone and configure

```bash
git clone https://github.com/KaungHtetCho-22/localcowork-lite.git
cd localcowork-lite
cp .env.example .env
```

Edit `.env` — the only value you must change:

```bash
# Set this to a folder on your machine the agent is allowed to access
FILESYSTEM_SANDBOX_DIR=/home/yourname/Documents
```

### Step 2 — Build the images

```bash
docker compose -f docker-compose.gpu.yaml build
```

> **Note:** The model image compiles llama.cpp with CUDA from source. This takes 20–30 minutes on the first build. It is fully cached after that — subsequent builds are instant.

### Step 3 — Start everything

```bash
docker compose -f docker-compose.gpu.yaml up -d
```

Docker starts services in the correct order automatically:

1. **model** — llama-server starts, downloads Qwen2.5-7B (~4.4 GB on first run), loads onto GPU
2. **backend** — FastAPI starts after the model healthcheck passes
3. **frontend** — nginx starts after backend is ready

Watch the model loading progress:

```bash
docker logs -f localcowork-lite-model-1
```

When you see `llama server listening at http://0.0.0.0:8080` the model is ready.

### Step 4 — Open the app

Navigate to **http://localhost** in your browser.

### Useful commands

```bash
# Check all services are running
docker compose -f docker-compose.gpu.yaml ps

# View logs for a specific service
docker logs -f localcowork-lite-backend-1

# Restart only the backend (after code changes)
docker compose -f docker-compose.gpu.yaml restart backend

# Stop everything
docker compose -f docker-compose.gpu.yaml down

# Stop and delete all data (ChromaDB, sessions, audit log)
docker compose -f docker-compose.gpu.yaml down -v
```

### No GPU? Use the CPU stack

```bash
docker compose -f docker-compose.yaml up -d
```

> **Warning:** CPU inference is significantly slower — expect 5–15 seconds per token. The app still works correctly.

### What persists between restarts

| Path | Contents |
|---|---|
| `.data/chroma/` | ChromaDB vector embeddings — your knowledge base |
| `.data/sessions.db` | Conversation history |
| `.data/audit/` | JSONL audit trail |
| `huggingface_cache` volume | Downloaded model weights — 4.4 GB, downloaded once |

---

## Running as a Desktop App (Tauri)

LocalCowork Lite includes a [Tauri 2.0](https://tauri.app) desktop app that wraps the React frontend in a native window. The app automatically manages the model server — you don't need a browser or to remember to start llama-server manually.

> Install the `.deb` — the app auto-starts both `llama-server` and the Python backend. No terminals needed.

### Requirements

- Rust (install via [rustup.rs](https://rustup.rs))
- Node.js 20+
- Ubuntu system libraries:

```bash
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev libappindicator3-dev \
  librsvg2-dev patchelf libssl-dev libgtk-3-dev
```

### One-time setup

```bash
# Install Tauri CLI
cargo install tauri-cli --version "^2.0"

# Install frontend dependencies
cd frontend && npm install

# Copy llama-server as a Tauri sidecar
mkdir -p src-tauri/binaries
cp /usr/local/bin/llama-server \
   src-tauri/binaries/llama-server-x86_64-unknown-linux-gnu
chmod +x src-tauri/binaries/llama-server-x86_64-unknown-linux-gnu
```

### Running the desktop app

**Terminal 1 — Start the Python backend:**

```bash
cd localcowork-lite
source .venv/bin/activate
uv run uvicorn backend.main:app --port 8000
```

Wait for: `INFO: Application startup complete.`

**Terminal 2 — Launch the desktop app:**

```bash
cd frontend
cargo tauri dev
```

A native desktop window opens. The app shows a loading screen while llama-server starts and the model loads. Once ready, the full chat UI appears.

> **First launch:** The model downloads ~4.4 GB from HuggingFace. This takes a few minutes depending on your connection. It is cached locally — subsequent launches load in 30–60 seconds.

### Building a distributable installer

```bash
cd frontend
cargo tauri build
```

This produces:

```
src-tauri/target/release/bundle/
  deb/localcowork-lite_0.1.0_amd64.deb     ← install with: sudo dpkg -i
  appimage/localcowork-lite_0.1.0.AppImage  ← portable, no install needed
```

Install the `.deb` and the app appears in your Ubuntu application menu.

---

## MCP Servers & Tools

| Server | Tools | Description |
|---|---|---|
| **knowledge** | `ingest_document` `ingest_directory` `search` `list_sources` `delete_source` | ChromaDB RAG pipeline — ingest PDFs/DOCX/TXT/MD, semantic search |
| **filesystem** | `list_dir` `read_file` `search_files` | Sandboxed file access — agent cannot read outside configured sandbox path |
| **document** | `extract_text` `diff_documents` `create_report` | Extract text from PDFs/DOCX, compare document versions, generate PDF reports |
| **audit** | `get_tool_log` `get_summary` | Full JSONL audit trail of every tool call — name, args, result, latency, success |
| **system** | `get_system_info` `get_disk_usage` `get_running_processes` | OS info, CPU/RAM usage with charts, disk space, top processes |
| **google** | `list_emails` `search_emails` `summarize_thread` `send_email` `list_events` `create_event` `find_free_slots` `create_time_block` | Gmail read/search/send + Google Calendar CRUD via OAuth2 |

**21 tools across 6 servers** — carefully sized so a 7B model can select accurately.

---

## Hardware Requirements

Designed and tested on **NVIDIA RTX 3060 6GB VRAM**:

| Component | Choice | VRAM Usage |
|---|---|---|
| LLM | Qwen2.5-7B-Instruct Q4_K_M | ~4.5 GB |
| Embeddings | nomic-embed-text-v1.5 | CPU only — 0 GB |
| ChromaDB | local persistent (SQLite) | 0 GB |
| KV cache headroom | ctx-size 32768 | ~1.0 GB |
| **Total** | | **~5.5 GB ✅** |

Works on any GPU with 6GB+ VRAM. On 8GB+ you can increase `--ctx-size` further.

---

## Prerequisites (Manual Setup)

Install these before running setup:

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) |
| llama.cpp | latest | See below |

### Install llama.cpp

```bash
# Ubuntu/Debian with CUDA (RTX 3060):
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j$(nproc)
sudo cp build/bin/llama-server /usr/local/bin/

# macOS:
brew install llama.cpp

# Windows:
# Download prebuilt binary from https://github.com/ggerganov/llama.cpp/releases
# Choose the CUDA version matching your driver
```

---

## Quick Start (Manual)

### Step 1 — Clone and run setup

```bash
git clone https://github.com/KaungHtetCho-22/localcowork-lite.git && cd localcowork-lite
chmod +x scripts/*.sh
./scripts/setup-dev.sh
```

### Step 2 — Start the model server (Terminal 1)

```bash
./scripts/start-model.sh
```

Wait until you see `llama server listening` before continuing.

### Step 3 — Configure environment

Edit `.env` to match your setup:

```bash
FILESYSTEM_SANDBOX_DIR=/home/yourname/Documents
LLM_MAX_TOKENS=1024
```

### Step 4 — Start the backend (Terminal 2)

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

### Step 5 — Start the frontend (Terminal 3)

```bash
cd frontend && npm run dev
```

### Step 6 — Open the app

Navigate to **http://localhost:5173** in your browser.

---

## Google Integration (Gmail + Calendar)

To enable the `google` MCP server you need OAuth2 credentials from Google Cloud.

### Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (e.g. `localcowork-lite`)
3. Enable these APIs under **APIs & Services → Enable APIs**:
   - **Gmail API**
   - **Google Calendar API**
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop App**
   - Name: `localcowork`
5. Download the JSON → save as `backend/mcp_servers/google/credentials.json`
6. Go to **OAuth consent screen**:
   - Publishing status: **Testing**
   - Add your Gmail under **Test users**
7. Under **Authorized redirect URIs** add: `http://localhost:8085/`

### First Run Authentication

On the first Google tool call, a browser window opens asking you to sign in.

```bash
# If Google tools stop working (expired token), re-authenticate:
rm -f backend/mcp_servers/google/token.json
# Restart the backend and trigger any Google tool call
```

---

## Configuration Reference

All settings live in `.env`:

```bash
# Model server
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=qwen2.5-7b-instruct
LLM_TEMPERATURE=0.1
LLM_TOP_P=0.1
LLM_MAX_TOKENS=1024

# Backend
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:5173

# Knowledge base
CHROMA_PERSIST_DIR=./.data/chroma
EMBED_MODEL=nomic-ai/nomic-embed-text-v1.5
EMBED_DEVICE=cpu

# Filesystem sandbox (agent cannot go outside this path)
FILESYSTEM_SANDBOX_DIR=~/Documents

# Audit log
AUDIT_LOG_PATH=./.data/audit/tool_calls.jsonl

# Agent limits
MAX_TOOL_CALLS=10
TOOL_TIMEOUT=30
```

---

## Running Tests

```bash
uv pip install -e ".[dev]" --python .venv/bin/python
uv run pytest tests/ -v
uv run pytest tests/ --cov=backend --cov-report=term-missing
```

53 tests across 3 modules — all run fully offline with no model server required.

| Module | Tests | Covers |
|---|---|---|
| `test_db.py` | 18 | SQLite persistence — save, load, delete, list, ordering, isolation |
| `test_tool_router.py` | 12 | Tool registry, schema generation, risk classification, dispatch |
| `test_conversation.py` | 23 | Agent loop, HITL approve/reject/bypass, DB persistence calls |

---

## Adding a New Tool

1. Open the relevant `backend/mcp_servers/<server>/server.py`
2. Write an `async def` handler
3. Call `register_tool()` at the bottom:

```python
async def my_tool(param: str) -> dict:
    return {"result": param.upper()}

register_tool(
    server="myserver",
    name="my_tool",
    description="Converts text to uppercase. Use when the user wants text uppercased.",
    parameters={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "Text to convert"},
        },
        "required": ["param"],
    },
    handler=my_tool,
    risk="safe",  # "safe" | "write" | "destructive"
)
```

4. Add `"myserver"` to the `servers` list in `backend/agent_core/tool_router.py`
5. Restart the backend — tool is live immediately

---

## Project Structure

```
localcowork-lite/
├── backend/
│   ├── main.py                     FastAPI app, WebSocket chat, REST endpoints
│   ├── config.py                   Pydantic settings loaded from .env
│   ├── agent_core/
│   │   ├── conversation.py         Agent loop — LLM ↔ tool dispatch ↔ HITL ↔ history
│   │   ├── tool_router.py          Tool registry, risk classification, dispatch + audit
│   │   ├── db.py                   SQLite session persistence
│   │   └── audit.py                Async JSONL audit logger
│   ├── inference/
│   │   └── client.py               OpenAI-compat client (llama.cpp / Ollama / vLLM)
│   └── mcp_servers/
│       ├── knowledge/server.py     ChromaDB RAG
│       ├── filesystem/server.py    Sandboxed file ops
│       ├── document/server.py      PDF/DOCX processing
│       ├── audit/server.py         Audit log tools
│       ├── system/server.py        OS/CPU/RAM/disk
│       └── google/server.py        Gmail + Google Calendar
├── frontend/
│   ├── src/
│   │   ├── App.tsx                 Chat UI, tool traces, HITL dialog
│   │   └── components/
│   │       └── SystemInfoChart.tsx CPU/RAM charts
│   └── src-tauri/                  Tauri desktop app (Rust)
│       ├── src/
│       │   ├── main.rs             Entry point
│       │   └── lib.rs              Sidecar management, Tauri commands
│       ├── Cargo.toml
│       └── tauri.conf.json
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── Dockerfile.model            CPU build
│   ├── Dockerfile.model.gpu        GPU build (CUDA)
│   └── nginx.conf
├── docker-compose.yaml             CPU stack
├── docker-compose.gpu.yaml         GPU stack
├── tests/
│   ├── conftest.py
│   ├── test_db.py
│   ├── test_tool_router.py
│   └── test_conversation.py
├── scripts/
│   ├── setup-dev.sh
│   └── start-model.sh
├── .env.example
└── pyproject.toml
```

---

## Known Limitations

- **Multi-step chains**: reliable for 1–3 tool calls; longer chains may lose track — use specific prompts
- **Context window**: very long email threads or large documents may hit the 32K limit
- **Tool selection accuracy**: with 21 tools, occasional mis-selection happens — clear prompts help
- **Google OAuth**: uses production OAuth app — token persists long-term. If it expires, delete `token.json` and re-authenticate
- **Tauri one-click**: `.deb` installer auto-starts model server and backend — no terminals needed
---
