# backend/knowledge_graph/graph_store.py
"""
NetworkX MultiDiGraph wrapper with version-independent JSON persistence.

Persists:
  * graph.json           - {version, nodes[], edges[]}  (our own schema, so it
                           round-trips across networkx versions)
  * graph_metadata.json  - {graph_version, build_timestamp, document_count,
                           node_count, edge_count}

Keeps two in-memory indexes for O(1) query-time lookups:
  * alias_index : normalized alias -> node_id   (entity linking)
  * doc_index   : document_id -> {node_id, ...}
"""

import json
import os
import re
import time

import networkx as nx

from . import models


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


class GraphStore:
    def __init__(self):
        self.g = nx.MultiDiGraph()
        self.alias_index = {}   # normalized alias -> node_id
        self.doc_index = {}     # document_id -> set(node_id)
        self.metadata = {}

    # ───────────────────────── build ─────────────────────────
    def add_node(self, node_id, ntype, label, **attrs):
        chunk_ids = attrs.pop("chunk_ids", None) or []
        aliases = attrs.pop("aliases", None) or []
        if self.g.has_node(node_id):
            data = self.g.nodes[node_id]
            for v in chunk_ids:
                if v not in data["chunk_ids"]:
                    data["chunk_ids"].append(v)
            for k, v in attrs.items():
                if v not in (None, "") and not data.get(k):
                    data[k] = v
        else:
            data = {"type": ntype, "label": label, "chunk_ids": list(chunk_ids), "aliases": list(aliases)}
            data.update({k: v for k, v in attrs.items() if v is not None})
            self.g.add_node(node_id, **data)
        # indexes
        self._index_alias(label, node_id)
        for a in aliases:
            self._index_alias(a, node_id)
        did = attrs.get("document_id")
        if did:
            self.doc_index.setdefault(did, set()).add(node_id)
        return node_id

    def add_edge(self, u, v, relation, **attrs):
        # key=relation -> at most one edge per (u, v, relation): natural de-dup.
        if u and v and u != v:
            self.g.add_edge(u, v, key=relation, relation=relation, **attrs)

    def _index_alias(self, alias, node_id):
        n = _norm(alias)
        if n:
            self.alias_index.setdefault(n, node_id)

    # ─────────────────────── persistence ───────────────────────
    def save(self, graph_path, meta_path=None, doc_count=0):
        nodes = [{"id": n, **d} for n, d in self.g.nodes(data=True)]
        edges = [{"u": u, "v": v, **d} for u, v, d in self.g.edges(data=True)]
        os.makedirs(os.path.dirname(graph_path) or ".", exist_ok=True)
        if os.path.exists(graph_path):
            os.replace(graph_path, graph_path + ".bak")   # keep one rollback copy
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump({"version": models.GRAPH_VERSION, "nodes": nodes, "edges": edges},
                      f, ensure_ascii=False)

        self.metadata = {
            "graph_version":   models.GRAPH_VERSION,
            "build_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "document_count":  doc_count,
            "node_count":      self.g.number_of_nodes(),
            "edge_count":      self.g.number_of_edges(),
        }
        meta_path = meta_path or os.path.join(os.path.dirname(graph_path) or ".", "graph_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        return self.metadata

    @classmethod
    def load(cls, graph_path, meta_path=None):
        store = cls()
        with open(graph_path, encoding="utf-8") as f:
            data = json.load(f)
        for nd in data.get("nodes", []):
            nd = dict(nd)
            nid = nd.pop("id")
            store.g.add_node(nid, **nd)
            store._index_alias(nd.get("label", ""), nid)
            for a in nd.get("aliases", []) or []:
                store._index_alias(a, nid)
            did = nd.get("document_id")
            if did:
                store.doc_index.setdefault(did, set()).add(nid)
        for ed in data.get("edges", []):
            ed = dict(ed)
            u, v = ed.pop("u"), ed.pop("v")
            rel = ed.get("relation", "related")
            store.g.add_edge(u, v, key=rel, **ed)
        meta_path = meta_path or os.path.join(os.path.dirname(graph_path) or ".", "graph_metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                store.metadata = json.load(f)
        return store

    # ───────────────────────── query ─────────────────────────
    def resolve(self, alias):
        """alias text -> node_id (or None)."""
        return self.alias_index.get(_norm(alias))

    def neighbors(self, node_id, relations=None, out=True, inn=True):
        """Return [(other_node, relation, direction, edge_attrs)]."""
        res = []
        if not self.g.has_node(node_id):
            return res
        if out:
            for _, v, _, d in self.g.out_edges(node_id, keys=True, data=True):
                if relations is None or d.get("relation") in relations:
                    res.append((v, d.get("relation"), "out", d))
        if inn:
            for u, _, _, d in self.g.in_edges(node_id, keys=True, data=True):
                if relations is None or d.get("relation") in relations:
                    res.append((u, d.get("relation"), "in", d))
        return res

    def label(self, node_id):
        return self.g.nodes[node_id].get("label", node_id) if self.g.has_node(node_id) else node_id
