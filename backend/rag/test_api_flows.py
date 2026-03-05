from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from rag.models import Document, Session


class _ImmediateThread:
    def __init__(self, target=None, args=None, kwargs=None, daemon=None):
        self._target = target
        self._args = args or ()
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


class ApiFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session_name = "e2e-session"
        Session.objects.create(name=self.session_name)

    @patch("rag.views.threading.Thread", _ImmediateThread)
    @patch("rag.views.IngestionService.ingest_document")
    def test_upload_and_list_documents_flow(self, mock_ingest_document):
        mock_ingest_document.return_value = {"status": "success"}
        file_obj = SimpleUploadedFile(
            "sample.pdf",
            b"%PDF-1.4 fake",
            content_type="application/pdf",
        )

        upload_response = self.client.post(
            "/api/upload/",
            {"file": file_obj, "session": self.session_name},
            format="multipart",
        )
        self.assertEqual(upload_response.status_code, 202)
        self.assertIn("document_id", upload_response.data)
        self.assertTrue(Document.objects.filter(id=upload_response.data["document_id"]).exists())

        list_response = self.client.get(f"/api/pdfs/?session={self.session_name}")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data["pdfs"]), 1)

    @patch("rag.views.ask_with_citations")
    def test_ask_returns_citations(self, mock_ask_with_citations):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="qa.pdf",
            session=session,
            status="INDEXED",
        )
        mock_ask_with_citations.return_value = {
            "answer": "Test answer",
            "citations": [
                {
                    "source": doc.filename,
                    "page": 0,
                    "chunk_id": "c1",
                    "snippet": "evidence",
                    "score": 0.91,
                }
            ],
            "is_refusal": False,
            "is_insufficient_evidence": False,
            "retrieved_chunks_count": 1,
            "confidence_score": 0.91,
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "What is the evidence?",
                "session": self.session_name,
                "sources": [doc.filename],
                "mode": "qa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["answer"], "Test answer")
        self.assertEqual(len(response.data["citations"]), 1)
        self.assertEqual(response.data["citations"][0]["source"], doc.filename)

    @patch("rag.views_highlights.HighlightService.index_highlight")
    @patch("rag.views_highlights.HighlightService.search_highlights")
    def test_highlight_create_and_search_flow(
        self,
        mock_search_highlights,
        mock_index_highlight,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="hl.pdf", session=session, status="INDEXED")
        mock_index_highlight.return_value = "hl_1"
        mock_search_highlights.return_value = [
            {
                "id": 1,
                "document_id": doc.id,
                "filename": doc.filename,
                "page": 1,
                "start_offset": 0,
                "end_offset": 10,
                "text": "highlight text",
                "note": "",
                "tags": [],
                "score": 0.8,
            }
        ]

        create_res = self.client.post(
            "/api/highlights/",
            {
                "document_id": doc.id,
                "page": 1,
                "start_offset": 0,
                "end_offset": 14,
                "text": "highlight text",
                "note": "note",
                "tags": ["tag1"],
            },
            format="json",
        )
        self.assertEqual(create_res.status_code, 201)
        self.assertEqual(create_res.data["filename"], doc.filename)
        self.assertTrue(create_res.data["embedding_indexed"])

        search_res = self.client.get(
            f"/api/highlights/search/?session={self.session_name}&q=highlight"
        )
        self.assertEqual(search_res.status_code, 200)
        self.assertEqual(len(search_res.data["results"]), 1)
        self.assertEqual(search_res.data["results"][0]["filename"], doc.filename)
