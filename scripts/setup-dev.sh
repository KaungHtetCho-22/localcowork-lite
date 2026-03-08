#!/usr/bin/env bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  LocalCowork Lite — Dev Setup (uv)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Check uv is installed ─────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo ""
  echo "  uv not found. Installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "  ✓ uv $(uv --version)"

# ── Python venv + dependencies ────────────────────────────────────────────────
echo ""
echo "▶ Setting up Python backend..."

uv venv .venv --python 3.11
echo "  ✓ .venv created (Python 3.11)"

uv pip install -e ".[dev]" --python .venv/bin/python
echo "  ✓ Dependencies installed"

# ── .env ─────────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  ✓ .env created from .env.example (edit to match your setup)"
else
  echo "  ✓ .env already exists, skipping"
fi

# ── Data directories ──────────────────────────────────────────────────────────
mkdir -p .data/chroma .data/documents .data/audit
echo "  ✓ Data directories created"

# ── Frontend ──────────────────────────────────────────────────────────────────
echo ""
echo "▶ Setting up React frontend..."

if ! command -v node &>/dev/null; then
  echo "  ✗ Node.js not found. Install Node 20+ from https://nodejs.org"
  exit 1
fi
echo "  ✓ Node $(node --version)"

cd frontend
npm install --silent
cd ..
echo "  ✓ Node dependencies installed"

# ── Done ──────────────────────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
