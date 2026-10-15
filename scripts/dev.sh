#!/usr/bin/env bash
# One-command local setup: backend venv + deps, frontend build, server on :8000.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
cd "$ROOT/frontend"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
cd "$ROOT/backend"
echo "RoboVerse Studio → http://localhost:8000  (API docs: /docs)"
exec .venv/bin/uvicorn roboverse.main:app --host 0.0.0.0 --port "${PORT:-8000}"
