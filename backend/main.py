# backend/main.py
import sys
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rag import get_rag_answer
from intent_router import classify_intent, get_response, DOCUMENT_QUESTION

# Scope config (defensive: if unavailable, fall back to ALL_SOURCES so /chat
# keeps working exactly as before — full backward compatibility).
try:
    from scope_config import normalize_scope, exposed_sources, DEFAULT_SCOPE
except Exception:  # pragma: no cover
    DEFAULT_SCOPE = "ALL_SOURCES"
    def normalize_scope(s): return DEFAULT_SCOPE
    def exposed_sources(): return ["ALL_SOURCES"]

# Phase 3 knowledge graph (defensive — /graph/status reports availability).
try:
    from knowledge_graph import graph_query as _kg
except Exception:  # pragma: no cover
    _kg = None

# UTF-8 console so logging a message/emoji never crashes on the Windows cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI()

# ✅ FIX 1: Allow any origin - internal website se bhi kaam karega
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # credentials ke saath "*" nahi chalta
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: Optional[str] = None
    query: Optional[str] = None
    message: Optional[str] = None
    scope: Optional[str] = None   # knowledge-source scope; missing/invalid -> ALL_SOURCES

@app.get("/")
def health_check():
    return {"status": "NTPC RAG Chatbot is running ✅"}

@app.get("/sources")
def list_sources():
    """
    Guided-conversation entry point: the sources a new chat can scope to.
    Flat string list for now; extensible later (labels/doc_count) without
    breaking existing clients.
    """
    return {
        "message": "Welcome to NTPC Organizational Memory. Select a knowledge source.",
        "available_sources": exposed_sources(),
    }

@app.get("/graph/status")
def graph_status():
    """Knowledge-graph health: loaded, version, node/edge counts, build timestamp."""
    if _kg is None:
        return {"loaded": False}
    try:
        return _kg.status()
    except Exception:
        return {"loaded": False}

@app.post("/chat")
async def chat(request: ChatRequest):
    user_question = (request.question or request.query or request.message or "").strip()
    scope = normalize_scope(request.scope)   # missing/invalid -> ALL_SOURCES

    # ── Intent router (regex/keyword, no LLM) — runs BEFORE retrieval ──
    intent = classify_intent(user_question)
    print(f"[chat] intent={intent} scope={scope} | msg={user_question!r}")
    if intent != DOCUMENT_QUESTION:
        # Small-talk / meta / unclear → canned reply, same JSON shape, no RAG.
        return {
            "answer": get_response(intent),
            "sources": [],
            "follow_up_questions": [],
            "scope": scope,
        }

    try:
        result = await get_rag_answer(user_question, scope=scope)
        if isinstance(result, dict):
            result.setdefault("scope", scope)   # echo the selected scope
            return result
        return {
            "answer": str(result),
            "sources": [],
            "follow_up_questions": [
                "Latest Annual Report",
                "Revenue highlights",
                "Capacity addition",
            ],
            "scope": scope,
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong.")