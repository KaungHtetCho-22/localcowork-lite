# AI Engineering Concepts in LocalCowork Lite

A detailed breakdown of every AI engineering concept applied in this project — what it is, why it matters, and exactly where it appears in the codebase.

---

## 1. Tool-Calling / Function Calling

### What it is
Tool-calling is a capability where an LLM can decide, mid-generation, to pause and invoke an external function instead of generating text. The model receives a list of available tool schemas (name, description, JSON parameters), and when it determines a tool would answer the query better than its training data, it emits a structured `tool_call` object instead of a text response.

### How it works here
The LLM (Qwen2.5-7B) is given 21 tool schemas in OpenAI format on every request:

```python
# backend/agent_core/tool_router.py
{
    "type": "function",
    "function": {
        "name": "knowledge.search",
        "description": "Semantic search over the local knowledge base...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "n_results": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    }
}
```

When the LLM decides to call a tool, it returns:
```json
{
  "tool_calls": [{
    "id": "tc_abc123",
    "function": {
      "name": "knowledge.search",
      "arguments": "{\"query\": \"attention mechanism\"}"
    }
  }]
}
```

The `ToolRouter` parses this, dispatches the call, appends the result to history, and re-calls the LLM — which now has the tool result in context to synthesize a response.

### Why it matters
Without tool-calling, the LLM can only hallucinate answers from training data. With it, the LLM becomes an orchestrator that can act on your actual files, real calendar, and live email — grounded in truth.

---

## 2. RAG — Retrieval-Augmented Generation

### What it is
RAG is the pattern of retrieving relevant context from an external knowledge store and injecting it into the LLM prompt before generation. It solves the fundamental limitation that LLMs only know what was in their training data.

### The full pipeline in this project

**Ingestion (offline):**
```
Document (PDF/DOCX/TXT/MD)
  → extract raw text           (PyMuPDF / python-docx)
  → split into 512-word chunks  (sliding window, 50-word overlap)
  → embed each chunk            (nomic-embed-text-v1.5, 768-dim vectors)
  → store vectors + text        (ChromaDB, persisted to .data/chroma/)
```

**Retrieval (at query time):**
```
User query
  → embed query                 (same nomic-embed-text-v1.5 model)
  → cosine similarity search    (ChromaDB top-K, default K=5)
  → return most relevant chunks
```

**Augmentation:**
The retrieved chunks become the tool result, appended to conversation history. The LLM then generates an answer grounded in your actual documents rather than training data.

### Key design decisions
- **Embedding model on CPU**: `nomic-embed-text-v1.5` runs on CPU so it doesn't compete with the LLM for the 6GB VRAM budget
- **ChromaDB persistence**: vectors survive backend restarts — you ingest once, search forever
- **`trust_remote_code=True`**: required for nomic-embed's custom pooling layer
- **`einops` dependency**: required by nomic-embed's attention implementation

### Why it matters
This is the pattern behind every serious enterprise document Q&A system. The same architecture runs in production at companies like Notion, Glean, and Salesforce — just with larger models and managed vector stores.

---

## 3. Agentic Loop / ReAct Pattern

### What it is
An agent loop is a repeated cycle of: **reason → act → observe → reason again**. The model doesn't just answer once — it can chain multiple tool calls, using the result of one tool to inform the next decision.

This mirrors the **ReAct** (Reasoning + Acting) pattern from the 2022 paper by Yao et al., where the model interleaves thought steps with tool actions.

### How it works here

```python
# backend/agent_core/conversation.py
for _ in range(settings.max_tool_calls):
    response = await inference.chat(self._history, tools=tools)

    if not response.get("tool_calls"):
        # Model chose to respond in text — exit loop
        yield {"type": "text_delta", "content": response["content"]}
        yield {"type": "done"}
        return

    # Model chose a tool — dispatch it
    for tc in response["tool_calls"]:
        result = await dispatch(tool_name, arguments, session_id)
        # Append result to history → loop continues
        self._history.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": json.dumps(result),
        })
    # LLM is called again with the tool result in context
```

A real multi-step chain looks like:
```
Turn 1: LLM → filesystem.search_files (find PDFs)
Turn 2: LLM → knowledge.ingest_document (index paper1.pdf)
Turn 3: LLM → knowledge.ingest_document (index paper2.pdf)
Turn 4: LLM → "Done. Ingested 6 PDFs." (text response)
```

### Why it matters
Single-turn LLM calls can't handle tasks that require sequential actions. The agent loop is what separates a chatbot from an agent.

---

## 4. MCP — Model Context Protocol

### What it is
MCP (Model Context Protocol) is an open standard (introduced by Anthropic, 2024) for connecting LLMs to external tools and data sources. It defines a server/client architecture where tool providers expose a standardized interface.

### How it's used here
Rather than hardcoding tool implementations in the agent, tools are organized as independent MCP-style server modules. Each server:
- Registers its tools via `register_tool()` at import time
- Is auto-discovered by `ToolRouter` at startup
- Can be added, removed, or swapped without touching the agent loop

```
backend/mcp_servers/
  knowledge/server.py   → ChromaDB tools
  filesystem/server.py  → file system tools
  document/server.py    → document processing tools
  audit/server.py       → audit log tools
  system/server.py      → OS monitoring tools
  google/server.py      → Gmail + Calendar tools
```

This separation means each server can be developed, tested, and versioned independently — exactly the microservices philosophy applied to AI tools.

### Why it matters
This is the direction the industry is moving. Every major AI platform (Anthropic, OpenAI, Google) now supports MCP or equivalent tool-server patterns. Familiarity with this pattern is a real signal of production ML engineering maturity.

---

## 5. Human-in-the-Loop (HITL)

### What it is
HITL is the design pattern of inserting human judgment checkpoints into an automated AI workflow. Rather than letting the agent act autonomously on all tasks, the system pauses at high-risk actions and requires explicit human approval before proceeding.

### How it works here

**Risk classification** — every tool is tagged at registration:
```python
register_tool(..., risk="safe")        # list, search, read — executes immediately
register_tool(..., risk="write")       # create, ingest — pauses for approval
register_tool(..., risk="destructive") # send, delete — pauses for approval
```

**Pause mechanism** — `asyncio.Event` is used to suspend the generator mid-execution:
```python
# conversation.py — agent pauses here
self._confirm_event.clear()
yield {"type": "tool_confirm", "tool": tool_name, "risk": risk, ...}
await self._confirm_event.wait()  # ← suspends until user decides

# main.py — WebSocket receive loop resolves it
if data.get("type") == "confirm":
    cm.resolve_confirmation(data.get("approved", False))
    continue
```

**Concurrency fix** — the agent turn runs as a background `asyncio` task so the WebSocket receive loop stays free to receive the confirmation message while the generator is suspended:
```python
asyncio.ensure_future(run_turn())
```

### Why it matters
HITL is a core AI safety concept. Without it, a misunderstood instruction like "clean up my emails" could send hundreds of emails or delete important threads. It also directly addresses AI alignment concerns — keeping humans in control of consequential actions.

---

## 6. Streaming with WebSockets + Async Generators

### What it is
Instead of waiting for the entire agent response before showing anything, the system streams events to the frontend as they happen — tool calls appear the moment they're dispatched, text streams token by token.

### How it works here

**Backend — async generator:**
```python
# conversation.py
async def turn(self, user_message: str) -> AsyncIterator[dict]:
    yield {"type": "tool_call", "tool": "knowledge.search", ...}
    # ... tool executes ...
    yield {"type": "tool_result", "success": True, "latency_ms": 38}
    yield {"type": "text_delta", "content": "Based on your papers..."}
    yield {"type": "done"}
```

**Backend — WebSocket dispatch:**
```python
# main.py
async for event in cm.turn(user_message):
    await websocket.send_text(json.dumps(event))
```

**Frontend — progressive rendering:**
```tsx
// App.tsx
if (event.type === "tool_call")    → add pending trace card
if (event.type === "tool_result")  → resolve trace card with latency
if (event.type === "text_delta")   → append to message content
if (event.type === "done")         → stop streaming cursor
```

### Why it matters
Streaming is table-stakes for production AI UX. A 7B model takes 3–8 seconds to generate a full response — without streaming the UI appears frozen. Tool traces visible in real time also give users transparency into what the agent is doing, building trust.

---

## 7. Vector Embeddings & Semantic Search

### What it is
Embeddings are dense numerical representations of text (768-dimensional vectors here) where semantically similar text maps to nearby points in vector space. Semantic search finds documents by meaning rather than exact keyword matching.

### How it works here

```python
# knowledge/server.py
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

embedding_fn = SentenceTransformerEmbeddingFunction(
    model_name="nomic-ai/nomic-embed-text-v1.5",
    trust_remote_code=True,
    device="cpu",
)
```

A query like `"how do transformers handle long sequences?"` will retrieve chunks about attention windows, positional encoding, and context length — even if none of those chunks contain the exact phrase "long sequences".

**Cosine similarity** is used for distance, meaning the angle between vectors matters, not their magnitude. This makes results robust to documents of different lengths.

### Why it matters
Keyword search fails on technical and scientific documents where the same concept is expressed in many different ways. Semantic search is what makes RAG actually useful — it's the difference between finding the right passage and returning irrelevant results.

---

## 8. Conversation History Management

### What it is
LLMs are stateless — each API call is independent. To simulate memory, the full conversation history (user messages, assistant messages, tool calls, tool results) is sent on every request. This is sometimes called the "context window as memory" pattern.

### How it works here

```python
# Every message is appended in OpenAI multi-turn format:
[
  {"role": "system",    "content": "You are LocalCowork..."},
  {"role": "user",      "content": "Ingest my research PDFs"},
  {"role": "assistant", "content": null, "tool_calls": [...]},
  {"role": "tool",      "tool_call_id": "tc1", "content": "{\"indexed\": 6}"},
  {"role": "assistant", "content": "Done. 6 PDFs indexed."},
  {"role": "user",      "content": "What do they say about attention?"},
]
```

**Persistence layer** — every message is saved to SQLite immediately after appending:
```python
self._history.append(msg)
save_message(self.session_id, msg["role"], msg)
```

On `ConversationManager.__init__`, history is loaded from SQLite so sessions survive backend restarts.

### Key limitation
At 32K context tokens (~24,000 words), the window fills after many tool-heavy turns. There is currently no summarization or sliding window — a known weakness that would be fixed with a background summarization step.

---

## 9. Audit Logging

### What it is
Every tool call — its name, arguments, result, success status, latency, and timestamp — is written to an append-only JSONL log. This provides a complete, tamper-evident record of everything the agent did.

### How it works here

```python
# backend/agent_core/audit.py
async def log_tool_call(
    session_id: str,
    tool_name: str,
    arguments: dict,
    result: dict,
    latency_ms: float,
):
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "tool": tool_name,
        "arguments": arguments,
        "success": result["success"],
        "latency_ms": latency_ms,
    }
    async with aiofiles.open(AUDIT_LOG_PATH, "a") as f:
        await f.write(json.dumps(entry) + "\n")
```

The `audit` MCP server exposes this log as agent-callable tools (`get_tool_log`, `get_summary`) so the agent can answer questions like "how many tool calls did we make?" from within a conversation.

### Why it matters
In production AI systems, auditability is non-negotiable — especially for actions like sending emails or modifying calendar events. The audit trail is also critical for debugging model mis-selections and measuring tool call accuracy over time.

---

## 10. OpenAI-Compatible Inference Abstraction

### What it is
Rather than tying the backend to a specific model server, the `InferenceClient` talks to any server that implements the OpenAI `/v1/chat/completions` API. This makes the model server swappable without any backend code changes.

### How it works here

```python
# backend/inference/client.py
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url=settings.llm_base_url,  # http://localhost:8080/v1
    api_key="not-needed",
)

response = await client.chat.completions.create(
    model=settings.llm_model,
    messages=history,
    tools=tool_schemas,
    temperature=settings.llm_temperature,
)
```

**Compatible backends** (zero code changes):
- `llama.cpp` server — used in production here
- `Ollama` — change `LLM_BASE_URL=http://localhost:11434/v1`
- `vLLM` — change `LLM_BASE_URL=http://localhost:8000/v1`
- `OpenAI API` — change `LLM_BASE_URL=https://api.openai.com/v1` + add key

### Why it matters
The OpenAI API format has become the de facto standard for LLM inference. Building against it means the system is future-proof — you can swap Qwen for Llama 4 or Mistral without touching the agent code.

---

## Areas for Improvement

### High Priority

**1. Parallel tool dispatch**
Tools currently execute sequentially. Ingesting 6 PDFs takes 6× longer than ingesting 1. Fix: `asyncio.gather()` for independent tool calls in the same LLM turn, with a history format that supports parallel results.

**2. Context window management**
After 5–6 tool-heavy turns the 32K context fills. Fix: implement a background summarization step that compresses old history when token count exceeds a threshold (e.g. 20K tokens), keeping the last N turns verbatim.

**3. Tool selection benchmarking**
There is no measurement of how often the 7B model selects the correct tool. Fix: build a small eval set of 50–100 (query, expected_tool) pairs and run it regularly. Target: >80% single-step accuracy.

**4. Embedding model cold start**
First call to any knowledge tool downloads (~270MB) and loads the embedding model — causing a 30–60 second freeze. Fix: preload the embedding model at backend startup in the FastAPI `lifespan` handler.

### Medium Priority

**5. Re-ranking**
ChromaDB returns top-K by cosine similarity but cosine similarity alone is a weak signal. Fix: add a cross-encoder re-ranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) as a second pass over the top-20 candidates before sending top-5 to the LLM.

**6. Naive chunking**
512-word sliding window splits mid-sentence and mid-table. Fix: use semantic chunking (split on paragraph boundaries, headings, or sentence boundaries) to preserve coherent units of meaning.

**7. No tool pre-filtering**
All 21 tool schemas are sent on every request (~3K tokens). At 50+ tools this degrades accuracy and wastes context. Fix: embed tool descriptions and retrieve the top-K most relevant tools per query using a small retriever model.

**8. Frontend error recovery**
If the backend crashes mid-stream, the UI shows a spinning loader forever. Fix: add a 30-second timeout on the frontend that shows an error state and a retry button if no `done` event is received.

### Lower Priority

**9. No conversation summarization sidebar**
The `/sessions` endpoint exists but the frontend doesn't use it. Fix: add a left sidebar that lists past sessions with timestamps, allowing users to resume any previous conversation.

**10. Synchronous OAuth refresh**
`_get_creds()` calls `creds.refresh(Request())` synchronously, blocking the FastAPI async thread. Fix: wrap in `asyncio.run_in_executor()` or use the async Google auth library.

---

## Advantages

| Advantage | Detail |
|---|---|
| **Complete privacy** | Zero data leaves the machine — no API keys, no telemetry, no vendor access to your documents or emails |
| **Zero marginal cost** | No per-token billing after hardware setup — run it continuously for free |
| **Offline capable** | Works with no internet connection once model and embeddings are downloaded |
| **Transparent execution** | Every tool call is visible in the UI trace panel and logged to the audit trail — no black box |
| **HITL safety** | Write and destructive actions require explicit approval — prevents accidental data loss |
| **Persistent memory** | SQLite-backed sessions survive backend restarts — agent remembers previous conversations |
| **Swappable backend** | OpenAI-compat abstraction means any model server works without code changes |
| **Extensible** | Adding a new tool takes ~20 lines — no changes to the core agent loop |
| **Testable** | All business logic is decoupled from the LLM — 53 tests run fully offline with mocks |

---

## Disadvantages

| Disadvantage | Detail |
|---|---|
| **Hardware barrier** | Requires a GPU with 6GB+ VRAM — runs slowly on CPU only |
| **Model capability ceiling** | 7B models are significantly less capable than GPT-4 or Claude 3.5 on complex multi-step reasoning |
| **Setup complexity** | Requires installing llama.cpp, configuring OAuth, and running 3 separate processes |
| **Context window exhaustion** | No summarization means long sessions degrade after many tool-heavy turns |
| **Sequential tool execution** | Multi-document ingestion is slow — no parallel dispatch yet |
| **Cold start latency** | First embedding model load takes 30–60 seconds |
| **No mobile/remote access** | Bound to localhost — accessing from another device requires tunneling (e.g. ngrok) |
| **Google OAuth friction** | Requires manual Cloud Console setup and re-authentication when tokens expire |
| **No fine-tuning** | Tool selection is zero-shot — a fine-tuned router model would significantly improve accuracy |s