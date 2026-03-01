"""
Multi-document synthesis service for compare and literature review modes.

This service provides cross-document analysis capabilities:
- Compare mode: Identifies claims and stances across multiple papers
- Literature review mode: Generates structured reviews with citations
"""

import json
from typing import List, Dict, Any, Optional
from collections import defaultdict
from rag.services.ollama_client import create_llm


class SynthesisService:
    """Service for multi-document analysis and synthesis."""

    def __init__(self, model: str = "mistral"):
        """
        Initialize synthesis service.
        """
        self.llm = create_llm(model=model)

    def compare_papers(
        self,
        question: str,
        docs: List[Any],
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Compare multiple papers on a specific topic.
        """
        if not docs:
            return {
                "topic": question,
                "claims": [],
                "message": "No documents found to compare"
            }

        # Group documents by source
        docs_by_source = defaultdict(list)
        for doc in docs:
            source = doc.metadata.get("source", "unknown")
            docs_by_source[source].append(doc)

        # Build context with source-separated sections
        context_parts = []
        for source, source_docs in docs_by_source.items():
            source_context = f"\n\n--- Document: {source} ---\n"
            for doc in source_docs:
                page = doc.metadata.get("page", "?")
                source_context += f"\n[Page {page}]: {doc.page_content}\n"
            context_parts.append(source_context)

        context = "\n".join(context_parts)

        prompt = f"""You are a scientific research analyst comparing multiple papers.
It is CRITICAL that you distinguish between the different papers listed below.
The user is asking: "{question}"

Analyze the documents below and identify key claims.
For each claim, identify:
1. What the claim states
2. Which papers support, contradict, or remain neutral on this claim. Refer to papers EXPLICITLY by their filenames.
3. Specific evidence (page numbers and excerpts) from each paper.

Documents provided:
{context}

Output your analysis in the following JSON format:
{{
  "claims": [
    {{
      "claim": "Clear statement of the claim",
      "papers": [
        {{
          "paper_id": "filename.pdf",
          "stance": "supports|contradicts|neutral",
          "evidence": [
            {{
              "page": 5,
              "excerpt": "Relevant quote from the paper"
            }}
          ]
        }}
      ]
    }}
  ]
}}

If only one paper is provided in the context, clearly state that in a "message" field in your JSON, but still try to provide claims from that single paper. However, if multiple papers are present, you MUST compare them.

Include 3-5 major claims. Focus on contrasting findings.

THINKING PROCESS:
(Before providing the JSON, analyze how each document addresses the claim)

JSON OUTPUT:
"""


        response = self.llm.invoke(prompt)

        # Parse LLM response
        try:
            # Extract JSON from response (may have markdown wrappers)
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                parsed = json.loads(json_str)

                return {
                    "topic": question,
                    "claims": parsed.get("claims", []),
                    "num_papers": len(docs_by_source),
                    "sources": list(docs_by_source.keys())
                }
            else:
                raise ValueError("No JSON structure found in LLM response")
        except (json.JSONDecodeError, ValueError) as e:
            return {
                "topic": question,
                "text": response, # Fallback to raw text
                "num_papers": len(docs_by_source),
                "sources": list(docs_by_source.keys())
            }

    def generate_literature_review(
        self,
        topic: str,
        docs: List[Any],
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate a structured literature review.
        """
        if not docs:
            return {
                "topic": topic,
                "content": "No documents found to review"
            }

        context = "\n\n".join([
            f"Source: {d.metadata.get('source', 'unknown')} (Page {d.metadata.get('page', '?')})\n{d.page_content}"
            for d in docs
        ])

        prompt = f"""You are a research expert writing a structured literature review on: "{topic}"

Based on the retrieved snippets below, synthesize a review with the following sections:
1. Introduction: Overview of the topic
2. Key Themes: Major findings identified across documents
3. Methodological Approaches: How the research was conducted
4. Synthesis: How the papers relate to each other
5. Conclusion: Future directions or summary

Use formal academic tone. 
Retrieved Snippets:
{context}

THINKING PROCESS:
(Identify the core themes and findings from the snippets before writing)

LITERATURE REVIEW:
"""

        response = self.llm.invoke(prompt)

        # Clean response if the model included the thinking process
        if "LITERATURE REVIEW:" in response:
            final_content = response.split("LITERATURE REVIEW:")[-1].strip()
        else:
            final_content = response.strip()

        return {
            "topic": topic,
            "title": f"Literature Review: {topic}",
            "content": final_content,
            "num_sources": len(set(d.metadata.get('source') for d in docs))
        }
