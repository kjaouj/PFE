import logging
import requests
import time
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class SemanticScholarService:
    """Service for interacting with Semantic Scholar API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def _safe_request(self, url: str, params: Dict) -> Dict:
        """Helper to handle rate limits with exponential backoff retries."""
        for attempt in range(max_attempts := 5):
            try:
                response = requests.get(url, params=params, timeout=20)
                
                if response.status_code == 429:
                    # Exponential backoff: 5, 10, 20, 40...
                    wait = (2 ** attempt) * 5
                    logger.warning(f"Semantic Scholar Rate Limit (429). Attempt {attempt+1}/{max_attempts}. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                
                if response.status_code != 200:
                    logger.error(f"Semantic Scholar API Error {response.status_code}: {response.text}")
                
                response.raise_for_status()
                return response.json()
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Request attempt {attempt+1} failed: {e}")
                if attempt == max_attempts - 1:
                    raise
                time.sleep(2)
        
        return {}


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
                    'abstract': metadata['abstract']
                }
            )
            
            if not created:
                document.title = metadata['title']
                document.abstract = metadata['abstract']
                document.save()
            
            # Use provided source_type
            PaperSource.objects.get_or_create(
                source_type=source_type,
                external_id=paper_id,
                defaults={
                    'title': metadata['title'],
                    'authors': ", ".join(metadata['authors']),
                    'abstract': metadata['abstract'],
                    'pdf_url': pdf_url or "",
                    'document': document
                }
            )


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
                    except:
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
        authors = [a.get("name") for a in paper.get("authors", [])]
        pdf_info = paper.get("openAccessPdf")
        pdf_url = pdf_info.get("url") if pdf_info else None
        
        return {
            "external_id": paper.get("paperId", ""),
            "title": paper.get("title", "No Title"),
            "authors": authors,
            "abstract": paper.get("abstract", "No abstract available."),
            "published_date": str(paper.get("year", "N/A")),
            "entry_url": paper.get("url", ""),
            "pdf_url": pdf_url,
            "source_type": "semanticscholar"
        }

