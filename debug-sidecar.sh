#!/bin/bash
# =============================================================================
# debug-sidecar.sh
# Installs a debug wrapper for the uvicorn-backend sidecar, rebuilds the .deb,
# and reinstalls it. After launching the app, run with --logs to read output.
#
# Usage:
#   ./debug-sidecar.sh          — install debug wrapper + rebuild + reinstall
#   ./debug-sidecar.sh --logs   — read the sidecar log after launching the app
#   ./debug-sidecar.sh --clean  — restore normal wrapper + rebuild + reinstall
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SIDECAR_DIR="$PROJECT_ROOT/frontend/src-tauri/binaries"
TRIPLE="x86_64-unknown-linux-gnu"
WRAPPER="$SIDECAR_DIR/uvicorn-backend-$TRIPLE"
LOG="/tmp/uvicorn-backend.log"

build_and_install() {
    echo "[1/2] Building .deb..."
    cd "$PROJECT_ROOT/frontend"
    cargo tauri build 2>&1 | tail -5

    echo "[2/2] Installing .deb..."
    DEB=$(find src-tauri/target/release/bundle/deb -name "*.deb" | head -1)
    sudo dpkg -i "$DEB"
    echo "✓ Installed. Launch the app now."
}

# ── --logs: just read the log ─────────────────────────────────────────────
if [ "$1" = "--logs" ]; then
    if [ ! -f "$LOG" ]; then
        echo "No log found at $LOG — launch the app first."
        exit 1
    fi
    echo "=== $LOG ==="
    cat "$LOG"
    exit 0
fi

# ── --clean: restore normal wrapper ──────────────────────────────────────
if [ "$1" = "--clean" ]; then
    echo "Restoring normal wrapper..."
    cat > "$WRAPPER" << 'WRAPPER_CONTENT'
#!/bin/bash
DATA_DIR="$HOME/.local/share/localcowork-lite"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/uvicorn-backend-dir/uvicorn-backend" "$@"
WRAPPER_CONTENT
    chmod +x "$WRAPPER"
    echo "✓ Normal wrapper restored"
    build_and_install
    exit 0
fi

# ── default: install debug wrapper ───────────────────────────────────────
echo "Installing debug wrapper → logs will go to $LOG"

cat > "$WRAPPER" << 'WRAPPER_CONTENT'
#!/bin/bash
exec > /tmp/uvicorn-backend.log 2>&1
echo "=== wrapper started at $(date) ==="
echo "=== pwd: $(pwd) ==="
echo "=== HOME: $HOME ==="
echo "=== USER: $USER ==="

DATA_DIR="$HOME/.local/share/localcowork-lite"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"
echo "=== cd to: $DATA_DIR ==="

DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=== binary dir: $DIR ==="
echo "=== launching: $DIR/uvicorn-backend-dir/uvicorn-backend ==="
echo "=== checking binary exists: $(ls -la $DIR/uvicorn-backend-dir/uvicorn-backend 2>&1) ==="

exec "$DIR/uvicorn-backend-dir/uvicorn-backend" "$@"
WRAPPER_CONTENT

chmod +x "$WRAPPER"
echo "✓ Debug wrapper written"

build_and_install

echo ""
echo "Next steps:"
echo "  1. Launch LocalCowork Lite from app menu"
echo "  2. Wait for it to fail"
echo "  3. Run: ./debug-sidecar.sh --logs"
echo ""