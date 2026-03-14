import tempfile
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from langchain_core.documents import Document as LangchainDocument
from rest_framework.test import APIClient

from rag.models import Document, IngestionJob, Session
from rag.services.retrieval import ScoredDocument


class ApiFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session_name = "e2e-session"
        Session.objects.create(name=self.session_name)

    def test_upload_and_list_documents_flow(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
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
            self.assertTrue(IngestionJob.objects.filter(id=upload_response.data["job_id"]).exists())

            list_response = self.client.get(f"/api/pdfs/?session={self.session_name}")
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(len(list_response.data["pdfs"]), 1)
            self.assertEqual(list_response.data["pdfs"][0]["storage_path"], "pdfs/sample.pdf")
            self.assertEqual(list_response.data["pdfs"][0]["file_url"], "/media/pdfs/sample.pdf")

    def test_duplicate_upload_name_keeps_real_storage_path(self):
        other_session = Session.objects.create(name="other-session")

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            first_upload = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("sample.pdf", b"%PDF-1.4 first", content_type="application/pdf"),
                    "session": self.session_name,
                },
                format="multipart",
            )
            self.assertEqual(first_upload.status_code, 202)

            second_upload = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("sample.pdf", b"%PDF-1.4 second", content_type="application/pdf"),
                    "session": other_session.name,
                },
                format="multipart",
            )
            self.assertEqual(second_upload.status_code, 202)

            second_doc = Document.objects.get(id=second_upload.data["document_id"])
            self.assertEqual(second_doc.filename, "sample.pdf")
            self.assertTrue(second_doc.storage_path.startswith("pdfs/sample_"))
            self.assertNotEqual(second_doc.storage_path, "pdfs/sample.pdf")

            list_response = self.client.get(f"/api/pdfs/?session={other_session.name}")
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(list_response.data["pdfs"][0]["storage_path"], second_doc.storage_path)
            self.assertEqual(list_response.data["pdfs"][0]["file_url"], f"/media/{second_doc.storage_path}")

    @patch("rag.services.ingestion.IngestionService.ingest_document")
    def test_worker_processes_queued_upload_job(self, mock_ingest_document):
        mock_ingest_document.return_value = {"status": "success"}

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            upload_response = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("queued.pdf", b"%PDF-1.4 fake", content_type="application/pdf"),
                    "session": self.session_name,
                },
                format="multipart",
            )

            self.assertEqual(upload_response.status_code, 202)
            job = IngestionJob.objects.get(id=upload_response.data["job_id"])
            self.assertEqual(job.status, "QUEUED")

            call_command("process_ingestion_jobs", "--once")

            job.refresh_from_db()
            self.assertEqual(job.status, "SUCCEEDED")
            mock_ingest_document.assert_called_once()

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

    def test_lit_review_requires_two_selected_documents(self):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="solo.pdf", session=session, status="INDEXED")

        response = self.client.post(
            "/api/ask/",
            {
                "question": "Summarize themes and gaps",
                "session": self.session_name,
                "sources": [doc.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("requires at least 2", response.data["error"])

    @patch("rag.views.SynthesisService.generate_literature_review")
    @patch("rag.views.RetrievalService.retrieve")
    def test_lit_review_returns_citations_for_cross_paper_synthesis(
        self,
        mock_retrieve,
        mock_generate_review,
    ):
        session = Session.objects.get(name=self.session_name)
        doc_a = Document.objects.create(filename="a.pdf", session=session, status="INDEXED")
        doc_b = Document.objects.create(filename="b.pdf", session=session, status="INDEXED")
        mock_retrieve.return_value = [
            ScoredDocument(
                LangchainDocument(page_content="Shared approach", metadata={"source": doc_a.filename, "page": 0}),
                score=0.9,
                chunk_id="a1",
            ),
            ScoredDocument(
                LangchainDocument(page_content="Open problem", metadata={"source": doc_b.filename, "page": 1}),
                score=0.8,
                chunk_id="b1",
            ),
        ]
        mock_generate_review.return_value = {
            "title": "Literature Review: test",
            "content": "Structured review",
            "num_sources": 2,
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "Summarize themes and gaps",
                "session": self.session_name,
                "sources": [doc_a.filename, doc_b.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content"], "Structured review")
        self.assertEqual(len(response.data["citations"]), 2)

    @patch("rag.views.SynthesisService.generate_literature_review")
    @patch("rag.views.RetrievalService.retrieve")
    def test_lit_review_balances_retrieval_across_selected_sources(
        self,
        mock_retrieve,
        mock_generate_review,
    ):
        session = Session.objects.get(name=self.session_name)
        doc_a = Document.objects.create(filename="a.pdf", session=session, status="INDEXED")
        doc_b = Document.objects.create(filename="b.pdf", session=session, status="INDEXED")

        def _retrieve(*, query, sources, k, use_hybrid, use_multi_query, use_reranking):
            source = sources[0]
            return [
                ScoredDocument(
                    LangchainDocument(
                        page_content=f"chunk for {source}",
                        metadata={"source": source, "page": 0},
                    ),
                    score=0.9 if source == "a.pdf" else 0.8,
                    chunk_id=f"{source}-1",
                )
            ]

        mock_retrieve.side_effect = _retrieve
        mock_generate_review.return_value = {
            "title": "Literature Review: test",
            "content": "Structured review",
            "num_sources": 2,
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "What are the main directions?",
                "session": self.session_name,
                "sources": [doc_a.filename, doc_b.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_retrieve.call_count, 2)
        called_sources = {call.kwargs["sources"][0] for call in mock_retrieve.call_args_list}
        self.assertEqual(called_sources, {"a.pdf", "b.pdf"})

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

    @patch("rag.services.ollama_client.create_embeddings")
    @patch("langchain_chroma.Chroma")
    @patch("rag.views.default_storage.delete")
    @patch("rag.views.default_storage.exists")
    def test_delete_pdf_uses_document_storage_path(
        self,
        mock_exists,
        mock_delete,
        mock_chroma_cls,
        mock_create_embeddings,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="sample.pdf",
            storage_path="pdfs/sample_abcd123.pdf",
            session=session,
            status="INDEXED",
        )
        mock_exists.return_value = True
        mock_create_embeddings.return_value = Mock()
        mock_chroma = Mock()
        mock_chroma.get.return_value = {"ids": []}
        mock_chroma_cls.return_value = mock_chroma

        response = self.client.delete(
            "/api/delete/",
            {"session": self.session_name, "filename": doc.filename},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        mock_delete.assert_called_once_with("pdfs/sample_abcd123.pdf")
