#!/bin/bash
# =============================================================================
# build-pyinstaller.sh
# Bundles the Python backend into a standalone binary and registers it as a
# Tauri sidecar. Run from the project root.
#
# When to run:
#   - First time setup
#   - Any time backend/ Python code changes
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SIDECAR_DIR="$PROJECT_ROOT/frontend/src-tauri/binaries"
TRIPLE="x86_64-unknown-linux-gnu"
VENV="$PROJECT_ROOT/.venv"
PYTHON="$VENV/bin/python"
PYINSTALLER="$VENV/bin/pyinstaller"

echo ""
echo "=================================================="
echo " Step 1/3 — Build Python backend binary"
echo "=================================================="
echo ""

# ── Ensure pyinstaller is installed ──────────────────────────────────────
if [ ! -f "$PYINSTALLER" ]; then
    echo "Installing pyinstaller..."
    "$VENV/bin/pip" install pyinstaller
fi

# ── Write launcher.py ─────────────────────────────────────────────────────
cat > "$PROJECT_ROOT/backend/launcher.py" << 'LAUNCHER'
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
LAUNCHER
echo "✓ backend/launcher.py written"

# ── Get site-packages path ─────────────────────────────────────────────────
SITE_PACKAGES=$("$PYTHON" -c "import site; print(site.getsitepackages()[0])")
echo "✓ site-packages: $SITE_PACKAGES"

# ── Run PyInstaller ────────────────────────────────────────────────────────
echo ""
echo "Building binary (2-5 min)..."
cd "$PROJECT_ROOT"

"$PYINSTALLER" --onefile \
  --name uvicorn-backend \
  --runtime-tmpdir /tmp/localcowork-lite \
  --paths "$SITE_PACKAGES" \
  --add-data "backend:backend" \
  --hidden-import fastapi \
  --hidden-import fastapi.middleware \
  --hidden-import fastapi.middleware.cors \
  --hidden-import uvicorn \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols \
  --hidden-import uvicorn.protocols.http \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan \
  --hidden-import uvicorn.lifespan.on \
  --hidden-import starlette \
  --hidden-import starlette.routing \
  --hidden-import starlette.middleware \
  --hidden-import pydantic \
  --hidden-import pydantic_settings \
  --hidden-import aiofiles \
  --hidden-import chromadb \
  --hidden-import chromadb.db.impl \
  --hidden-import chromadb.db.impl.sqlite \
  --hidden-import chromadb.segment \
  --hidden-import chromadb.segment.impl.vector \
  --hidden-import chromadb.segment.impl.vector.local_hnsw \
  --hidden-import chromadb.segment.impl.metadata \
  --hidden-import chromadb.segment.impl.metadata.sqlite \
  --hidden-import sentence_transformers \
  --hidden-import openai \
  --hidden-import google_auth_oauthlib \
  --hidden-import google_auth_oauthlib.flow \
  --hidden-import googleapiclient \
  --hidden-import googleapiclient.discovery \
  --hidden-import charset_normalizer \
  --hidden-import chardet \
  --hidden-import email.mime.text \
  --hidden-import email.mime.multipart \
  --hidden-import email.mime.base \
  --collect-all chromadb \
  --clean --noconfirm \
  backend/launcher.py

echo "✓ dist/uvicorn-backend built"

# ── Test the binary ────────────────────────────────────────────────────────
echo ""
echo "=================================================="
echo " Step 2/3 — Test binary"
echo "=================================================="
echo ""

pkill -f "dist/uvicorn-backend" 2>/dev/null || true
rm -rf /tmp/localcowork-lite
sleep 1

"$PROJECT_ROOT/dist/uvicorn-backend" &
BACKEND_PID=$!
echo "Started PID $BACKEND_PID, waiting 8s..."
sleep 8

if curl -sf http://localhost:8000/health > /dev/null; then
    echo "✓ Backend healthy at http://localhost:8000/health"
    kill $BACKEND_PID 2>/dev/null || true
    wait $BACKEND_PID 2>/dev/null || true
else
    echo "✗ Backend did not respond. Run manually to see error:"
    echo "  ./dist/uvicorn-backend"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

# ── Copy to Tauri sidecar ──────────────────────────────────────────────────
echo ""
echo "=================================================="
echo " Step 3/3 — Register as Tauri sidecar"
echo "=================================================="
echo ""

mkdir -p "$SIDECAR_DIR"
cp "$PROJECT_ROOT/dist/uvicorn-backend" \
   "$SIDECAR_DIR/uvicorn-backend-$TRIPLE"
chmod +x "$SIDECAR_DIR/uvicorn-backend-$TRIPLE"
echo "✓ Copied to binaries/uvicorn-backend-$TRIPLE"

# ── Update tauri.conf.json ─────────────────────────────────────────────────
"$PYTHON" - << 'PYEOF'
import json
conf_path = "frontend/src-tauri/tauri.conf.json"
with open(conf_path) as f:
    conf = json.load(f)
conf['bundle']['externalBin'] = [
    'binaries/llama-server',
    'binaries/uvicorn-backend',
]
with open(conf_path, 'w') as f:
    json.dump(conf, f, indent=2)
print("✓ tauri.conf.json updated")
PYEOF

echo ""
echo "=================================================="
echo " build-pyinstaller.sh complete"
echo " Next: ./build-tauri.sh"
echo "=================================================="
echo ""