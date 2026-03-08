# LocalCowork Lite

**A fully on-device AI agent with MCP tool-calling — runs entirely on a consumer GPU with 6GB VRAM.**

Inspired by [LiquidAI's LocalCowork](https://github.com/Liquid4All/cookbook/tree/main/examples/localcowork), rebuilt in Python for accessibility and scaled to fit consumer hardware. No cloud APIs, no data leaving your machine, no vendor lock-in.

[![tests](https://github.com/KaungHtetCho-22/localcowork-lite/actions/workflows/pytest.yml/badge.svg)](https://github.com/KaungHtetCho-22/localcowork-lite/actions/workflows/pytest.yml)

![Python](https://img.shields.io/badge/python-3.11-blue)

---

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
Agent: google.send_email → to: abc8@gmail.com, subject: Re: Offer Letter (540ms)
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
- **Portfolio**: demonstrates production ML engineering — RAG pipelines, agent loops, MCP servers, audit logging

---

## Architecture

```
┌─────────────────────────────────────────────┐
│           React + TypeScript (Vite)          │
│    Chat UI · Tool Trace Panel · Charts        │
└───────────────────┬─────────────────────────┘
                    │ WebSocket (ws://localhost:8000)
┌───────────────────▼─────────────────────────┐
│           FastAPI Backend (Python)            │
│                                               │
│  ConversationManager                          │
│    └─ manages message history + agent loop    │
│                                               │
│  ToolRouter                                   │
│    └─ auto-discovers MCP servers at startup   │
│    └─ dispatches tool calls + audit logging   │
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

1. User message is appended to history
2. LLM is called with the full history + all tool schemas
3. If the LLM emits a `tool_call` → dispatch it → append result → call LLM again
4. Repeat up to `MAX_TOOL_CALLS` times (default: 10)
5. Stream final text response back to the frontend via WebSocket

### MCP Tool Registration

Each server module calls `register_tool()` at import time. The `ToolRouter` auto-discovers all servers by importing them, builds OpenAI-compatible tool schemas, and routes calls by name (`server.tool_name`). Adding a new tool requires no changes to the core agent — just register it in the server module and restart.

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

## Prerequisites

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

## Quick Start

### Step 1 — Clone and run setup

```bash
git clone https://github.com/KaungHtetCho-22/localcowork-lite.git && cd localcowork-lite
chmod +x scripts/*.sh
./scripts/setup-dev.sh
```

This creates a `.venv` with all Python dependencies via `uv`, copies `.env.example` to `.env`, and installs frontend Node packages.

### Step 2 — Start the model server (Terminal 1)

```bash
./scripts/start-model.sh
```

Wait until you see `llama server listening` before continuing.

### Step 3 — Configure environment

Edit `.env` to match your setup:

```bash
# Sandbox — agent can only access files under this path
FILESYSTEM_SANDBOX_DIR=/home/yourname/Documents

# Match ctx-size with what you passed to llama-server
# Default max tokens per response
LLM_MAX_TOKENS=1024
```

### Step 4 — Start the backend (Terminal 2)

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

Verify it's healthy:
```bash
curl http://localhost:8000/health
# → {"status":"ok","llm_connected":true,...}
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

### First Run

On the first Google tool call, a browser window opens asking you to sign in and grant permissions. After approval, `token.json` is saved and reused automatically.

```bash
# If Google tools stop working, re-authenticate:
rm -f backend/mcp_servers/google/token.json
# Then restart the backend and trigger any Google tool call
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
EMBED_DEVICE=cpu                          # use 'cuda' for GPU embeddings

# Filesystem sandbox (agent cannot go outside this path)
FILESYSTEM_SANDBOX_DIR=~/Documents

# Document output directory
DOCUMENT_OUTPUT_DIR=./.data/documents

# Audit log
AUDIT_LOG_PATH=./.data/audit/tool_calls.jsonl

# Agent limits
MAX_TOOL_CALLS=10
TOOL_TIMEOUT=30

# Google (optional)
# credentials.json + token.json live in backend/mcp_servers/google/
```

---

## Adding a New Tool

1. Open the relevant `backend/mcp_servers/<server>/server.py`
2. Write an `async def` handler
3. Call `register_tool()` at the bottom:

```python
async def my_tool(param: str) -> dict:
    """Does something useful."""
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
)
```

4. Add `"myserver"` to the `servers` list in `backend/agent_core/tool_router.py`
5. Restart the backend — tool is live immediately

**Tips for good tool descriptions:**
- Be specific about *when* to call this tool vs similar tools
- Describe parameters clearly — the LLM fills these from your message
- Keep names in `server.tool_name` format

---

## Project Structure

```
localcowork-lite/
├── backend/
│   ├── main.py                     FastAPI app, WebSocket chat, REST endpoints
│   ├── config.py                   Pydantic settings loaded from .env
│   ├── agent_core/
│   │   ├── conversation.py         Agent loop — LLM ↔ tool dispatch ↔ history
│   │   ├── tool_router.py          Tool registry, auto-discovery, dispatch + audit
│   │   └── audit.py                Async JSONL audit logger
│   ├── inference/
│   │   └── client.py               OpenAI-compat client (works with llama.cpp / Ollama / vLLM)
│   └── mcp_servers/
│       ├── knowledge/server.py     ChromaDB RAG — ingest, search, manage sources
│       ├── filesystem/server.py    Sandboxed file ops
│       ├── document/server.py      PDF/DOCX extract, diff, PDF report generation
│       ├── audit/server.py         Expose audit log as agent-callable tools
│       ├── system/server.py        OS/CPU/RAM/disk via psutil
│       └── google/server.py        Gmail + Google Calendar via Google API OAuth2
├── frontend/
│   └── src/
│       ├── App.tsx                 Chat UI — messages, tool trace panel, suggestions
│       └── components/
│           └── SystemInfoChart.tsx CPU/RAM radial gauges + memory pie (Recharts)
├── scripts/
│   ├── setup-dev.sh                One-command setup using uv + npm
│   └── start-model.sh              Start llama-server optimised for RTX 3060
├── .env.example                    Config template — copy to .env
└── pyproject.toml                  Python project + dependencies
```

---


## Known Limitations

- **Multi-step chains**: reliable for 1–3 tool calls; longer chains may lose track — use specific prompts
- **Context window**: very long email threads or large documents may hit the 32K limit; chunking helps
- **Tool selection**: with 21 tools, occasional mis-selection happens — clear, specific prompts improve accuracy
- **Google OAuth**: token expires periodically — delete `token.json` and re-authenticate if needed
- **Filesystem sandbox**: the agent cannot access files outside `FILESYSTEM_SANDBOX_DIR` by design

---
