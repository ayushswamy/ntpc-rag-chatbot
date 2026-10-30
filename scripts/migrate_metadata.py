# scripts/migrate_metadata.py
"""
In-place metadata migration (Phase 1).

Backfills document_type / source_system / department / year / document_id onto
EXISTING ChromaDB chunks WITHOUT re-embedding, using scope_config.classify_document().

Why in place (collection.update) instead of `indexer.py --rebuild`:
  * No re-embedding      -> seconds, not minutes.
  * No delete/recreate   -> the live backend keeps serving during the migration
                            (it only re-reads metadata); a restart afterwards
                            applies the new scope-filtering code path.
  * Idempotent           -> classification is derived purely from `source`, so
                            re-running converges to the same result.

Run:  backend\\venv\\Scripts\\python.exe scripts\\migrate_metadata.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import chromadb
from scope_config import classify_document, UNKNOWN_TYPE

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "chroma")
COLLECTION_NAME = "ntpc_content"
BATCH = 5000


def migrate():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    col = client.get_collection(COLLECTION_NAME)
    print(f"Collection '{COLLECTION_NAME}': {col.count()} chunks")

    data = col.get(include=["metadatas"])      # ids are always returned
    ids, metas = data["ids"], data["metadatas"]

    new_ids, new_metas = [], []
    type_counts, unknown_sources = {}, set()

    for cid, meta in zip(ids, metas):
        meta = dict(meta or {})
        source = meta.get("source", "")
        fields = classify_document(source, meta.get("title", ""))
        meta.update(fields)                    # add/overwrite the 5 Phase-1 fields
        new_ids.append(cid)
        new_metas.append(meta)
        dt = fields["document_type"]
        type_counts[dt] = type_counts.get(dt, 0) + 1
        if dt == UNKNOWN_TYPE and source:
            unknown_sources.add(source)

    # Batched in-place update (embeddings untouched).
    for i in range(0, len(new_ids), BATCH):
        col.update(ids=new_ids[i:i + BATCH], metadatas=new_metas[i:i + BATCH])
        print(f"  updated {min(i + BATCH, len(new_ids))}/{len(new_ids)}")

    print("\n=== document_type distribution ===")
    for dt, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {c:6d}  {dt}")

    # Decision #3: auto-detect & report sources that matched NO known prefix, so the
    # deployment notes can flag server/local prefix differences (still searchable
    # via ALL_SOURCES in the meantime).
    if unknown_sources:
        print(f"\n[!] {len(unknown_sources)} source(s) classified as '{UNKNOWN_TYPE}' "
              f"(reachable via ALL_SOURCES). Sample:")
        for s in sorted(unknown_sources)[:25]:
            print(f"     - {s}")
    else:
        print("\nAll sources matched a known scope prefix.")

    print("\nDone. Restart the backend so scope filtering takes effect.")


if __name__ == "__main__":
    migrate()
