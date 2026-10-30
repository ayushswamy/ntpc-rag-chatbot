"""
Orchestrator - runs all (or selected) fetch agents, then re-indexes new files
into the chatbot's ChromaDB so the running bot can answer from them.

Run from the PROJECT ROOT:

    python -m scripts.agents.orchestrator                 # all agents, then re-index
    python -m scripts.agents.orchestrator --only annual_reports
    python -m scripts.agents.orchestrator --agents os_tc edop
    python -m scripts.agents.orchestrator --headed        # watch the browser (non-headless)
    python -m scripts.agents.orchestrator --dry-run       # network health checks only
    python -m scripts.agents.orchestrator --no-reindex    # fetch but skip the indexer

All URLs, folders, selectors, timeouts and retry counts come from
config/.env.agents (copy config/.env.agents.template). Nothing is hard-coded.
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .base_agent import DownloadManifest
from .fetch_annual_reports import AnnualReportsAgent
from .fetch_circular_repository import CircularRepositoryAgent
from .fetch_csr_list import CSRListAgent
from .fetch_edop import EDOPAgent
from .fetch_empexp import EmpExpAgent
from .fetch_ntpc_wiki import NTPCWikiAgent
from .fetch_os_tc_docs import OSTCDocsAgent
from .fetch_safety_portal import SafetyPortalAgent

# UTF-8 console so any stray glyph never crashes on the Windows code page,
# whether printing to a terminal or being redirected to a log file.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")

# scripts/agents/orchestrator.py -> scripts/agents -> scripts -> <project root>
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _abs(rel: str) -> str:
    """Resolve a (possibly relative) path against the project root."""
    p = Path(rel)
    return str(p if p.is_absolute() else _PROJECT_ROOT / p)


def load_config() -> dict:
    env_file = _PROJECT_ROOT / "config" / ".env.agents"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded config: {env_file}")
    else:
        logger.warning(
            f".env.agents not found at {env_file} - using built-in defaults. "
            "Copy config/.env.agents.template -> config/.env.agents to customize."
        )

    return {
        # ── Folder paths ─────────────────────────────────────────────
        "PDF_DIR": _abs(os.getenv("PDF_DIR", "frontend/public/reports")),
        "DOWNLOADS_DIR": _abs(os.getenv("DOWNLOADS_DIR", "data/raw/downloads")),
        "MANIFEST_PATH": _abs(os.getenv("MANIFEST_PATH", "data/raw/agent_manifest.json")),
        "LOG_DIR": _abs(os.getenv("LOG_DIR", "logs/agents")),
        # ── Retry / timeout / mode ───────────────────────────────────
        "AGENT_TIMEOUT_SECONDS": int(os.getenv("AGENT_TIMEOUT_SECONDS", "180")),
        "AGENT_MAX_RETRIES": int(os.getenv("AGENT_MAX_RETRIES", "3")),
        "AGENT_RETRY_BACKOFF_SECONDS": int(os.getenv("AGENT_RETRY_BACKOFF_SECONDS", "5")),
        "AGENT_MAX_FILES": int(os.getenv("AGENT_MAX_FILES", "0")),
        "HTTP_TIMEOUT_SECONDS": int(os.getenv("HTTP_TIMEOUT_SECONDS", "60")),
        "PLAYWRIGHT_HEADLESS": os.getenv("PLAYWRIGHT_HEADLESS", "true"),
        # ── Source URLs ───────────────────────────────────────────────
        "OS_TC_URL": os.getenv("OS_TC_URL", "http://10.0.8.241/OS-TCDocs/OS_TC_Main.aspx"),
        "EDOP_URL": os.getenv("EDOP_URL", "https://ccitapps.ntpc.co.in/edop"),
        "EMPEXP_URL": os.getenv("EMPEXP_URL", "http://ccitapps.ntpc.co.in/empexp"),
        "ANNUAL_REPORTS_URL": os.getenv(
            "ANNUAL_REPORTS_URL",
            "https://www.ntpc.co.in/investors/financial-performance/annual-reports",
        ),
        # ── CSS selectors ─────────────────────────────────────────────
        "OS_TC_DOC_LINK_SELECTOR": os.getenv(
            "OS_TC_DOC_LINK_SELECTOR",
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']",
        ),
        "OS_TC_NEXT_PAGE_SELECTOR": os.getenv("OS_TC_NEXT_PAGE_SELECTOR", ""),
        "OS_TC_MAX_PAGES": int(os.getenv("OS_TC_MAX_PAGES", "20")),
        "EDOP_DOC_LINK_SELECTOR": os.getenv(
            "EDOP_DOC_LINK_SELECTOR",
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']",
        ),
        "EDOP_SUB_PATHS": os.getenv("EDOP_SUB_PATHS", ""),
        # EDOP is a JS app with no files; it's ingested via its public JSON API.
        # full = all clauses + detailed power rows (per-DoP PDFs); summary = counts only.
        "EDOP_FETCH_MODE": os.getenv("EDOP_FETCH_MODE", "full"),
        "EMPEXP_DOC_LINK_SELECTOR": os.getenv(
            "EMPEXP_DOC_LINK_SELECTOR",
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']",
        ),
        "EMPEXP_SUB_PATHS": os.getenv("EMPEXP_SUB_PATHS", ""),
        # EmpExp is a paginated DataTable (not a file repo); walk up to N pages.
        "EMPEXP_MAX_PAGES": int(os.getenv("EMPEXP_MAX_PAGES", "30")),
        "ANNUAL_REPORTS_PDF_SELECTOR": os.getenv(
            "ANNUAL_REPORTS_PDF_SELECTOR", "a[href$='.pdf'], a[href*='.pdf']"
        ),
        # ── New Source 5: Circular Repository (files) ─────────────────
        "CIRCULAR_REPOSITORY_URL": os.getenv(
            "CIRCULAR_REPOSITORY_URL", "https://ccitapps.ntpc.co.in/circularrepository"
        ),
        "CIRCULAR_DOC_LINK_SELECTOR": os.getenv(
            "CIRCULAR_DOC_LINK_SELECTOR",
            "a[href$='.pdf'], a[href*='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']",
        ),
        # ── New Source 6: NTPC Wiki (page crawl) ──────────────────────
        "NTPC_WIKI_URL": os.getenv("NTPC_WIKI_URL", "https://ccitapps.ntpc.co.in/ntpcwiki"),
        "WIKI_MAX_DEPTH": int(os.getenv("WIKI_MAX_DEPTH", "2")),
        "WIKI_MAX_PAGES": int(os.getenv("WIKI_MAX_PAGES", "50")),
        # ── New Source 7: Safety Portal (mixed, shallow crawl) ────────
        "SAFETY_URL": os.getenv("SAFETY_URL", "http://10.0.8.68/safety"),
        "SAFETY_MAX_DEPTH": int(os.getenv("SAFETY_MAX_DEPTH", "1")),
        "SAFETY_MAX_PAGES": int(os.getenv("SAFETY_MAX_PAGES", "25")),
        # ── New Source 8: CSR List (paginated table -> JSON) ──────────
        "CSR_LIST_URL": os.getenv(
            "CSR_LIST_URL", "https://itstaging.ntpc.co.in/om/CSRlist/CSRLIST"
        ),
        "CSR_MAX_PAGES": int(os.getenv("CSR_MAX_PAGES", "30")),
    }


AGENT_CLASSES = {
    # ── original 4 ──
    "os_tc": OSTCDocsAgent,
    "edop": EDOPAgent,
    "empexp": EmpExpAgent,
    "annual_reports": AnnualReportsAgent,
    # ── new 4 ──
    "circular_repository": CircularRepositoryAgent,
    "ntpcwiki": NTPCWikiAgent,
    "safety_portal": SafetyPortalAgent,
    "csr_list": CSRListAgent,
}

# Friendly aliases so `--only fetch_ntpc_wiki` / `ntpc_wiki` resolve correctly.
_ALIASES = {
    "fetch_ntpc_wiki": "ntpcwiki", "ntpc_wiki": "ntpcwiki", "wiki": "ntpcwiki",
    "circular": "circular_repository", "safety": "safety_portal", "csr": "csr_list",
}


def _resolve(name: str) -> str:
    n = name.strip().lower()
    if n in AGENT_CLASSES:
        return n
    if n in _ALIASES:
        return _ALIASES[n]
    if n.startswith("fetch_") and n[len("fetch_"):] in AGENT_CLASSES:
        return n[len("fetch_"):]
    return n

# Maps the network status from BaseAgent.check_network() to a human phrase.
_HEALTH_PHRASE = {
    "reachable": "reachable",
    "refused": "reachable (port closed - site may be down)",
    "timeout": "Timeout (likely off NTPC LAN/VPN)",
    "dns_failure": "Off NTPC intranet - host unreachable (DNS failed)",
    "unreachable": "Off NTPC intranet - host unreachable",
}

# Maps the post-run agent status to an honest per-source verdict.
_VERDICT = {
    "ok": "SUCCESS",
    "structure_changed": "FAILED-NEEDS-TUNING (reachable but page structure changed / no files found)",
    "timeout": "FAILED-NETWORK (timeout - off NTPC LAN/VPN?)",
    "dns_failure": "FAILED-NETWORK (off NTPC intranet)",
    "unreachable": "FAILED-NETWORK (off NTPC intranet)",
    "refused": "FAILED-NETWORK (port closed / site down)",
    "error": "FAILED (see error)",
}


def health_check_banner(agents: dict):
    print(f"\n{'='*60}")
    print("  NETWORK HEALTH CHECK")
    print(f"{'='*60}")
    for name, agent in agents.items():
        reachable, status, msg = agent.check_network()
        mark = "OK " if reachable else "XX "
        phrase = _HEALTH_PHRASE.get(status, status)
        print(f"  [{mark}] {name:<16} {phrase}")
        logger.info(f"health[{name}] {status}: {msg}")
    print(f"{'='*60}\n")


def run_reindex() -> bool:
    """Invoke scripts/indexer.py in-process-isolated (subprocess) to rebuild the index."""
    indexer = _PROJECT_ROOT / "scripts" / "indexer.py"
    if not indexer.exists():
        logger.error(f"Indexer not found at {indexer}; skipping re-index.")
        return False
    logger.info(f"Re-indexing via {indexer} ...")
    try:
        completed = subprocess.run(
            [sys.executable, str(indexer)],
            cwd=str(_PROJECT_ROOT),
        )
        if completed.returncode == 0:
            logger.info("Re-index complete. Restart the backend if it caches the collection at startup.")
            return True
        logger.error(f"Indexer exited with code {completed.returncode}.")
        return False
    except Exception as exc:
        logger.error(f"Failed to run indexer: {exc}")
        return False


def run_build_graph(graph_llm: int = 0) -> bool:
    """
    Rebuild the knowledge graph from the (freshly re-indexed) ChromaDB.

    Tier 0+1 only by default (structural + regex — deterministic, needs no Ollama),
    so it is safe to run automatically on the fetch machine. Pass graph_llm > 0 to
    also run the optional Tier-2 LLM extraction on the first N documents.

    Best-effort: a failure here NEVER fails the fetch run.
    """
    builder = _PROJECT_ROOT / "scripts" / "build_graph.py"
    if not builder.exists():
        logger.warning(f"build_graph.py not found at {builder}; skipping graph rebuild.")
        return False
    cmd = [sys.executable, str(builder)]
    if graph_llm > 0:
        cmd += ["--llm", str(graph_llm)]
    tier = f"(Tier 2 LLM on first {graph_llm} docs)" if graph_llm > 0 else "(Tier 0+1, deterministic)"
    logger.info(f"Rebuilding knowledge graph via {builder} {tier} ...")
    try:
        completed = subprocess.run(cmd, cwd=str(_PROJECT_ROOT))
        if completed.returncode == 0:
            logger.info("Knowledge graph rebuilt. Restart the backend to load the new graph.")
            return True
        logger.error(f"build_graph.py exited with code {completed.returncode}.")
        return False
    except Exception as exc:
        logger.error(f"Failed to run build_graph.py: {exc}")
        return False


async def run(agent_names: list[str], dry_run: bool, headed: bool, reindex: bool,
              build_graph: bool = True, graph_llm: int = 0):
    config = load_config()
    if headed:
        config["PLAYWRIGHT_HEADLESS"] = "false"

    manifest = DownloadManifest(Path(config["MANIFEST_PATH"]))

    # Seed dedup with files already in the reports folder so agents skip
    # identical content a human already placed there (idempotent re-runs).
    seeded = manifest.seed_from_dir(Path(config["PDF_DIR"]))
    if seeded:
        logger.info(f"Seeded dedup manifest with {seeded} pre-existing file(s) from {config['PDF_DIR']}")

    if not agent_names:
        agent_names = list(AGENT_CLASSES.keys())
    else:
        agent_names = [_resolve(n) for n in agent_names]

    unknown = set(agent_names) - set(AGENT_CLASSES)
    if unknown:
        logger.error(f"Unknown agent(s): {unknown}. Available: {list(AGENT_CLASSES)}")
        sys.exit(2)

    agents = {name: AGENT_CLASSES[name](config, manifest) for name in agent_names}

    # Startup health check on every selected source.
    health_check_banner(agents)

    if dry_run:
        logger.info("Dry run - no fetching performed.")
        return

    run_time = datetime.now().isoformat()
    results: dict = {}
    for name, agent in agents.items():
        print(f"\n{'-'*60}")
        print(f"  Agent: {name}")
        print(f"{'-'*60}")
        try:
            results[name] = await agent.run_with_retry()
        except Exception as exc:  # never let one agent abort the others
            logger.error(f"[{name}] crashed: {type(exc).__name__}: {exc}")
            results[name] = {"success": False, "status": "error", "error": str(exc),
                             "downloaded": 0, "skipped": 0, "failed": 0, "files": []}

    # ── Run log ──────────────────────────────────────────────────────
    log_dir = Path(config["LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    log_file.write_text(
        json.dumps({"run_time": run_time, "agents_run": agent_names, "results": results}, indent=2)
    )
    logger.info(f"Run log saved: {log_file}")

    # ── Summary ──────────────────────────────────────────────────────
    total_dl = total_skip = total_fail = 0
    all_files: list[str] = []
    print(f"\n{'='*60}")
    print("  SUMMARY (honest per-source verdict)")
    print(f"{'='*60}")
    for name, r in results.items():
        dl, sk, fa = r.get("downloaded", 0), r.get("skipped", 0), r.get("failed", 0)
        total_dl += dl; total_skip += sk; total_fail += fa
        all_files += r.get("files", [])
        verdict = _VERDICT.get(r.get("status", ""), r.get("status", "unknown"))
        print(f"  {name:<16} {verdict}")
        print(f"       downloaded={dl}  skipped={sk}  failed={fa}  ({r.get('duration_sec', 0)}s)")
        if r.get("error"):
            print(f"       error: {r['error']}")
    print(f"{'-'*60}")
    print(f"  TOTAL  downloaded={total_dl}  skipped={total_skip}  failed={total_fail}")
    print(f"  PDF folder (indexed):  {config['PDF_DIR']}")
    print(f"  Other downloads:       {config['DOWNLOADS_DIR']}")
    if all_files:
        print(f"\n  Files this run:")
        for f in all_files:
            print(f"    - {f}")
    print(f"{'='*60}\n")

    # ── Re-index only if we actually fetched something new, then rebuild the
    #    knowledge graph off the fresh index (the graph reads ChromaDB) ───────
    if reindex and total_dl > 0:
        if run_reindex() and build_graph:
            run_build_graph(graph_llm)
        elif not build_graph:
            logger.info("--no-graph set - skipping knowledge-graph rebuild.")
    elif reindex:
        logger.info("No new files downloaded - skipping re-index and graph rebuild.")
    else:
        logger.info("--no-reindex set - skipping re-index and graph rebuild.")


def main():
    parser = argparse.ArgumentParser(
        description="NTPC fetch-agent orchestrator - downloads intranet/web files and re-indexes."
    )
    parser.add_argument("--only", metavar="NAME",
                        help=f"Run exactly one agent. Choices: {', '.join(AGENT_CLASSES)}")
    parser.add_argument("--agents", nargs="*", metavar="NAME",
                        help=f"Agents to run (default: all 8). Choices: {', '.join(AGENT_CLASSES)}")
    parser.add_argument("--headed", action="store_true",
                        help="Run Playwright with a visible browser window (overrides PLAYWRIGHT_HEADLESS).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Network health checks only - no downloads, no re-index.")
    parser.add_argument("--no-reindex", action="store_true",
                        help="Fetch files but do not run the indexer afterwards.")
    parser.add_argument("--no-graph", action="store_true",
                        help="Skip rebuilding the knowledge graph after re-indexing.")
    parser.add_argument("--graph-llm", type=int, default=0, metavar="N",
                        help="Enable Tier-2 LLM graph extraction on the first N docs (needs Ollama). 0 = skip.")
    args = parser.parse_args()

    names = [args.only] if args.only else (args.agents or [])
    asyncio.run(run(names, dry_run=args.dry_run, headed=args.headed,
                    reindex=not args.no_reindex,
                    build_graph=not args.no_graph, graph_llm=args.graph_llm))


if __name__ == "__main__":
    main()
