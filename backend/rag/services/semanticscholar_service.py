import logging
import requests
from datetime import datetime
from typing import List, Dict

from rag.services.resilience import (
    call_with_resilience,
    CircuitOpenError,
    TransientExternalError,
)

logger = logging.getLogger(__name__)

class SemanticScholarService:
    """Service for interacting with Semantic Scholar API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    @staticmethod
    def _safe_text(value, default: str = "") -> str:
        """Normalize provider strings because Semantic Scholar often returns explicit nulls."""
        if value is None:
            return default
        return str(value).strip()

    def _safe_request(self, url: str, params: Dict) -> Dict:
        """Semantic Scholar request with retry and circuit breaker."""

        def _request() -> Dict:
            response = requests.get(url, params=params, timeout=20)
            if response.status_code == 429:
                raise TransientExternalError("Semantic Scholar rate limited (429)")
            response.raise_for_status()
            return response.json()

        try:
            return call_with_resilience(
                provider="semanticscholar",
                operation="request",
                func=_request,
                retry_exceptions=(
                    requests.exceptions.RequestException,
                    TransientExternalError,
                ),
            )
        except CircuitOpenError:
            raise


    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search Semantic Scholar.
        """
        logger.info(f"Searching Semantic Scholar: query='{query}'")

        try:
            url = f"{self.BASE_URL}/paper/search"
            params = {
                "query": query,
                "limit": max_results,
                "fields": "title,authors,abstract,url,year,externalIds,openAccessPdf"
            }
            
            data = self._safe_request(url, params)
            results = []
            for paper in data.get("data", []):
                results.append(self._extract_metadata(paper))

            return results

        except Exception as e:
            logger.error(f"Semantic Scholar search failed: {e}")
            raise

    def fetch_metadata(self, paper_id: str) -> Dict:
        """Fetch metadata for a specific paper."""
        url = f"{self.BASE_URL}/paper/{paper_id}"
        params = {"fields": "title,authors,abstract,url,year,externalIds,openAccessPdf"}
        data = self._safe_request(url, params)
        return self._extract_metadata(data)

    def import_paper(self, paper_id: str, session_name: str, source_type: str = 'doi') -> Dict:
        """Import from Semantic Scholar with PDF fallback to Abstract."""
        import os
        import threading
        from pathlib import Path
        from django.conf import settings
        from rag.models import Session, Document, PaperSource
        from rag.services.ingestion import IngestionService
        from rag.utils import normalize_filename

        try:
            metadata = self.fetch_metadata(paper_id)
            session = Session.objects.get(name=session_name)
            
            pdf_url = metadata.get('pdf_url')
            safe_filename = normalize_filename(f"scholar_{paper_id[:8]}.pdf" if pdf_url else f"scholar_{paper_id[:8]}_abstract.txt")
            
            document, created = Document.objects.get_or_create(
                filename=safe_filename, 
                session=session,
                defaults={
                    'title': metadata['title'],
                    'abstract': metadata['abstract'],
                }
            )
            
            if not created:
                document.title = metadata['title']
                document.abstract = metadata['abstract']
                document.save()
            
            published_date = None
            year_text = self._safe_text(metadata.get("published_date"))
            if year_text and year_text.isdigit():
                published_date = datetime(int(year_text), 1, 1).date()

            paper_source, paper_source_created = PaperSource.objects.get_or_create(
                source_type=source_type,
                external_id=paper_id,
                defaults={
                    'title': metadata['title'],
                    'authors': ", ".join(metadata['authors']),
                    'abstract': metadata['abstract'],
                    'published_date': published_date,
                    'pdf_url': pdf_url or "",
                    'entry_url': metadata.get("entry_url", ""),
                    'document': document
                }
            )
            if not paper_source_created:
                paper_source.title = metadata["title"]
                paper_source.authors = ", ".join(metadata["authors"])
                paper_source.abstract = metadata["abstract"]
                paper_source.published_date = published_date
                paper_source.pdf_url = pdf_url or ""
                paper_source.entry_url = metadata.get("entry_url", "")
                paper_source.document = document
                paper_source.save()


            def background_import(doc_id, url, meta):
                from rag.models import Document
                from rag.services.ingestion import IngestionService
                try:
                    ingestion = IngestionService()
                    if url:
                        # Attempt PDF download
                        save_dir = os.path.join(settings.MEDIA_ROOT, "pdfs")
                        Path(save_dir).mkdir(parents=True, exist_ok=True)
                        doc = Document.objects.get(id=doc_id)
                        doc.status = 'PROCESSING'
                        doc.save()
                        
                        filepath = os.path.join(save_dir, doc.filename)
                        resp = requests.get(url, stream=True, timeout=30)
                        resp.raise_for_status()
                        with open(filepath, 'wb') as f:
                            for chunk in resp.iter_content(chunk_size=8192):
                                f.write(chunk)
                        
                        ingestion.ingest_document(doc.id, filepath)
                    else:
                        # Fallback to metadata ingestion
                        ingestion.ingest_metadata_only(
                            doc_id, 
                            meta['title'], 
                            meta['abstract'], 
                            ", ".join(meta['authors'])
                        )
                    PaperSource.objects.filter(source_type=source_type, external_id=paper_id).update(
                        document_id=doc_id,
                        imported=True,
                    )
                except Exception as e:
                    logger.error(f"Scholar import failed: {e}")
                    # If PDF failed, try abstract fallback as last resort
                    try:
                        ingestion.ingest_metadata_only(
                            doc_id, 
                            meta['title'], 
                            meta['abstract'], 
                            ", ".join(meta['authors'])
                        )
                        PaperSource.objects.filter(source_type=source_type, external_id=paper_id).update(
                            document_id=doc_id,
                            imported=True,
                        )
                    except Exception:
                        doc = Document.objects.get(id=doc_id)
                        doc.status = 'FAILED'
                        doc.error_message = str(e)
                        doc.save()

            threading.Thread(target=background_import, args=(document.id, pdf_url, metadata), daemon=True).start()
            return {"success": True, "message": "Import initiated (Summary fallback enabled)"}

        except Exception as e:
            logger.error(f"Scholar import failed: {e}")
            raise

    def _extract_metadata(self, paper: Dict) -> Dict:
        """Unified dictionary structure."""
        authors = [
            self._safe_text(a.get("name"))
            for a in paper.get("authors", [])
            if self._safe_text(a.get("name"))
        ]
        pdf_info = paper.get("openAccessPdf")
        pdf_url = pdf_info.get("url") if pdf_info else None
        
        return {
            "external_id": self._safe_text(paper.get("paperId")),
            "title": self._safe_text(paper.get("title"), "No Title"),
            "authors": authors,
            "abstract": self._safe_text(paper.get("abstract"), "No abstract available."),
            "published_date": self._safe_text(paper.get("year"), ""),
            "entry_url": self._safe_text(paper.get("url")),
            "pdf_url": pdf_url,
            "source_type": "semanticscholar"
        }

