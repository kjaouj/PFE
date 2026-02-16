# 📄 Technical Documentation: Scientific Research Navigator

This document provides a deep dive into the architecture, component roles, and strategic roadmap for the Scientific Research Navigator project. It is designed to serve as both a developer guide and a reference for the Mid-Course Defense.

---

## 🎯 1. MVP & Concept
**Core Statement**: A session-based RAG system that provides researchers with a "cognitive workspace" where they can ingest, query, and compare scientific papers with strict adherence to source material and zero-tolerance for hallucinations.

### User Scenarios
1. **Isolated Research**: A student researching "Graph Neural Networks" creates a dedicated session, uploads 5 papers, and asks for a synthesis of their methodologies without interference from other unrelated projects.
2. **Cross-Paper Comparison**: A researcher selects two papers with conflicting results and uses **Compare Mode** to automatically generate a table of claims and stances.
3. **Automated Lit Review**: A user provides a complex topic (e.g., "Impact of LLMs on Software Engineering") and generates a structured literature review based on a curated list of arXiv and PubMed imports.

---

## 🏗️ 2. Functional Flow & Architecture

The system follows a classic **Retrieval-Augmented Generation (RAG)** pipeline, modularized for multi-document and multi-source handling.

### Pipeline Flow
1. **Data Acquisition**: PDF Upload (Local) or API Import (arXiv, PubMed, etc.).
2. **Ingestion Layer**: `PyPDFLoader` extracts text -> `RecursiveCharacterTextSplitter` creates semantic chunks (1000 chars) -> Metadata enrichment (source, page, section).
3. **Vector Storage**: Chunks are embedded using `nomic-embed-text` and stored in a session-specific **ChromaDB** index.
4. **Retrieval**: User query is embedded -> Vector search finds top-K relevant chunks -> Source filtering ensures only selected documents are used.
5. **Synthesis**: `Mistral-7B` processes the context and query to generate grounded answers or structured JSON (for comparisons).

---

## 📊 3. Data Strategy
### Data Sources
- **Internal**: Local PDF files uploaded by the user.
- **External**: Integrated APIs for real-time scientific discovery:
    - **arXiv**: General physics, CS, math.
    - **PubMed**: Bio-medical and life sciences.
    - **Semantic Scholar**: Open research graph (used for metadata and search).
    - **ACL Anthology**: NLP and computational linguistics.
    - **medRxiv**: Pre-print health sciences.

### Data State & Volume
- **Format**: PDF for ingestion; JSON for metadata/search results.
- **Limits**: Current ingestion handles ~10-20 papers per session comfortably on local hardware. Vector stores are persists to disk for persistence.

---

## 🧠 4. Machine Learning Strategy
### Models
- **Embeddings (Baseline)**: `nomic-embed-text` (v1.5). Chosen for its 8k context window and high performance in document retrieval.
- **LLM (Core)**: `Mistral-7B` (via Ollama). Used for its balance of reasoning capability and local performance. 
- **System Prompting**: Strict grounding instructions are used to prevent hallucinations ("Answer ONLY using provided context").

### Why this strategy?
By running local models (Mistral/Nomic), we ensure **data privacy** for sensitive research and eliminate API costs, making it a sustainable tool for researchers.

---

## 📈 5. Evaluation Strategy
The system uses a **Monitoring-based Evaluation** approach via the `MetricsService`.

- **Metrics Tracked**:
    - **Latency**: End-to-end response time (Target: < 5s for QA).
    - **Error Rate**: Ratio of failed queries or ingestion timeouts.
    - **Session Activity**: Tracking unique session growth.
- **Monitoring Dashboard**: A real-time analytics interface in the frontend (accessible via the "Monitoring" tab) that visualizes these metrics using the internal `MetricsService`.
- **Protocol**: We use a "Golden Dataset" of known questions/answers for specific papers to manually validate the precision of citations.
- **Future Evaluation**: Planning to integrate **RAGAS** or **TruLens** for automated faithfulness and relevancy scoring.

---

## 🛠️ 6. Technical Component Reference

### Backend (Django)
| Script/Module | Role |
| :--- | :--- |
| `rag/models.py` | Defines relational schema for `Session`, `Document`, `Question`, and `RunLog`. |
| `rag/views.py` | Primary API endpoints for session management and RAG queries. |
| `rag/ingest.py` | Core logic for PDF loading, semantic chunking, and vector DB insertion. |
| `rag/query.py` | Handles retrieval logic and LLM prompting for QA mode. |
| `rag/router.py` | Categorizes questions (e.g., "What is this paper about?") to optimize retrieval strategy. |
| `services/synthesis.py` | Advanced logic for **Compare** and **Lit Review** modes (JSON parsing from LLM). |
| `services/metrics.py` | Aggregates performance data for the dashboard. |
| `services/*_service.py` | Dedicated connectors for external APIs (arXiv, PubMed, etc.). |

### Frontend (React)
| Component | Role |
| :--- | :--- |
| `App.js` | Main application state, monitoring dashboard, and polling for ingest status. |
| `App.css` | Custom styling for the Dark/Light mode academic interface and metrics grid. |

---

## 📅 7. Roadmap (Plan pour la suite)
- **Phase 1 (Current)**: Multi-source search and basic QA/Compare modes operational.
- **Phase 2 (Late Feb)**: Implement recursive retrieval for better handling of complex questions. Enhance metadata extraction (Author, DOI).
- **Phase 3 (March)**: Interactive PDF Viewer (viewer.js) to highlight cited text directly in the browser.
- **Final Milestone**: Full deployment and performance optimization for concurrent users.
