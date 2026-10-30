# backend/hybrid_retriever.py
"""
Hybrid candidate retrieval (Phase 2).

Combines, into ONE de-duplicated candidate pool for the reranker:
  1. metadata/scope-filtered VECTOR search (dense embeddings)
  2. exact circular-NUMBER keyword match against filenames (CHRC992.pdf etc.)

Dependency-injected (`collection`, `embed_fn`, `sub_queries`) so it has no import
cycle with rag.py and is unit-testable. Scope filtering and the keyword pass keep
the exact semantics shipped in Phase 1, relocated here as the single retrieval home.
"""

import re
from scope_config import normalize_scope, scope_to_where, document_type_for_scope
from structured_log import slog

_SOURCE_CACHE = None


def _all_sources(collection):
    """Distinct source filenames (cached). Used by the keyword pass."""
    global _SOURCE_CACHE
    if _SOURCE_CACHE is None:
        try:
            metas = collection.get(include=["metadatas"])["metadatas"]
            _SOURCE_CACHE = sorted({m.get("source", "") for m in metas if m})
        except Exception:
            _SOURCE_CACHE = []
    return _SOURCE_CACHE


def keyword_id_chunks(collection, question, scope=None):
    """
    Lexical pass: match circular numbers in the query (CHRC 992, 992/2026, ...)
    against document FILENAMES and return that file's chunks. SCOPE-AWARE — drops
    matches whose document_type != the active scope.
    """
    q = question.upper()
    ids = set(re.findall(r'CHRC\s*(?:NO\.?)?\s*(\d{1,4})', q))
    ids |= set(re.findall(r'\b(\d{2,4})\s*/\s*\d{2,4}\b', q))
    ids |= set(re.findall(r'CIRCULAR\s*(?:NO\.?)?\s*(\d{1,4})', q))
    if not ids:
        return []
    matched = []
    for src in _all_sources(collection):
        u = src.upper().replace(" ", "")
        for n in ids:
            if f"CHRC{n}" in u or (("CHRC" in u or "CIRCULAR" in u) and n in u):
                matched.append(src)
                break
    if not matched:
        return []
    try:
        res = collection.get(where={"source": {"$in": matched}},
                             include=["documents", "metadatas"])
        pairs = list(zip(res["documents"], res["metadatas"]))
    except Exception:
        return []
    # Scope-aware: keep only matches whose document_type equals the active scope.
    target_dt = document_type_for_scope(scope) if scope else ""
    if target_dt:
        pairs = [(d, m) for d, m in pairs if m.get("document_type", "") == target_dt]
    return pairs


def _build_where(scope, year_file):
    """Merge scope (document_type) + year (source) into one Chroma `where`."""
    clauses = []
    sw = scope_to_where(scope)
    if sw:
        clauses.append(sw)
    if year_file:
        clauses.append({"source": year_file})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def hybrid_candidates(collection, embed_fn, sub_queries, question, scope,
                      year_file=None, strict_year=False, pool_size=30,
                      distance_cutoff=2.0):
    """
    Return a de-duplicated candidate pool [(text, meta, distance)] for reranking.

    Scope isolation: when a real scope is active we run ONLY the scoped vector
    pass (no unfiltered pass that would leak other scopes). For ALL_SOURCES we
    keep the year-hybrid (year-filtered + unfiltered) behaviour. Keyword matches
    are prepended at distance -1.0 so exact circular lookups always survive the
    pool (and are later pinned through reranking by rag.py).
    """
    scope = normalize_scope(scope)
    scoped = scope_to_where(scope) is not None
    if scoped:
        where_passes = [_build_where(scope, year_file)]
    elif year_file and not strict_year:
        where_passes = [_build_where(scope, year_file), None]
    else:
        where_passes = [_build_where(scope, year_file)]

    seen = {}
    n = min(pool_size, collection.count())
    for sq in sub_queries:
        try:
            emb = embed_fn(sq)
        except Exception:
            continue
        for where in where_passes:
            try:
                kwargs = {"query_embeddings": [emb], "n_results": n,
                          "include": ["documents", "metadatas", "distances"]}
                if where:
                    kwargs["where"] = where
                res = collection.query(**kwargs)
                for c, m, d in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
                    key = f"{m.get('source', '')}::{c[:120]}"
                    if key not in seen or d < seen[key][2]:
                        seen[key] = (c, m, d)
            except Exception as e:
                slog("VECTOR", error=str(e))

    ranked = sorted(seen.values(), key=lambda x: x[2])
    kept = [r for r in ranked if r[2] < distance_cutoff] or ranked[:pool_size]
    kept = kept[:pool_size]

    # Prepend exact circular-number matches (scope-aware), de-duplicated.
    kw = keyword_id_chunks(collection, question, scope)
    if kw:
        existing = {(m.get("source", ""), c[:120]) for c, m, _ in kept}
        for doc, meta in reversed(kw):
            if (meta.get("source", ""), doc[:120]) not in existing:
                kept.insert(0, (doc, meta, -1.0))
        slog("KEYWORD", scope=scope, injected=len(kw))

    slog("VECTOR", scope=scope, pool=len(kept))
    return kept
