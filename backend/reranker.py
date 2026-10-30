# backend/reranker.py
"""
Cross-encoder reranker (Phase 2).

Re-scores retrieved candidates against the query with
`cross-encoder/ms-marco-MiniLM-L-6-v2` and returns the best `top_n`.

ROBUSTNESS (critical for the offline production server):
  * The model is loaded LAZILY and only once (singleton).
  * If it can't load — e.g. HF_HUB_OFFLINE=1 and the model isn't cached yet, or
    sentence-transformers is missing — we DO NOT raise. We fall back to the
    original vector-distance order. So the backend keeps answering even before
    the reranker model has been staged on the server.
  * Set RERANK_ENABLED=0 to disable reranking entirely.

Candidates are (text, meta, distance) tuples; the return preserves that shape
(re-ordered) so downstream build_context / build_sources are unchanged. The
original vector `distance` is kept (NOT replaced by the cross-encoder score),
so the DISTANCE_CUTOFF filter in build_sources still behaves correctly.
"""

import os
from structured_log import slog

_MODEL_NAME = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
_RERANK_ENABLED = os.getenv("RERANK_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")

_model = None
_load_failed = False


def _get_model():
    """Lazy singleton load; on any failure, disable reranking gracefully."""
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(_MODEL_NAME)
        print(f"[ok] Reranker loaded: {_MODEL_NAME}")
    except Exception as e:
        _load_failed = True
        print(f"[warn] Reranker unavailable ({e}); falling back to vector-distance order.")
    return _model


def rerank(question, candidates, top_n=5):
    """
    candidates: list of (text, meta, distance). Returns the best `top_n` of the
    SAME tuple shape, re-ordered by cross-encoder relevance. Graceful fallback to
    vector-distance order if the model is disabled/unavailable.
    """
    if not candidates:
        return []
    if not _RERANK_ENABLED:
        return candidates[:top_n]
    model = _get_model()
    if model is None:
        slog("RERANK", status="fallback", kept=min(top_n, len(candidates)))
        return candidates[:top_n]
    try:
        scores = model.predict([(question, c[0]) for c in candidates])
        order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
        top = [candidates[i] for i in order[:top_n]]
        slog("RERANK", scored=len(candidates), kept=len(top),
             top=[(candidates[i][1].get("source", ""), round(float(scores[i]), 3))
                  for i in order[:top_n]])
        return top
    except Exception as e:
        slog("RERANK", error=str(e))
        return candidates[:top_n]
