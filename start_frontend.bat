@echo off
REM ============================================================
REM  Starts the NTPC chatbot FRONTEND (Next.js production server).
REM  Requires `npm run build` to have been done once already.
REM  Run by a Windows service (NSSM) or Task Scheduler at startup.
REM ============================================================
cd /d "%~dp0frontend"
if not exist "%~dp0logs" mkdir "%~dp0logs"
call npx next start -p 3000 >> "%~dp0logs\frontend.log" 2>&1
