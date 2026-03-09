# Technical Documentation: Scientific Research Navigator

This document describes how the project currently works in code, including request lifecycles, data model semantics, retrieval internals, ingestion behavior, and operational tradeoffs.

## 1. System Overview

Scientific Research Navigator is a session-based RAG system composed of:
- A Django REST backend (`backend/rag`) handling ingestion, retrieval, synthesis, persistence, and metrics
- A React frontend (`frontend/src/App.js`) acting as the interactive research workspace
- Ollama-hosted local models for embeddings and generation
- Session-scoped Chroma vector stores on disk
- PostgreSQL (via Docker) or SQLite fallback (via settings)

Primary design objective:
- Keep workflows isolated by session while enabling multi-document evidence-grounded scientific analysis.

## 2. Runtime Architecture

### 2.1 Backend Runtime

- Framework: Django + DRF function-based endpoints
- URL root: `backend/config/urls.py` maps `/api/` to `rag.urls`
- App registration and middleware in `backend/config/settings.py`
- Media files served by Django in `DEBUG=True` mode (`/media/...`)

### 2.2 Frontend Runtime

- React app with central stateful component in `frontend/src/App.js`
- API client abstraction in `frontend/src/api.js`
- Frontend connects to backend via `REACT_APP_API_BASE_URL` (default `http://127.0.0.1:8000`)

### 2.3 Storage Layers

Relational DB:
- Session/workflow metadata, documents, Q&A history, run logs, highlights

Object/media storage (Django default storage):
- Uploaded/imported PDFs under `media/pdfs/`

Vector storage (Chroma):
- Session collection path: `CHROMA_PERSIST_DIR/<session_name>`
- Highlight embeddings stored in a dedicated collection name `highlights` (same session persist path)

## 3. Domain Model and Schema Semantics

Defined in `backend/rag/models.py`.

### 3.1 Session
- Unique `name`
- Owns documents, questions, run logs

### 3.2 Document
- `(filename, session)` unique together
- Metadata: `title`, `abstract`, `page_count`
- Status fields:
  - `status`: `UPLOADED|PROCESSING|INDEXED|FAILED`
  - `processing_started_at`, `processing_completed_at`, `error_message`

### 3.3 PaperSource
- Tracks external provider metadata and external IDs
- One-to-one optional link to `Document`
- `source_type` values include `arxiv`, `pubmed`, `doi`, `acl`, `medrxiv`, `manual`
- `imported` indicates successful import flow completion

### 3.4 Question / Answer
- `Question` belongs to a `Session`
- `Answer` is one-to-one with `Question`
- `Answer.citations` stores serialized chunk evidence
- `Answer.metadata` stores structured payloads (e.g., comparison claims, lit review title)

### 3.5 RunLog
Captured per ask call, including:
- Context: session, mode, source filters, question text
- Performance: `latency_ms`, optional `retrieval_ms`, `generation_ms`
- Grounding metadata: refusal flags, insufficient-evidence flags, chunk counts, confidence
- Error trace fields for failed runs

### 3.6 Highlight / HighlightEmbedding
- Highlight stores user annotation on a document page with offsets, note, and tags
- HighlightEmbedding maps highlight IDs to vector IDs for semantic retrieval

## 4. API Surface and Behavioral Contracts

Routes declared in `backend/rag/urls.py`.

### 4.1 Session APIs
- `POST /api/session/`: create-or-get by name
- `GET /api/sessions/`: list sessions ordered by creation desc
- `DELETE /api/session/<session_name>/`: delete session + Chroma folder + orphaned files

### 4.2 Document APIs
- `POST /api/upload/`: upload PDF and start async ingestion thread
- `GET /api/pdfs/?session=<name>`: list documents in session
- `DELETE /api/delete/`: remove document from DB, Chroma, and possibly filesystem
- `GET /api/documents/<id>/status/`: ingestion status/metadata timestamps
- `GET /api/documents/<id>/page-text/?page=<1-indexed>`: extracted per-page text via `pypdf`
- `POST /api/documents/<id>/retry/`: reset failed doc and retry ingestion (PDF or metadata-only fallback)

### 4.3 Query APIs
- `POST /api/ask/`: orchestrates `qa`, `compare`, `lit_review`
- `GET /api/history/?session=<name>`: rehydrates chat history from Question/Answer records

### 4.4 External Search/Import APIs
- `GET /api/search/external/?q=...&source=...`
- `POST /api/import/external/`
- Providers: arXiv, PubMed, Semantic Scholar, ACL, medRxiv
- Legacy arXiv-specific routes remain (`/api/arxiv/search/`, `/api/arxiv/import/`)

### 4.5 Highlights APIs
- `GET|POST /api/highlights/`
- `DELETE /api/highlights/<id>/`
- `GET /api/highlights/search/?session=...&q=...`

### 4.6 Metrics API
- `GET /api/metrics/summary/?since=<days>`

## 5. Ingestion Pipeline Internals

Primary implementation: `backend/rag/services/ingestion.py`.

### 5.1 PDF Ingestion (`ingest_document`)
1. Set `Document.status=PROCESSING`, set `processing_started_at`
2. Load pages using `PyPDFLoader`
3. Extract title/abstract heuristically from first page (`rag/metadata.py`)
4. Persist metadata and page count to `Document`
5. Attach per-page metadata:
   - `source`: filename
   - `page`: zero-indexed page integer
   - `section`: `abstract` for first page else `body`
6. Split pages with `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)`
7. Insert chunks into session Chroma store
8. Mark document `INDEXED`, set completion time, clear error

Failure behavior:
- Any exception marks `Document.status=FAILED` and stores message

### 5.2 Metadata-only Ingestion (`ingest_metadata_only`)
Used when full PDF is unavailable (notably PubMed and some Semantic Scholar fallbacks).

Process:
- Build virtual text from title/authors/abstract
- Create synthetic LangChain document with metadata including `virtual=True`
- Split and index into Chroma
- Mark as `INDEXED` with note in `error_message`: summary-only mode

### 5.3 Async Execution Model
- Upload/import/retry routes spawn daemon threads inside API process
- No Celery or distributed queue currently
- Implication: processing is tied to web process lifecycle

## 6. Retrieval and QA Pipeline

Primary modules:
- `backend/rag/query.py`
- `backend/rag/services/retrieval.py`

### 6.1 RetrievalService Core
Features implemented:
- Vector similarity retrieval from Chroma (`similarity_search_with_relevance_scores`)
- BM25 lexical retrieval over fetched corpus (`rank_bm25`)
- Hybrid fusion via Reciprocal Rank Fusion (RRF)
- Optional multi-query expansion using LLM-generated query variants
- Optional reranking by term overlap weighting
- Optional recursive retrieval helper (implemented; not wired into main ask flow)

`ScoredDocument` wrapper standardizes:
- Score
- Deterministic `chunk_id` (source/page/content hash)
- Snippet extraction
- Citation serialization

### 6.2 QA Orchestration (`ask_with_citations`)
1. Retrieve chunks via RetrievalService (unless docs override provided)
2. Build context blocks with `SOURCE` and `PAGE`
3. Generate answer with Ollama LLM prompt enforcing grounded reasoning
4. Build deduplicated citations by chunk ID
5. Classify output for refusal/insufficient-evidence phrase heuristics
6. Return answer + evidence + timing + confidence

If no chunks retrieved:
- Returns refusal-style fallback answer with empty citations and low confidence

### 6.3 Specialized QA Routing in `views.ask_question`
Before default QA retrieval, the backend checks question intent for some fast paths when source is selected:
- Title questions -> return `Document.title`
- Page-count questions -> return `Document.page_count`
- "About this paper" questions -> retrieve abstract/body targeted docs and run QA

If specialized handling fails, fallback is default QA retrieval.

## 7. Compare and Literature Review Flows

Implemented in `views.ask_question` + `services/synthesis.py`.

### 7.1 Compare Mode
- Requires at least 2 distinct selected sources
- Performs per-source retrieval to reduce source imbalance
- Merges candidates, keeps top-scored chunks
- If fewer than 2 source documents retrieved, returns explicit insufficiency message
- Otherwise LLM is prompted to output structured JSON claims and stances
- Includes one repair pass if JSON parse fails

Returned metadata includes:
- topic, claims list, message, source count, source list, and chunk citations

### 7.2 Literature Review Mode
- Hybrid retrieval over selected/all sources
- LLM prompt requests structured review sections (intro/themes/methods/synthesis/conclusion)
- Persisted as answer text with metadata title + mode

## 8. External Provider Services and Resilience

### 8.1 Providers
- `ArxivService`: arxiv client search + metadata + optional PDF download and ingestion
- `PubmedService`: Entrez search/summary; currently metadata-first import path
- `SemanticScholarService`: HTTP API for search/metadata/import with optional open-access PDF fetch
- `ACLService`: Semantic Scholar subclass with venue/identifier filtering
- `MedRxivService`: Semantic Scholar subclass with medRxiv/bioRxiv targeting

### 8.2 Resilience Layer
`backend/rag/services/resilience.py` provides:
- Bounded retries
- Exponential backoff
- In-memory per-provider circuit breaker with cooldown

Configuration from Django settings:
- `EXTERNAL_API_RETRIES`
- `EXTERNAL_API_RETRY_BACKOFF_SECONDS`
- `EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD`
- `EXTERNAL_API_CIRCUIT_OPEN_SECONDS`

## 9. Highlight Pipeline

Primary files:
- `views_highlights.py`
- `services/highlight_service.py`

### 9.1 Create Highlight
- Client submits document/page/offset/text/note/tags
- Backend writes `Highlight`
- Attempts semantic indexing to Chroma collection `highlights`
- If embedding indexing fails, highlight is kept and note is annotated with failure text

### 9.2 Search Highlights
- Semantic search first (`similarity_search_with_relevance_scores` filtered by session)
- Lexical fallback/complement using `icontains` on text/note/tags
- Results hydrated to full highlight payload in relevance order

## 10. Metrics and Observability

`MetricsService` logs run-level telemetry for every ask request.

Collected data:
- Overall latency
- Optional stage timings: retrieval/generation and derived orchestration time
- Error frequency and error type distribution
- Grounding indicators (refusal and low-evidence rates)
- Average retrieved chunk counts and confidence

`/api/metrics/summary/` aggregates metrics for configurable trailing window (`since` days, default 7).

Frontend monitoring dashboard displays these aggregates in `monitoring` mode.

## 11. Frontend Interaction Model

Main logic in `frontend/src/App.js`.

### 11.1 State Domains
- Session selection and management
- Source list and selected source filters
- Mode toggle (`qa`, `compare`, `lit_review`, `monitoring`)
- Message history rendering
- External search/import panel
- PDF drawer and citation navigation
- Highlight CRUD + highlight search

### 11.2 User Journey (Common)
1. Create/select session
2. Upload PDF or import from external provider
3. Wait for status to reach `INDEXED` (polling every 3s while processing)
4. Select indexed sources
5. Ask question in selected mode
6. Inspect citations -> open PDF.js viewer
7. Save/search/delete highlights

### 11.3 Citation Viewer Behavior
- Builds document URL from backend media path
- Fetches page text to derive best phrase match for viewer search parameter
- Falls back to snippet-based fuzzy search phrase when exact phrase is not found

## 12. Configuration and Environment

Source of truth: `backend/config/settings.py` and `backend/.env.example`.

Notable runtime toggles:
- DB backend switch (`sqlite` fallback if `DB_ENGINE` unset)
- Retrieval knobs (`RAG_QA_USE_HYBRID`, `RAG_QA_USE_MULTI_QUERY`, `RAG_QA_USE_RERANKING`, `RAG_QA_TOP_K`)
- Generation knobs (`RAG_LLM_MODEL`, `RAG_LLM_TEMPERATURE`, `RAG_LLM_NUM_CTX`, `RAG_LLM_NUM_PREDICT`)
- Resilience knobs (retry/circuit breaker variables)

Ollama endpoint resolution:
- `services/ollama_client.py` probes configured URL + Docker-aware fallbacks (`host.docker.internal`, `172.17.0.1`, localhost)

## 13. Deployment and Containers

`docker-compose.yml` runs:
- Postgres 15
- Ollama
- Backend container (migrate + runserver)
- Frontend container (`npm start`)

Notes:
- Compose backend uses Postgres by default and persists media/chroma volumes
- GPU override file only sets `gpus: all` for Ollama service

## 14. Testing and Coverage Snapshot

Implemented backend tests in `backend/rag/` include:
- API flow tests for upload/list/ask/highlights
- Citation serialization and page-alignment regression tests
- Resilience behavior tests (retry + circuit breaker)

Command:
```bash
cd backend
python manage.py test rag -v 2
```

## 15. Current Limitations and Engineering Debt

- Background ingestion threads are not durable task workers
- Some provider imports depend on metadata-only fallbacks due PDF availability constraints
- Heuristic metadata extraction (title/abstract) can be noisy on complex first pages
- Retrieval recursive strategy exists but is not yet integrated into request path
- Outdated helper scripts (`backend/test_query.py`, `backend/test_ingest.py`) do not match current signatures
- Page metadata in retrieval citations is zero-indexed internally and normalized in frontend display

## 16. Extension Points

Practical next hardening points:
1. Move ingestion/import to queue workers (Celery/RQ) with retry persistence
2. Add auth/multi-user ownership boundaries on sessions and documents
3. Version prompts and retrieval parameters per run for reproducibility
4. Expand evaluation suite with fixture corpora and mode-specific quality assertions
5. Improve metadata extraction with structured parser pipeline (title/abstract/authors/DOI)

---

This documentation reflects the repository state as of March 9, 2026 and is aligned with current backend/frontend codepaths.
