# backend/knowledge_graph/graph_query.py
"""
Query-time knowledge-graph use (Phase 3).

Loads graph.json lazily (singleton) and, given a question + the retrieved chunk
metadata, returns enrichment used AFTER retrieval+rerank and BEFORE the LLM:
  * related_documents / related_circulars / related_topics  (cross-source nav)
  * context_text       - compact "Known relationships" block for the LLM prompt
  * suggested_questions - relationship-driven follow-ups

ROBUST: if graph.json is missing or fails to load, every function degrades to an
empty result and the backend keeps answering (enrichment is purely additive).
"""

import os
import re

from . import models
from .graph_store import GraphStore

_GRAPH_PATH = os.path.join(os.path.dirname(__file__), "graph.json")
_store = None
_load_failed = False


def get_store():
    """Lazy singleton load of the graph; never raises."""
    global _store, _load_failed
    if _store is not None or _load_failed:
        return _store
    try:
        if os.path.exists(_GRAPH_PATH):
            _store = GraphStore.load(_GRAPH_PATH)
            print(f"[ok] Knowledge graph loaded: {_store.g.number_of_nodes()} nodes, "
                  f"{_store.g.number_of_edges()} edges")
        else:
            _load_failed = True
            print("[warn] graph.json not found; graph enrichment disabled.")
    except Exception as e:
        _load_failed = True
        print(f"[warn] graph load failed ({e}); enrichment disabled.")
    return _store


def status() -> dict:
    """For GET /graph/status."""
    s = get_store()
    if s is None:
        return {"loaded": False, "version": models.GRAPH_VERSION,
                "node_count": 0, "edge_count": 0, "build_timestamp": None}
    meta = dict(s.metadata or {})
    return {
        "loaded": True,
        "version": meta.get("graph_version", models.GRAPH_VERSION),
        "node_count": s.g.number_of_nodes(),
        "edge_count": s.g.number_of_edges(),
        "build_timestamp": meta.get("build_timestamp"),
        "document_count": meta.get("document_count"),
    }


def _seed_nodes(store, question, metadatas):
    """Entity-link the question + retrieved documents to graph nodes."""
    nodes = set()
    cid = models.canonical_circular_id(question)
    if cid and store.g.has_node(cid):
        nodes.add(cid)
    elif cid:
        m = re.search(r"chrc-(\d+)", cid)
        if m:                                   # bare "CHRC 992" -> year-qualified node via alias
            r = store.resolve(f"CHRC {m.group(1)}")
            if r:
                nodes.add(r)
    for meta in metadatas or []:
        did = meta.get("document_id") or meta.get("source")
        if did:
            dn = models.node_id(models.DOCUMENT, did)
            if store.g.has_node(dn):
                nodes.add(dn)
    return nodes


def enrich(question, metadatas, max_items=4):
    """Return graph enrichment for a query (empty dict if the graph is unavailable)."""
    store = get_store()
    if store is None:
        return {}
    seeds = _seed_nodes(store, question, metadatas)
    if not seeds:
        return {}

    related_docs, related_circulars, related_topics = [], [], []

    # 1-hop neighbours of the seeds
    for node in seeds:
        for other, rel, direction, attrs in store.neighbors(node):
            od = store.g.nodes.get(other, {})
            ot, label = od.get("type"), od.get("label", other)
            if ot == models.CIRCULAR and label not in related_circulars and other not in seeds:
                related_circulars.append(label)
            elif ot == models.TOPIC and label not in related_topics:
                related_topics.append(label)

    # 2-hop: other documents sharing a topic with the seeds (cross-source navigation)
    seed_topics = set()
    for node in seeds:
        for other, rel, d, a in store.neighbors(node, relations={models.ABOUT_TOPIC}):
            seed_topics.add(other)
    for tn in list(seed_topics)[:6]:
        for other, rel, direction, a in store.neighbors(tn, relations={models.ABOUT_TOPIC},
                                                         out=False, inn=True):
            od = store.g.nodes.get(other, {})
            if od.get("type") == models.DOCUMENT and other not in seeds:
                lbl = od.get("label", "")
                if lbl and lbl not in related_docs:
                    related_docs.append(lbl)

    related_docs = related_docs[:max_items]
    related_circulars = related_circulars[:max_items]
    related_topics = related_topics[:max_items]

    # compact context block for the LLM prompt (bounded)
    lines = []
    if related_circulars:
        lines.append("Related circulars: " + ", ".join(related_circulars))
    if related_topics:
        lines.append("Related topics: " + ", ".join(related_topics))
    if related_docs:
        lines.append("Related documents: " + ", ".join(d[:60] for d in related_docs))
    context_text = ("Known relationships from the NTPC knowledge graph:\n" + "\n".join(lines)) \
        if lines else ""

    # relationship-driven suggested questions
    suggestions = []
    for c in related_circulars[:2]:
        suggestions.append(f"Tell me about {c}")
    for t in related_topics[:2]:
        suggestions.append(f"What does NTPC say about {t}?")

    return {
        "related_documents":   related_docs,
        "related_circulars":   related_circulars,
        "related_topics":      related_topics,
        "context_text":        context_text,
        "suggested_questions": suggestions,
    }
