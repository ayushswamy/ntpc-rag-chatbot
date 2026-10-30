# backend/knowledge_graph/models.py
"""
Knowledge-graph vocabulary + id canonicalization (Phase 3).

Pure constants and helpers (no NetworkX), so it's unit-testable and shared by the
builder, store, and query modules. The controlled vocabularies keep the graph
consistent across the deterministic tiers and the optional LLM tier.
"""

import re

GRAPH_VERSION = "1.0"

# ── Entity (node) types ──
DOCUMENT   = "document"
CIRCULAR   = "circular"
PERSON     = "person"
ROLE       = "role"
DEPARTMENT = "department"
POLICY     = "policy"
TOPIC      = "topic"
POWER      = "power"
AMOUNT     = "amount"
SCOPE      = "scope"
YEAR       = "year"

# ── Relation (edge) types ──
BELONGS_TO_SCOPE = "belongs_to_scope"
HAS_YEAR         = "has_year"
ISSUED_BY        = "issued_by"
DOCUMENTED_IN    = "documented_in"
SUPERSEDES       = "supersedes"
REFERENCES       = "references"
HAS_ROLE         = "has_role"
REPORTS_TO       = "reports_to"
APPROVES         = "approves"
APPROVAL_LIMIT   = "approval_limit"
OWNS_POLICY      = "owns_policy"
ABOUT_TOPIC      = "about_topic"
SUBTOPIC_OF      = "subtopic_of"

RELATION_TYPES = {
    BELONGS_TO_SCOPE, HAS_YEAR, ISSUED_BY, DOCUMENTED_IN, SUPERSEDES, REFERENCES,
    HAS_ROLE, REPORTS_TO, APPROVES, APPROVAL_LIMIT, OWNS_POLICY, ABOUT_TOPIC, SUBTOPIC_OF,
}


def slug(text: str) -> str:
    """Lowercase, collapse non-alphanumerics to hyphens. 'Executive Director' -> 'executive-director'."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def node_id(ntype: str, label: str) -> str:
    """Namespaced node id, e.g. ('role','Executive Director') -> 'role:executive-director'."""
    return f"{ntype}:{slug(label)}"


def canonical_circular_id(text: str):
    """
    Normalize a circular reference to a canonical node id:
      'CHRC No. 992/2026', 'CHRC 992 / 2026', 'CHRC992', 'CIRCULAR NO. 992 / 2026'
        -> 'circular:chrc-992-2026'
    Returns None if no circular number is found. This is the linchpin for collapsing
    all the textual variants of a circular number onto ONE graph node.
    """
    if not text:
        return None
    t = text.upper()
    m = re.search(r"CHRC\s*(?:NO\.?)?\s*(\d{1,4})\s*/\s*(\d{2,4})", t)
    if not m:
        m = re.search(r"CIRCULAR\s*(?:NO\.?)?\s*(\d{1,4})\s*/\s*(\d{2,4})", t)
    if m:
        return node_id(CIRCULAR, f"chrc-{m.group(1)}-{m.group(2)}")
    m = re.search(r"CHRC\s*(?:NO\.?)?\s*(\d{1,4})\b", t)   # number without year (e.g. filename CHRC992)
    if m:
        return node_id(CIRCULAR, f"chrc-{m.group(1)}")
    return None


def circular_label(node: str) -> str:
    """'circular:chrc-992-2026' -> 'CHRC 992/2026' for display."""
    s = node.split(":", 1)[-1].upper().replace("CHRC-", "CHRC ").replace("-", "/")
    return s
