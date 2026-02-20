import time
import threading
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Session, Document, Question, Answer, RunLog, PaperSource
from .utils import get_default_session, normalize_filename
from .query import ask_with_citations, retrieve_paper_overview
from .ingest import ingest_pdf

from .services.ingestion import IngestionService
from .services.metrics import MetricsService
from .services.synthesis import SynthesisService

from .router import is_title_question, is_about_paper_question, is_page_count_question

@api_view(["GET"])
def document_status(request, document_id):
    """
    Get detailed status of a document ingestion.
    """
    try:
        document = Document.objects.get(id=document_id)

        processing_time = None
        if document.processing_started_at and document.processing_completed_at:
            processing_time = (
                document.processing_completed_at - document.processing_started_at
            ).total_seconds()

        return Response({
            "document_id": document.id,
            "filename": document.filename,
            "session": document.session.name,
            "status": document.status,
            "uploaded_at": document.uploaded_at,
            "processing_started_at": document.processing_started_at,
            "processing_completed_at": document.processing_completed_at,
            "processing_time_seconds": processing_time,
            "error_message": document.error_message,
            "metadata": {
                "title": document.title,
                "abstract": document.abstract,
                "page_count": document.page_count
            }
        }, status=status.HTTP_200_OK)

    except Document.DoesNotExist:
        return Response(
            {"error": "Document not found"},
            status=status.HTTP_404_NOT_FOUND
        )

@api_view(["GET"])
def metrics_summary(request):
    """
    Get aggregated metrics for monitoring dashboard.
    """
    since_days = request.GET.get("since", "7")
    try:
        since_days = int(since_days)
    except ValueError:
        since_days = 7

    metrics_service = MetricsService()
    summary = metrics_service.get_summary(since_days=since_days)
    return Response(summary, status=status.HTTP_200_OK)

@api_view(["POST"])
def ask_question(request):
    question_text = request.data.get("question")
    session_name = request.data.get("session")
    sources = request.data.get("sources") or []
    mode = request.data.get("mode", "qa")  # New: mode support

    if not question_text:
        return Response(
            {"error": "Missing 'question'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Normalize sources
    sources = [normalize_filename(s) for s in sources]

    # Resolve session
    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response(
            {"error": f"Session '{session_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    question_obj = Question.objects.create(
        text=question_text,
        session=session
    )

    start_time = time.time()
    metrics_service = MetricsService()
    synthesis_service = SynthesisService()
    retrieved_chunks = []

    try:
        if mode == "compare":
            # Comparison mode logic
            from langchain_chroma import Chroma
            from langchain_ollama import OllamaEmbeddings
            from .utils import get_session_path
            
            persist_dir = get_session_path(session.name)
            embeddings = OllamaEmbeddings(model="nomic-embed-text")
            vectordb = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
            
            if sources and len(sources) > 1:
                # Per-source retrieval to ensure multidocument awareness
                all_docs = []
                for src in sources:
                    sdocs = vectordb.similarity_search(question_text, k=4, filter={"source": src})
                    all_docs.extend(sdocs)
                docs = all_docs
            else:
                docs = vectordb.similarity_search(question_text, k=10, filter={"source": {"$in": sources}} if sources else None)
            
            retrieved_chunks = [
                {"doc": d.metadata.get("source"), "page": d.metadata.get("page"), "score": 0.0}
                for d in docs
            ]
            
            result = synthesis_service.compare_papers(question_text, docs, sources)
            
            Answer.objects.create(
                question=question_obj,
                text=f"Comparison on: {question_text}",
                citations=[],
                metadata=result
            )

        elif mode == "lit_review":
            from langchain_chroma import Chroma
            from langchain_ollama import OllamaEmbeddings
            from .utils import get_session_path
            
            persist_dir = get_session_path(session.name)
            embeddings = OllamaEmbeddings(model="nomic-embed-text")
            vectordb = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
            
            if sources and len(sources) > 1:
                all_docs = []
                for src in sources:
                    sdocs = vectordb.similarity_search(question_text, k=5, filter={"source": src})
                    all_docs.extend(sdocs)
                docs = all_docs
            else:
                docs = vectordb.similarity_search(question_text, k=15, filter={"source": {"$in": sources}} if sources else None)
            
            retrieved_chunks = [
                {"doc": d.metadata.get("source"), "page": d.metadata.get("page"), "score": 0.0}
                for d in docs
            ]
            
            result = synthesis_service.generate_literature_review(question_text, docs, sources)
            
            Answer.objects.create(
                question=question_obj,
                text=result.get("content", ""),
                citations=[],
                metadata={
                    "title": result.get("title"),
                    "mode": "lit_review"
                }
            )

        else:
            # Existing QA Logic
            if is_title_question(question_text) and sources:
                doc = Document.objects.get(session=session, filename=sources[0])
                result = {"answer": doc.title or "Title not available.", "citations": []}
            elif is_page_count_question(question_text) and sources:
                doc = Document.objects.get(session=session, filename=sources[0])
                result = {"answer": f"The document '{doc.filename}' has {doc.page_count or 'unknown'} pages.", "citations": []}
            elif is_about_paper_question(question_text) and sources:
                docs = retrieve_paper_overview(question=question_text, session_name=session.name, source=sources[0])
                result = ask_with_citations(question=question_text, session_name=session.name, docs_override=docs)
            else:
                result = ask_with_citations(question=question_text, session_name=session.name, sources=sources or None)

            Answer.objects.create(
                question=question_obj,
                text=result["answer"],
                citations=result["citations"]
            )
            
            retrieved_chunks = [
                {"doc": c["source"], "page": c["page"], "score": 0.0}
                for c in result.get("citations", [])
            ]

        # Log metrics
        latency_ms = int((time.time() - start_time) * 1000)
        metrics_service.log_query(
            session=session,
            question=question_obj,
            question_text=question_text,
            mode=mode,
            sources=sources,
            latency_ms=latency_ms,
            retrieved_chunks=retrieved_chunks
        )

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        metrics_service.log_query(
            session=session,
            question=question_obj,
            question_text=question_text,
            mode=mode,
            sources=sources,
            latency_ms=latency_ms,
            retrieved_chunks=retrieved_chunks,
            error=e
        )
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)





@api_view(["POST"])
def upload_pdf(request):
    """
    Upload a PDF file and trigger async ingestion.
    """
    file = request.FILES.get("file")
    session_name = request.POST.get("session")

    if not file:
        return Response(
            {"error": "No file provided"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not file.name.lower().endswith(".pdf"):
        return Response(
            {"error": "Only PDF files are allowed"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Resolve session
    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response(
            {"error": f"Session '{session_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    # Save file
    saved_path = default_storage.save(
        f"pdfs/{file.name}",
        ContentFile(file.read())
    )

    full_path = Path(default_storage.path(saved_path))
    normalized = normalize_filename(file.name)

    # Register document in relational DB
    document, created = Document.objects.get_or_create(
        filename=normalized,
        session=session
    )

    # Reset status if re-uploading
    if not created:
        document.status = 'UPLOADED'
        document.error_message = None
        document.processing_started_at = None
        document.processing_completed_at = None
        document.save()

    # Trigger async ingestion
    def ingest_in_background():
        service = IngestionService()
        service.ingest_document(document.id, str(full_path))

    thread = threading.Thread(target=ingest_in_background, daemon=True)
    thread.start()

    return Response(
        {
            "message": "PDF upload initiated. Processing in background.",
            "document_id": document.id,
            "filename": file.name,
            "session": session.name,
            "status": document.status
        },
        status=status.HTTP_202_ACCEPTED
    )


@api_view(["GET"])
def list_pdfs(request):
    """
    List PDFs available in a session.
    """
    session_name = request.GET.get("session")

    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response(
            {"error": f"Session '{session_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    pdfs = session.documents.values(
        "id",
        "filename",
        "title",
        "abstract",
        "status",
        "error_message"
    )


    return Response(
        {
            "session": session.name,
            "pdfs": list(pdfs),
        },
        status=status.HTTP_200_OK
    )


@api_view(["POST"])
def create_session(request):
    name = request.data.get("name")

    if not name:
        return Response(
            {"error": "Session name required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    session, created = Session.objects.get_or_create(name=name)

    return Response(
        {
            "session": session.name,
            "created": created
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )


@api_view(["GET"])
def list_sessions(request):
    sessions = Session.objects.all().order_by("-created_at")
    data = [{"name": s.name, "created_at": s.created_at} for s in sessions]
    return Response(data, status=status.HTTP_200_OK)


@api_view(["DELETE"])
def delete_session(request, session_name):
    try:
        session = Session.objects.get(name=session_name)
        # Chroma cleanup: get the path and delete the directory
        import shutil
        from .utils import get_session_path
        persist_dir = get_session_path(session_name)
        if Path(persist_dir).exists():
            shutil.rmtree(persist_dir)
            
        # Filesystem cleanup: potentially delete all PDFs unique to this session
        for doc in session.documents.all():
            other_uses = Document.objects.filter(filename=doc.filename).exclude(id=doc.id).exists()
            if not other_uses:
                file_path = f"pdfs/{doc.filename}"
                if default_storage.exists(file_path):
                    default_storage.delete(file_path)
        
        session.delete()
        return Response({"message": "Session and all associated data deleted"}, status=status.HTTP_200_OK)
    except Session.DoesNotExist:
        return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(["DELETE"])
def delete_pdf(request):
    """
    Remove a PDF from a session:
    1. Delete from relational DB
    2. Delete from Chroma vector store
    3. Cleanup physical file if no other session uses it
    """
    session_name = request.data.get("session")
    filename = request.data.get("filename")

    if not session_name or not filename:
        return Response(
            {"error": "Missing 'session' or 'filename'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        session = Session.objects.get(name=session_name)
        document = Document.objects.get(session=session, filename=filename)
    except (Session.DoesNotExist, Document.DoesNotExist):
        return Response(
            {"error": "Document or Session not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # 1. Delete from Chroma
    from langchain_chroma import Chroma
    from langchain_ollama import OllamaEmbeddings
    from .utils import get_session_path

    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    try:
        # Get IDs of documents to delete
        res = vectordb.get(where={"source": filename})
        if res["ids"]:
            vectordb.delete(ids=res["ids"])
    except Exception as e:
        print(f"Error deleting from Chroma: {e}")

    # 2. Delete from Filesystem
    file_path = f"pdfs/{filename}"
    other_uses = Document.objects.filter(filename=filename).exclude(id=document.id).exists()
    if not other_uses:
        if default_storage.exists(file_path):
            default_storage.delete(file_path)

    # 3. Delete from Relational DB
    document.delete()

    return Response(
        {"message": f"Document '{filename}' deleted successfully"},
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
def get_history(request):
    session_name = request.GET.get("session")
    
    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
        questions = session.questions.all().order_by("created_at")
        
        history = []
        for q in questions:
            history.append({
                "role": "user",
                "text": q.text,
            })
            # Try to get the answer
            try:
                a = q.answer
                item = {
                    "role": "assistant",
                    "text": a.text,
                    "citations": a.citations
                }
                # Include metadata (comparison, title, etc.)
                if a.metadata:
                    if "claims" in a.metadata:
                        item["comparison"] = a.metadata
                    if "title" in a.metadata:
                        item["title"] = a.metadata["title"]
                
                history.append(item)
            except Answer.DoesNotExist:
                pass
                
        return Response({"history": history}, status=status.HTTP_200_OK)
    except Session.DoesNotExist:
        return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
