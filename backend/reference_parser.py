# backend/reference_parser.py
"""
Reference-aware query analysis (Reference-Aware Retrieval, Steps 1-2).

Pure, dependency-free functions shared by the intent router and the retrieval
stage, so all "is this an exact document reference?" logic lives in ONE tested
place instead of scattered regexes.

Public API:
    parse_reference(text)            -> {"reference_type","reference_number",
                                         "type_key","number_key","raw"} | None
    classify_reference_intent(text)  -> one of the intent constants below
    canonical_type(text)             -> canonical reference-type label | ""
    normalize_number(text)           -> canonical number key for exact matching

Design notes
------------
* References in the NTPC corpus live in document CONTENT (e.g. "Circular No.
  301(P&S)"), not filenames. The number can be plain (52), department-qualified
  (301(P&S)), year-qualified (182/2019, 12/2022) or a compound ref (01/CC/PS-957).
* Reference TYPES are matched longest-first so "System Circular" wins over
  "Circular", "Office Order" is not split, etc.
* Everything is case-insensitive; matching keys are upper-cased and space-stripped
  so "Circular No. 301 (P&S)" and "circular301(p&s)" collapse to one key.
"""

import re

# ── Intent constants (Step 2) ──────────────────────────────────────────────
EXACT_REFERENCE = "EXACT_REFERENCE"
YEAR_SEARCH     = "YEAR_SEARCH"
DOCUMENT_SEARCH = "DOCUMENT_SEARCH"
TOPIC_SEARCH    = "TOPIC_SEARCH"
SEMANTIC_SEARCH = "SEMANTIC_SEARCH"

# ── Reference-type vocabulary ──────────────────────────────────────────────
# Canonical label -> aliases that map onto it. Longer / more specific types MUST
# come before their substrings (System Circular before Circular) so the alternation
# below matches the most specific type present.
_REF_TYPE_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("System Circular", ("system circular", "sys circular", "system cir")),
    ("Office Order",     ("office order", "office memo", "office memorandum")),
    ("Circular",         ("circular", "cir", "chrc", "cciom")),
    ("Instruction",      ("instruction", "instr")),
    ("Memo",             ("memo", "memorandum", "office memorandum")),
    ("Notification",     ("notification", "notice")),
    ("Ref",              ("ref no", "ref", "reference no", "reference")),
]

# Flat alias -> canonical, longest alias first (so "office memorandum" beats "memo").
_ALIAS_TO_CANON: list[tuple[str, str]] = sorted(
    ((alias, canon) for canon, aliases in _REF_TYPE_ALIASES for alias in aliases),
    key=lambda kv: -len(kv[0]),
)

# A reference NUMBER, tolerant of real NTPC formatting:
#   digits, then optionally a parenthetical (with internal spaces: "269 (P & S)"),
#   then optional compound/year segments joined by / or - where each following
#   segment is UPPER-case letters or digits (CC, PS, 957, 2019) — so a trailing
#   lower-case word like "125 - reg" is NOT swallowed into the number.
# Matches: 52, 125, 401, 301(P&S), 269 (P & S), 182/2019, 12/2022, 01/CC/PS-957.
_NUM = r"\d+(?:\s*\([^)]{1,14}\))?(?:\s*[/-]\s*[0-9A-Z&]+)*"

# type alternation, longest alias first so multi-word types are not split.
_TYPE_ALT = "|".join(
    re.escape(alias) for alias, _ in sorted(_ALIAS_TO_CANON, key=lambda kv: -len(kv[0]))
)
# Connector between the type and number, tolerant of "NO.", "No.:", "No :", ":", "-".
_CONN = r"\s*(?:no\.?|number|#)?\s*[:.\-]?\s*"
_REF_RE = re.compile(
    rf"(?P<type>{_TYPE_ALT}){_CONN}(?P<num>{_NUM})",
    re.IGNORECASE,
)
# STRICT connector REQUIRES an explicit "No"/"Number"/"#"/":" — i.e. the document
# is *declaring* its identity ("CIRCULAR NO. 301(P&S)"), not merely mentioning a
# number in passing ("as per circular 952"). Used only for document-level tagging.
_STRICT_CONN = r"\s*(?:no\.?|number|#|:)\s*[:.\-]?\s*"
_REF_RE_STRICT = re.compile(
    rf"(?P<type>{_TYPE_ALT}){_STRICT_CONN}(?P<num>{_NUM})",
    re.IGNORECASE,
)

# Identity types name a document; "Ref" is a routing/file number that often appears
# ALONGSIDE the real identity in a header, so it must never win over an identity type.
_IDENTITY_TYPES = {"System Circular", "Circular", "Instruction",
                   "Office Order", "Memo", "Notification"}

# A bare fiscal/calendar year, used for YEAR_SEARCH classification.
_YEAR_RE = re.compile(r"\b(19|20)\d{2}(?:\s*[-/]\s*\d{2,4})?\b")


def canonical_type(text: str) -> str:
    """Map any type alias (case-insensitive) to its canonical label, or ''."""
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    for alias, canon in _ALIAS_TO_CANON:
        if t == alias:
            return canon
    # Substring fallback (e.g. the matched 'system circular no' chunk).
    for alias, canon in _ALIAS_TO_CANON:
        if alias in t:
            return canon
    return ""


def normalize_number(text: str) -> str:
    """Canonical number key: upper-case, spaces removed. '301 (P&S)' -> '301(P&S)'."""
    return re.sub(r"\s+", "", (text or "").upper())


def _iter_refs(text: str, rx=_REF_RE):
    """Yield every structured reference found in `text`, left to right."""
    for m in rx.finditer(text or ""):
        canon = canonical_type(m.group("type"))
        if not canon:
            continue
        # Space-normalize the number so "269 (P & S)" == "269(P&S)".
        number = re.sub(r"\s+", "", m.group("num")).strip().rstrip(".")
        if not re.search(r"\d", number):        # a type word with no real number
            continue
        yield {
            "reference_type":   canon,
            "reference_number": number,
            "type_key":         canon.upper().replace(" ", ""),
            "number_key":       normalize_number(number),
            "raw":              m.group(0).strip(),
            "pos":              m.start(),
        }


def parse_reference(text: str, strict: bool = False) -> dict | None:
    """
    Extract the best structured document reference from `text`.

    Returns {reference_type, reference_number, type_key, number_key, raw} or None.
    When several references appear (e.g. a header with both "Ref. No. …" and
    "CIRCULAR NO. …"), an IDENTITY type wins over a routing "Ref"; otherwise the
    left-most match is used. `strict=True` requires an explicit "No/:" connector
    (identity declaration) — used for document-level tagging to avoid mentions.
    """
    refs = list(_iter_refs(text, _REF_RE_STRICT if strict else _REF_RE))
    if not refs:
        return None
    identity = [r for r in refs if r["reference_type"] in _IDENTITY_TYPES]
    return (identity or refs)[0]


def classify_reference_intent(text: str) -> str:
    """
    Classify a (already-known-to-be-a-document) query into a retrieval intent.

    EXACT_REFERENCE  - contains a structured reference (Circular No.301(P&S), ...)
    YEAR_SEARCH      - dominated by a bare year / fiscal year and little else
    DOCUMENT_SEARCH  - names a document type/title but no reference number
    TOPIC_SEARCH     - short keyword-y phrase
    SEMANTIC_SEARCH  - everything else (default; same retrieval path as TOPIC)
    """
    q = (text or "").strip()
    if not q:
        return SEMANTIC_SEARCH

    if parse_reference(q) is not None:
        return EXACT_REFERENCE

    words = q.split()

    # A query that is essentially just a year.
    if _YEAR_RE.search(q) and len(words) <= 3:
        return YEAR_SEARCH

    # Names a document kind but no number → browse that document class.
    low = q.lower()
    if any(alias in low for alias, _ in _ALIAS_TO_CANON) and len(words) <= 6:
        return DOCUMENT_SEARCH

    # Short phrase → topic; longer natural-language question → semantic.
    return TOPIC_SEARCH if len(words) <= 5 else SEMANTIC_SEARCH


# Convenience: does this query want an exact reference lookup?
def is_exact_reference(text: str) -> bool:
    return classify_reference_intent(text) == EXACT_REFERENCE


# ── Ingest-side helpers (Step 6): derive a chunk/document's OWN reference ────
# The "heading zone": a reference within the first _HEAD_CHARS of a chunk identifies
# that chunk/section. A reference appearing only DEEPER in the text is a MENTION,
# not an identity, and is intentionally ignored so body mentions don't cause false
# exact matches (the core bug this pipeline fixes).
_HEAD_CHARS = 400


def reference_key(type_key: str, number_key: str) -> str:
    """Single combined key for exact metadata matching: 'CIRCULAR::301(P&S)'."""
    return f"{type_key}::{number_key}" if type_key and number_key else ""


def reference_meta(ref: dict | None) -> dict:
    """Chroma-safe metadata (all scalars, never None) for a parsed reference."""
    if not ref:
        return {"reference_type": "", "reference_number": "", "reference_key": ""}
    return {
        "reference_type":   ref["reference_type"],
        "reference_number": ref["reference_number"],
        "reference_key":    reference_key(ref["type_key"], ref["number_key"]),
    }


def extract_document_reference(title: str = "", header_text: str = "",
                               scan_chars: int = _HEAD_CHARS) -> dict | None:
    """
    A document's OWN identity reference. Prefer a STRICTLY-declared reference at the
    TOP of the first page ("CIRCULAR NO. 301(P&S)" — carries the full, year-qualified
    number), falling back to the title/filename (e.g. CHRC992, CCIOM1036) parsed
    leniently when the page declares none. Strict header matching stops a passing
    mention of another circular from mis-tagging the whole document.
    """
    r = parse_reference((header_text or "")[:scan_chars], strict=True)
    if r:
        return r
    return parse_reference(title or "", strict=False)


def extract_chunk_reference(chunk_text: str, head_chars: int = _HEAD_CHARS) -> dict | None:
    """
    Identity reference of a single chunk = a STRICTLY-declared reference in its
    HEADING zone ("System Circular No. 182/2019"). Used for compilation documents
    (e.g. an Instruction section inside Closing Guidelines) that have no single
    document-level reference. Strict matching stops bare body mentions ("circular 2")
    from tagging the chunk with a spurious reference.
    """
    r = parse_reference((chunk_text or "")[:head_chars], strict=True)
    # A bare single-digit number in body text (a list item / running header, e.g.
    # "Circular No. 2") is noise, never a document identity — reject at chunk level.
    if r and re.fullmatch(r"\d", r["number_key"]):
        return None
    return r


if __name__ == "__main__":  # quick manual check
    for s in ["Circular No.301(P&S)", "Instruction 301(P&S)",
              "System Circular No.182/2019", "Office Order 52",
              "Ref No.01/CC/PS-957", "Circular 125", "Memo 12/2022",
              "Physical Verification", "GR/IR clearing", "2023-24"]:
        print(f"{s!r:32} -> {classify_reference_intent(s):16} {parse_reference(s)}")
