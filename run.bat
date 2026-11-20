@echo off
REM Install dependencies, (re)train models if needed, and start the web app.
cd /d %~dp0
python -m pip install -r requirements.txt
python -c "from src.risk import load_models; load_models()" 2>NUL || python -m src.train
echo Open http://127.0.0.1:8000
python -m uvicorn app.main:app --port 8000
