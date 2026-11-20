#!/usr/bin/env bash
# Install dependencies, (re)train models if needed, and start the web app.
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
python3 -c "from src.risk import load_models; load_models()" 2>/dev/null || python3 -m src.train
echo "Open http://127.0.0.1:8000"
python3 -m uvicorn app.main:app --port 8000
