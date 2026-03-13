from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from rag.models import Document, PaperSource, Session
from rag.services.resilience import CircuitOpenError, TransientExternalError
from rag.services.semanticscholar_service import SemanticScholarService


class SemanticScholarServiceTests(SimpleTestCase):
    def test_extract_metadata_normalizes_null_fields(self):
        service = SemanticScholarService()

        metadata = service._extract_metadata(
            {
                "paperId": "abc123",
                "title": "Clinical Paper",
                "authors": [{"name": "Author One"}, {"name": None}],
                "abstract": None,
                "url": None,
                "year": 2026,
                "openAccessPdf": None,
            }
        )

        self.assertEqual(metadata["external_id"], "abc123")
        self.assertEqual(metadata["authors"], ["Author One"])
        self.assertEqual(metadata["abstract"], "No abstract available.")
        self.assertEqual(metadata["entry_url"], "")
        self.assertEqual(metadata["published_date"], "2026")


class ExternalViewErrorMappingTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("rag.views_external.SemanticScholarService.search")
    def test_external_search_maps_transient_errors_to_429(self, mock_search):
        mock_search.side_effect = TransientExternalError("Semantic Scholar rate limited (429)")

        response = self.client.get("/api/search/external/?q=llm&source=semanticscholar")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"], "Semantic Scholar rate limited (429)")

    @patch("rag.views_external.SemanticScholarService.search")
    def test_external_search_maps_open_circuit_to_503(self, mock_search):
        mock_search.side_effect = CircuitOpenError("Circuit open for provider 'semanticscholar' during 'request'")

        response = self.client.get("/api/search/external/?q=llm&source=semanticscholar")

        self.assertEqual(response.status_code, 503)


class DocumentPageTextTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session = Session.objects.create(name="page-text-session")

    def test_document_page_text_falls_back_to_metadata_for_virtual_documents(self):
        document = Document.objects.create(
            filename="pubmed_1234.pdf",
            session=self.session,
            title="Sample title",
            abstract="Sample abstract",
            status="INDEXED",
            error_message="Note: Full PDF was unavailable. Summary-only mode.",
        )
        PaperSource.objects.create(
            document=document,
            source_type="pubmed",
            external_id="1234",
            title="Sample title",
            authors="Alice Smith, Bob Jones",
            abstract="Sample abstract",
            entry_url="https://pubmed.ncbi.nlm.nih.gov/1234/",
        )

        response = self.client.get(f"/api/documents/{document.id}/page-text/?page=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content_type"], "text")
        self.assertIn("TITLE: Sample title", response.data["text"])
        self.assertIn("ABSTRACT:", response.data["text"])
