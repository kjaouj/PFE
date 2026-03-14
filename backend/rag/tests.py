from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from rag.models import Document, IngestionJob, PaperSource, Session
from rag.services.resilience import CircuitOpenError, TransientExternalError
from rag.services.semanticscholar_service import SemanticScholarService
from rag.services.synthesis import SynthesisService


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


class ExternalImportQueueTests(TestCase):
    @patch.object(SemanticScholarService, "fetch_metadata")
    def test_semantic_scholar_import_enqueues_durable_job(self, mock_fetch_metadata):
        mock_fetch_metadata.return_value = {
            "external_id": "abc123",
            "title": "Queued paper",
            "authors": ["Alice", "Bob"],
            "abstract": "Abstract text",
            "published_date": "2026",
            "entry_url": "https://example.org/paper",
            "pdf_url": "https://example.org/paper.pdf",
            "source_type": "semanticscholar",
        }
        session = Session.objects.create(name="import-session")

        result = SemanticScholarService().import_paper("abc123", session.name)

        self.assertTrue(result["success"])
        self.assertIn("job_id", result)
        job = IngestionJob.objects.get(id=result["job_id"])
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(job.job_type, "SEMANTIC_SCHOLAR_IMPORT")


class LiteratureReviewSynthesisTests(SimpleTestCase):
    def test_generate_literature_review_formats_structured_cross_paper_output(self):
        docs = [
            type(
                "Doc",
                (),
                {"metadata": {"source": "a.pdf", "page": 0}, "page_content": "A chunk about retrievers."},
            )(),
            type(
                "Doc",
                (),
                {"metadata": {"source": "b.pdf", "page": 1}, "page_content": "B chunk about generation."},
            )(),
        ]

        responses = iter([
            "FOCUS: a.pdf studies retrieval pretraining.\nMETHODS: a.pdf uses retrieval-aware objectives.\nCONTRIBUTIONS: a.pdf improves retrieval-conditioned language modeling.\nLIMITATIONS: a.pdf leaves robustness underexplored.",
            "FOCUS: b.pdf studies retrieval-augmented generation.\nMETHODS: b.pdf injects retrieved evidence during generation.\nCONTRIBUTIONS: b.pdf improves generation with retrieval conditioning.\nLIMITATIONS: b.pdf leaves efficiency tradeoffs partially unresolved.",
            "- a.pdf and b.pdf both rely on explicit retrieval to improve downstream language modeling.",
            "- a.pdf emphasizes pretraining, whereas b.pdf emphasizes generation-time conditioning.",
            "- a.pdf uses retrieval-aware objectives, while b.pdf focuses on conditioning generation on retrieved evidence.",
            "- a.pdf and b.pdf both leave robustness and efficiency tradeoffs only partially resolved.",
            "- Together, a.pdf and b.pdf suggest retrieval is valuable, but system design depends on whether the focus is pretraining or generation.",
        ])
        service = SynthesisService()
        service.llm = type("StubLlm", (), {"invoke": lambda self, prompt: next(responses)})()

        result = service.generate_literature_review("retrieval directions", docs, ["a.pdf", "b.pdf"])

        self.assertEqual(result["num_sources"], 2)
        self.assertIn("1. Scope of Review", result["content"])
        self.assertIn("a.pdf", result["content"])
        self.assertIn("b.pdf", result["content"])
        self.assertNotIn("The text provided appears", result["content"])
        self.assertNotIn("did not return a valid structured review", result["content"])
