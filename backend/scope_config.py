# backend/scope_config.py
"""
Single source of truth for knowledge-source SCOPES and document classification.

Imported by:
  - scripts/indexer.py           tag NEW chunks with classification metadata
  - scripts/migrate_metadata.py  backfill metadata on EXISTING chunks (in place)
  - backend/rag.py               scope -> Chroma `where` filter, scope-aware keyword pass
  - backend/main.py              GET /sources, request validation

Design goals
  * Extensible    - add a scope (or reveal ESG) by editing ONLY this file.
  * Robust        - documents matching no scope are tagged "unknown" and stay
                    reachable via ALL_SOURCES; nothing is ever dropped.
  * Pure/testable - classify_document() and the scope helpers are side-effect free.
"""

from dataclasses import dataclass
import re

# ── Legacy annual-report PDFs (predate the agent "<system>_<date>_" naming) ──
# Canonical copy lives here; rag.py imports it. Maps report period -> filename.
YEAR_TO_FILE = {
    "2017-18": "2017-18.pdf",
    "2018-19": "annual-report-2018-19.pdf",
    "2019-20": "44-final-NTPC-AR-30082020.pdf",
    "2020-21": "NTPC_Annual Report_20-21.pdf",
    "2021-22": "Annual-Report-2021-22.pdf",
    "2022-23": "47th Annual Report of NTPC 2022-2023 New.pdf",
    "2023-24": "Annual Report 2023-24.pdf",
    "2024-25": "Annual Report 2024-25_1.pdf",
}
LATEST_YEAR = "2024-25"
_FILE_TO_YEAR = {v: k for k, v in YEAR_TO_FILE.items()}

ALL_SOURCES = "ALL_SOURCES"
DEFAULT_SCOPE = ALL_SOURCES
UNKNOWN_TYPE = "unknown"


@dataclass(frozen=True)
class Scope:
    key: str            # API token, e.g. "CIRCULARS"
    label: str          # human label (for future GET /sources enrichment)
    document_type: str  # metadata value used for the Chroma filter ("" = no filter)
    source_system: str  # canonical producing system, stored on each chunk
    prefixes: tuple     # filename prefixes that classify into this scope
    exposed: bool = True  # show in GET /sources?


# Order here = display order; ALL_SOURCES is appended last by exposed_sources().
SCOPES: "list[Scope]" = [
    # OS/TC documents, displayed to users as "LMIs/OGN" (document_type stays os_tc).
    Scope("LMIs/OGN", "LMIs/OGN", "os_tc", "os_tc", ("os_tc_",)),
    Scope("DOP", "Delegation of Powers", "dop", "edop", ("edop_", "dop_")),
    Scope("CIRCULARS", "Circulars", "circular", "circular_repository",
          ("circular_repository_", "circular_")),
    Scope("EMPLOYEE_EXPERIENCE", "Employee Experience", "employee_experience", "empexp",
          ("empexp_",)),
    Scope("NTPC_PEDIA", "NTPC Pedia", "ntpc_pedia", "ntpc_wiki",
          ("ntpcwiki_", "ntpc_wiki_", "ntpcpedia_")),
    Scope("CSR", "CSR", "csr", "csr_list", ("csr_list_", "csr_")),
    Scope("ANNUAL_REPORT", "Annual Reports", "annual_report", "annual_reports",
          ("annual_reports_", "annual_report_")),
    # ESG is sourced from the safety portal — the "safety" data IS ESG data, so the
    # safety_portal_* files classify as document_type=esg (SAFETY scope was renamed to ESG).
    Scope("ESG", "ESG", "esg", "safety_portal", ("safety_portal_", "safety_")),
    # ALL_SOURCES = no filter; handled specially everywhere.
    Scope(ALL_SOURCES, "All Sources", "", "", (), exposed=True),
]

# Lookup is case-INSENSITIVE on the key (so "LMIs/OGN", "lmis/ogn" all match) while
# the canonical mixed-case display key is preserved for /sources and the echoed scope.
_BY_KEY = {s.key.upper(): s for s in SCOPES}


# ───────────────────────── scope helpers (pure) ─────────────────────────
def _resolve(scope):
    """Scope token (any case) -> Scope object, or None."""
    if not scope:
        return _BY_KEY.get(ALL_SOURCES.upper())
    return _BY_KEY.get(str(scope).strip().upper())


def normalize_scope(scope) -> str:
    """Any-case token -> the canonical display key; invalid/missing -> DEFAULT_SCOPE."""
    s = _resolve(scope)
    return s.key if s else DEFAULT_SCOPE


def is_valid_scope(scope) -> bool:
    return _resolve(scope) is not None


def scope_to_where(scope):
    """
    Chroma `where` clause for a scope, or None for ALL_SOURCES / unknown.
    This is the heart of scope filtering: it narrows retrieval to one
    document_type so e.g. a CIRCULARS query never searches annual reports.
    """
    s = _resolve(scope)
    if s is None or not s.document_type:      # ALL_SOURCES has empty document_type
        return None
    return {"document_type": s.document_type}


def document_type_for_scope(scope) -> str:
    s = _resolve(scope)
    return s.document_type if s else ""


def exposed_sources() -> "list[str]":
    """Scope keys for GET /sources (ESG hidden). ALL_SOURCES is always last."""
    keys = [s.key for s in SCOPES if s.exposed and s.key != ALL_SOURCES]
    keys.append(ALL_SOURCES)
    return keys


# ──────────────────── document classification (pure) ────────────────────
def _year_from(source: str, title: str = "") -> str:
    """Best-effort year. Returns '' (never None) when unknown."""
    s = source or ""
    if s in _FILE_TO_YEAR:                     # legacy annual report -> its period
        return _FILE_TO_YEAR[s]
    blob = f"{s} {title}"
    m = re.search(r"\b\d{1,4}\s*/\s*(20\d{2})\b", blob)   # "CHRC 992/2026" -> 2026
    if m:
        return m.group(1)
    m = re.search(r"(20\d{2})", blob)          # any explicit 4-digit year
    if m:
        return m.group(1)
    return ""


# Coarse department hints (Phase 1; richer values arrive with the Phase-3 graph).
_DEPARTMENT_HINTS = {
    "corporate_hr": ("corporate-hr", "corporate hr", "hr-policy", "human resource"),
    "contracts":    ("contracts", "procurement", "purchase order", "bid"),
    "finance":      ("finance", "closing of accounts", "closing guidelines", "audit"),
    "safety":       ("safety",),
    "csr":          ("csr", "corporate social responsibility"),
    "vigilance":    ("vigilance", "fraud prevention"),
}


def _department_from(source: str, title: str) -> str:
    blob = f"{source} {title}".lower()
    for dept, needles in _DEPARTMENT_HINTS.items():
        if any(n in blob for n in needles):
            return dept
    return ""


def classify_document(source: str, title: str = "") -> dict:
    """
    Derive Phase-1 classification metadata from a chunk's `source` (filename or URL).

    Pure & deterministic -> unit-testable and idempotent (safe to re-run in the
    in-place migration). All values are non-null scalars because ChromaDB rejects
    None / lists in metadata. Documents that match no known prefix get
    document_type="unknown" but remain reachable via ALL_SOURCES (never dropped).

    Returns: {document_type, source_system, department, year, document_id}.
    """
    src = (source or "").strip()
    low = src.lower()

    # 1) Known agent filename prefix -> its scope.
    for s in SCOPES:
        for p in s.prefixes:
            if p and low.startswith(p):
                return {
                    "document_type": s.document_type,
                    "source_system": s.source_system,
                    "department":    _department_from(src, title),
                    "year":          _year_from(src, title),
                    "document_id":   src,
                }

    # 2) Website page (source is a URL) -> NTPC Pedia / website.
    if low.startswith("http"):
        return {
            "document_type": "ntpc_pedia",
            "source_system": "website",
            "department":    _department_from(src, title),
            "year":          _year_from(src, title),
            "document_id":   src,
        }

    # 3) Legacy annual-report PDF (no prefix; matched by exact filename).
    if src in _FILE_TO_YEAR:
        return {
            "document_type": "annual_report",
            "source_system": "annual_reports",
            "department":    "",
            "year":          _FILE_TO_YEAR[src],
            "document_id":   src,
        }

    # 4) Fallback: unknown type, still reachable via ALL_SOURCES.
    return {
        "document_type": UNKNOWN_TYPE,
        "source_system": "legacy",
        "department":    _department_from(src, title),
        "year":          _year_from(src, title),
        "document_id":   src,
    }
