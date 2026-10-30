# NTPC RAG Chatbot — Project Guide & Runbook

> **Project root (actual):** `D:\om chatbot\ntpc-rag-chatbot`
> (Note: not `D:\ntpc-rag-chatbot` — the folder is under `om chatbot\`, so paths contain a space; quote them in PowerShell.)
> Originally built on macOS; this guide is for the Windows port.

---

## PART 1 — Summary of changes

### What was broken / missing on arrival
- **`backend/venv` was a dead macOS venv** (`pyvenv.cfg` pointed at `/opt/anaconda3` and `/Users/ayushkumar/...`). Unusable on Windows.
- **`backend/requirements.txt` was a 615-line macOS Anaconda `pip freeze`** — full of `@ file:///private/var/...` local URLs and `pyobjc-*` (Mac-only) packages. `pip install -r` fails immediately on Windows.
- **No working Windows Python environment** existed (global Python 3.12 had only pip); the backend was not actually runnable here.
- **`indexer.py` and the agents printed emoji/box-drawing** that crash on the Windows console (cp1252 `UnicodeEncodeError`).
- The four fetch agents existed but used **plain `httpx`** for downloads, which the NTPC network edge blocks with **`403 URLBlocked`**.
- `node_modules`, `.next`, widget `dist`, and `__pycache__` were copied from the Mac (machine-specific) and were deleted.

### Key fixes applied (macOS → Windows port)
- **Rebuilt the venv**: fresh `python -m venv backend\venv`; replaced the Mac freeze with a clean, pinned **`requirements-windows.txt`** (and matching `backend/requirements.txt`). **`chromadb` is pinned to `1.5.9`** to match the on-disk index built on the Mac (a version mismatch can fail to read it). `pyobjc-*` and all `file://` lines are gone.
- **Hardcoded Mac paths**: none were found in the Python source — it already used `pathlib`/relative paths. The Mac-isms were the venv, the requirements file, and the console-encoding crashes.
- **Console encoding**: added a UTF-8 `stdout/stderr` reconfigure guard to `indexer.py` and the orchestrator, and switched agent log messages to ASCII tags (`[ok]/[skip]/[fail]`).
- **The download blocker (`403 URLBlocked`)**: all agents now download through **Chromium's own network context** (`context.request`), which shares the browser's proxy/session. This is the single change that made every source work.
- **Agents hardened**: per-run file logs, `{agent}_{YYYYMMDD}_{name}` filenames with URL-decoding, hash-dedup **seeded from the existing reports folder** (idempotent — won't duplicate files already present), an `AGENT_MAX_FILES` safety cap, network health check with clear *reachable / timeout / off-intranet* states, and a fixed browser-close bug.
- **Entry point**: `python -m scripts.agents.orchestrator` with `--only / --agents / --headed / --dry-run / --no-reindex`; re-indexing wired to run automatically after a fetch. The old `scripts/orchestrator.py` is now a forwarding shim.
- **EDOP**: it's a JS app with **no files** — discovered its public JSON API and the agent now ingests the **full Delegation-of-Powers clauses + power rows** (one PDF per DoP category).
- **Indexer extended**: now also ingests **Excel/Word/CSV** (`.xlsx/.docx/.csv`) from `data/raw/downloads/` (added `openpyxl`, `python-docx`).

### Files created / modified / deleted (by area)
**Created**
- root: `requirements-windows.txt`, `requirements-agents.txt`, `PROJECT_GUIDE.md`
- agents: `scripts/__init__.py`, `scripts/agents/orchestrator.py`
- config: `config/.env.agents` (from template; gitignored)
- backup: `backend/chroma_backup_20260603/` (pre-change index snapshot)

**Modified**
- backend: `backend/requirements.txt` (replaced the Mac freeze)
- agents: `scripts/agents/base_agent.py`, `fetch_os_tc_docs.py`, `fetch_edop.py`, `fetch_empexp.py`, `fetch_annual_reports.py`, `scripts/orchestrator.py` (→ shim), `scripts/indexer.py`, `scripts/scheduler_setup.py`
- config: `config/.env.agents.template`
- docs: `AGENTS_README.md`

**Deleted**
- `backend/venv` (Mac venv → recreated as a Windows venv), `backend/__pycache__`
- `frontend/.next`, `frontend/node_modules`, `ntpc-chat-widget/node_modules`, `ntpc-chat-widget/dist` (regenerate with `npm install`)
- `scripts/chroma` (stray empty DB)

**Deliberately untouched** (as requested): the chat UIs (`frontend/app/*`, `ntpc-chat-widget/src/*`) and the RAG core `backend/rag.py`, `backend/embedder.py`, `backend/main.py`. (`indexer.py` was extended for non-PDF ingest — a build-step change, not the chatbot's query logic.)

### Decisions you should know about
- **LLM**: `llama3.2` via Ollama (hardcoded in `backend/rag.py`, `MODEL = "llama3.2"`). Installed model is `llama3.2:latest`.
- **Embeddings**: `all-MiniLM-L6-v2` via `sentence-transformers` (CPU torch build).
- **OS/TC cap**: `AGENT_MAX_FILES=50` by default (the OS/TC site exposes ~430 PDFs). Raise it to pull more.
- **EDOP mode**: `EDOP_FETCH_MODE=full` (all clauses + powers). `summary` mode is available for a lightweight pull.
- **Index is a full rebuild**: `indexer.py` deletes and recreates the `ntpc_content` collection each run (it's idempotent; a backup exists).

### Still incomplete / fragile
- **Intranet sources need the NTPC LAN/VPN** — OS/TC, EDOP, EmpExp are intranet-only.
- **Re-index is a full rebuild**, not incremental (fine, just slower as the corpus grows).
- The **running backend caches the collection at import** — restart it after a re-index to serve new content.
- **`node_modules` are not installed** right now (cleaned up) — run `npm install` in `frontend/` and `ntpc-chat-widget/` before first use.
- **EDOP full clause text** depends on the intranet API staying public/unchanged; some legacy `.xls/.doc/.ppt` files (if any appear) are skipped by the indexer.

---

## PART 2 — How the project works

**In one paragraph:** This is a local, offline-capable Retrieval-Augmented-Generation (RAG) chatbot for NTPC. A user asks a question in the web UI; the FastAPI backend embeds the question (`all-MiniLM-L6-v2`), retrieves the most relevant text chunks from a local ChromaDB vector store (built from NTPC annual reports, website pages, OS/TC technical documents, EmpExp PDFs, and EDOP delegation-of-powers data), and asks a local Ollama `llama3.2` model to answer **using only that retrieved context**, returning the answer plus its sources. A separate set of Playwright "fetch agents" periodically downloads fresh documents from NTPC sites into the data folder and re-indexes them so the chatbot's knowledge stays current.

**Data flow**
```
  LIVE Q&A:
  Browser :3000 ─▶ Frontend (Next.js, app/page.tsx) ─┐
                                                       │ POST /chat
  Browser :5173 ─▶ Widget   (Vite/React, ChatWidget) ─┤  {question}
                                                       ▼
                                          Backend  FastAPI :8000 (main.py → rag.py)
                                                       │  embed query (embedder.py)
                                                       ▼
                                          ChromaDB  backend/chroma  (collection: ntpc_content)
                                                       │  top-K chunks + sources
                                                       ▼
                                          Ollama  llama3.2  ──▶ answer + sources ──▶ UI

  FETCH / INDEX PIPELINE (run periodically, offline):
  scripts.agents.orchestrator ─▶ Playwright/Chromium ─▶ NTPC sites (intranet + public)
        │                                                       │ files
        │                                                       ▼
        │                       frontend/public/reports/*.pdf  +  data/raw/downloads/*.{xlsx,docx,csv}
        │                                                       ▼
        └────────────────────────────▶ scripts/indexer.py (chunk + embed) ─▶ backend/chroma
```

**Roles**
- **Backend** (`backend/`, FastAPI on **:8000**) — `main.py` exposes `GET /` (health) and `POST /chat`; `rag.py` does retrieval + prompt + Ollama call; `embedder.py` loads the embedding model.
- **Frontend** (`frontend/`, Next.js on **:3000**) — the main chat web app (`app/page.tsx`). This is the URL you open to use the chatbot.
- **Widget** (`ntpc-chat-widget/`, Vite/React on **:5173**) — an embeddable chat widget (for dropping into other NTPC web pages); `public/widget.js` is the standalone embed script.
- **Agents** (`scripts/agents/`) — Playwright bots that fetch documents from four NTPC sources into the data folder, then trigger re-indexing.
- **Ollama** — runs the local `llama3.2` LLM that writes the final answer.
- **ChromaDB** (`backend/chroma/`) — the persistent vector store (collection `ntpc_content`, currently ~11,325 chunks) the backend searches.

### Intent router (small-talk shortcut)
Greetings, thanks, goodbyes, and "who/what are you / what can you do" messages **skip RAG** and get an instant canned reply — handled by **`backend/intent_router.py`** (pure regex/keyword, **no LLM, no new deps**). `backend/main.py` calls `classify_intent()` *before* retrieval; only `DOCUMENT_QUESTION` messages hit ChromaDB + Ollama.
- **Intents:** `GREETING`, `THANKS`, `GOODBYE`, `HOW_ARE_YOU`, `IDENTITY_HELP`, `UNCLEAR` → canned; **`DOCUMENT_QUESTION`** → full RAG (unchanged).
- **Rules:** case-insensitive, edge-punctuation stripped, word-boundary regex; small-talk patterns apply **only to messages ≤ 6 words** (so *"hi, what was profit in 2023"* still runs RAG). A canned reply is chosen at random per request so it doesn't feel repetitive.
- **Latency:** canned replies are instant (~0.0s) vs ~40–60s for a real CPU RAG answer.
- **Logged:** every request prints `[chat] intent=<LABEL> | msg=...` in the backend terminal — use it to verify routing.
- **To customize:** edit the canned-response lists or regex patterns in `backend/intent_router.py` (auto-reloads if the backend runs with `--reload`).

---

## PART 3 — How to run the project (Windows)

### Prerequisites
- **Python 3.12** (installed: 3.12.2) — `python --version`
- **Node.js LTS** (for Next.js 16 + Vite 8) — `node --version`
- **Ollama** with the model: `ollama list` should show `llama3.2:latest` (`ollama pull llama3.2` if missing)
- On the **NTPC LAN/VPN** only if you intend to run the intranet agents (sources 1–3)

### First-time setup (from a clean clone)
```powershell
cd "D:\om chatbot\ntpc-rag-chatbot"

# 1) Python venv + dependencies (the Windows-clean file — NOT the old Mac freeze)
python -m venv backend\venv
backend\venv\Scripts\python.exe -m pip install --upgrade pip
backend\venv\Scripts\python.exe -m pip install -r requirements-windows.txt
backend\venv\Scripts\python.exe -m playwright install chromium

# 2) Frontend + widget Node deps (node_modules were cleaned during the port)
cd frontend;            npm install; cd ..
cd ntpc-chat-widget;    npm install; cd ..

# 3) Agent config (auto-created on first agent run, or copy it explicitly)
copy config\.env.agents.template config\.env.agents
```
**.env files:** `backend/.env` is empty and not required (the RAG config lives in `backend/rag.py`). The agent config is `config/.env.agents` (gitignored). The UI→backend URL is **not** an env var — it's hardcoded to `http://localhost:8000` in `frontend/app/page.tsx` (line 25) and `ntpc-chat-widget/src/ChatWidget.jsx` (line 4).

### Daily startup — three terminals

**Terminal 1 — Backend** (FastAPI on :8000)
```powershell
cd "D:\om chatbot\ntpc-rag-chatbot\backend"
.\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
# alive check (new terminal or browser):
#   Invoke-RestMethod http://localhost:8000/
#   -> {"status":"NTPC RAG Chatbot is running ✅"}
```

**Terminal 2 — Frontend** (Next.js on :3000)
```powershell
cd "D:\om chatbot\ntpc-rag-chatbot\frontend"
npm run dev
# -> http://localhost:3000
```

**Terminal 3 — Widget** (Vite on :5173)
```powershell
cd "D:\om chatbot\ntpc-rag-chatbot\ntpc-chat-widget"
npm run dev
# -> http://localhost:5173
```

**Which URL do I open?** → **http://localhost:3000** is the chatbot (main app). **http://localhost:5173** is the embeddable widget preview. Both call the backend on :8000, which must be running first. (Ollama runs as a background service; if not, start it with `ollama serve`.)

---

## PART 4 — How and when to use the AI agents

### The four agents (source → output)

| Agent | Fetches from | Produces / where |
|-------|--------------|------------------|
| **fetch_os_tc_docs** (`os_tc`) | `http://10.0.8.241/OS-TCDocs/OS_TC_Main.aspx` (intranet, ASP.NET) — OS/TC technical documents (~430 PDFs) | PDFs → `frontend/public/reports/os_tc_<date>_*.pdf` (capped at `AGENT_MAX_FILES`) |
| **fetch_edop** (`edop`) | `https://ccitapps.ntpc.co.in/edop` (intranet, JSON API — no files) — Delegation of Powers | 1 PDF per DoP → `frontend/public/reports/edop_<date>_delegation_of_powers_<DOP>.pdf`; raw JSON → `data/raw/downloads/edop/` |
| **fetch_empexp** (`empexp`) | `http://ccitapps.ntpc.co.in/empexp` (intranet) — Employee Experience docs | PDFs → `frontend/public/reports/empexp_<date>_*.pdf` |
| **fetch_annual_reports** (`annual_reports`) | `https://www.ntpc.co.in/investors/financial-performance/annual-reports` (**public**) — annual reports | PDFs → `frontend/public/reports/annual_reports_<date>_*.pdf` |

PDFs always land in `frontend/public/reports/` (what the indexer reads). Non-PDF files would go to `data/raw/downloads/<agent>/`. A hash manifest at `data/raw/agent_manifest.json` prevents re-downloading unchanged files.

### When to run the agents
- **New data published** — e.g., a new annual report, new OS/TC circulars, updated DoP.
- **Before a demo** — to make sure the latest documents are indexed.
- **On a schedule** — e.g., nightly, via Windows Task Scheduler (see below).
- After moving to a machine that's **freshly on the NTPC LAN** and you want intranet content.

### When NOT to run the agents
- **When the PC is off the NTPC intranet/VPN** — sources 1–3 (`10.0.8.241`, `ccitapps.ntpc.co.in`) will report **`Off NTPC intranet - host unreachable`** / **`Timeout`** and be skipped. `annual_reports` (public) still works.
- The orchestrator does a health check first and skips unreachable sources rather than faking success — so a partial run off-LAN is safe, it just won't fetch intranet docs.

### How to run (exact commands, from the project root)
```powershell
cd "D:\om chatbot\ntpc-rag-chatbot"

# Run ALL agents, then auto re-index
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator

# Run a SINGLE agent
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --only annual_reports

# Run a subset
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --agents os_tc edop

# Watch the browser (non-headless), useful for debugging selectors
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --only annual_reports --headed

# Network health check only — no downloads
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --dry-run

# Fetch but skip the re-index
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --no-reindex
```
To pull more OS/TC docs, raise `AGENT_MAX_FILES` in `config/.env.agents` (default 50; the site has ~430).

### Scheduling recurring runs (REGISTERED — daily 12:00 PM)
A Windows Task Scheduler job **`NTPC_FetchAgents`** is registered and live. Daily at **12:00 PM (noon)** it runs `scripts\run_agents.bat` → `python -m scripts.agents.orchestrator`: fetch every source → skip byte-identical files (hash dedup) → download only new/changed files → auto re-index ChromaDB. All output is appended to `logs\agents\scheduled.log`.

> **Runs only while you are logged on** (LogonType: Interactive). The PC must be **on AND on the NTPC LAN/VPN at 12:00 PM**, or the three intranet sources are skipped (annual_reports still works). To run even when logged off: Task Scheduler → `NTPC_FetchAgents` → *Run whether user is logged on or not* (needs your Windows password). If the backend was left running overnight, **restart it** after the run so it serves the new index.

Manage it:
```powershell
Get-ScheduledTaskInfo   -TaskName NTPC_FetchAgents       # next/last run + last result
Start-ScheduledTask     -TaskName NTPC_FetchAgents       # run now (full fetch + re-index)
Disable-ScheduledTask   -TaskName NTPC_FetchAgents       # pause
Enable-ScheduledTask    -TaskName NTPC_FetchAgents       # resume
Unregister-ScheduledTask -TaskName NTPC_FetchAgents -Confirm:$false   # remove
Get-Content logs\agents\scheduled.log -Tail 40           # read the run log
```
(`scripts/scheduler_setup.py` still prints equivalent cron / Task Scheduler XML if you ever need to recreate the job manually.)

### Logs
- Per-agent: `logs/agents/<agent>_<timestamp>.log` (URL, mode, each file, errors, duration)
- Per run: `logs/agents/run_<timestamp>.json` (machine-readable summary)
```powershell
Get-ChildItem logs\agents | Sort-Object LastWriteTime -Descending | Select-Object -First 5
Get-Content (Get-ChildItem logs\agents\os_tc_*.log | Sort-Object LastWriteTime -Desc | Select -First 1)
```

### Confirm new data reached the chatbot
1. Agents auto re-index after a successful fetch. To re-index manually:
   ```powershell
   backend\venv\Scripts\python.exe scripts\indexer.py
   ```
   The last line prints e.g. `Done! 11325 chunks saved to ChromaDB`.
2. **Restart the backend** (it caches the collection at startup).
3. Ask a question that only the new docs can answer, e.g. in the UI:
   - OS/TC: *"What does NTPC's guideline on condensate polishing plant operation cover?"*
   - EDOP: *"Who is authorized to sanction or abolish posts in HR?"*

---

## PART 5 — Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `python` opens Microsoft Store / "not found" | Windows Store alias | Use the venv python directly (`backend\venv\Scripts\python.exe`) or `py`, or turn off the alias in *Settings → App execution aliases*. |
| `pip install` crashes on `pyobjc` / `file:///` lines | Old macOS `pip freeze` | Install from **`requirements-windows.txt`**, not the original Mac list. |
| Frontend/widget loads but chat fails / network error | Backend not on :8000, or URL mismatch | Start the backend first; the URL is hardcoded `http://localhost:8000` in `frontend/app/page.tsx:25` and `ntpc-chat-widget/src/ChatWidget.jsx:4` — edit those if you change the port. |
| `npm run dev` fails: missing modules | `node_modules` were cleaned in the port | `npm install` in `frontend/` and `ntpc-chat-widget/`. |
| Agent: `Off NTPC intranet - host unreachable` / `Timeout` | PC not on NTPC LAN/VPN | Connect to the NTPC network (sources 1–3 are intranet-only); `annual_reports` still works off-LAN. |
| Agent downloads fail `403 URLBlocked` | A direct (non-browser) request hit the NTPC proxy | Already handled — agents download via Chromium's context. If you add new download code, use `download_via_context`, not raw httpx. |
| `LLM error ... Check if Ollama is running` | Ollama down or wrong model | `ollama list` (expect `llama3.2:latest`); `ollama serve`; `ollama pull llama3.2`. Model name in `backend/rag.py` is `llama3.2`. |
| ChromaDB read error / `no such column` after copying from Mac | chromadb version mismatch | Keep `chromadb==1.5.9` pinned (matches the on-disk index); restore `backend/chroma_backup_20260603` if needed. |
| Indexer crashes with `UnicodeEncodeError` (`✅`) | Emoji print on cp1252 console | Already fixed (UTF-8 reconfigure). If you add prints, keep ASCII or rely on that guard. |
| "Knowledge base not ready" answer | Index empty / not built | Run `scripts\indexer.py`, then restart the backend. |
| Chatbot doesn't show newly fetched docs | Backend cached old collection | Restart the backend after re-index. |

---

## PART 6 — Quick reference card

| Item | Value |
|---|---|
| **Project root** | `D:\om chatbot\ntpc-rag-chatbot` |
| **Backend** | `cd backend; .\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000` → http://localhost:8000 (health `GET /`, chat `POST /chat`) |
| **Frontend (open this)** | `cd frontend; npm run dev` → **http://localhost:3000** |
| **Widget** | `cd ntpc-chat-widget; npm run dev` → http://localhost:5173 |
| **Run all agents + reindex** | `backend\venv\Scripts\python.exe -m scripts.agents.orchestrator` |
| **One agent** | `... -m scripts.agents.orchestrator --only annual_reports` |
| **Re-index manually** | `backend\venv\Scripts\python.exe scripts\indexer.py` |
| **Small-talk router** | `backend/intent_router.py` (regex, no LLM) — greetings/thanks/etc. skip RAG; log line `[chat] intent=...` |
| **LLM** | Ollama `llama3.2` (`llama3.2:latest`) |
| **Embeddings** | `all-MiniLM-L6-v2` (sentence-transformers) |
| **Vector store** | `backend\chroma` — collection `ntpc_content`, chromadb **1.5.9** (~11,325 chunks) |
| **Index backup** | `backend\chroma_backup_20260603` |
| **PDF data folder** | `frontend\public\reports` (indexer reads here) |
| **Non-PDF downloads** | `data\raw\downloads\<agent>` (xlsx/docx/csv indexed) |
| **Logs** | `logs\agents\<agent>_<timestamp>.log` + `run_<timestamp>.json` |
| **Agent config** | `config\.env.agents` (from `.env.agents.template`) |
| **Dependencies** | `requirements-windows.txt` (Python), `npm install` (frontend + widget) |

---

## PART 7 — Live server deployment (production)

> This documents the **production server**, which is separate from the local dev setup in PARTs 1–6. Day-to-day server commands also live in **`OPS_CHEATSHEET.md`**.

### Where it runs
- **Server:** Windows host **`STAGESEV1`**, reached via **Remote Desktop** as the **`Administrator`** account.
- **Project path:** **`E:\ayush\NTPC-CHATBOT-DEPLOY-READY`** (NOT the local `D:\om chatbot\...`). Editing the local files does nothing on the server until copied over.
- **Public URL:** **https://itstaging.ntpc.co.in/chatbot/** — **IIS** (app pool **`NTPC-ChatbotPool`**, "No Managed Code") reverse-proxies `/chatbot` → `127.0.0.1:8000`.

### Two layers — don't confuse them
```
Browser → https://itstaging.ntpc.co.in/chatbot/
        → IIS site (NTPC-ChatbotPool)  — reverse proxy only, runs NO Python
        → uvicorn / FastAPI on 127.0.0.1:8000   ← the REAL backend
```
`NTPC-ChatbotPool` showing "Started" does **not** mean the backend is up — it only proxies. If uvicorn is down, the public URL returns **502 Bad Gateway**.

### How the backend is started
- **Launcher:** `E:\ayush\NTPC-CHATBOT-DEPLOY-READY\start_backend.bat` → `cd backend`; sets `PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`; runs
  `venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --root-path /chatbot >> logs\backend.log 2>&1`.
  (`HTTP_PROXY` is set per-user via `setx`, not in the bat.)
- **Auto-start:** scheduled task **`omchatbot`** (Task Scheduler Library, root `\`), trigger **At log on of `STAGESEV1\Administrator`**, LogonType Interactive, runs `start_backend.bat`.
  - It MUST be **At-Logon** (not At-Startup): Ollama and the per-user `HTTP_PROXY` only exist inside the Administrator session.
  - **Restart command:**
    ```powershell
    schtasks /End /TN "omchatbot"
    schtasks /Run /TN "omchatbot"
    ```
- ⚠️ **Disconnect, never Sign out** — the backend AND Ollama live in the Administrator session; signing out kills both. (Surviving a reboot with nobody logged in would need Ollama-as-a-service + auto-login/SYSTEM task — not done.)

### ⚠️ Startup-timing gotcha
uvicorn binds port 8000 **only after** the embedding model + Chroma index finish loading (lifespan startup runs before bind). So for ~30–90s after a start, `http://127.0.0.1:8000/` returns "connection refused" **even though it is loading fine**. Don't conclude failure at 30s — check for a live `python.exe … uvicorn` process; only *no* python process means it actually failed. Health check (bypasses the system proxy):
```powershell
$wc = New-Object System.Net.WebClient; $wc.Proxy = $null
$wc.DownloadString("http://127.0.0.1:8000/")
```
> ⚠️ Do **not** restart with `Start-Process cmd.exe -ArgumentList '/c','"...bat"'` — the nested-quote handling fails silently and leaves the backend down. Use the `omchatbot` task, or run uvicorn in the foreground for a visible/debuggable start.

### Edit + restart the backend on the server
```powershell
notepad E:\ayush\NTPC-CHATBOT-DEPLOY-READY\backend\rag.py     # code loads at startup; no --reload
schtasks /End /TN "omchatbot"; Start-Sleep 3; schtasks /Run /TN "omchatbot"   # apply, then verify health
```

### Agents on the server — 7 sources (vs 4 locally)
The agents scrape **7 sources**: `os_tc, edop, empexp, circular_repository, ntpcwiki, safety_portal, csr_list` (intranet — need the NTPC LAN). `annual_reports` (public NTPC website) is the only one that works off-LAN. Run with the offline env vars set; the orchestrator auto re-indexes, then **restart the backend** (it caches the collection at import):
```powershell
cd E:\ayush\NTPC-CHATBOT-DEPLOY-READY
$env:PYTHONUTF8=1; $env:HF_HUB_OFFLINE=1; $env:TRANSFORMERS_OFFLINE=1
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --only circular_repository
```

### Retrieval fix — circular-number queries (CHRC etc.)
`rag.py` retrieval was 100% vector search (all-MiniLM), which can't match exact IDs like "CHRC No. 992/2026", so those queries returned annual reports. Added a **keyword pass** (`keyword_id_chunks` + `_all_sources` in `backend/rag.py`): it extracts circular numbers from the query and matches them against document **filenames** (the files are named `CHRC992.pdf`), forcing those chunks to the top of the context (distance −1.0). Vector search still handles normal questions; no re-index needed (`rag.py`-only). Deploy to the server via the self-backing-up patch (see `OPS_CHEATSHEET.md` / session notes), then restart `omchatbot`.

### Known data gaps
- **"Fetched" ≠ "indexed" ≠ "searchable".** After any fetch, confirm with a substring check:
  ```python
  col.get(where_document={"$contains": "<term>"}, include=["metadatas"])   # 0 = not searchable
  ```
- **Scanned circulars** (e.g. `CHRC455.pdf`) have `text_chars=0` — `get_text()` extracts nothing, so they're unsearchable. Fixing them needs **OCR**: install **Tesseract** on the server (an IT request) + an indexer change to OCR image-only pages (`page.get_textpage_ocr()`). Not done.

### Backup & restore (server)
Backup the backend (code + chroma index, **excluding** the recreatable `venv`) to a timestamped zip:
```powershell
$ts=Get-Date -Format "yyyyMMdd_HHmmss"; $stage="E:\ayush\backups\_stage_$ts"; $zip="E:\ayush\backups\backend_$ts.zip"
robocopy "E:\ayush\NTPC-CHATBOT-DEPLOY-READY\backend" $stage /E /XD venv __pycache__ /R:1 /W:1 | Out-Null
Compress-Archive -Path "$stage\*" -DestinationPath $zip -CompressionLevel Optimal -Force
if (Test-Path $zip) { Remove-Item $stage -Recurse -Force }
```
**Restore:** stop `omchatbot` → snapshot current → `Remove-Item backend\chroma -Recurse -Force` → `Expand-Archive $zip -DestinationPath …\backend -Force` → start `omchatbot`. The zip has **no `venv`** — on a fresh machine recreate it from `requirements-windows.txt`. Copy the zip **off-server** for real disaster recovery.
