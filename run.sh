#!/bin/bash

# 1. Kill existing process on port 8000
echo "[Setup] Cleaning up port 8000..."
lsof -ti :8000 | xargs kill -9 2>/dev/null

# 2. Activate virtual environment (check local .venv first, then fallback)
if [ -d ".venv" ]; then
    echo "[Env] Activating local .venv..."
    source .venv/bin/activate
elif [ -d "$HOME/fin_auto_venv" ]; then
    echo "[Env] Activating $HOME/fin_auto_venv..."
    source "$HOME/fin_auto_venv/bin/activate"
else
    echo "[Warning] No virtual environment found. Running with system python."
fi

# 3. Start server
echo "[FastAPI] Starting server at http://localhost:8000"
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload \
  --reload-dir api \
  --reload-dir screener \
  --reload-dir services \
  --reload-dir static \
  --reload-dir templates