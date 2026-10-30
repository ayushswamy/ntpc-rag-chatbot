# backend/structured_log.py
"""
Tiny structured logger for the retrieval pipeline. One tagged line per stage:

    [QUERY]    q='CHRC 992' scope='CIRCULARS'
    [SCOPE]    where={'document_type': 'circular'}
    [KEYWORD]  scope='CIRCULARS' injected=1
    [VECTOR]   scope='CIRCULARS' candidates=42
    [METADATA] kept=15 top=[('...CHRC992.pdf', -1.0), ...]

Gated by the RAG_DEBUG env var (1/true/yes/on) so production logs stay clean.
`format_line` is pure (unit-testable); `slog` is the side-effecting wrapper.
"""

import os


def _enabled() -> bool:
    return os.getenv("RAG_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def format_line(tag: str, fields: dict) -> str:
    """Pure formatter -> '[TAG] k=v k=v'. Used by tests and by slog()."""
    body = " ".join(f"{k}={v!r}" for k, v in fields.items())
    return (f"[{tag}] {body}").rstrip()


def slog(tag: str, **fields) -> None:
    """Print a structured line iff RAG_DEBUG is enabled."""
    if _enabled():
        print(format_line(tag, fields), flush=True)
