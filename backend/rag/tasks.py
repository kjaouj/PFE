import threading
from django.utils import timezone
from .models import Document
from .ingest import ingest_pdf

def start_ingestion_thread(path: str, session_name: str, document_id: int):
    """
    Spawns a background thread to handle PDF ingestion.
    """
    thread = threading.Thread(
        target=background_ingestion_task,
        args=(path, session_name, document_id),
        daemon=True
    )
    thread.start()

def background_ingestion_task(path: str, session_name: str, document_id: int):
    """
    The actual task that runs in the background.
    """
    try:
        document = Document.objects.get(id=document_id)
        document.status = 'PROCESSING'
        document.processing_started_at = timezone.now()
        document.save(update_fields=['status', 'processing_started_at'])

        # Run the actual ingestion
        ingest_pdf(path, session_name, document)

        # Success
        document.status = 'INDEXED'
        document.processing_completed_at = timezone.now()
        document.error_message = None
        document.save(update_fields=['status', 'processing_completed_at', 'error_message'])

    except Exception as e:
        # Failure
        try:
            document = Document.objects.get(id=document_id)
            document.status = 'FAILED'
            document.error_message = str(e)
            document.save(update_fields=['status', 'error_message'])
        except:
            pass
        print(f"Ingestion failed for document {document_id}: {e}")
