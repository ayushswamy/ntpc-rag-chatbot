@echo off
REM ============================================================
REM  Starts the NTPC chatbot BACKEND (FastAPI/uvicorn) for deployment.
REM  Run by a Windows service (NSSM) or Task Scheduler at startup.
REM  Sets the offline flags so the embedding model loads from the
REM  bundled cache (no internet). Ollama is reached directly (the
REM  rag.py client uses trust_env=False, so the proxy is bypassed).
REM ============================================================
cd /d "%~dp0backend"
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
if not exist "%~dp0logs" mkdir "%~dp0logs"
venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 >> "%~dp0logs\backend.log" 2>&1
