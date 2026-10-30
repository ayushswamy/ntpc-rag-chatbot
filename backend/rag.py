# backend/rag.py
import os
import sys

# UTF-8 stdout/stderr so the status prints (checkmark / cross emoji) never crash
# on the Windows cp1252 console or when output is redirected to a log file.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import asyncio
import chromadb
import ollama
from embedder import embed_text

# ── scope configuration + structured logging (Phase 1) ─────────────────────
# Imported defensively: if scope_config is unavailable (e.g. mid-deploy), the
# backend still serves with scope filtering DISABLED (ALL_SOURCES behaviour),
# preserving full backward compatibility instead of crashing.
try:
    from scope_config import (
        YEAR_TO_FILE, LATEST_YEAR, ALL_SOURCES, DEFAULT_SCOPE,
        normalize_scope, scope_to_where,
    )
    _SCOPE_CONFIG_OK = True
except Exception as _e:  # pragma: no cover - defensive fallback
    print(f"⚠️  scope_config unavailable ({_e}); scope filtering disabled.")
    _SCOPE_CONFIG_OK = False
    ALL_SOURCES = "ALL_SOURCES"
    DEFAULT_SCOPE = ALL_SOURCES
    LATEST_YEAR = "2024-25"
    YEAR_TO_FILE = {
        "2017-18": "2017-18.pdf",
        "2018-19": "annual-report-2018-19.pdf",
        "2019-20": "44-final-NTPC-AR-30082020.pdf",
        "2020-21": "NTPC_Annual Report_20-21.pdf",
        "2021-22": "Annual-Report-2021-22.pdf",
        "2022-23": "47th Annual Report of NTPC 2022-2023 New.pdf",
        "2023-24": "Annual Report 2023-24.pdf",
        "2024-25": "Annual Report 2024-25_1.pdf",
    }
    def normalize_scope(scope): return ALL_SOURCES
    def scope_to_where(scope): return None

try:
    from structured_log import slog
except Exception:  # pragma: no cover
    def slog(tag, **fields):  # no-op fallback
        pass

# ── Phase 2: hybrid retrieval + cross-encoder reranking ────────────────────
# Imported defensively: if either module is missing the backend still answers.
try:
    from hybrid_retriever import hybrid_candidates
except Exception as _e:  # pragma: no cover
    print(f"⚠️  hybrid_retriever unavailable ({_e}).")
    def hybrid_candidates(collection, embed_fn, sub_queries, question, scope,
                          year_file=None, strict_year=False, pool_size=30,
                          distance_cutoff=2.0):
        return []

try:
    from reranker import rerank
except Exception as _e:  # pragma: no cover
    print(f"⚠️  reranker unavailable ({_e}); using retrieval order.")
    def rerank(question, candidates, top_n=5):
        return candidates[:top_n]

# Reference-Aware Retrieval: exact document-reference lookup before vector search.
try:
    from reference_parser import parse_reference, reference_key, EXACT_REFERENCE
    _REF_OK = True
except Exception as _e:  # pragma: no cover
    print(f"⚠️  reference_parser unavailable ({_e}); exact-reference lookup disabled.")
    _REF_OK = False
    EXACT_REFERENCE = "EXACT_REFERENCE"
    def parse_reference(text, strict=False): return None
    def reference_key(type_key, number_key): return ""

# ── Phase 3: knowledge-graph enrichment (used AFTER rerank, BEFORE the LLM) ──
try:
    from knowledge_graph import graph_query as _kg
except Exception as _e:  # pragma: no cover
    print(f"⚠️  knowledge_graph unavailable ({_e}); enrichment disabled.")
    _kg = None

def graph_enrich(question, metadatas):
    """Graph enrichment; never raises (purely additive)."""
    if _kg is None:
        return {}
    try:
        return _kg.enrich(question, metadatas) or {}
    except Exception as e:
        slog("GRAPH", error=str(e))
        return {}

# Dedicated Ollama client with trust_env=False, so the loopback call to Ollama
# (127.0.0.1:11434) ignores ALL HTTP(S)_PROXY / system-proxy settings and is
# never routed through the NTPC web proxy (which blocks local addresses).
_OLLAMA = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"), trust_env=False)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHROMA_PATH     = os.path.join(os.path.dirname(__file__), "chroma")
COLLECTION_NAME = "ntpc_content"
MODEL           = "llama3.2"
RERANK_POOL     = 30           # candidates pulled before reranking
RERANK_TOP_N    = 5            # chunks kept after reranking -> fed to the LLM
DISTANCE_CUTOFF = 2.0
MAX_CONTEXT_CHARS = 12000      # context budget that fits num_ctx below

# NOTE: YEAR_TO_FILE / LATEST_YEAR come from scope_config (single source of truth).

QUERY_EXPANSIONS: dict[str, str] = {
    "brighter plan":    "Brighter Plan 2032 renewable energy strategy decarbonization net zero",
    "vision":           "NTPC vision mission strategy long term plan",
    "strategy":         "NTPC strategy plan target goals objectives",
    "green hydrogen":   "green hydrogen projects pilot NTPC electrolyzer",
    "renewable":        "renewable energy capacity target solar wind 2032 GW",
    "solar":            "solar power capacity MW GW projects commissioned",
    "wind":             "wind energy capacity projects commissioned MW",
    "hydro":            "hydro power hydroelectric capacity stations",
    "nuclear":          "nuclear energy power NTPC atomic",
    "coal":             "coal based thermal power stations capacity generation",
    "dividend":         "dividend per share interim final equity shareholder payout",
    "total income":     "total income revenue from operations turnover crore",
    "profit":           "profit after tax PAT net profit crore",
    "revenue":          "revenue total income operations crore financial",
    "debt":             "debt borrowings long term short term crore ratio",
    "credit rating":    "credit rating CRISIL ICRA AAA debt rating",
    "capex":            "capital expenditure capex investment crore",
    "pat":              "profit after tax PAT net profit crore earnings",
    "ebitda":           "EBITDA operating profit earnings before interest tax depreciation",
    "plf":              "Plant Load Factor PLF coal stations national average generation",
    "capacity":         "installed capacity commercial MW GW stations total",
    "generation":       "gross generation units BU billion units sent out",
    "employees":        "number of employees workforce manpower human resource",
    "stations":         "power stations plants NTPC locations units",
    "csr":              "CSR corporate social responsibility community development education health",
    "esg":              "ESG environment social governance sustainability reporting",
    "carbon":           "carbon emission CO2 greenhouse gas climate change",
    "water":            "water consumption stewardship management conservation",
    "environment":      "environment sustainability green emission pollution",
    "subsidiaries":     "subsidiaries joint ventures NTPC group companies list",
    "board":            "board of directors chairman CMD management executive",
    "awards":           "awards recognition achievements honours certifications",
    "related party":    "related party transactions subsidiaries associates",
    "auditor":          "statutory auditor CA chartered accountant audit firm",
    "director":         "board of directors independent executive non-executive members",
    "chairman":         "chairman CMD MD CEO management board NTPC",
    "shareholder":      "shareholders equity shares AGM annual general meeting",
}

SYSTEM_PROMPT = """You are a strict document retrieval assistant for NTPC Limited.

ABSOLUTE RULES:
1. Use ONLY the context provided — ZERO outside knowledge
2. If not in context → say EXACTLY: "This information is not available in the provided NTPC documents."
3. NEVER say 'However', 'based on general knowledge', 'I am unable to verify' — FORBIDDEN
4. NEVER guess — only state what is written in context
5. Put source citations at the END of the answer only — never at the beginning or inline before the content
6. State numbers directly — never say 'not explicitly stated'
7. Minimum 3-4 sentences with all numbers"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHROMADB INIT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def init_collection():
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        col    = client.get_collection(name=COLLECTION_NAME)
        print(f"✅ ChromaDB loaded. Documents: {col.count()}")
        return col
    except Exception as e:
        print(f"❌ ChromaDB error: {e}")
        return None

collection = init_collection()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_years(question: str) -> list[str]:
    return [y for y in YEAR_TO_FILE if y in question]

def is_current_question(question: str) -> bool:
    return any(kw in question.lower() for kw in
               ["current", "latest", "now", "today", "recent", "abhi", "present"])

def expand_query(question: str) -> str:
    q_lower    = question.lower()
    expansions = [exp for key, exp in QUERY_EXPANSIONS.items() if key in q_lower]
    if expansions:
        return f"{question} {' '.join(expansions)}"
    return question

def generate_sub_queries(question: str) -> list[str]:
    q     = question.strip()
    q_exp = expand_query(q)
    stopwords = {"what","is","are","the","of","in","for","a","an","and","or",
                 "was","were","has","have","how","many","much","ntpc","about",
                 "tell","me","give","from","to","its","their","which","who"}
    keywords = " ".join(
        w for w in q.lower().split()
        if w not in stopwords and len(w) > 3
    )
    return list(dict.fromkeys([q, q_exp, keywords]))


async def fetch_multi_year_parallel(question, years, scope, sub_queries):
    """Multi-year comparison: one scoped hybrid pool per year, merged + de-duped."""
    loop = asyncio.get_event_loop()

    def _one(yr):
        return hybrid_candidates(
            collection, embed_text, sub_queries, question, scope,
            year_file=YEAR_TO_FILE.get(yr), strict_year=True,
            pool_size=RERANK_POOL, distance_cutoff=DISTANCE_CUTOFF,
        )

    results = await asyncio.gather(*[loop.run_in_executor(None, _one, yr) for yr in years])

    combined, seen, final = [], set(), []
    for pool in results:
        combined += pool
    for chunk, meta, dist in sorted(combined, key=lambda x: x[2]):
        key = (meta.get("source", ""), chunk[:120])
        if key not in seen:
            seen.add(key)
            final.append((chunk, meta, dist))
    return final


def build_context(chunks: list[str], metadatas: list[dict]) -> str:
    parts, total = [], 0
    for i, (chunk, meta) in enumerate(zip(chunks, metadatas)):
        source = meta.get("source", meta.get("title", "Unknown"))
        page   = meta.get("page", "")

        # Website URL vs PDF page number shown differently.
        if source.startswith("http"):
            label = f"{meta.get('title','Website')} | {meta.get('section','')} | {source}"
        else:
            label = f"{source} | Page {page}" if page else source

        entry  = f"[Source {i+1}: {label}]\n{chunk}"
        if total + len(entry) > MAX_CONTEXT_CHARS:
            break
        parts.append(entry)
        total += len(entry)
    return "\n\n---\n\n".join(parts)


def build_sources(metadatas: list[dict], distances: list[float]) -> list[dict]:
    sources, seen = [], set()
    for meta, dist in sorted(zip(metadatas, distances), key=lambda x: x[1]):
        if dist >= DISTANCE_CUTOFF:
            continue
        source = meta.get("source", "Unknown")
        if source not in seen:
            seen.add(source)

            if source.startswith("http"):
                sources.append({
                    "title":   meta.get("title", "NTPC Website"),
                    "url":     source,
                    "section": meta.get("section", "")
                })
            else:
                sources.append({
                    "title":   source.replace(".pdf","").replace("-"," ").replace("_"," "),
                    "url":     "",
                    "section": f"Page {meta.get('page','N/A')}"
                })
        if len(sources) == 4:
            break
    return sources


def parse_llm_response(raw: str) -> tuple[str, list[str]]:
    followups, answer_lines = [], []
    for line in raw.split("\n"):
        if line.strip().startswith("FOLLOWUP:"):
            followups.append(line.replace("FOLLOWUP:", "").strip())
        else:
            answer_lines.append(line)
    return "\n".join(answer_lines).strip(), followups


DEFAULT_FOLLOWUPS = [
    "What is NTPC's renewable energy capacity?",
    "What are NTPC's financial highlights for the latest year?",
    "How has NTPC's installed capacity grown over the years?",
]

# Phase 2: scope-aware seed suggestions (Phase 3 graph will make these dynamic).
_SCOPE_SUGGESTIONS = {
    "CIRCULARS":           ["Show related circulars", "Who issued this circular?",
                            "Which circular does it supersede?"],
    "DOP":                 ["Show the approval hierarchy", "What is the approval limit?",
                            "Show related delegation-of-powers clauses"],
    "ANNUAL_REPORT":       ["Compare with the previous year", "What was the profit after tax?",
                            "How has installed capacity grown?"],
    "SAFETY":              ["Show related safety guidelines", "What standards apply?",
                            "Any recent safety circulars?"],
    "CSR":                 ["What is the CSR budget allocation?", "Show related CSR initiatives",
                            "What are the CSR focus areas?"],
    "OS_TC":               ["Show related technical guidelines", "Which OS/TC standards apply?",
                            "Explain the operational procedure"],
    "EMPLOYEE_EXPERIENCE": ["What are the eligibility criteria?", "Show related employee policies",
                            "What benefits apply?"],
    "NTPC_PEDIA":          ["Tell me more on this topic", "Show related topics",
                            "Give the background"],
}


def suggest_questions(question, scope, llm_followups, graph_suggestions=None):
    """
    Suggested questions: prefer GRAPH-driven follow-ups (Phase 3), then the LLM's
    own follow-ups, then scope-aware seeds — de-duplicated, never echoing the question.
    """
    out = (list(graph_suggestions or []) + list(llm_followups or [])
           + _SCOPE_SUGGESTIONS.get(scope, []))
    seen, final = set(), []
    ql = question.strip().lower()
    for q in out:
        k = q.strip().lower()
        if k and k != ql and k not in seen:
            seen.add(k)
            final.append(q.strip())
    return final[:3] if final else DEFAULT_FOLLOWUPS


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REFERENCE-AWARE RETRIEVAL (exact document-reference lookup)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def exact_reference_lookup(ref: dict) -> list:
    """
    Step 3: exact metadata lookup by reference_key, run BEFORE any vector search.
    Returns [(text, meta, -1.0)] for the chunks of the matching document(s); the
    -1.0 distance marks them as exact so they pin ahead of any semantic result.
    Scope is intentionally NOT applied — an exact reference is unambiguous and must
    resolve to its document wherever it lives.
    """
    if collection is None:
        return []
    key = reference_key(ref["type_key"], ref["number_key"])
    if not key:
        return []
    try:
        res = collection.get(where={"reference_key": key},
                             include=["documents", "metadatas"])
    except Exception as e:
        slog("EXACT", error=str(e))
        return []
    docs  = res.get("documents") or []
    metas = res.get("metadatas") or []
    return [(d, m, -1.0) for d, m in zip(docs, metas)]


def reference_collision_filter(final: list, ref: dict) -> list:
    """
    Steps 7-8 (fallback path only): when a reference was detected but had NO exact
    match, reject chunks whose reference entity CONFLICTS with the query
    (non-empty reference_key != query key), pin any that match, and keep neutral
    (unreferenced/topic) chunks. This guarantees a mixed set of different reference
    entities is never sent to the LLM.
    """
    key = reference_key(ref["type_key"], ref["number_key"])
    kept, dropped = [], []
    for c in final:
        rk = c[1].get("reference_key", "")
        if rk and rk != key:
            dropped.append(c)
        else:
            kept.append(c)
    if dropped:
        slog("COLLISION", query_key=key,
             dropped=[(c[1].get("source", ""), c[1].get("reference_key", "")) for c in dropped])
    kept.sort(key=lambda c: 0 if c[1].get("reference_key", "") == key else 1)
    return kept or final


async def _generate_answer(question, chunks, metadatas, distances, scope, instruction) -> dict:
    """Shared tail: graph-enrich → build context → LLM → parse → sources/followups.
    Used by BOTH the exact-reference path and the hybrid/semantic path."""
    graph = graph_enrich(question, metadatas)
    slog("GRAPH", topics=graph.get("related_topics"), circulars=graph.get("related_circulars"))

    context = build_context(chunks, metadatas)
    graph_block = ("\n\n" + graph["context_text"]) if graph.get("context_text") else ""

    user_message = f"""Context from NTPC documents (annual reports, circulars, policies, safety, CSR, HR/EDOP, and website):

{context}{graph_block}

Question: {question}
Instruction: {instruction}

Rules:
- Detailed and complete answer with exact numbers
- For comparisons: show ALL years side by side
- ONLY use information from the context above
- Minimum 3-4 sentences
- Write the full answer FIRST. Then, at the END, add one line starting with "Sources:" listing the report name/page OR website URL you used. NEVER place sources at the start or middle of the answer.

After the Sources line, add exactly 3 follow-up questions, each on a new line prefixed with 'FOLLOWUP:'"""

    try:
        response = _OLLAMA.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            keep_alive="30m",   # keep model warm in RAM → avoid cold-start reloads
            options={
                "temperature": 0.1,
                "num_predict": 600,
                "num_ctx":     8192,
            }
        )
        raw = response["message"]["content"]
    except Exception as e:
        return {
            "answer":              f"LLM error: {str(e)}. Check if Ollama is running.",
            "sources":             [],
            "follow_up_questions": DEFAULT_FOLLOWUPS,
        }

    answer, llm_followups = parse_llm_response(raw)
    sources               = build_sources(metadatas, distances)
    followups             = suggest_questions(question, scope, llm_followups,
                                              graph.get("suggested_questions"))
    return {
        "answer":              answer,
        "sources":             sources,
        "follow_up_questions": followups,
        "related_topics":      graph.get("related_topics", []),
        "related_documents":   graph.get("related_documents", []),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN RAG FUNCTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def get_rag_answer(question: str, scope=None) -> dict:
    scope = normalize_scope(scope)
    slog("QUERY", q=question, scope=scope)
    slog("SCOPE", where=scope_to_where(scope))

    if collection is None or collection.count() == 0:
        return {
            "answer":              "Knowledge base not ready. Please run indexer.py first.",
            "sources":             [],
            "follow_up_questions": DEFAULT_FOLLOWUPS,
        }

    # ── Reference-Aware Retrieval: EXACT lookup BEFORE vector search (Steps 1-5) ──
    ref = parse_reference(question) if _REF_OK else None
    if ref:
        exact = exact_reference_lookup(ref)
        slog("REFERENCE", intent=EXACT_REFERENCE, type=ref["reference_type"],
             number=ref["reference_number"],
             key=reference_key(ref["type_key"], ref["number_key"]), matched=len(exact))
        if exact:
            # Rerank WITHIN the matched document(s) to surface the chunks most
            # relevant to the question, then answer — skipping semantic retrieval.
            top = rerank(question, exact, top_n=RERANK_TOP_N) or exact[:RERANK_TOP_N]
            instruction = (
                f'This is an EXACT reference lookup for {ref["reference_type"]} '
                f'{ref["reference_number"]}. Answer ONLY from this document and state '
                f'its subject and key contents. Do NOT bring in any other '
                f'circular/instruction/order.')
            result = await _generate_answer(
                question, [c[0] for c in top], [c[1] for c in top],
                [c[2] for c in top], scope, instruction)
            result["mode"] = "exact_reference"
            result["reference"] = {"type": ref["reference_type"],
                                   "number": ref["reference_number"]}
            return result
        # No exact match → fall through to hybrid (Step 5), keeping `ref` so the
        # collision filter can still reject conflicting reference entities.

    found_years   = detect_years(question)
    is_comparison = len(found_years) > 1
    year_hint     = found_years[0] if len(found_years) == 1 else None
    sub_queries   = generate_sub_queries(question)

    async def _pool(scp):
        if is_comparison:
            return await fetch_multi_year_parallel(question, found_years, scp, sub_queries)
        return hybrid_candidates(
            collection, embed_text, sub_queries, question, scp,
            year_file=YEAR_TO_FILE.get(year_hint) if year_hint else None,
            pool_size=RERANK_POOL, distance_cutoff=DISTANCE_CUTOFF,
        )

    candidates = await _pool(scope)

    # Decision #7 (Phase 1): scope filtering must NEVER prevent retrieval — if a
    # real scope produced nothing, fall back to ALL_SOURCES so the user still gets
    # an answer rather than an empty one.
    if not candidates and scope != ALL_SOURCES:
        slog("SCOPE", fallback="ALL_SOURCES", reason="zero results in scope")
        candidates = await _pool(ALL_SOURCES)

    if not candidates:
        return {
            "answer":              "This information is not available in the provided NTPC documents.",
            "sources":             [],
            "follow_up_questions": DEFAULT_FOLLOWUPS,
        }

    # Rerank to the best RERANK_TOP_N — but PIN exact circular-number matches
    # (distance == -1.0 from the keyword pass) so the Phase-1 CHRC lookup guarantee
    # survives reranking.
    pinned = [c for c in candidates if c[2] == -1.0]
    rest   = [c for c in candidates if c[2] != -1.0]
    reranked_rest = rerank(question, rest, top_n=max(RERANK_TOP_N - len(pinned), 1))
    final = (pinned + reranked_rest)[:max(RERANK_TOP_N, len(pinned))]

    # Reference-Aware collision filtering (Steps 7-8): a reference was detected but
    # had no exact match — reject chunks of a DIFFERENT reference entity so the LLM
    # never sees mixed references.
    if ref:
        final = reference_collision_filter(final, ref)

    chunks     = [c[0] for c in final]
    metadatas  = [c[1] for c in final]
    distances  = [c[2] for c in final]

    if is_comparison:
        instruction = f"Compare data across years: {', '.join(found_years)} — show EACH year separately with numbers."
    elif year_hint:
        instruction = (f"Prefer figures from the {year_hint} annual report, but ALSO use any "
                       f"other relevant NTPC documents present in the context.")
    else:
        instruction = "Use the most recent year available in context."

    return await _generate_answer(question, chunks, metadatas, distances, scope, instruction)


if __name__ == "__main__":
    # Smoke test: exact reference lookup.
    result = asyncio.run(get_rag_answer("Circular No.301(P&S)"))
    print(result)
