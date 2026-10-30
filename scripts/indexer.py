# scripts/indexer.py
import json
import os
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Windows port: the progress prints below use emoji; reconfigure stdout/stderr to
# UTF-8 so they don't crash on the cp1252 console (or when output is redirected).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import chromadb
import fitz
from embedder import embed_texts
from scope_config import classify_document   # Phase 1: per-chunk classification metadata
# Reference-Aware Retrieval (Step 6): tag chunks with their structured reference.
from reference_parser import (
    extract_document_reference, extract_chunk_reference, reference_meta,
)

REFERENCE_INDEX_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "reference_index.json")

# Strip the agent filename prefix ("circular_repository_20260608_") so the clean
# document title can be parsed for a reference (CCIOM1036, CHRC992, ...).
_AGENT_PREFIX_RE = re.compile(r"^[a-z_]+_\d{8}_", re.IGNORECASE)

PDF_DIR    = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "reports")
RAW_DIR    = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
# Non-PDF files fetched by the agents (Excel/Word/CSV) land here.
DOWNLOADS_DIR = os.path.join(RAW_DIR, "downloads")

# ✅ FIX: Relative path - kisi bhi PC pe kaam karega
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "chroma")
COLLECTION_NAME = "ntpc_content"

CHUNK_SIZE = 400
OVERLAP    = 50

def chunk_text(text, size=CHUNK_SIZE, overlap=OVERLAP):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i+size])
        if len(chunk.strip()) >= 50:
            chunks.append(chunk)
        i += size - overlap
    return chunks

def extract_pdf_chunks(pdf_path):
    doc = fitz.open(pdf_path)
    chunks = []
    filename = os.path.basename(pdf_path)
    total_text = 0

    # ── Document-level identity reference (Reference-Aware Retrieval) ──
    # A reference declared at the top of page 1 (or, failing that, in the filename)
    # means the WHOLE document IS that reference → tag every chunk with it, so an
    # exact-reference query returns the entire document. Compilations (Closing
    # Guidelines) declare none here and fall through to per-chunk heading tagging.
    header = ""
    for page in doc:
        t = page.get_text()
        if t.strip():
            header = t
            break
    clean_title = _AGENT_PREFIX_RE.sub("", filename)
    doc_ref = extract_document_reference(title=clean_title, header_text=header)

    for page_num, page in enumerate(doc):
        text = page.get_text()
        total_text += len(text)
        if not text.strip():
            continue
        for chunk in chunk_text(text):
            # Doc identity wins; else a section heading inside a compilation
            # (e.g. an Instruction within Closing Guidelines) tags just its chunk.
            ref = doc_ref or extract_chunk_reference(chunk)
            meta = {
                "source":  filename,
                "title":   filename,
                "url":     filename,
                "section": f"page_{page_num + 1}",
                "page":    str(page_num + 1),
            }
            meta.update(reference_meta(ref))
            chunks.append({"text": chunk, "meta": meta})

    if total_text < 100:
        print(f"  ⚠️  WARNING: {filename} has no extractable text — may be scanned!")

    return chunks


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Non-PDF office extraction (Excel / Word / CSV)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUPPORTED_OFFICE_EXTS = (".docx", ".xlsx", ".csv", ".txt", ".json")
LEGACY_OFFICE_EXTS    = (".xls", ".doc", ".ppt", ".pptx")


def _docx_text(path):
    import docx
    d = docx.Document(path)
    parts = [p.text.strip() for p in d.paragraphs if p.text and p.text.strip()]
    for tbl in d.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _xlsx_sheets_text(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            out.append((ws.title, "\n".join(rows)))
    wb.close()
    return out


def _csv_text(path):
    import csv
    lines = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row if c and c.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _txt_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _json_lines(obj):
    """Flatten arbitrary JSON into readable 'key: value' / 'k=v | ...' lines."""
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines += _json_lines(v)
            else:
                lines.append(f"{k}: {v}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                lines.append(" | ".join(
                    f"{k}={v}" for k, v in item.items() if not isinstance(v, (dict, list))))
                for k, v in item.items():
                    if isinstance(v, (dict, list)):
                        lines += _json_lines(v)
            else:
                lines.append(str(item))
    else:
        lines.append(str(obj))
    return lines


def _json_text(path):
    with open(path, encoding="utf-8") as f:
        return "\n".join(_json_lines(json.load(f)))


def extract_office_chunks(path):
    """Return [{text, meta}] for a .docx/.xlsx/.csv/.txt/.json file (PDF-shaped)."""
    ext = os.path.splitext(path)[1].lower()
    filename = os.path.basename(path)
    base_meta = {"source": filename, "title": filename, "url": filename, "page": "0"}
    chunks = []
    try:
        if ext == ".docx":
            for ch in chunk_text(_docx_text(path)):
                chunks.append({"text": ch, "meta": {**base_meta, "section": "document"}})
        elif ext == ".xlsx":
            for sheet, text in _xlsx_sheets_text(path):
                for ch in chunk_text(text):
                    chunks.append({"text": ch, "meta": {**base_meta, "section": f"sheet:{sheet}"}})
        elif ext == ".csv":
            for ch in chunk_text(_csv_text(path)):
                chunks.append({"text": ch, "meta": {**base_meta, "section": "csv"}})
        elif ext == ".txt":
            for ch in chunk_text(_txt_text(path)):
                chunks.append({"text": ch, "meta": {**base_meta, "section": "text"}})
        elif ext == ".json":
            for ch in chunk_text(_json_text(path)):
                chunks.append({"text": ch, "meta": {**base_meta, "section": "data"}})
    except Exception as e:
        print(f"  ⚠️  Failed to extract {filename}: {e}")
        return []
    return chunks


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gather chunks per source (each item = {"text","meta"})
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def gather_page_items():
    items = []
    pages_file = os.path.join(RAW_DIR, "pages.json")
    if not os.path.exists(pages_file):
        print("⚠️  pages.json not found — skipping website pages.")
        return items
    with open(pages_file, encoding="utf-8") as f:
        pages = json.load(f)
    for page in pages:
        texts = page.get("paragraphs", []) + page.get("list_items", []) + page.get("tables", [])
        for chunk in chunk_text(" ".join(texts)):
            items.append({"text": chunk, "meta": {
                "source": page.get("url", "website"), "title": page.get("title", "NTPC Website"),
                "url": page.get("url", ""), "section": page.get("section", "General"), "page": "0"}})
    print(f"✅ Website pages: {len(items)} chunks from {len(pages)} pages")
    return items


def gather_pdf_items(skip_sources=None):
    items = []
    if not os.path.isdir(PDF_DIR):
        print(f"⚠️  PDF folder not found: {PDF_DIR}")
        return items
    pdfs = sorted(f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf"))
    todo = [f for f in pdfs if not (skip_sources is not None and f in skip_sources)]
    print(f"\n📄 PDFs: {len(pdfs)} total, {len(todo)} to index"
          + (" (new only)" if skip_sources is not None else ""))
    for f in todo:
        ch = extract_pdf_chunks(os.path.join(PDF_DIR, f))
        print(f"  {f} → {len(ch)} chunks")
        items += ch
    return items


def gather_office_items(skip_sources=None):
    items, legacy = [], []
    if not os.path.isdir(DOWNLOADS_DIR):
        return items
    files = []
    for root, _dirs, fs in os.walk(DOWNLOADS_DIR):
        for fn in fs:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SUPPORTED_OFFICE_EXTS:
                files.append(os.path.join(root, fn))
            elif ext in LEGACY_OFFICE_EXTS:
                legacy.append(fn)
    todo = [p for p in sorted(files) if not (skip_sources is not None and os.path.basename(p) in skip_sources)]
    if files:
        print(f"\n📑 Downloads (docx/xlsx/csv/txt/json): {len(files)} total, {len(todo)} to index"
              + (" (new only)" if skip_sources is not None else ""))
        for fp in todo:
            ch = extract_office_chunks(fp)
            print(f"  {os.path.basename(fp)} → {len(ch)} chunks")
            items += ch
    if legacy:
        print(f"  ⚠️  {len(legacy)} legacy file(s) skipped (convert to xlsx/docx): {legacy[:5]}")
    return items


def _batch_add(collection, items, ids):
    if not items:
        return 0
    # Phase 1: single choke-point — tag EVERY chunk (pdf/office/website) with
    # classification metadata (document_type/source_system/department/year/document_id)
    # so scope filtering works. Derived purely from the chunk's `source`.
    for it in items:
        it["meta"].update(classify_document(it["meta"].get("source", ""),
                                            it["meta"].get("title", "")))
        # Ensure every chunk carries the reference fields (office/website chunks
        # get empty strings) so the Chroma `where` filter is always well-defined.
        it["meta"].setdefault("reference_type", "")
        it["meta"].setdefault("reference_number", "")
        it["meta"].setdefault("reference_key", "")
    texts = [it["text"] for it in items]
    metas = [it["meta"] for it in items]
    print("⏳ Creating embeddings — thoda time lagega...")
    embeddings = embed_texts(texts)
    BATCH = 5000
    for i in range(0, len(texts), BATCH):
        collection.add(documents=texts[i:i+BATCH], embeddings=embeddings[i:i+BATCH],
                       ids=ids[i:i+BATCH], metadatas=metas[i:i+BATCH])
        print(f"  ✅ Batch {i//BATCH + 1} added")
    return len(texts)


def write_reference_index(collection):
    """
    Write backend/reference_index.json — a browsable catalog mapping every exact
    reference_key -> {reference_type, reference_number, sources[], chunk_count}
    (Reference-Aware Retrieval, Step 6). Rebuilt from the WHOLE collection so it
    always matches the live index. Used for fast existence checks and logging.
    """
    try:
        metas = collection.get(include=["metadatas"])["metadatas"]
    except Exception as e:
        print(f"  ⚠️  reference index skipped: {e}")
        return
    idx: dict = {}
    for m in metas:
        if not m:
            continue
        key = m.get("reference_key", "")
        if not key:
            continue
        entry = idx.setdefault(key, {
            "reference_type":   m.get("reference_type", ""),
            "reference_number": m.get("reference_number", ""),
            "sources":          [],
            "chunk_count":      0,
        })
        entry["chunk_count"] += 1
        src = m.get("source", "")
        if src and src not in entry["sources"]:
            entry["sources"].append(src)
    try:
        with open(REFERENCE_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        print(f"🔖 Reference index: {len(idx)} distinct references → {os.path.abspath(REFERENCE_INDEX_PATH)}")
    except OSError as e:
        print(f"  ⚠️  could not write reference index: {e}")


def full_rebuild(client):
    items = gather_page_items() + gather_pdf_items() + gather_office_items()
    print(f"\n📊 Total chunks to embed: {len(items)}")
    try:
        client.delete_collection(COLLECTION_NAME)
        print("🗑️  Old collection deleted.")
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)
    _batch_add(collection, items, [f"doc_{i}" for i in range(len(items))])
    write_reference_index(collection)
    print(f"\n{'='*50}\n🎉 Done (full rebuild)! {collection.count()} chunks in ChromaDB\n{'='*50}\n")


def incremental(client):
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        collection = None
    if collection is None or collection.count() == 0:
        print("No existing collection — doing a full build instead.")
        full_rebuild(client)
        return

    existing = collection.get(include=["metadatas"])
    existing_sources = {m.get("source") for m in existing["metadatas"] if m}
    print(f"Existing collection: {collection.count()} chunks across {len(existing_sources)} sources.")

    items = gather_pdf_items(skip_sources=existing_sources) + gather_office_items(skip_sources=existing_sources)
    if not items:
        print("\n✅ Index already up to date — no new files to add.")
        return
    print(f"\n📊 New chunks to embed: {len(items)}")
    # Unique IDs namespaced by source so they never collide with existing ids.
    ids = [f"{it['meta']['source']}::{i}" for i, it in enumerate(items)]
    _batch_add(collection, items, ids)
    write_reference_index(collection)
    print(f"\n{'='*50}\n🎉 Done (incremental)! +{len(items)} chunks, total now {collection.count()}"
          f"\n   Restart the backend so it serves the new content.\n{'='*50}\n")


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="NTPC indexer — incremental by default (adds only new files); --rebuild for a full rebuild.")
    ap.add_argument("--rebuild", action="store_true",
                    help="Delete and recreate the collection from ALL sources (pages + PDFs + downloads).")
    args = ap.parse_args()

    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    if args.rebuild:
        print("=== FULL REBUILD ===")
        full_rebuild(client)
    else:
        print("=== INCREMENTAL INDEX (add new files only) ===")
        incremental(client)


if __name__ == "__main__":
    main()