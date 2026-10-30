# NTPC Fetch-Agent System

Automated download layer for the NTPC RAG chatbot. Four fetch agents navigate
NTPC sources, download documents, and drop them into the same folder the
chatbot's indexer already reads (`frontend/public/reports/`) — then re-index —
with **no changes to the UI or the RAG query code**.

---

## Quick Start (Windows)

```powershell
# 1. Create the venv and install dependencies (one time)
python -m venv backend\venv
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\venv\Scripts\python.exe -m playwright install chromium

# 2. Config is auto-created from the template on first run; to customize:
copy config\.env.agents.template config\.env.agents

# 3. Run ALL agents, then auto re-index (run from the project root)
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator

# 4. Run a single agent / a subset
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --only annual_reports
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --agents os_tc edop

# 5. Watch the browser navigate (non-headless) — great for tuning selectors
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --only annual_reports --headed

# 6. Network health check only (no downloads, no re-index)
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --dry-run

# 7. Fetch but skip the re-index (e.g. to inspect files first)
backend\venv\Scripts\python.exe -m scripts.agents.orchestrator --no-reindex
```

`python scripts/orchestrator.py` still works (it forwards to the module above).

> **NTPC LAN / VPN required for 3 of 4 sources.** `10.0.8.241` and
> `ccitapps.ntpc.co.in` are intranet-only; `www.ntpc.co.in` (annual reports) is
> public. The orchestrator runs a health check first and labels each source
> *reachable / Timeout / off-intranet*.

> **Downloads go through the browser, not httpx.** The NTPC network edge returns
> `403 URLBlocked` to direct (httpx) file requests. Agents therefore download via
> Chromium's own network context (`context.request`), which shares the browser's
> proxy + session. `download_http_links()` remains as a fallback for sources that
> don't need the proxy.

---

## Architecture

```
scripts/
├── __init__.py                  ← makes `python -m scripts.agents.orchestrator` work
├── agents/
│   ├── base_agent.py            ← retry/backoff, hash-dedup (+ folder seeding),
│   │                              save_file, network check, per-run file logging,
│   │                              browser-context + httpx downloaders, text→PDF
│   ├── orchestrator.py          ← runner: health banner, --only/--headed/--dry-run,
│   │                              JSON run-log, summary, auto re-index
│   ├── fetch_os_tc_docs.py      ← Source 1: ASP.NET grid (Playwright, paginated)
│   ├── fetch_edop.py            ← Source 2: JS app → JSON API → per-DoP clause PDFs
│   ├── fetch_empexp.py          ← Source 3: EmpExp doc links (subclass of EDOP)
│   └── fetch_annual_reports.py  ← Source 4: public NTPC site (Playwright)
├── orchestrator.py              ← deprecated shim → forwards to scripts.agents.orchestrator
├── indexer.py                   ← rebuilds backend/chroma from reports/*.pdf + pages.json + downloads/*.{xlsx,docx,csv}
└── scheduler_setup.py           ← prints cron line / Windows Task Scheduler XML

config/
├── .env.agents.template         ← copy → .env.agents and edit
└── .env.agents                  ← your actual config (gitignored)

data/raw/
├── agent_manifest.json          ← content-hash dedup map (auto-created/seeded)
└── downloads/{os_tc,edop,empexp} ← non-PDF files + EDOP raw JSON

frontend/public/reports/         ← ALL downloaded PDFs land here (what indexer reads)
backend/chroma/                  ← the live ChromaDB index (chromadb==1.5.9)
logs/agents/                     ← <agent>_<timestamp>.log + run_<timestamp>.json
```

**File naming** — `{agent}_{YYYYMMDD}_{original}.{ext}`, e.g.
`annual_reports_20260603_Annual Report 2024-25_1.pdf`. URL-encoded names are
decoded (`%20` → space) and Windows-illegal characters are stripped.

**Dedup** — a SHA-256 of each file's content lives in `agent_manifest.json`. On
startup the manifest is **seeded from the existing reports folder**, so files a
human already placed there (or a prior run fetched) are skipped — re-runs are
idempotent. Delete the manifest to force a full re-download.

**Safety cap** — `AGENT_MAX_FILES` (env, default `0` = unlimited) limits how many
files each agent downloads per run. Useful for large repositories (OS/TC exposes
430+ PDFs).

---

## Site Navigation — How Each Agent Works

### Source 1 — OS/TC Documents (`OS_TC_URL`) — ✅ working
`http://10.0.8.241/OS-TCDocs/OS_TC_Main.aspx` — ASP.NET grid with ~430 direct
PDF links. Playwright loads the page, collects links matching
`OS_TC_DOC_LINK_SELECTOR`, follows `__doPostBack` links via
`expect_download()`, paginates via `OS_TC_NEXT_PAGE_SELECTOR` (up to
`OS_TC_MAX_PAGES`), and downloads through the browser context.

### Source 2 — EDOP (`EDOP_URL`) — ✅ working (JSON API, not files)
`https://ccitapps.ntpc.co.in/edop` is a JavaScript app (DoPDigitizationNew) with
**no downloadable files**. Its Delegation-of-Powers data comes from a public
(login-free) JSON API discovered from the page's inline JS:
`home/GetAllDops`, `home/GetClausesByDop?dop=`, `home/GetClauseDetails?dop=&clauseNo=`
(non-admin DoPs), `home/GetClauseDetailsForAdminFuntion?...` (admin DoPs),
`home/GetAcronyms?dop=`.

Controlled by **`EDOP_FETCH_MODE`**:
- `full` (default) — walks every DoP → every clause → its detailed power rows
  (the ~1917 powers: nature of power / subject matter / officer authorized /
  extent of power), emitting **one PDF per DoP category**
  (`edop_<date>_delegation_of_powers_<DOP>.pdf`).
- `summary` — just category names + clause counts (lightweight).

Raw JSON is archived under `data/raw/downloads/edop/`.

### Source 3 — Employee Experience (`EMPEXP_URL`) — ✅ working
`http://ccitapps.ntpc.co.in/empexp` — serves PDFs under `/empexp/uploads/`.
Implemented as a subclass of the EDOP agent (shared doc-scan logic; the JSON-API
step is a no-op here).

### Source 4 — Annual Reports (`ANNUAL_REPORTS_URL`) — ✅ working
`https://www.ntpc.co.in/investors/financial-performance/annual-reports` — public,
JS-rendered. Playwright collects PDF links; downloaded via the browser context.

**If an agent reports `FAILED-NEEDS-TUNING`** (reachable but 0 files found), the
page structure/selector changed — open it in a browser, inspect a download link,
and update the relevant `*_DOC_LINK_SELECTOR` (or `*_SUB_PATHS`) in `.env.agents`.

---

## Re-indexing

Re-index runs **automatically** after a fetch that downloaded new files (unless
`--no-reindex`). It calls `scripts/indexer.py`, which rebuilds the
`ntpc_content` collection in `backend/chroma` from:
- every PDF in `frontend/public/reports/`,
- `data/raw/pages.json` (scraped web pages), and
- **Excel / Word / CSV** files (`.xlsx`, `.docx`, `.csv`) under
  `data/raw/downloads/` — the non-PDF files the agents fetch.
  (Legacy `.xls`/`.doc`/`.ppt` are skipped with a warning — convert to the
  modern format to index them.)

```powershell
# Manual re-index
backend\venv\Scripts\python.exe scripts\indexer.py
```

> The running backend caches the collection at import time — **restart the
> backend** after a re-index for the chatbot to serve the new content.

---

## Running on a Schedule

```powershell
# Windows Task Scheduler
backend\venv\Scripts\python.exe scripts\scheduler_setup.py --windows --time 02:00 > ntpc_agents.xml
schtasks /Create /XML ntpc_agents.xml /TN NTPC_FetchAgents
# Delete later:  schtasks /Delete /TN NTPC_FetchAgents /F
```

`scheduler_setup.py` also prints a Linux/macOS cron line (`--cron "0 2 * * *"`).
Both invoke `python -m scripts.agents.orchestrator` (which re-indexes itself).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Off NTPC intranet - host unreachable` / `Timeout` | Off NTPC LAN/VPN | Connect to the NTPC network |
| `403 URLBlocked` on downloads | Using httpx instead of the browser context | Already fixed — agents download via `context.request` |
| `FAILED-NEEDS-TUNING` (0 files found) | Selector/structure changed | Inspect the page; update `*_DOC_LINK_SELECTOR` |
| Too many files from OS/TC | Large repository | Set `AGENT_MAX_FILES=50` (env or `.env.agents`) |
| PDF re-downloaded though present | manifest deleted | Normal; it re-seeds from the folder and dedups |
| Chatbot doesn't show new docs | Backend cached old collection | Restart the backend after re-index |
```
