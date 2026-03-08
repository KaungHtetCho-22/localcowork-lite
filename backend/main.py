"""
LocalCowork Lite — FastAPI backend
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings
from backend.agent_core.conversation import ConversationManager
from backend.agent_core.tool_router import list_tools
from backend.agent_core.audit import audit
from backend.inference.client import inference


# ── Session store (in-memory, one ConversationManager per session) ────────────
_sessions: dict[str, ConversationManager] = {}


def _get_session(session_id: str) -> ConversationManager:
    if session_id not in _sessions:
        cm = ConversationManager()
        cm.session_id = session_id
        _sessions[session_id] = cm
    return _sessions[session_id]


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✓ LocalCowork Lite backend starting")
    print(f"  LLM endpoint : {settings.llm_base_url}")
    print(f"  ChromaDB     : {settings.chroma_persist_dir}")
    print(f"  Sandbox      : {settings.sandbox_path}")
    yield
    print("LocalCowork Lite backend stopped")


app = FastAPI(title="LocalCowork Lite", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    llm_ok = await inference.health()
    return {
        "status": "ok",
        "llm_connected": llm_ok,
        "llm_url": settings.llm_base_url,
        "model": settings.llm_model,
    }


@app.get("/tools")
async def get_tools():
    return {"tools": list_tools(), "count": len(list_tools())}


@app.get("/audit")
async def get_audit(session_id: str | None = None, limit: int = 50):
    entries = await audit.get_log(session_id=session_id, limit=limit)
    summary = await audit.summary(session_id=session_id)
    return {"entries": entries, "summary": summary}


class ResetRequest(BaseModel):
    session_id: str


@app.post("/session/reset")
async def reset_session(req: ResetRequest):
    if req.session_id in _sessions:
        _sessions[req.session_id].reset()
    return {"status": "reset", "session_id": req.session_id}


# ── WebSocket chat endpoint ────────────────────────────────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    """
    WebSocket protocol:
      Client → {"message": "user text"}
      Server → stream of JSON events:
        {"type": "tool_call",   "tool": "...", "arguments": {...}}
        {"type": "tool_result", "tool": "...", "success": bool, "result": ..., "latency_ms": ...}
        {"type": "text_delta",  "content": "..."}
        {"type": "done"}
        {"type": "error",       "message": "..."}
    """
    await websocket.accept()
    cm = _get_session(session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            user_message = data.get("message", "").strip()
            if not user_message:
                continue

            try:
                async for event in cm.turn(user_message):
                    await websocket.send_text(json.dumps(event))
            except Exception as exc:
                await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))

    except WebSocketDisconnect:
        pass
