# scripts/build_graph.py
"""
Build the knowledge graph from ChromaDB and persist it (Phase 3).

  python scripts\\build_graph.py            # Tier 0 + Tier 1 (fast, deterministic)
  python scripts\\build_graph.py --llm 150  # also Tier 2 LLM on the first 150 docs

Writes:
  backend/knowledge_graph/graph.json
  backend/knowledge_graph/graph_metadata.json

Decoupled from indexing on purpose: the vector index build stays fast, and this
graph is preferably built LOCALLY then graph.json copied to production (Tier 2
needs Ollama, so build where Ollama runs).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import chromadb
from knowledge_graph.graph_builder import build_from_chroma

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "chroma")
COLLECTION_NAME = "ntpc_content"
GRAPH_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "knowledge_graph")
GRAPH_PATH = os.path.join(GRAPH_DIR, "graph.json")
META_PATH = os.path.join(GRAPH_DIR, "graph_metadata.json")


def main():
    ap = argparse.ArgumentParser(description="Build the NTPC knowledge graph from ChromaDB.")
    ap.add_argument("--llm", type=int, default=0,
                    help="Run Tier-2 LLM extraction on the first N documents (needs Ollama). 0 = skip.")
    args = ap.parse_args()

    col = chromadb.PersistentClient(path=CHROMA_PATH).get_collection(COLLECTION_NAME)
    print(f"Collection: {col.count()} chunks")

    llm_client = model = None
    if args.llm > 0:
        import ollama
        llm_client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
                                   trust_env=False)
        model = "llama3.2"
        print(f"Tier-2 LLM extraction enabled for up to {args.llm} documents.")

    store, doc_count = build_from_chroma(
        col, use_llm=(args.llm > 0), llm_client=llm_client, model=model, max_llm_docs=args.llm)
    meta = store.save(GRAPH_PATH, META_PATH, doc_count=doc_count)

    print("\n=== graph built ===")
    for k, v in meta.items():
        print(f"  {k}: {v}")
    print(f"\nWritten: {os.path.abspath(GRAPH_PATH)}")
    print("Restart the backend so it loads the new graph.")


if __name__ == "__main__":
    main()
