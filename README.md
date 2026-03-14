# Scientific Research Navigator

Scientific Research Navigator is a session-scoped, local-first RAG platform for scientific papers.

It combines:
- A Django + DRF backend for session/document/query orchestration
- Chroma vector indexes per session
- Ollama-hosted local embedding + generation models
- A React frontend for ingestion, grounded Q&A, comparison, literature review, monitoring, and highlight workflows

## What Is Implemented Now

### Core Workspace
- Session management: create/list/delete sessions
- Session isolation: each session has isolated documents, chat history, and Chroma persist path
- Document management: upload/list/delete PDFs, ingestion status, retry ingestion
- Chat history: persisted as Question/Answer records per session

### Retrieval and Generation Modes
- `qa`: grounded answer generation with chunk-level citations
- `compare`: cross-paper structured comparison with claims and per-paper stances
- `lit_review`: structured multi-source literature review generation
- `monitoring` (frontend view): aggregated metrics from run logs

### Retrieval Stack
- Vector retrieval (Chroma similarity)
- Optional BM25 lexical retrieval (`rank-bm25`)
- Reciprocal Rank Fusion for hybrid merge
- Optional LLM query expansion (multi-query)
- Lightweight reranking using keyword overlap
- Session/document source filtering

### Citation and Evidence UX
- Citation payload includes: `source`, `page`, `chunk_id`, `snippet`, `score`
- Frontend opens PDF.js viewer anchored to citation page and search phrase
- Highlight creation from citation snippets
- Highlight semantic search + lexical fallback

### External Discovery/Import
Unified external search/import endpoints support:
- arXiv
- PubMed
- Semantic Scholar
- ACL (via Semantic Scholar filtering)
- medRxiv (via Semantic Scholar filtering)

Provider calls are guarded by retry + exponential backoff + per-provider circuit breaker.

## Repository Layout

```text
.
+-- backend/
¦   +-- config/                  # Django settings + URL root
¦   +-- rag/                     # RAG app (models, views, services, tests)
¦   +-- requirements.txt
¦   +-- Dockerfile
+-- frontend/
¦   +-- src/App.js               # Main app UI and client orchestration
¦   +-- src/api.js               # Frontend API client
¦   +-- src/App.css              # UI theme + layout styles
¦   +-- Dockerfile
+-- docker-compose.yml
+-- README.md
+-- TECHNICAL_DOCUMENTATION.md
```

## Backend API (Current)

Base prefix: `/api/`

- `POST /ask/`
- `POST /upload/`
- `GET /pdfs/`
- `DELETE /delete/`
- `GET /history/`
- `POST /session/`
- `GET /sessions/`
- `DELETE /session/<session_name>/`
- `GET /metrics/summary/`
- `GET /documents/<id>/status/`
- `GET /documents/<id>/page-text/?page=<1-indexed>`
- `POST /documents/<id>/retry/`
- `GET|POST /highlights/`
- `DELETE /highlights/<highlight_id>/`
- `GET /highlights/search/`
- `GET /search/external/`
- `POST /import/external/`
- Legacy arXiv-only routes still present:
  - `GET /arxiv/search/`
  - `POST /arxiv/import/`

## Data Model (Django)

Main tables:
- `Session`
- `Document` (status lifecycle + extracted metadata)
- `PaperSource` (external metadata and linkage)
- `Question`
- `Answer` (citations + optional metadata)
- `RunLog` (latency, mode, grounding, errors)
- `Highlight`
- `HighlightEmbedding`

## Runtime Dependencies

- Python: 3.11 (Dockerfile), project requirement `3.10+`
- Django: `>=5,<7` (currently generated from Django 6.0.1 project template)
- DRF, CORS headers
- LangChain ecosystem + Chroma
- Ollama local models (default: `mistral`, `nomic-embed-text`)
- React 19 frontend (`react-scripts`)

## Local Setup (Without Docker)

### 1) Start Ollama and pull models
```bash
ollama pull mistral
ollama pull nomic-embed-text
```

### 2) Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: .\\venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
python manage.py migrate
python manage.py runserver
```

Backend runs on `http://127.0.0.1:8000`

### 2b) Ingestion worker
Run the durable ingestion worker in a second shell:

```bash
cd backend
source venv/bin/activate  # Windows: .\\venv\\Scripts\\activate
python manage.py process_ingestion_jobs
```

### 3) Frontend
```bash
cd frontend
npm install
npm start
```

Frontend runs on `http://localhost:3000`

Optional frontend API override:
- `REACT_APP_API_BASE_URL=http://127.0.0.1:8000`

## Docker Setup

```bash
docker compose up --build
```

Services:
- `postgres` (15)
- `ollama`
- `backend` (`:8000`)
- `backend-worker` (durable ingestion/import worker)
- `frontend` (`:3000`)

Optional GPU pass-through (compose override exists):
- `docker-compose.gpu.yml` sets `gpus: all` for Ollama service

## Environment Variables (Backend)

Key variables from `backend/.env.example`:
- Django: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- DB: `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- CORS: `CORS_ALLOW_ALL`
- Ollama: `OLLAMA_BASE_URL`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`
- Chroma: `CHROMA_PERSIST_DIR`
- Retrieval/LLM knobs: `RAG_QA_*`, `RAG_LLM_*`
- Resilience: `EXTERNAL_API_RETRIES`, `EXTERNAL_API_RETRY_BACKOFF_SECONDS`, `EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD`, `EXTERNAL_API_CIRCUIT_OPEN_SECONDS`

## Current Behavior Notes

- Ingestion and external imports are queued in the database and processed by `python manage.py process_ingestion_jobs`.
- `Document.status` transitions: `QUEUED/UPLOADED -> PROCESSING -> INDEXED` or `FAILED`.
- Some imported sources ingest metadata-only (summary mode) when full PDF is unavailable.
- Citation pages are currently stored zero-indexed in chunk metadata; frontend displays as one-indexed.
- Session deletion removes session Chroma directory and attempts PDF cleanup when files are no longer referenced.

## Testing

Backend includes regression and flow tests under `backend/rag/`.

Run:
```bash
cd backend
python manage.py test rag -v 2
```

Notable suites:
- `rag.test_api_flows`
- `rag.test_citations_and_alignment`
- `rag.test_resilience`

## Known Gaps / Practical Caveats

- The ingestion worker is durable and database-backed, but still requires a separate long-lived worker process to be running.
- External provider rate limits and incomplete metadata vary by source.
- PubMed path currently imports primarily in metadata-summary mode.
- Some legacy helper scripts (`backend/test_query.py`, `backend/test_ingest.py`) are outdated relative to current function signatures.

## License

No explicit license file is currently present in the repository.

