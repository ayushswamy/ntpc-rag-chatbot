@echo off
REM ============================================================
REM  NTPC fetch agents - scheduled daily run (fetch + auto re-index)
REM  Invoked by the Windows Task Scheduler job "NTPC_FetchAgents".
REM  All output is appended to logs\agents\scheduled.log
REM ============================================================
cd /d "D:\om chatbot\ntpc-rag-chatbot"
echo ===== Run started %DATE% %TIME% ===== >> "logs\agents\scheduled.log"
"D:\om chatbot\ntpc-rag-chatbot\backend\venv\Scripts\python.exe" -m scripts.agents.orchestrator >> "logs\agents\scheduled.log" 2>&1
echo ===== Run finished %DATE% %TIME% (exit %ERRORLEVEL%) ===== >> "logs\agents\scheduled.log"
