from langchain_chroma import Chroma
from langchain_ollama import OllamaLLM, OllamaEmbeddings

from rag.utils import get_session_path

from collections import Counter


def ask_with_citations(
    question: str,
    session_name: str,
    sources=None,
    docs_override=None,
    k: int = 8,  # Increased k for more context
):
    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    # USE OVERRIDE IF PROVIDED
    if docs_override is not None:
        docs = docs_override

    else:
        # Improved retrieval: if multiple sources, get a balanced set
        if sources and len(sources) > 1:
            all_docs = []
            per_source_k = max(2, k // len(sources))
            for src in sources:
                sdocs = vectordb.similarity_search(question, k=per_source_k, filter={"source": src})
                all_docs.extend(sdocs)
            docs = all_docs
        elif sources:
            docs = vectordb.similarity_search(
                question,
                k=k,
                filter={"source": {"$in": sources}}
            )
        else:
            docs = vectordb.similarity_search(question, k=k)


    if not docs:
        return {
            "answer": "I cannot find any relevant sections in the selected documents to answer this question.",
            "citations": []
        }

    # Normalize docs → text with source info
    context_parts = []
    for d in docs:
        source = d.metadata.get("source", "unknown")
        page = d.metadata.get("page", "?")
        content = d.page_content if hasattr(d, "page_content") else d
        context_parts.append(f"--- SOURCE: {source}, PAGE: {page} ---\n{content}")
    
    context = "\n\n".join(context_parts)

    llm = OllamaLLM(model="mistral")

    prompt = f"""You are a precise scientific research assistant.

INSTRUCTIONS:
1. Answer the question using ONLY the provided context.
2. If the answer isn't explicitly in the context but can be reasonably inferred based ONLY on the evidence provided, do so and state it is an inference.
3. If you truly cannot find the answer, don't just say "I can't answer". Instead, briefly summarize what the documents DO say about the topic, then explain what specific information is missing.
4. Use a professional, academic tone.
5. If multiple documents are provided, compare their findings if relevant.

CONTEXT:
{context}

QUESTION:
{question}

THINKING PROCESS:
(Analyze the context step-by-step before providing your final answer)

ANSWER:
"""

    response = llm.invoke(prompt)
    
    # Split to remove the thinking process from the final output if the model includes it
    if "ANSWER:" in response:
        final_answer = response.split("ANSWER:")[-1].strip()
    else:
        final_answer = response.strip()

    page_counts = Counter(
        (d.metadata.get("source"), d.metadata.get("page"))
        for d in docs
    )

    citations = [
        {
            "source": source,
            "page": page,
            "count": count
        }
        for (source, page), count in page_counts.items()
    ]

    return {
        "answer": final_answer,
        "citations": citations
    }



def retrieve_paper_overview(
    question: str,
    session_name: str,
    source: str,
    k_body: int = 4,
):
    """
    Retrieve a structured overview of a paper:
    - Always include abstract
    - Add top-k body chunks for reasoning
    """

    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )

    # ✅ 1. Retrieve ABSTRACT chunks (correct Chroma filter)
    abstract_docs = vectordb.similarity_search(
        "abstract",
        k=5,
        filter={
            "$and": [
                {"source": {"$eq": source}},
                {"section": {"$eq": "abstract"}},
            ]
        }
    )

    # ✅ 2. Retrieve BODY chunks (semantic)
    body_docs = vectordb.similarity_search(
        question,
        k=k_body,
        filter={
            "$and": [
                {"source": {"$eq": source}},
                {"section": {"$eq": "body"}},
            ]
        }
    )

    # ✅ 3. Combine
    docs = []
    docs.extend(abstract_docs)
    docs.extend(body_docs)

    return docs
