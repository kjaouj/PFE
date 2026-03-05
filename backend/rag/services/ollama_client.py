import logging
from pathlib import Path
from typing import List, Optional

import requests
from django.conf import settings
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from functools import lru_cache

logger = logging.getLogger(__name__)


def _in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _candidate_base_urls() -> List[str]:
    configured = getattr(settings, "OLLAMA_BASE_URL", "").strip()
    candidates: List[str] = []

    if configured:
        candidates.append(configured)

    if _in_docker():
        candidates.extend(
            [
                "http://host.docker.internal:11434",
                "http://172.17.0.1:11434",
            ]
        )

    candidates.append("http://localhost:11434")

    seen = set()
    deduped: List[str] = []
    for url in candidates:
        normalized = url.rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


@lru_cache(maxsize=1)
def resolve_ollama_base_url(timeout_seconds: float = 1.5) -> Optional[str]:
    for base_url in _candidate_base_urls():
        try:
            response = requests.get(
                f"{base_url}/api/tags",
                timeout=timeout_seconds,
            )
            if response.status_code < 500:
                return base_url
        except requests.RequestException:
            continue

    candidates = ", ".join(_candidate_base_urls())
    logger.error(f"Ollama is unreachable. Tried: {candidates}")
    return _candidate_base_urls()[0] if _candidate_base_urls() else None


def create_embeddings(model: str = "nomic-embed-text") -> OllamaEmbeddings:
    base_url = resolve_ollama_base_url()
    kwargs = {"model": model}
    if base_url:
        kwargs["base_url"] = base_url
    return OllamaEmbeddings(**kwargs)


def create_llm(model: str = "mistral") -> OllamaLLM:
    base_url = resolve_ollama_base_url()
    kwargs = {
        "model": model,
        "temperature": getattr(settings, "RAG_LLM_TEMPERATURE", 0.2),
        "num_predict": getattr(settings, "RAG_LLM_NUM_PREDICT", 320),
        "num_ctx": getattr(settings, "RAG_LLM_NUM_CTX", 4096),
        "keep_alive": getattr(settings, "RAG_LLM_KEEP_ALIVE", "30m"),
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OllamaLLM(**kwargs)
