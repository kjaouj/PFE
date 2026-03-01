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

    def _parse_compare_json(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse and validate compare response JSON.
        """
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            return None

        candidate = response[json_start:json_end]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None

        claims = parsed.get("claims")
        if claims is None:
            return None
        if not isinstance(claims, list):
            return None

        # Soft normalization of expected shape
        normalized_claims = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            normalized_claims.append(
                {
                    "claim": claim.get("claim", ""),
                    "papers": claim.get("papers", []),
                }
            )
        parsed["claims"] = normalized_claims
        return parsed

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
                raw_page = doc.metadata.get("page", "?")
                if isinstance(raw_page, int):
                    page = raw_page + 1
                else:
                    page = raw_page
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

JSON OUTPUT:
"""
        response = self.llm.invoke(prompt)
        parsed = self._parse_compare_json(response)

        # Retry once with stricter instruction if needed
        if parsed is None:
            repair_prompt = (
                "Return ONLY valid JSON with this schema:\n"
                '{"claims":[{"claim":"...","papers":[{"paper_id":"...","stance":"supports|contradicts|neutral","evidence":[{"page":1,"excerpt":"..."}]}]}],'
                '"message":"optional"}\n\n'
                f"Original output to fix:\n{response}"
            )
            repaired = self.llm.invoke(repair_prompt)
            parsed = self._parse_compare_json(repaired)

        if parsed is None:
            return {
                "topic": question,
                "claims": [],
                "message": "Could not produce a structured comparison. Try narrowing the question.",
                "num_papers": len(docs_by_source),
                "sources": list(docs_by_source.keys()),
            }

        return {
            "topic": question,
            "claims": parsed.get("claims", []),
            "message": parsed.get("message", ""),
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
            f"Source: {d.metadata.get('source', 'unknown')} (Page {(d.metadata.get('page', '?') + 1) if isinstance(d.metadata.get('page', '?'), int) else d.metadata.get('page', '?')})\n{d.page_content}"
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
