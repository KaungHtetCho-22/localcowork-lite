"""
Document MCP Server — text extraction, summarization, PDF generation
Tools: extract_text, summarize, diff_documents, create_report
"""
from __future__ import annotations

import difflib
from pathlib import Path

from backend.agent_core.tool_router import register_tool
from backend.config import settings


def _extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz
        doc = fitz.open(str(path))
        return "\n".join(page.get_text() for page in doc)
    elif suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        raise ValueError(f"Unsupported format: {suffix}")


async def extract_text(file_path: str) -> dict:
    """Extract text content from a PDF, DOCX, TXT, or MD file."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = _extract(path)
    return {
        "file": str(path),
        "text": text,
        "word_count": len(text.split()),
        "char_count": len(text),
    }


async def diff_documents(file_path_a: str, file_path_b: str) -> dict:
    """Compare two documents and return a unified diff of changes."""
    path_a = Path(file_path_a).expanduser().resolve()
    path_b = Path(file_path_b).expanduser().resolve()

    text_a = _extract(path_a).splitlines(keepends=True)
    text_b = _extract(path_b).splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        text_a, text_b,
        fromfile=path_a.name,
        tofile=path_b.name,
        lineterm="",
    ))

    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    return {
        "file_a": str(path_a),
        "file_b": str(path_b),
        "additions": additions,
        "deletions": deletions,
        "total_changes": additions + deletions,
        "diff": "".join(diff[:200]),  # cap to avoid huge payloads
    }


async def create_report(title: str, content: str, output_filename: str) -> dict:
    """Generate a simple PDF report from title + markdown content."""
    import fitz

    out_dir = Path(settings.document_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_filename

    doc = fitz.open()
    page = doc.new_page()

    # Title
    page.insert_text((72, 72), title, fontsize=18, fontname="helv")
    # Body
    page.insert_text((72, 110), content[:3000], fontsize=11, fontname="helv")

    doc.save(str(out_path))
    doc.close()

    return {
        "status": "created",
        "output_path": str(out_path),
        "title": title,
        "size_bytes": out_path.stat().st_size,
    }


# ── Register ──────────────────────────────────────────────────────────────────

register_tool(
    server="document",
    name="extract_text",
    description="Extract all text from a PDF, DOCX, TXT, or MD file.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the document"},
        },
        "required": ["file_path"],
    },
    handler=extract_text,
)

register_tool(
    server="document",
    name="diff_documents",
    description="Compare two document versions and return a unified diff showing what changed.",
    parameters={
        "type": "object",
        "properties": {
            "file_path_a": {"type": "string", "description": "Path to the original document"},
            "file_path_b": {"type": "string", "description": "Path to the revised document"},
        },
        "required": ["file_path_a", "file_path_b"],
    },
    handler=diff_documents,
)

register_tool(
    server="document",
    name="create_report",
    description="Generate a PDF report with a title and body content.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Report title"},
            "content": {"type": "string", "description": "Report body text (markdown ok)"},
            "output_filename": {"type": "string", "description": "Output filename e.g. 'summary.pdf'"},
        },
        "required": ["title", "content", "output_filename"],
    },
    handler=create_report,
)
