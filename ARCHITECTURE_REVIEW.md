# NTPC RAG Chatbot — Principal-Level Architecture Review & Interview Prep

> Brutally honest technical review based on a full read of the actual code
> (`backend/rag.py`, `main.py`, `intent_router.py`, `embedder.py`,
> `scripts/indexer.py`, `scripts/agents/*`). Written to prepare you to defend
> every decision against a Principal AI Engineer.

---

## 0. THE ONE-LINE TRUTH (read this first)

This is a **competent, pragmatic single-node RAG demo with a strong document-acquisition (scraping) layer** — and it is **mislabeled as "agentic AI."** Your single biggest interview risk is the word *agent*. Nothing in this system is an LLM agent. The "agents" are deterministic Playwright web-scrapers (ETL jobs). A senior will catch this in 30 seconds. If *you* name it first and frame it correctly, you turn your biggest weakness into a credibility win.

The second biggest risk: the RAG retrieval is **naive** (fixed-size word chunks, a single weak embedding model, L2 distance with a magic cutoff, a hand-maintained synonym dictionary, and debug `print()` statements in the hot path). It works for a demo and a small corpus; it will not hold up to hard questions about precision/recall, scaling, or numeric/financial accuracy.

---

## 1. PROJECT UNDERSTANDING

### System architecture (as actually built)

```
┌─────────────────────────────────────────────────────────────────┐
│  OFFLINE: Document Acquisition + Indexing (run on a schedule)    │
│                                                                  │
│  8 Playwright "fetch agents" ──► PDFs / JSON / xlsx / docx       │
│   (orchestrator.py)               │                              │
│                                   ▼                              │
│                          scripts/indexer.py                      │
│   PyMuPDF (PDF text) + office parsers ─► word-chunk (400/50)     │
│                                   │                              │
│                          all-MiniLM-L6-v2 (384-dim)              │
│                                   ▼                              │
│                       ChromaDB PersistentClient                  │
│                       collection: "ntpc_content"                 │
└─────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────┐
│  ONLINE: Query serving                                           │
│                                                                  │
│  Next.js (page.tsx) ──POST /chat──► FastAPI (main.py)            │
│                                       │                          │
│                            intent_router (regex, no LLM)         │
│                                       │ DOCUMENT_QUESTION        │
│                                       ▼                          │
│                              rag.get_rag_answer()                │
│        ┌──────────────────────────────┼───────────────────────┐ │
│        │ query expansion (dict)  sub-queries  year detection   │ │
│        │ keyword circular-number lexical match                 │ │
│        ▼                              ▼                         │ │
│   embed each sub-query ──► ChromaDB .query() (L2, top_k=15)     │ │
│        │  dedup + sort + distance<2.0 filter                    │ │
│        ▼                                                        │ │
│   build_context (12k char cap) ──► Ollama llama3.2 (local)      │ │
│        ▼                                                        │ │
│   parse answer + FOLLOWUP lines + build_sources (citations)     │ │
└─────────────────────────────────────────────────────────────────┘
```

### End-to-end query flow
1. User types in Next.js chat (`frontend/app/page.tsx`), POSTs `{question}` to `/chat`.
2. `main.py` extracts the text, runs `classify_intent()` (pure regex). Small talk → canned reply, **no RAG**. Otherwise → `get_rag_answer()`.
3. `get_rag_answer()`:
   - `detect_years()` — string-matches `"2023-24"` etc. to decide single-year vs multi-year comparison.
   - `generate_sub_queries()` — original + dictionary-expanded + stop-word-stripped keyword string.
   - For each sub-query: `embed_text()` (MiniLM) → `collection.query()`. If a year is named, runs **two passes** (year-filtered + unfiltered).
   - Dedup by `source::chunk[:120]`, sort by L2 distance, drop anything ≥ 2.0; fallback to raw top-K if everything is filtered out.
   - `keyword_id_chunks()` — regex for `CHRC 992/2026`-style codes, matched against filenames, inserted at distance `-1.0` (always first).
   - `build_context()` packs chunks up to 12,000 chars with `[Source N: ...]` labels.
   - One `_OLLAMA.chat()` call (llama3.2, temp 0.1, num_ctx 8192, num_predict 600).
   - `parse_llm_response()` splits out `FOLLOWUP:` lines; `build_sources()` produces up to 4 dedup'd citations.
4. JSON `{answer, sources, follow_up_questions}` returned and rendered.

### Major modules & responsibilities
| Module | Responsibility |
|---|---|
| `frontend/app/page.tsx` | Chat UI, calls `/chat`, renders answer + sources + follow-ups |
| `backend/main.py` | FastAPI app, CORS, request-shape normalization, intent gate |
| `backend/intent_router.py` | Deterministic regex small-talk/meta classifier (no LLM) |
| `backend/rag.py` | The whole retrieval + prompt + generation pipeline |
| `backend/embedder.py` | SentenceTransformer wrapper (`all-MiniLM-L6-v2`) |
| `scripts/indexer.py` | Ingestion: PDF/office extraction, chunking, embedding, Chroma writes |
| `scripts/agents/*` | 8 Playwright scrapers + base class (retry, dedup, logging) |
| `scripts/agents/orchestrator.py` | Runs scrapers, health checks, then triggers re-index |

---

## 2. DEEP ARCHITECTURE REVIEW (per component)

### 2.1 FastAPI layer (`main.py`)
- **What/why:** thin async HTTP boundary; accepts `question|query|message` (loose contract for multiple frontends/widgets).
- **Good:** async endpoint, intent gate avoids burning the LLM on "hi".
- **Bad / will be challenged:**
  - `allow_origins=["*"]` — open CORS on an **internal NTPC** tool. Indefensible for an enterprise deployment.
  - No auth, no rate limit, no request ID, no structured logging — just `print()`.
  - Generic `500 "Something went wrong"` hides failure modes; no error taxonomy.
  - `collection` is loaded **once at import** (`rag.py` line 155). After re-index you **must restart** the backend — documented but fragile; a silent staleness bug.
- **Failure scenarios:** Ollama down → caught, returns "LLM error" string with 200 (should be 503). Chroma empty → friendly message. Unhandled exceptions → 500.
- **Scalability:** single process; `SentenceTransformer` + Chroma loaded per-process. Horizontal scaling needs externalized vector store + shared model serving.

### 2.2 Intent router (`intent_router.py`)
- **Why it exists:** cheap deterministic gate so greetings never hit retrieval/LLM. Sensible.
- **Good:** zero-dependency, fast, testable, `MAX_SHORTTALK_WORDS` guard prevents "hi what was profit in 2023" misclassification.
- **Bad:** English/Hinglish hardcoded patterns; no out-of-scope/refusal intent; no "is this answerable from our corpus" gate. Everything ≥7 words is forced to `DOCUMENT_QUESTION` → the LLM must self-police hallucination.
- **Alternative:** small embedding classifier or zero-shot LLM intent — but the regex approach is *correctly* chosen for latency/cost here. Defend it as a deliberate trade-off.

### 2.3 RAG pipeline (`rag.py`) — the core
Covered in depth in §3. Headline architectural smells:
- **Debug `print()` of every retrieved chunk** in `multi_query_chroma` (lines ~287–331). This is production-hot-path I/O on every query. Remove or gate behind a logger/level.
- **Two `if __name__ == "__main__"` blocks** at the bottom — dead/confusing.
- **Magic numbers** (`TOP_K=15`, `DISTANCE_CUTOFF=2.0`, `MAX_CONTEXT_CHARS=12000`, `num_ctx=8192`) tuned by hand with inline justifications. Honest, but a reviewer will ask "measured how?" — you have **no eval harness**, so the answer is "by eyeballing," which is the weak point.
- **`QUERY_EXPANSIONS`** — a 40-entry hand-maintained synonym dict. Clever band-aid for MiniLM's domain weakness, but unmaintainable and brittle (covers what the author thought of; silent gaps otherwise).
- **`keyword_id_chunks`** — a lexical escape hatch because dense vectors can't match `CHRC992`. This is you *manually reinventing hybrid (sparse) retrieval* for one document type. The principled fix is real hybrid search (BM25 + dense).

### 2.4 Embedder (`embedder.py`)
- `all-MiniLM-L6-v2`, 384-dim, loaded at import. Tiny, fast, CPU-friendly, free. See §6.

### 2.5 Indexer (`indexer.py`)
- **What:** PyMuPDF page-text extraction → word chunking (400 words, 50 overlap) → MiniLM → Chroma. Also office/CSV/JSON.
- **Good:** incremental mode (skip-by-source), batch adds (5000), legacy-format warnings, web pages + office + PDF unified into one `{text, meta}` shape.
- **Bad / will be challenged:**
  - **Fixed word-count chunking ignores document structure** — tables, financial statements, and multi-column annual-report layouts get shredded. PyMuPDF `get_text()` on a multi-column PDF interleaves columns → garbled chunks. This directly harms the financial-number accuracy the product promises.
  - **No table-aware extraction** — annual reports are mostly tables; you're embedding linearized text of tables. Numbers lose their row/column semantics.
  - **No OCR** — scanned PDFs are silently near-empty (only a warning).
  - **Incremental keys** `f"{source}::{i}"` are positional — re-running on a *changed* file with the same name without a rebuild risks ID collisions/duplicates. Dedup is by source presence, not content hash, so an **updated** PDF with the same filename won't be re-indexed without `--rebuild`.
  - Full rebuild **deletes then recreates** the collection — a window of zero results if the backend queries mid-rebuild.

### 2.6 Fetch agents (`scripts/agents/*`)
- **What they really are:** robust, well-engineered **Playwright scrapers / ETL**. `BaseAgent` gives retry+backoff, SHA-256 content dedup, browser-context downloads (to beat the `403 URLBlocked` corporate WAF), network health classification, per-run logging, text→PDF rendering for JSON sources. This is genuinely the **strongest, most production-minded part of the codebase.**
- **The naming problem:** they are called "agents" but contain **no LLM, no reasoning, no planning, no tool selection.** They are a fixed pipeline per source. See §4 — this is the central interview trap.

---

## 3. RAG ANALYSIS

### Pipeline as built
- **Ingestion:** Playwright fetch → PyMuPDF/office parse → word chunks → MiniLM → Chroma.
- **Chunking:** 400 words / 50 overlap, min 50 chars. **Page-bounded** (chunks never cross PDF pages — good for citation, bad when an answer spans a page break).
- **Metadata:** `source, title, url, section (page_N / sheet:x), page`. Thin — no doc type, no date, no fiscal-year field, no access level, no semantic section title.
- **Embeddings:** single dense model, query-time per sub-query.
- **Storage:** one Chroma collection, default HNSW, L2 distance.
- **Retrieval:** multi-sub-query, optional year filter, dedup, L2 < 2.0, top-15.
- **Context:** concatenate up to 12k chars with source labels.
- **Citation:** `build_sources()` dedups by filename, up to 4, splits website vs PDF.

### Why it works (defensible strengths)
- Small, curated, single-tenant corpus → even naive retrieval recalls enough.
- Sub-query expansion + dual-pass (year-filtered + global) materially improves recall on a heterogeneous corpus (reports + circulars + CSR + wiki).
- Page-level citation is honest and verifiable.
- Low temperature + strict system prompt reduces (not eliminates) hallucination.

### Limitations (be the one to name them)
1. **Embedding model is the ceiling.** 384-dim general MiniLM is weak on financial/numeric/legal text and acronym-heavy NTPC jargon. The synonym dict and circular-number hack are symptoms of this.
2. **L2 distance + absolute cutoff 2.0** is unnormalized and corpus-specific. Cosine similarity with normalized embeddings is the norm; an absolute L2 threshold won't transfer if the model or corpus changes.
3. **No reranking** — top-15 by raw vector distance goes straight to the LLM. Precision@k is unmanaged.
4. **No real hybrid search** — you hand-built a lexical patch for one case (circular numbers) instead of BM25.
5. **Table/number fidelity** — chunking destroys tabular structure; "total income 2023-24" can pull the wrong row.
6. **No evaluation** — no golden Q/A set, no recall@k, no faithfulness/groundedness metric. Every tuning decision is unfalsifiable.
7. **Year handling is string matching** — "last fiscal year", "FY24", "2023-2024" variants slip through `YEAR_TO_FILE`.

### Specific retrieval improvements (ranked)
| Improvement | Why | Effort |
|---|---|---|
| **Add reranker** (cross-encoder `bge-reranker-v2-m3` / Cohere Rerank) | Biggest precision win; reorder top-30→top-5 | Low |
| **Hybrid search** (BM25 + dense, RRF fusion) | Kills the circular-number hack + acronym misses | Medium |
| **Upgrade embeddings** to `bge-large`/`e5-large`/`gte-large` (or a financial-tuned model) | Raises the whole ceiling | Low–Med |
| **Structure-aware + table-aware chunking** (Unstructured.io, Docling, layout parse) | Fixes numeric accuracy at the root | Medium |
| **Richer metadata + filtering** (doc_type, fiscal_year, access_level) | Precise filtered retrieval, enables RBAC | Medium |
| **Build an eval set** (50–100 graded Q/A) | Makes every other change measurable | Medium |

### Should you add…?
- **Hybrid search — YES.** It's the principled version of code you already wrote by hand.
- **Reranking — YES.** Highest ROI single change; you currently feed unranked vectors to a small LLM.
- **Query rewriting — PARTIALLY.** You already do keyword/synonym expansion. An LLM rewrite/HyDE step would help conversational and multi-part queries, at a latency cost. Worth it *after* reranking.
- **Multi-hop — NOT YET.** Most questions are single-fact lookups. Multi-hop matters for "compare X across documents and explain why" — defer until you have eval evidence it's needed. (Your multi-year comparison is a *fan-out*, not true multi-hop reasoning.)

---

## 4. AGENTIC AI REVIEW (your highest-stakes section)

### Are these agents? **No.** Say so first.
The 8 "fetch agents" are **deterministic scrapers** with a shared base class. The control flow is fixed code: navigate → select links → download → dedup → save. There is:
- **No LLM in the loop**, no reasoning, no planning, no dynamic tool selection, no goal decomposition, no memory/state beyond a hash manifest.

By the standard definition (an LLM that decides actions, selects tools, and loops on observations toward a goal), **this is a workflow / ETL pipeline, not an agentic system.** The orchestrator is a sequential task runner, not a planner.

> **Interview move:** "We call them agents because each is an autonomous, self-healing acquisition unit — retry, dedup, health-classify — but I want to be precise: they're deterministic ETL workers, not LLM agents. I chose determinism on purpose: for compliance document acquisition inside a corporate WAF, I want reproducible, auditable behavior, not an LLM improvising network calls." That answer wins the room.

### The query side has *no* agent either
`get_rag_answer` is a linear function. No routing between tools, no self-correction, no retrieval-grade-and-retry loop. It's classic single-shot RAG.

### What should become tools vs stay deterministic
- **Keep deterministic (do NOT agent-ify):** the scrapers. Auditability > flexibility for document acquisition.
- **Could become tools (query side), behind one orchestrating agent:**
  - `vector_search(query, filters)`
  - `keyword_search(code)` (the circular-number lookup)
  - `compare_years(metric, years)`
  - `get_document_metadata(source)`
  - `web/intranet_live_lookup` (future)
  An LLM router/agent could then *decide* which tool(s) a question needs instead of always running the same path.

### How each framework would (and wouldn't) help
- **LangGraph — best fit.** Model the query pipeline as an explicit state graph: `route → retrieve → grade → (rewrite & re-retrieve | rerank) → generate → check-groundedness → respond`. Gives you the retrieval-grading and self-correction loop you lack today, with checkpointing and observability. This is the upgrade I'd actually recommend.
- **CrewAI — weak fit.** Role-based multi-agent (researcher/writer/critic) is overkill for single-fact document QA; adds latency and non-determinism for little gain. Maybe a "researcher + verifier" pair for complex comparison questions.
- **AutoGen — weak fit here.** Conversational multi-agent + code execution shines for analytical/coding tasks; for grounded enterprise QA it adds cost and unpredictability. Not worth it.

> The honest senior-level take: **don't add a framework to look agentic.** Add LangGraph *only* to get retrieval grading + self-correction + observability — concrete capabilities you're missing — not for the buzzword.

---

## 5. VECTOR DATABASE REVIEW (ChromaDB)

### Usage
- `PersistentClient` on local disk (`backend/chroma`), single collection `ntpc_content`, default HNSW + L2, metadata filtering via `where`.
- Loaded once at process start; `_all_sources()` caches all metadata in memory.

### Scalability issues
- **Single-node, embedded, file-backed.** No HA, no replication, no horizontal scale. Fine for thousands–low-hundred-thousands of chunks; not for multi-GB corpora or concurrent heavy load.
- **`collection.get(include=["metadatas"])`** pulls *all* metadata into RAM (in `_all_sources`, `_SOURCE_CACHE`, indexer dedup). O(N) memory — breaks at scale.
- **No multi-tenancy / per-doc ACL** → cannot enforce RBAC at the retrieval layer (critical for internal HR/EDOP/circular docs).
- **Re-index = delete+recreate** → availability gap; no zero-downtime reindex.

### Enterprise alternatives
| DB | Strengths | Weaknesses | Fit for NTPC-scale |
|---|---|---|---|
| **ChromaDB** | Zero-ops, great for dev/POC | Single-node, weak HA/RBAC | Current stage only |
| **Qdrant** | Rust, fast, payload filtering, **hybrid + native RBAC/payload filtering**, self-host or cloud | Smaller ecosystem | **Best fit** — self-hostable on NTPC intranet, strong metadata filtering for access control |
| **Weaviate** | Built-in hybrid (BM25+dense), modules, RBAC | Heavier ops | Strong alternative |
| **Pinecone** | Fully managed, scales effortlessly | **SaaS/cloud** — likely a non-starter for an air-gapped PSU intranet; data residency | Poor fit (data leaves premises) |
| **pgvector** | Reuse existing Postgres, transactional, joins with RBAC tables | Slower at very large scale, needs tuning | Good if NTPC already runs Postgres |

**Recommendation for NTPC:** **Qdrant (self-hosted)** — keeps data on the intranet (data-sovereignty for a state utility), native hybrid + payload filtering for RBAC, and a clean migration path from Chroma. pgvector if they want to lean on existing DBA/Postgres ops. Avoid Pinecone unless cloud is explicitly approved.

---

## 6. EMBEDDING MODEL REVIEW

- **Current:** `all-MiniLM-L6-v2`, **384 dims**, ~80MB, CPU-fast, free/local, 256-token input window.
- **Cost:** effectively zero (local). **Accuracy:** mediocre on domain/numeric/long text; the 256-token cap means your 400-word (~520-token) chunks are **truncated at embed time** — a real bug: chunks larger than the model's window lose their tail. This alone justifies smaller chunks *or* a longer-context embedder.

### Better alternatives
| Model | Dims | Why |
|---|---|---|
| `BAAI/bge-large-en-v1.5` | 1024 | Strong MTEB, local, free; big quality jump |
| `intfloat/e5-large-v2` | 1024 | Excellent retrieval, query/passage prefixes |
| `Alibaba-NLP/gte-large-en-v1.5` | 1024 | 8k context — fixes the truncation problem |
| `voyage-finance-2` / `voyage-3` | API | Finance-tuned; best numeric/financial accuracy (but external API) |
| `nomic-embed-text` (via Ollama) | 768 | Long context, fully local, fits your Ollama stack |

- **Multilingual:** if Hindi/regional queries matter, `bge-m3` (multilingual + multi-granularity + **built-in dense+sparse+ColBERT**, 8k ctx) is ideal and also gives you hybrid for free.
- **Domain fine-tuning:** feasible later — generate (query, positive-chunk) pairs from your corpus (or from logged user questions) and fine-tune `bge`/`e5` with contrastive loss. High effort; do it only after reranking + a better base model plateau.

> **Lowest-effort high-impact move:** swap MiniLM → `bge-m3` or `nomic-embed-text` (local, longer context, gives hybrid), shrink chunks to ≤ model window. Re-embed and re-index.

---

## 7. LLM REVIEW

- **Current:** Ollama **`llama3.2`** (3B) local, temp 0.1, `num_ctx=8192`, `num_predict=600`, `keep_alive=30m`.
- **Prompting:** strict "use only context" system prompt + per-request rules + `FOLLOWUP:` convention. Reasonable prompt engineering; the strictness is good for groundedness.
- **Context usage:** 12k chars (~3k tokens) context into an 8k window — fits. Note the prior bug (3072 ctx silently truncating) is fixed; good catch by the author.

### Will another LLM perform better? **Yes, materially.**
- **llama3.2 3B is small.** It will miss nuance, mis-sum numbers, and occasionally ignore "context-only" rules. For a financial/compliance assistant, model quality is your accuracy ceiling alongside retrieval.
- **Local/open upgrades (keep on-prem — right call for a PSU):**
  - `llama3.1:8b` / `llama3.3:70b` (if GPU allows), `qwen2.5:14b/32b-instruct` (strong on numbers/tables), `mistral-small`, `phi-4`. Qwen2.5-14B-Instruct is a sweet spot for on-prem accuracy/cost.
- **Quantization:** Ollama already serves quantized GGUF (Q4_K_M default). For bigger models on limited VRAM, Q4/Q5 is the standard trade. Mention AWQ/GPTQ for vLLM if they move to GPU serving.
- **Local deployment:** already local — the correct posture for NTPC data. For throughput, graduate from Ollama (single-stream-ish) to **vLLM/TGI** (continuous batching, higher concurrency) when you need to serve many users.

### Cost optimization
- Local = no per-token cost; cost is GPU/CPU time. Optimize via: smaller context (better retrieval ⇒ fewer chunks), prompt caching, batching, and right-sizing the model. The `keep_alive=30m` warm-model decision is a good one — name it.

---

## 8. PRODUCTION READINESS REVIEW

| Capability | Status | Verdict |
|---|---|---|
| Authentication | ❌ none | Blocker for internal HR/EDOP data |
| Authorization / RBAC | ❌ none | Anyone who reaches the API reads everything |
| CORS | ❌ `*` | Must restrict to NTPC origins |
| Logging | ⚠️ `print()` only | No structured/centralized logs, no request IDs |
| Monitoring / tracing | ❌ none | No latency/error/quality metrics, no APM |
| Rate limiting | ❌ none | DoS / abuse exposure |
| Caching | ❌ none (only model `keep_alive`) | Repeated queries re-embed + re-generate |
| Audit trail | ⚠️ scraper run-logs only | No query/answer audit (needed for compliance) |
| Data privacy | ⚠️ local (good) but `verify=False` on httpx, open API | TLS verification disabled = MITM risk |
| Prompt-injection defense | ❌ none | Retrieved doc text + user text trusted blindly |
| Hallucination prevention | ⚠️ prompt-only | No groundedness check / citation verification |
| PII handling | ❌ none | Employee-experience/EDOP data ungoverned |
| Secrets management | ⚠️ `.env` files | OK for now; no vault |

**Missing enterprise features:** SSO (NTPC AD/LDAP), per-document ACL enforced at retrieval, query+answer audit log, content moderation, answer-confidence scoring, feedback capture (thumbs up/down → eval set), API gateway, health/readiness probes, graceful reindex, model/version pinning, and an evaluation/regression suite in CI.

**Top 5 must-fix before "production at NTPC":**
1. AuthN (AD/LDAP SSO) + lock down CORS.
2. RBAC at retrieval (metadata `access_level` filter) — internal HR/EDOP must not leak.
3. Structured logging + query/answer audit trail.
4. Rate limiting + proper HTTP status codes (503 when Ollama/Chroma down).
5. Remove `verify=False`; fix TLS trust to the NTPC CA.

---

## 9. PERFORMANCE REVIEW

### Bottlenecks & latency sources
1. **LLM generation** — dominant cost (~hundreds of ms–seconds for 600 tokens on CPU/small GPU).
2. **Multiple embeddings per query** — `generate_sub_queries` yields up to 3 sub-queries; each is embedded separately, and year queries run **2 passes** → up to ~6 Chroma queries + 3 embed calls per user question. Synchronous and serial in the single-year path.
3. **`print()` of 20 chunks per query** — real I/O on the hot path.
4. **`_all_sources()` / metadata `.get()`** — O(N) full-metadata scans; cached but memory-heavy.
5. **Cold model load** — mitigated by `keep_alive=30m` (good).

### Recommendations
- **Cache:** (a) embedding cache (hash→vector) for repeated/expanded queries; (b) full-answer cache for identical questions (Redis); (c) reuse one embedding across the year-filter dual pass instead of re-embedding.
- **Retrieval:** batch-embed the sub-queries in one `model.encode([...])` call; run the dual passes concurrently.
- **Async:** the single-year path is sync; only the multi-year path uses `asyncio.gather`. Make retrieval consistently async / thread-pooled; stream the LLM response to cut perceived latency.
- **Queue:** for re-indexing and scraping, move to a task queue (Celery/RQ/Arq) with a worker pool; decouple ingestion from serving.
- **Horizontal scaling:** externalize the vector store (Qdrant), serve embeddings + LLM behind dedicated services (vLLM/TGI + a model server), make the FastAPI app stateless, put it behind a load balancer. Today the in-process Chroma + in-process model block this.
- **Remove debug prints**; gate behind `logging` levels.

---

## 10. INTERVIEW PREP — 50 HARD QUESTIONS + MODEL ANSWERS

> Format: **Q** → concise model answer → *follow-up the senior will ask*.

### RAG (1–10)
1. **Why fixed-size word chunking over semantic/structural chunking?** → "Speed of build and simplicity; it's the wrong choice for table-heavy annual reports. Structure/table-aware chunking (Docling/Unstructured) is the right fix and my top ingestion improvement." *FU: how would you preserve table semantics?*
2. **Your chunks are ~520 tokens but MiniLM's window is 256 — what happens?** → "They're truncated at embed time; the chunk tail isn't represented. That's a real bug — fix by shrinking chunks or moving to an 8k-context embedder (gte/bge-m3)." *FU: how did you detect it?* (Honest answer: by reviewing the model card vs CHUNK_SIZE.)
3. **Why L2 distance and an absolute cutoff of 2.0?** → "Chroma default; the 2.0 is hand-tuned and corpus/model-specific, so it won't transfer. Cosine on normalized vectors + a relative/top-k threshold is more robust." *FU: what breaks if you swap the embedding model?* (The cutoff.)
4. **No reranker — defend that.** → "Can't fully. Feeding unranked top-15 to a small LLM is my biggest precision gap; a cross-encoder reranker is the highest-ROI change." *FU: which reranker and where in the pipeline?*
5. **Is this hybrid search?** → "No — but `keyword_id_chunks` is a hand-built sparse patch for circular numbers, which proves I need real BM25+dense fusion (RRF)." *FU: why does dense retrieval fail on 'CHRC992'?* (Out-of-distribution alphanumeric codes have no semantic neighborhood.)
6. **How do you measure retrieval quality?** → "I don't yet — no eval set. That's the honest gap; every threshold is eyeballed. I'd build a 50–100 graded Q/A set and track recall@k + faithfulness." *FU: how do you build groundedness metrics?* (LLM-as-judge / RAGAS.)
7. **Multi-year comparison — how does it work and where's the risk?** → "Fan-out: one filtered retrieval per year via `asyncio.gather`, merged. Risk: cross-year chunk dedup by `chunk[:120]` can drop a legit year's chunk if prefixes collide." *FU: fix?* (Dedup by source+id, not text prefix.)
8. **The synonym dictionary — maintainable?** → "No. It's a band-aid for weak embeddings. A better embedder + query rewriting replaces it." *FU: what queries silently fail today?* (Anything outside the 40 keys.)
9. **How is context window budgeted?** → "12k chars (~3k tok) into an 8k ctx; a prior bug had num_ctx=3072 silently truncating. Fixed." *FU: what if retrieval returns 15 long chunks?* (build_context truncates at 12k — may drop relevant chunks; reranking would prioritize.)
10. **Citation correctness — can you guarantee the cited source supports the claim?** → "No — citations are the retrieved sources, not verified against the generated sentence. A groundedness/attribution check is needed." *FU: how would you implement per-sentence attribution?*

### Agents (11–18)
11. **Are these真 agents?** → "No — deterministic Playwright ETL. I keep them deterministic on purpose for auditable compliance-document acquisition." *FU: when would you make them agentic?*
12. **What's the difference between a workflow and an agent?** → "An agent uses an LLM to choose actions/tools and loops on observations toward a goal; a workflow is fixed control flow. Mine is the latter." *FU: give an example query that needs true agency.* (Open-ended "investigate why PLF dropped and which circulars relate.")
13. **Why not LangGraph today?** → "Not needed for single-shot QA; I'd adopt it specifically to add retrieval-grading + self-correction + observability, not for the label." *FU: sketch the graph.* (route→retrieve→grade→rewrite/rerank→generate→groundedness→respond.)
14. **Would CrewAI/AutoGen help?** → "Marginally and at a latency/determinism cost; overkill for fact lookup. Maybe researcher+verifier for complex comparisons." *FU: cost of multi-agent?*
15. **How do agents survive the corporate WAF?** → "Downloads go through Chromium's `context.request` to reuse the browser proxy/session/TLS — plain httpx gets `403 URLBlocked`." *FU: security implication of `verify=False` fallback?* (MITM risk; fix.)
16. **How is idempotency guaranteed?** → "SHA-256 content hash manifest, seeded from existing files; identical content is skipped." *FU: what about an updated file with the same name?* (Hash differs → re-downloaded, but the *indexer* dedups by source name, so it won't re-embed without rebuild — a gap.)
17. **What happens when a site's HTML changes?** → "`structure_changed` status (reachable but 0 discovered) → flagged FAILED-NEEDS-TUNING; selectors live in `.env.agents`." *FU: could an LLM auto-repair selectors?* (Yes — a real agentic use case.)
18. **Orchestrator failure isolation?** → "Each agent wrapped in try/except; one crash never aborts others; per-run JSON log." *FU: partial-failure reindex policy?* (Reindex only if downloads>0.)

### Embeddings/VectorDB (19–28)
19. **Why MiniLM?** → "Free, local, fast for a POC; it's the quality ceiling and should move to bge/e5/gte or bge-m3." *FU: re-embed cost of switching?* (Full re-index.)
20. **384 vs 1024 dims — trade-off?** → "Lower dims = less storage/faster ANN but less expressive. For numeric/legal text, 1024-dim models retrieve better." *FU: storage math at 1M chunks?*
21. **Why ChromaDB?** → "Zero-ops embedded DB ideal for dev; not for HA/RBAC/scale." *FU: migration path?* (Re-embed into Qdrant; abstract the store behind an interface.)
22. **ChromaDB vs Qdrant vs Weaviate vs Pinecone for NTPC?** → "Qdrant self-hosted: on-prem data sovereignty + hybrid + payload-filter RBAC. Pinecone is SaaS → likely disallowed for PSU data." *FU: why not pgvector?* (Viable if they run Postgres.)
23. **How do you enforce access control at retrieval?** → "Today I can't — single collection, no ACL metadata. Add `access_level` to metadata and filter by the caller's role in the `where` clause." *FU: where does role come from?* (SSO token.)
24. **`_all_sources()` loads all metadata into RAM — scale issue?** → "Yes, O(N). Fine now, breaks at large N. Replace with a maintained source index or DB query." *FU: at what N does it hurt?*
25. **HNSW parameters — did you tune them?** → "No, defaults. ef_construction/M tuning trades recall vs latency/memory; I'd tune against an eval set." *FU: recall vs ef_search curve?*
26. **Cosine vs L2 — does it matter here?** → "With unnormalized embeddings, yes; cosine is standard for sentence-transformers. My absolute L2 cutoff is fragile." *FU: how to normalize?*
27. **Zero-downtime reindex?** → "Not today — full rebuild deletes the collection. Build a new collection, then atomically swap an alias/pointer." *FU: how does Chroma support aliases?* (It doesn't natively — another reason to move to Qdrant.)
28. **Embedding drift when corpus grows — how to keep thresholds valid?** → "Use relative top-k + reranker scores instead of absolute distance; recalibrate on the eval set per model change." *FU: monitoring for drift?*

### LLM (29–36)
29. **Why llama3.2 3B?** → "Local, free, fits modest hardware; it's undersized for financial accuracy. Qwen2.5-14B-Instruct or llama3.1-8B on GPU is the upgrade." *FU: accuracy vs latency trade?*
30. **How do you prevent hallucination?** → "Strict context-only system prompt + temp 0.1 + the not-available fallback. That's necessary but insufficient — no groundedness verification." *FU: add a verifier?* (LLM-as-judge on answer vs context.)
31. **Temperature 0.1 — why not 0?** → "Near-deterministic but a hair of fluency; 0 is defensible too. Minor." *FU: reproducibility needs?*
32. **num_predict=600 — what if the answer needs more?** → "It truncates; comparisons across many years can be cut. Make it adaptive." *FU: streaming?*
33. **Why Ollama not vLLM?** → "Ollama = simplest local serving for a POC. vLLM/TGI for production concurrency (continuous batching)." *FU: throughput difference?*
34. **Quantization impact on numeric accuracy?** → "Q4 can degrade arithmetic; for a finance bot, test Q5/Q8 vs FP16 on the eval set before shipping a quant." *FU: measure how?*
35. **Prompt injection via document content — mitigations?** → "None today; retrieved text is trusted. Mitigate with delimiting, instruction-hierarchy prompts, and stripping instruction-like patterns from chunks; never let context override system rules." *FU: example exploit?* (A PDF containing 'ignore previous instructions'.)
36. **How would you cut LLM latency 50%?** → "Better retrieval ⇒ fewer/shorter chunks, smaller context; stream tokens; right-size model; prompt cache." *FU: what dominates now?* (Generation.)

### FastAPI/System (37–43)
37. **Collection cached at import — consequence?** → "Stale after reindex until restart. Fix with a reload signal / file-watch / versioned collection pointer." *FU: zero-downtime reload?*
38. **CORS `*` on an internal tool — justify.** → "Can't; it was for quick multi-frontend testing. Lock to NTPC origins." *FU: why is `*`+credentials disallowed?* (Spec forbids it.)
39. **Error returns 200 with 'LLM error' string — problem?** → "Yes, masks failures from clients/monitoring. Should be 503 with an error code." *FU: error taxonomy?*
40. **No rate limiting — risk?** → "Abuse/DoS, and each request is expensive (embed+LLM). Add gateway/Redis token bucket." *FU: per-user or per-IP?*
41. **How stateless is the app?** → "Mostly, but in-process Chroma + model make it not horizontally scalable as-is." *FU: what to externalize first?* (Vector store, then model serving.)
42. **Request contract accepts question|query|message — why?** → "Loose coupling to multiple frontends/widget; mild smell, fine if documented." *FU: validation?* (Pydantic; reject empty.)
43. **How do you observe production behavior?** → "Today only prints. Need structured logs, request IDs, latency/quality metrics, tracing (OTel), and a query/answer audit store." *FU: what 3 metrics first?* (p95 latency, retrieval-empty rate, fallback-answer rate.)

### Security/Scale/Deployment/Cost (44–50)
44. **Biggest security gap?** → "No auth + open CORS + no RBAC on internal HR/EDOP data — a data-exposure risk. Auth + retrieval-level ACL come first." *FU: how to scope retrieval by role?*
45. **`verify=False` on httpx — why and risk?** → "To get past intranet TLS issues; it disables cert validation (MITM risk). Fix by trusting the NTPC CA bundle." *FU: proper fix?*
46. **PII/compliance for employee data?** → "Ungoverned today. Need PII tagging, access control, retention, and audit — especially for EDOP/EmpExp." *FU: data classification scheme?*
47. **How would you scale to 5,000 concurrent NTPC users?** → "Stateless API behind LB; Qdrant cluster; vLLM/TGI GPU pool with batching; Redis caches; async everywhere; queue for ingestion." *FU: which component saturates first?* (LLM serving.)
48. **Cost model on-prem?** → "No per-token cost; cost is GPU/engineering. Optimize via caching, retrieval quality (fewer chunks), right-sized model, batching." *FU: build vs cloud-API trade for a PSU?* (On-prem wins on data sovereignty.)
49. **Disaster recovery for the index?** → "Re-derivable from source docs + manifests, but a full re-scrape/re-embed is slow. Snapshot the vector store + back up `frontend/public/reports` and manifests." *FU: RTO/RPO?*
50. **If you had 2 weeks, what 3 things?** → "(1) Eval set + metrics, (2) reranker + better embedder, (3) auth + RBAC-at-retrieval. Measurable quality + the security floor." *FU: why eval first?* (Everything else is unfalsifiable without it.)

---

## 11. SYSTEM IMPROVEMENTS (ranked by Impact / Complexity / Effort)

### Quick wins (days)
| Change | Impact | Complexity | Effort |
|---|---|---|---|
| Remove debug `print()` from hot path; add `logging` | Med | Low | 1h |
| Lock CORS to NTPC origins; proper HTTP status codes | High (sec) | Low | 2h |
| Add a **reranker** (cross-encoder) over top-30 | **High** | Low | 1–2d |
| Batch-embed sub-queries; reuse embedding across passes | Med | Low | 0.5d |
| Shrink chunks to embedder window OR swap to long-ctx embedder | High | Low | 0.5–1d |
| Answer + embedding cache (Redis) | Med | Low | 1d |
| Fix multi-year dedup key (source+id, not text prefix) | Med | Low | 1h |

### Medium-term (weeks)
| Change | Impact | Complexity | Effort |
|---|---|---|---|
| **Evaluation harness** (graded Q/A, recall@k, faithfulness) | **High** | Med | 1–2w |
| **Hybrid search** (BM25 + dense, RRF) — retire the keyword hack | High | Med | 1w |
| **Upgrade embeddings** (bge-m3 / gte-large) + re-index | High | Med | 0.5w |
| **Structure/table-aware ingestion** (Docling/Unstructured) | **High** (numeric accuracy) | Med-High | 1–2w |
| **Auth (AD/LDAP SSO) + RBAC at retrieval** (access_level metadata) | **High** (sec) | Med | 1–2w |
| Upgrade LLM (Qwen2.5-14B/llama3.1-8B) on GPU via vLLM | High | Med | 1w |
| Structured logging, OTel tracing, query/answer audit store | High | Med | 1w |

### Long-term (quarters)
| Change | Impact | Complexity | Effort |
|---|---|---|---|
| Migrate vector store to **Qdrant** (HA, hybrid, RBAC, zero-downtime reindex) | High | High | 3–6w |
| **LangGraph** query graph: route→retrieve→grade→rewrite/rerank→generate→groundedness | High | High | 3–5w |
| Domain fine-tuned embeddings + (optional) LLM fine-tune on NTPC corpus | Med-High | High | 4–8w |
| LLM-auto-repair of scraper selectors (a genuinely agentic use case) | Med | High | 3–4w |
| Full MLOps: CI eval-regression gates, model/version pinning, feedback loop | High | High | ongoing |

---

## 12. EXECUTIVE SUMMARY & SCORES

**What this project gets right:** a working, honest, end-to-end RAG system with an unusually strong, production-minded **document-acquisition layer** (the scrapers — retry, content-hash dedup, WAF-aware downloads, health classification, honest per-source verdicts). The author shows real debugging maturity (the `num_ctx` truncation fix, the year-filter trap fix, the circular-number escape hatch). For a single-author internal tool, it's genuinely useful.

**What it is not:** it is not agentic, not secured, not measured, and not built to scale. The retrieval is naive and the embedding/LLM choices cap accuracy below what a financial/compliance assistant needs. There is no evaluation, so quality claims are unfalsifiable.

| Dimension | Score | One-line justification |
|---|---|---|
| **Architecture** | **6/10** | Clean, pragmatic single-node RAG; strong ETL layer; but naive retrieval, in-process coupling, no abstraction over store/model |
| **Production readiness** | **3/10** | No auth/RBAC/rate-limit, open CORS, `print()` logging, restart-to-refresh, `verify=False` |
| **Scalability** | **3/10** | In-process Chroma + model, O(N) metadata loads, delete-recreate reindex, single process |
| **Security** | **2/10** | Open API + open CORS + no RBAC on internal HR/EDOP data + disabled TLS verification |
| **AI/ML maturity** | **4/10** | Solid prompt discipline & sensible RAG instincts, but weak embeddings, no reranking/hybrid, no eval, mislabeled "agents" |

**Overall: a strong POC / internal MVP (≈5/10), one to two quarters of focused work away from a defensible enterprise deployment.** The fastest path to credibility: **(1) build an eval set, (2) add reranking + a better embedder + hybrid search, (3) add auth + RBAC-at-retrieval.** Do those three and every score above moves up by 2–3 points.

> **Closing interview posture:** lead with honesty. Name the "agent" misnomer yourself, name the missing eval harness yourself, and frame each weakness with the specific fix and its ROI. A Principal Engineer doesn't expect a junior project to be perfect — they're testing whether you *understand* its limits and can *prioritize* the fixes. This document gives you that map.
```

