"""
Knowledge MCP Server — RAG pipeline
Tools: ingest_document, search, list_sources, delete_source
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from backend.agent_core.tool_router import register_tool
from backend.config import settings

# ── ChromaDB client (lazy init) ──────────────────────────────────────────────
_client: chromadb.ClientAPI | None = None
_collection: Any = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.embed_model,
            device=settings.embed_device,
            trust_remote_code=True,
        )
        _collection = _client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ── Helpers ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """Simple sliding-window chunker."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # pymupdf
        doc = fitz.open(str(path))
        return "\n".join(page.get_text() for page in doc)
    elif suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def ingest_directory(directory: str, pattern: str = "*.pdf") -> dict:
    """Ingest all matching files in a directory into the knowledge base."""
    import glob
    path = Path(directory).expanduser().resolve()
    files = list(path.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching '{pattern}' in {path}")
    
    results = []
    for f in files:
        result = await ingest_document(str(f))
        results.append(result)
    
    return {"ingested": len(results), "files": [r["file"] for r in results]}

async def ingest_document(file_path: str) -> dict:
    """Ingest a document (PDF, TXT, MD, DOCX) into the knowledge base."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = _extract_text(path)
    chunks = _chunk_text(text)
    source_id = hashlib.md5(str(path).encode()).hexdigest()[:12]

    col = _get_collection()
    ids = [f"{source_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": str(path), "source_id": source_id, "chunk_index": i} for i in range(len(chunks))]

    # Delete existing chunks for this source before re-ingesting
    try:
        col.delete(where={"source_id": source_id})
    except Exception:
        pass

    col.add(documents=chunks, ids=ids, metadatas=metadatas)

    return {
        "status": "ingested",
        "file": str(path),
        "chunks": len(chunks),
        "source_id": source_id,
        "characters": len(text),
    }


async def search(query: str, n_results: int = 5) -> dict:
    """Semantic search across the knowledge base."""
    col = _get_collection()
    results = col.query(query_texts=[query], n_results=n_results)

    hits = []
    for i, doc in enumerate(results["documents"][0]):
        hits.append({
            "content": doc,
            "source": results["metadatas"][0][i].get("source", "unknown"),
            "distance": round(results["distances"][0][i], 4),
        })

    return {"query": query, "hits": hits, "total": len(hits)}


async def list_sources() -> dict:
    """List all ingested documents in the knowledge base."""
    col = _get_collection()
    all_meta = col.get(include=["metadatas"])["metadatas"]

    seen: dict[str, str] = {}
    for m in all_meta:
        sid = m.get("source_id", "")
        if sid not in seen:
            seen[sid] = m.get("source", "unknown")

    return {
        "sources": [{"source_id": k, "path": v} for k, v in seen.items()],
        "total": len(seen),
    }


async def delete_source(source_id: str) -> dict:
    """Remove a document and all its chunks from the knowledge base."""
    col = _get_collection()
    col.delete(where={"source_id": source_id})
    return {"status": "deleted", "source_id": source_id}


# ── Register ──────────────────────────────────────────────────────────────────

register_tool(
    server="knowledge",
    name="ingest_document",
    description="Ingest a document (PDF, TXT, MD, DOCX) into the local knowledge base for semantic search.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or ~ path to the document"},
        },
        "required": ["file_path"],
    },
    handler=ingest_document,
)

register_tool(
    server="knowledge",
    name="search",
    description="Semantic search across all ingested documents in the knowledge base.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language search query"},
            "n_results": {"type": "integer", "description": "Number of results to return (default 5)", "default": 5},
        },
        "required": ["query"],
    },
    handler=search,
)

register_tool(
    server="knowledge",
    name="list_sources",
    description="List all documents currently in the knowledge base.",
    parameters={"type": "object", "properties": {}},
    handler=list_sources,
)

register_tool(
    server="knowledge",
    name="delete_source",
    description="Remove a document from the knowledge base by source_id.",
    parameters={
        "type": "object",
        "properties": {
            "source_id": {"type": "string", "description": "The source_id returned by list_sources"},
        },
        "required": ["source_id"],
    },
    handler=delete_source,
)

register_tool(
    server="knowledge",
    name="ingest_directory",
    description="Ingest all files matching a pattern in a directory (e.g. all PDFs) into the knowledge base.",
    parameters={
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Directory path"},
            "pattern": {"type": "string", "description": "Glob pattern e.g. '*.pdf', '*.md'", "default": "*.pdf"},
        },
        "required": ["directory"],
    },
    handler=ingest_directory,
)