# backend/tests/test_reference_parser.py
"""
Regression tests for the reference parser + intent classifier (Steps 1-2, 10).

Runnable two ways (no hard pytest dependency):
    backend\\venv\\Scripts\\python.exe backend\\tests\\test_reference_parser.py
    pytest backend/tests/test_reference_parser.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reference_parser import (
    parse_reference, classify_reference_intent,
    EXACT_REFERENCE, TOPIC_SEARCH, SEMANTIC_SEARCH, YEAR_SEARCH, DOCUMENT_SEARCH,
)

# (query, expected_type, expected_number)
PARSE_CASES = [
    ("Circular No.301(P&S)",        "Circular",        "301(P&S)"),
    ("CIRCULAR NO. 301(P&S)",       "Circular",        "301(P&S)"),
    ("Instruction 301(P&S)",        "Instruction",     "301(P&S)"),
    ("System Circular No.182/2019", "System Circular", "182/2019"),
    ("System Circular 182/2019",    "System Circular", "182/2019"),
    ("Office Order 52",             "Office Order",     "52"),
    ("Ref No.01/CC/PS-957",         "Ref",             "01/CC/PS-957"),
    ("Circular 125",                "Circular",        "125"),
    ("Instruction 401",             "Instruction",     "401"),
    ("Memo 12/2022",                "Memo",            "12/2022"),
    ("CHRC 992/2026",               "Circular",        "992/2026"),
    # Real NTPC header formatting (from actual corpus):
    ("CIRCULAR NO.: 269 (P & S)",   "Circular",        "269(P&S)"),   # NO.: connector + internal spaces
    ("Circular No. 301(P&S)  Sub.:", "Circular",       "301(P&S)"),   # trailing text not swallowed
]

# Header with BOTH a routing Ref and the real identity — identity must win.
IDENTITY_PRIORITY = [
    ("Ref. No. 01/CC/PS-957  CIRCULAR NO. 301(P&S)", "Circular", "301(P&S)"),
    ("CIRCULAR NO.: 269 (P & S)  REF: 01/CC/PS-957", "Circular", "269(P&S)"),
]

# Queries that must NOT parse as a structured reference.
NON_REF = ["Physical Verification", "GR/IR clearing", "Late bid acceptance",
           "circular guidelines", "2023-24", "what is NTPC revenue"]

INTENT_CASES = [
    ("Circular No.301(P&S)",        EXACT_REFERENCE),
    ("System Circular 182/2019",    EXACT_REFERENCE),
    ("Office Order 52",             EXACT_REFERENCE),
    ("Physical Verification",       TOPIC_SEARCH),
    ("Late bid acceptance",         TOPIC_SEARCH),
    ("2023-24",                     YEAR_SEARCH),
]


def test_parse_positive():
    for q, typ, num in PARSE_CASES:
        r = parse_reference(q)
        assert r is not None, f"{q!r} should parse"
        assert r["reference_type"] == typ, f"{q!r} type: {r['reference_type']} != {typ}"
        assert r["reference_number"] == num, f"{q!r} number: {r['reference_number']} != {num}"


def test_parse_negative():
    for q in NON_REF:
        assert parse_reference(q) is None, f"{q!r} must NOT parse as a reference"


def test_identity_priority():
    for text, typ, num in IDENTITY_PRIORITY:
        r = parse_reference(text)
        assert r is not None, f"{text!r} should parse"
        assert r["reference_type"] == typ, f"{text!r}: {r['reference_type']} != {typ}"
        assert r["reference_number"] == num, f"{text!r}: {r['reference_number']} != {num}"


def test_type_vs_number_distinction():
    # The collision the spec is about: same number, different type.
    a = parse_reference("Circular No.301(P&S)")
    b = parse_reference("Instruction 301(P&S)")
    assert a["number_key"] == b["number_key"]      # same number
    assert a["type_key"] != b["type_key"]          # different entity


def test_intent():
    for q, intent in INTENT_CASES:
        got = classify_reference_intent(q)
        assert got == intent, f"{q!r} intent: {got} != {intent}"


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
