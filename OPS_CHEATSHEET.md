# NTPC Chatbot — Operations Cheat Sheet (live server)

Day-to-day commands for the deployed backend. Assumes you are logged in as
**Administrator** on the server (Ollama runs in that session) and the project is
at **`E:\ayush\NTPC-CHATBOT-DEPLOY-READY`** (adjust the path if different).

## Key facts
- **Backend** = Windows scheduled task **`NTPC-Backend`** → runs `start_backend.bat`
  → `uvicorn` on `127.0.0.1:8000`, in the background, logging to `logs\backend.log`.
- **Public URL** = `https://itstaging.ntpc.co.in/chatbot/`
  (IIS reverse-proxies `/chatbot` → `127.0.0.1:8000`). Chat call:
  `POST https://itstaging.ntpc.co.in/chatbot/chat`  body `{"question":"..."}`.
- **venv python** = `backend\venv\Scripts\python.exe`
- **Offline/env flags** (set persistently via `setx`, and inside `start_backend.bat`):
  `PYTHONUTF8=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HTTP_PROXY=http://10.0.9.40:8080`.
  Ollama is reached directly (rag.py uses `trust_env=False`), so the proxy never blocks it.

---

## A) Edit the backend (code)
```powershell
notepad E:\ayush\NTPC-CHATBOT-DEPLOY-READY\backend\rag.py     # or main.py, embedder.py
```
Edit, save. Python changes do **not** take effect until you restart the backend (step B).

## B) Run / restart the backend
GUI: Task Scheduler (`taskschd.msc`) → Library → **NTPC-Backend** → **End**, then **Run**.
Command line:
```powershell
schtasks /End /TN "NTPC-Backend"
schtasks /Run /TN "NTPC-Backend"
```
Verify it started:
```powershell
Get-Content E:\ayush\NTPC-CHATBOT-DEPLOY-READY\logs\backend.log -Tail 15
```
Expect `Documents: <N>` + `Application startup complete`. Quick local test (bypasses proxy):
```powershell
$wc = New-Object System.Net.WebClient; $wc.Proxy = $null
$wc.DownloadString("http://localhost:8080/")
```

## C) Run the agents (fetch new data → auto re-index)
```powershell
cd E:\ayush\NTPC-CHATBOT-DEPLOY-READY
$env:PYTHONUTF8=1; $env:HF_HUB_OFFLINE=1; $env:TRANSFORMERS_OFFLINE=1
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator
```
- One source only: append `--only <name>` where `<name>` is one of:
  `os_tc`, `edop`, `empexp`, `annual_reports`, `circular_repository`, `ntpcwiki`, `safety_portal`, `csr_list`
- Network health check only (no downloads): `--dry-run`
- Skip the re-index after fetching: `--no-reindex`
- Per-agent logs: `logs\agents\<agent>_<timestamp>.log`
- The orchestrator **auto re-indexes** new files at the end → then **restart the backend (step B)**
  so it serves the new data (it caches the index at startup).

## D) Re-index manually (rarely needed)
```powershell
cd E:\ayush\NTPC-CHATBOT-DEPLOY-READY
$env:PYTHONUTF8=1; $env:HF_HUB_OFFLINE=1; $env:TRANSFORMERS_OFFLINE=1
backend\venv\Scripts\python.exe scripts\indexer.py            # incremental (only new files)
backend\venv\Scripts\python.exe scripts\indexer.py --rebuild  # full rebuild
```
Then restart the backend (step B).

---

## Golden rules
1. **Edit code → restart the backend (B).** A running process won't see file changes.
2. **Run agents → restart the backend (B).** So the freshly-indexed data is served.
3. **Stay logged in as Administrator.** Ollama (the LLM) runs in that session; logging off stops answers.
4. **Intranet agents need the server on the NTPC LAN** (it is). `annual_reports` hits the public
   site (needs the proxy); the 7 intranet sources work directly.
5. **Don't normally touch IIS** — it only forwards. If the proxy misbehaves: in IIS Manager restart
   just the chatbot site, or `iisreset` (restarts *all* IIS sites on the box — use cautiously, other
   apps share it).

## Quick health checks
```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen   # backend listening?
ollama list                                          # llama3.2 present + Ollama up?
Get-ScheduledTaskInfo -TaskName "NTPC-Backend"       # last run / next run
```
