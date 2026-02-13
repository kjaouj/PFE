"""
Metrics Service

Logs and aggregates performance and quality metrics for RAG queries.
"""
import time
from typing import List, Dict, Any, Optional
from django.utils import timezone
from django.db.models import Avg, Count, F
from django.db.models.functions import TruncDate
from datetime import timedelta

from rag.models import RunLog, Session, Question

class MetricsService:
    """Service for logging and retrieving system metrics."""

    def log_query(
        self,
        session: Session,
        question_text: str,
        mode: str,
        latency_ms: int,
        retrieved_chunks: List[Dict],
        question: Optional[Question] = None,
        sources: Optional[List[str]] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        error: Optional[Exception] = None
    ) -> RunLog:
        """
        Log a single query execution.
        """
        error_type = type(error).__name__ if error else None
        error_message = str(error) if error else None

        log = RunLog.objects.create(
            session=session,
            question=question,
            question_text=question_text,
            mode=mode,
            sources=sources or [],
            latency_ms=latency_ms,
            retrieved_chunks=retrieved_chunks,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error_type=error_type,
            error_message=error_message
        )
        return log

    def get_summary(self, since_days: int = 7) -> Dict[str, Any]:
        """
        Aggregate metrics over a period of time.
        """
        start_date = timezone.now() - timedelta(days=since_days)
        logs = RunLog.objects.filter(created_at__gte=start_date)

        total_queries = logs.count()
        if total_queries == 0:
            return {
                "period": {"days": since_days},
                "queries": {"total": 0}
            }

        # Query stats
        by_mode = logs.values('mode').annotate(count=Count('id'))
        latency_avg = logs.aggregate(avg=Avg('latency_ms'))['avg']
        
        # Error stats
        errors = logs.exclude(error_type__isnull=True)
        error_count = errors.count()
        top_errors = errors.values('error_type').annotate(count=Count('id')).order_by('-count')[:5]

        # Retrieval stats
        # (This is simplified as retrieved_chunks is JSON)
        
        return {
            "period": {
                "start": start_date,
                "end": timezone.now(),
                "days": since_days
            },
            "queries": {
                "total": total_queries,
                "by_mode": {item['mode']: item['count'] for item in by_mode},
                "latency_avg_ms": int(latency_avg or 0),
            },
            "errors": {
                "count": error_count,
                "rate": round(error_count / total_queries, 3),
                "top_errors": list(top_errors)
            },
            "sessions": {
                "active_count": Session.objects.filter(run_logs__created_at__gte=start_date).distinct().count()
            }
        }
