# backend/tests/test_reference_retrieval.py
"""
Regression tests for the reference-aware RETRIEVAL logic (Steps 3-8, 10):
exact metadata lookup and reference collision filtering. Uses a fake collection so
it needs no embeddings, ChromaDB, or Ollama.

    backend\\venv\\Scripts\\python.exe backend\\tests\\test_reference_retrieval.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rag
from reference_parser import parse_reference


class FakeCollection:
    """Minimal stand-in that honours the {'reference_key': …} where filter."""
    def __init__(self, rows):        # rows = list of (text, meta)
        self._rows = rows

    def count(self):
        return len(self._rows)

    def get(self, where=None, include=None):
        docs, metas = [], []
        for text, meta in self._rows:
            if where and "reference_key" in where and meta.get("reference_key") != where["reference_key"]:
                continue
            docs.append(text)
            metas.append(meta)
        return {"documents": docs, "metadatas": metas}


ROWS = [
    ("Circular 301 body A",     {"source": "late_bids.pdf", "reference_key": "CIRCULAR::301(P&S)"}),
    ("Circular 301 body B",     {"source": "late_bids.pdf", "reference_key": "CIRCULAR::301(P&S)"}),
    ("Instruction 301 body",    {"source": "closing.pdf",   "reference_key": "INSTRUCTION::301(P&S)"}),
    ("System Circular 182 body",{"source": "closing.pdf",   "reference_key": "SYSTEMCIRCULAR::182/2019"}),
    ("neutral topic chunk",     {"source": "policy.pdf",    "reference_key": ""}),
]


def _fake():
    rag.collection = FakeCollection(ROWS)


def test_exact_lookup_returns_only_matching_entity():
    # Test 1: "Circular No.301(P&S)" must retrieve ONLY the Circular 301(P&S) doc.
    _fake()
    res = rag.exact_reference_lookup(parse_reference("Circular No.301(P&S)"))
    assert len(res) == 2, res
    assert all(m["reference_key"] == "CIRCULAR::301(P&S)" for _, m, _ in res)
    assert all(m["source"] == "late_bids.pdf" for _, m, _ in res)


def test_exact_lookup_distinguishes_type_from_same_number():
    # Test 2/6: same number 301(P&S), different type must NOT cross-contaminate.
    _fake()
    res = rag.exact_reference_lookup(parse_reference("Instruction 301(P&S)"))
    assert len(res) == 1
    assert res[0][1]["reference_key"] == "INSTRUCTION::301(P&S)"


def test_exact_lookup_system_circular():
    # Test 3: "System Circular 182/2019" resolves to exactly that entity.
    _fake()
    res = rag.exact_reference_lookup(parse_reference("System Circular 182/2019"))
    assert len(res) == 1
    assert res[0][1]["reference_key"] == "SYSTEMCIRCULAR::182/2019"


def test_collision_filter_drops_conflicting_entities():
    # Step 8: in the fallback path, a different reference entity is rejected, the
    # matching one is pinned first, and neutral topic chunks are kept.
    ref = parse_reference("Circular No.301(P&S)")
    final = [
        ("a", {"reference_key": "CIRCULAR::301(P&S)",    "source": "late_bids.pdf"}, 0.5),
        ("b", {"reference_key": "SYSTEMCIRCULAR::182/2019", "source": "closing.pdf"}, 0.4),
        ("c", {"reference_key": "",                      "source": "policy.pdf"},   0.6),
    ]
    kept = rag.reference_collision_filter(final, ref)
    keys = [c[1]["reference_key"] for c in kept]
    assert "SYSTEMCIRCULAR::182/2019" not in keys          # conflicting entity removed
    assert kept[0][1]["reference_key"] == "CIRCULAR::301(P&S)"  # match pinned first
    assert "" in keys                                       # neutral topic chunk kept


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed.")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
