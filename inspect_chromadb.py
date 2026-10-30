#!/usr/bin/env python3
"""
inspect_chromadb.py  —  READ-ONLY ChromaDB inspector for the NTPC RAG chatbot.

What it does
------------
* Auto-detects the ChromaDB persist directory used by this project
  (backend/chroma) and also lists any other Chroma stores found on disk
  (data/chroma_db, backups).
* For the chosen DB it reports:
    - total collections + names
    - document count per collection
    - first 5 sample chunks / metadatas / ids
    - data-quality analysis (duplicates, empties, missing metadata, huge chunks)
* Prints everything in readable tables.

SAFETY GUARANTEES (read-only)
-----------------------------
This script NEVER mutates the database. It only ever calls:
    chromadb.PersistentClient(...).list_collections()
    collection.count()
    collection.get(...)            # read
It does NOT call add / update / upsert / delete / modify / create / rebuild,
and it does NOT compute or write any embeddings.

Usage
-----
    python inspect_chromadb.py                # inspect the active backend/chroma
    python inspect_chromadb.py --path some/dir  # inspect a specific store
    python inspect_chromadb.py --all          # inspect every detected store
    python inspect_chromadb.py --samples 10   # show N samples instead of 5
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

# ---- make emoji / unicode safe on the Windows cp1252 console -----------------
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import chromadb
except Exception as e:  # pragma: no cover
    print("ERROR: could not import chromadb. Activate the project venv first.")
    print(f"       ({e})")
    sys.exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))

# Candidate locations, in priority order. The first that exists is the default.
CANDIDATE_PATHS = [
    os.path.join(HERE, "backend", "chroma"),            # active (rag.py / indexer.py)
    os.path.join(HERE, "data", "chroma_db"),            # stray/legacy
    os.path.join(HERE, "backend", "chroma_backup_20260608"),
    os.path.join(HERE, "backend", "chroma_backup_20260603"),
]

SAMPLE_DEFAULT = 5
LARGE_CHUNK_CHARS = 4000   # flag chunks longer than this as "unusually large"


# ----------------------------------------------------------------------------- helpers
def hr(char: str = "=", n: int = 78) -> str:
    return char * n


def is_chroma_dir(path: str) -> bool:
    return os.path.isdir(path) and os.path.isfile(os.path.join(path, "chroma.sqlite3"))


def detect_paths() -> list[str]:
    """Return every candidate path that looks like a real Chroma store."""
    found = []
    for p in CANDIDATE_PATHS:
        if is_chroma_dir(p) and p not in found:
            found.append(p)
    return found


def truncate(text: str, n: int = 160) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def fmt_table(rows: list[list[str]], headers: list[str]) -> str:
    """Tiny dependency-free table formatter."""
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep = "  ".join("-" * w for w in widths)
    out = [line, sep]
    for r in rows:
        out.append("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    return "\n".join(out)


# ----------------------------------------------------------------------------- inspection
def inspect_collection(col, samples: int) -> None:
    name = col.name
    print(hr("-"))
    print(f"COLLECTION: {name}")
    print(hr("-"))

    try:
        total = col.count()
    except Exception as e:
        print(f"  ! could not count collection: {e}")
        return
    print(f"  Documents: {total}")
    try:
        print(f"  Metadata (collection-level): {col.metadata}")
    except Exception:
        pass

    if total == 0:
        print("  (empty collection — nothing to sample)")
        return

    # ---- read a sample (READ-ONLY) ----
    n_sample = min(samples, total)
    try:
        sample = col.get(limit=n_sample, include=["documents", "metadatas"])
    except Exception as e:
        print(f"  ! could not read sample: {e}")
        return

    ids = sample.get("ids") or []
    docs = sample.get("documents") or []
    metas = sample.get("metadatas") or []

    print(f"\n  Sample document IDs (first {n_sample}):")
    for i in ids:
        print(f"    - {i}")

    print(f"\n  Sample chunks (first {n_sample}):")
    rows = [[str(i + 1), f"{len(docs[i] or '')}", truncate(docs[i], 150)]
            for i in range(len(docs))]
    print("    " + fmt_table(rows, ["#", "len", "text"]).replace("\n", "\n    "))

    print(f"\n  Sample metadata (first {n_sample}):")
    for i, m in enumerate(metas):
        print(f"    [{i + 1}] {m}")

    # ---- data quality analysis over the WHOLE collection (read-only) ----
    print("\n  Data-quality analysis (full scan, read-only):")
    analyze_quality(col, total)


def analyze_quality(col, total: int) -> None:
    """Scan all docs/metadatas in pages and report quality issues. Read-only."""
    page = 5000
    seen_offset = 0

    empty = 0
    missing_meta = 0
    large = 0
    largest = 0
    lengths_sum = 0
    text_counter: Counter[str] = Counter()
    meta_keys: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()

    while seen_offset < total:
        try:
            batch = col.get(limit=page, offset=seen_offset,
                            include=["documents", "metadatas"])
        except Exception as e:
            print(f"    ! scan stopped at offset {seen_offset}: {e}")
            break
        docs = batch.get("documents") or []
        metas = batch.get("metadatas") or []
        if not docs:
            break

        for d in docs:
            d = d or ""
            ln = len(d)
            lengths_sum += ln
            largest = max(largest, ln)
            if ln == 0 or not d.strip():
                empty += 1
            if ln > LARGE_CHUNK_CHARS:
                large += 1
            # hash the text to detect duplicates cheaply
            text_counter[d.strip()] += 1

        for m in metas:
            if not m:
                missing_meta += 1
                continue
            for k in m.keys():
                meta_keys[k] += 1
            src = m.get("source") or m.get("file") or m.get("url")
            if src:
                source_counter[str(src)] += 1

        seen_offset += len(docs)

    dup_groups = {t: c for t, c in text_counter.items() if c > 1 and t}
    dup_extra = sum(c - 1 for c in dup_groups.values())
    avg_len = (lengths_sum / total) if total else 0

    rows = [
        ["Total documents scanned", str(seen_offset)],
        ["Empty / whitespace-only chunks", str(empty)],
        ["Documents with missing metadata", str(missing_meta)],
        [f"Unusually large chunks (> {LARGE_CHUNK_CHARS} chars)", str(large)],
        ["Largest chunk (chars)", str(largest)],
        ["Average chunk length (chars)", f"{avg_len:.0f}"],
        ["Exact-duplicate text groups", str(len(dup_groups))],
        ["Redundant duplicate copies", str(dup_extra)],
        ["Distinct metadata keys seen", str(len(meta_keys))],
    ]
    print("    " + fmt_table(rows, ["Check", "Result"]).replace("\n", "\n    "))

    if meta_keys:
        print("\n    Metadata key coverage (count of docs having the key):")
        mk = [[k, str(v)] for k, v in meta_keys.most_common()]
        print("      " + fmt_table(mk, ["key", "docs"]).replace("\n", "\n      "))

    if source_counter:
        print("\n    Top sources by chunk count:")
        sc = [[truncate(s, 55), str(c)]
              for s, c in source_counter.most_common(15)]
        print("      " + fmt_table(sc, ["source", "chunks"]).replace("\n", "\n      "))

    if dup_groups:
        print("\n    Sample duplicated chunks (text → copies):")
        for t, c in sorted(dup_groups.items(), key=lambda x: -x[1])[:5]:
            print(f"      ({c}x) {truncate(t, 90)}")


def inspect_store(path: str, samples: int) -> None:
    print("\n" + hr())
    print(f"DATABASE: {path}")
    print(hr())
    if not is_chroma_dir(path):
        print("  ! no chroma.sqlite3 here — skipping")
        return
    try:
        client = chromadb.PersistentClient(path=path)
        collections = client.list_collections()
    except Exception as e:
        print(f"  ! could not open store: {e}")
        return

    print(f"  Total collections: {len(collections)}")
    names = [c.name for c in collections]
    print(f"  Collection names : {names}")

    for col in collections:
        inspect_collection(col, samples)


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only ChromaDB inspector.")
    ap.add_argument("--path", help="inspect a specific persist directory")
    ap.add_argument("--all", action="store_true",
                    help="inspect every detected Chroma store")
    ap.add_argument("--samples", type=int, default=SAMPLE_DEFAULT,
                    help=f"number of sample rows to show (default {SAMPLE_DEFAULT})")
    args = ap.parse_args()

    detected = detect_paths()
    print(hr())
    print("DETECTED CHROMA STORES")
    print(hr())
    if detected:
        for p in detected:
            tag = "  <-- active (rag.py)" if p.endswith(os.path.join("backend", "chroma")) else ""
            print(f"  * {p}{tag}")
    else:
        print("  (none found in candidate locations)")

    if args.path:
        targets = [args.path]
    elif args.all:
        targets = detected
    else:
        targets = detected[:1]  # default: the active store only

    if not targets:
        print("\nNothing to inspect.")
        return

    for p in targets:
        inspect_store(p, args.samples)

    print("\n" + hr())
    print("Done. (No data was modified — read-only inspection.)")
    print(hr())


if __name__ == "__main__":
    main()
