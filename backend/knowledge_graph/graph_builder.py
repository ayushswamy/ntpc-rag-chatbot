# backend/knowledge_graph/graph_builder.py
"""
Build the knowledge graph FROM the ChromaDB collection (chunks + Phase-1 metadata),
never re-parsing PDFs. Tiered extraction:

  Tier 0 (structural, free):  Document/Scope/Year/Department/Circular nodes and
                              belongs_to_scope / has_year / issued_by / documented_in.
  Tier 1 (regex, cheap):      supersedes & references (circular<->circular),
                              about_topic (from titles), amount nodes.
  Tier 2 (LLM, optional):     per-document triplet extraction, bounded by
                              max_llm_docs; OFF by default (use_llm=False).

All tiers are robust: any per-document failure is skipped, never aborts the build.
"""

import json
import re
from collections import defaultdict

from . import models
from .graph_store import GraphStore

# ── Tier 1 regexes ──
_SUPERSEDES = re.compile(
    r"(?:revised\s+vide|in\s+supersession\s+of|supersed\w*|replac\w*|amend\w*)"
    r"[^.\n]*?(?:CHRC|CIRCULAR)\s*(?:NO\.?)?\s*\d{1,4}\s*/\s*\d{2,4}", re.I)
_CIRC_REF = re.compile(r"(?:CHRC|CIRCULAR)\s*(?:NO\.?)?\s*\d{1,4}\s*/\s*\d{2,4}", re.I)
_AMOUNT = re.compile(r"Rs\.?\s*[\d,]+(?:\.\d+)?\s*(?:crore|lakh|cr\b|lac)?", re.I)

_TITLE_STOP = {
    "the", "of", "for", "and", "or", "to", "in", "a", "an", "ntpc", "reg", "new",
    "final", "guidelines", "circular", "report", "annual", "ltd", "limited", "pdf",
    "repository", "chrc", "cciom", "inclusive", "under", "with", "from", "regarding",
}

# Circulars carry their real subject after "Sub:"/"Subject:" — far better topics
# than the filename. Used in preference to the title when present.
_SUBJECT = re.compile(r"\b(?:Sub|Subject)\s*[:\-]\s*(.+)", re.I)


def _topic_source(title, head):
    m = _SUBJECT.search(head or "")
    if m:
        return m.group(1).split("\n")[0][:160]
    return title


def _doc_topics(title: str):
    """Coarse topic keywords from a document title (Tier 1)."""
    words = re.findall(r"[A-Za-z]{4,}", title or "")
    seen, out = set(), []
    for w in words:
        wl = w.lower()
        if wl not in _TITLE_STOP and wl not in seen:
            seen.add(wl)
            out.append(w)
    return out[:6]


def _circ_node(store, ref_text, document_id=None):
    cid = models.canonical_circular_id(ref_text)
    if not cid:
        return None
    # Alias the bare "CHRC <num>" form so a year-less query ("CHRC 992") still
    # resolves to the year-qualified node ("circular:chrc-992-2026").
    aliases = []
    m = re.search(r"chrc-(\d+)", cid)
    if m:
        aliases = [f"CHRC {m.group(1)}", f"CHRC{m.group(1)}"]
    store.add_node(cid, models.CIRCULAR, models.circular_label(cid),
                   document_id=document_id, aliases=aliases)
    return cid


def build_from_chroma(collection, use_llm=False, llm_client=None, model=None, max_llm_docs=0):
    """Returns (GraphStore, document_count)."""
    store = GraphStore()
    data = collection.get(include=["documents", "metadatas"])
    ids, docs, metas = data["ids"], data["documents"], data["metadatas"]

    by_doc = defaultdict(list)
    for cid, text, meta in zip(ids, docs, metas):
        meta = meta or {}
        did = meta.get("document_id") or meta.get("source") or ""
        by_doc[did].append((cid, text or "", meta))

    doc_count = 0
    for did, chunks in by_doc.items():
        if not did:
            continue
        try:
            doc_count += 1
            meta0 = chunks[0][2]
            dtype = meta0.get("document_type", "unknown")
            year = meta0.get("year", "")
            dept = meta0.get("department", "")
            title = meta0.get("title", did)

            doc_node = models.node_id(models.DOCUMENT, did)
            store.add_node(doc_node, models.DOCUMENT, title, document_id=did,
                           document_type=dtype, source_system=meta0.get("source_system", ""),
                           chunk_ids=[c[0] for c in chunks[:40]])

            # ── Tier 0: structural edges ──
            if dtype:
                sc = models.node_id(models.SCOPE, dtype)
                store.add_node(sc, models.SCOPE, dtype)
                store.add_edge(doc_node, sc, models.BELONGS_TO_SCOPE, method="structural")
            if year:
                yr = models.node_id(models.YEAR, year)
                store.add_node(yr, models.YEAR, year)
                store.add_edge(doc_node, yr, models.HAS_YEAR, method="structural")
            if dept:
                dp = models.node_id(models.DEPARTMENT, dept)
                store.add_node(dp, models.DEPARTMENT, dept.replace("_", " "))
                store.add_edge(doc_node, dp, models.ISSUED_BY, method="structural")

            # Circular node for this document. Prefer the YEAR-QUALIFIED form found
            # in the content (e.g. "992/2026") over the year-less filename ("CHRC992")
            # so both collapse onto one node.
            head = " ".join(c[1] for c in chunks[:2])[:2500]
            cid_node = _circ_node(store, head, did) or _circ_node(store, did, did) \
                or _circ_node(store, title, did)
            if cid_node:
                store.add_edge(cid_node, doc_node, models.DOCUMENTED_IN, method="structural")

            # ── Tier 1: topics (prefer the circular "Sub:" subject over the filename) ──
            for t in _doc_topics(_topic_source(title, head)):
                tn = models.node_id(models.TOPIC, t)
                store.add_node(tn, models.TOPIC, t)
                store.add_edge(doc_node, tn, models.ABOUT_TOPIC, method="title")

            # ── Tier 1: supersedes + references (bounded text scan) ──
            scan = " ".join(c[1] for c in chunks[:6])
            for m in _SUPERSEDES.finditer(scan):
                ref = _circ_node(store, m.group(0))
                if ref and cid_node and ref != cid_node:
                    store.add_edge(cid_node, ref, models.SUPERSEDES,
                                   method="regex", evidence=m.group(0)[:160])
            for m in _CIRC_REF.finditer(scan):
                ref = _circ_node(store, m.group(0))
                if ref and ref != cid_node:
                    store.add_edge(doc_node, ref, models.REFERENCES, method="regex")

            # ── Tier 2: optional LLM extraction (bounded) ──
            if use_llm and doc_count <= max_llm_docs and llm_client is not None:
                _llm_extract(store, doc_node, title, head, llm_client, model)
        except Exception as e:
            print(f"[graph] skip {did[:50]}: {e}")

    return store, doc_count


# ──────────────────────── Tier 2 (optional LLM) ────────────────────────
_LLM_RELATIONS = {
    "has_role": (models.PERSON, models.ROLE, models.HAS_ROLE),
    "reports_to": (models.ROLE, models.ROLE, models.REPORTS_TO),
    "owns_policy": (models.DEPARTMENT, models.POLICY, models.OWNS_POLICY),
    "approves": (models.ROLE, models.TOPIC, models.APPROVES),
}

_LLM_PROMPT = (
    "Extract relationships from this NTPC document as JSON only. "
    "Allowed relations: has_role(person->role), reports_to(role->role), "
    "owns_policy(department->policy), approves(role->topic). "
    'Return {"triples":[{"s":"...","r":"...","o":"..."}]} with at most 8 triples. '
    "Use ONLY text present below.\n\nTITLE: {title}\n\nTEXT:\n{text}"
)


def _llm_extract(store, doc_node, title, text, llm_client, model):
    """Best-effort per-document triplet extraction. Never raises."""
    try:
        resp = llm_client.chat(
            model=model,
            messages=[{"role": "user",
                       "content": _LLM_PROMPT.format(title=title, text=text[:2000])}],
            options={"temperature": 0.0, "num_predict": 300},
        )
        raw = resp["message"]["content"]
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return
        triples = json.loads(m.group(0)).get("triples", [])
        for tr in triples[:8]:
            r = (tr.get("r") or "").strip().lower()
            s, o = (tr.get("s") or "").strip(), (tr.get("o") or "").strip()
            if r not in _LLM_RELATIONS or not s or not o:
                continue
            st, ot, rel = _LLM_RELATIONS[r]
            sn = models.node_id(st, s)
            on = models.node_id(ot, o)
            store.add_node(sn, st, s)
            store.add_node(on, ot, o)
            store.add_edge(sn, on, rel, method="llm", source_doc=doc_node)
    except Exception as e:
        print(f"[graph] llm skip: {e}")
