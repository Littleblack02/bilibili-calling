"""Thresholded, traceable retrieval and failure-safe local reranking."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time
from typing import Any

from langchain_core.documents import Document
from loguru import logger

from app.config import settings
from app.services.ontology import OntologyService, get_ontology_service
from app.services.observability import metrics


@dataclass(frozen=True)
class RetrievalTier:
    name: str
    threshold: float
    weight: float


def _tier(variant: dict[str, Any]) -> RetrievalTier:
    if variant.get("concept_id") is None:
        return RetrievalTier("original", settings.rag_original_min_relevance, 1.0)
    relations = {
        str(edge.get("relation", ""))
        for edge in (variant.get("path") or [])
        if isinstance(edge, dict)
    }
    if relations & {"related", "requires", "requiredBy"}:
        return RetrievalTier("associative", settings.rag_associative_min_relevance, 0.50)
    if relations & {"broader", "narrower"}:
        return RetrievalTier("hierarchy", settings.rag_hierarchy_min_relevance, 0.70)
    return RetrievalTier("synonym", settings.rag_synonym_min_relevance, 0.85)


def _distance_to_relevance(distance: Any) -> float:
    try:
        numeric = max(0.0, float(distance))
    except (TypeError, ValueError):
        return 0.0
    return 1.0 / (1.0 + numeric)


def _document_key(document: Document) -> tuple[str, str, str]:
    metadata = document.metadata or {}
    return (
        str(metadata.get("bvid", "")),
        str(metadata.get("chunk_index", "")),
        document.page_content[:120],
    )


def _tokens(text: str) -> set[str]:
    normalized = (text or "").casefold()
    latin = set(re.findall(r"[a-z0-9_]+", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    return latin | set(chinese) | {
        chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))
    }


class GroundedReranker:
    """Deterministic structural reranker; no remote dependency or secret data."""

    def rerank(self, query: str, documents: list[Document]) -> list[Document]:
        query_tokens = _tokens(query)
        rescored: list[Document] = []
        for document in documents[: settings.rag_reranker_max_chunks]:
            content_tokens = _tokens(document.page_content)
            query_coverage = (
                len(query_tokens & content_tokens) / len(query_tokens)
                if query_tokens else 0.0
            )
            relevance = float(document.metadata.get("retrieval_relevance", 0.0))
            content_length = len(document.page_content.strip())
            evidence_completeness = min(1.0, content_length / 240.0)
            rerank_score = (
                0.58 * relevance
                + 0.27 * query_coverage
                + 0.15 * evidence_completeness
            )
            document.metadata = {
                **(document.metadata or {}),
                "reranker": "deterministic-coverage-v1",
                "rerank_relevance": round(relevance, 6),
                "rerank_query_coverage": round(query_coverage, 6),
                "rerank_evidence_completeness": round(evidence_completeness, 6),
                "rerank_score": round(rerank_score, 6),
            }
            rescored.append(document)
        rescored.sort(key=lambda item: item.metadata["rerank_score"], reverse=True)
        return rescored


class GroundedRetriever:
    def __init__(
        self,
        vectorstore: Any,
        ontology: OntologyService | None = None,
        reranker: GroundedReranker | None = None,
    ) -> None:
        self.vectorstore = vectorstore
        self.ontology = ontology or get_ontology_service()
        self.reranker = reranker or GroundedReranker()

    def _scored_search(
        self, query: str, k: int, search_filter: dict[str, Any] | None
    ) -> list[tuple[Document, float, float, str]]:
        relevance_method = getattr(
            self.vectorstore, "similarity_search_with_relevance_scores", None
        )
        if callable(relevance_method):
            kwargs = {"k": k}
            if search_filter:
                kwargs["filter"] = search_filter
            return [
                (document, max(0.0, min(1.0, float(score))), float(score), "relevance")
                for document, score in relevance_method(query, **kwargs)
            ]
        distance_method = getattr(self.vectorstore, "similarity_search_with_score", None)
        if not callable(distance_method):
            raise RuntimeError("Vector store has no score-bearing search method")
        kwargs = {"k": k}
        if search_filter:
            kwargs["filter"] = search_filter
        return [
            (document, _distance_to_relevance(score), float(score), "distance")
            for document, score in distance_method(query, **kwargs)
        ]

    def search(
        self, query: str, k: int = 5, bvids: list[str] | None = None
    ) -> list[Document]:
        started = time.perf_counter()
        if not query or not query.strip():
            metrics.inc("rag_retrieval_outcomes_total", outcome="empty_query")
            return []
        variants = self.ontology.expand_query(query, max_terms=8)
        pool_size = max(k, settings.rag_retrieval_pool_size)
        search_filter = {"bvid": {"$in": bvids}} if bvids else None
        fused: dict[tuple[str, str, str], dict[str, Any]] = {}
        total_variant_weight = 0.0

        for variant in variants:
            tier = _tier(variant)
            variant_weight = max(0.0, float(variant.get("weight", 1.0))) * tier.weight
            total_variant_weight += variant_weight
            results = self._scored_search(variant["query"], pool_size, search_filter)
            for rank, (document, relevance, raw_score, score_kind) in enumerate(results, 1):
                if relevance < tier.threshold:
                    continue
                key = _document_key(document)
                hit = {
                    "query": variant["query"],
                    "tier": tier.name,
                    "rank": rank,
                    "relevance": round(relevance, 6),
                    "raw_score": round(raw_score, 6),
                    "score_kind": score_kind,
                    "threshold": tier.threshold,
                    "variant_weight": round(variant_weight, 6),
                    "concept_id": variant.get("concept_id"),
                    "path": variant.get("path") or [],
                }
                row = fused.setdefault(key, {
                    "document": document,
                    "rrf": 0.0,
                    "max_relevance": 0.0,
                    "hits": [],
                })
                row["rrf"] += variant_weight / (60.0 + rank)
                row["max_relevance"] = max(row["max_relevance"], relevance)
                row["hits"].append(hit)

        if not fused:
            metrics.inc("rag_retrieval_outcomes_total", outcome="no_result")
            metrics.observe("rag_retrieval_duration_ms", (time.perf_counter() - started) * 1000)
            return []
        denominator = max(1e-9, total_variant_weight / 61.0)
        documents: list[Document] = []
        for row in fused.values():
            rrf_normalized = min(1.0, row["rrf"] / denominator)
            retrieval_score = 0.65 * row["max_relevance"] + 0.35 * rrf_normalized
            document = row["document"]
            hits = sorted(row["hits"], key=lambda item: (-item["relevance"], item["rank"]))
            document.metadata = {
                **(document.metadata or {}),
                "retrieval_schema_version": "2.0",
                "retrieval_score": round(retrieval_score, 6),
                "retrieval_relevance": round(row["max_relevance"], 6),
                "retrieval_rrf_score": round(row["rrf"], 6),
                "retrieval_hits": json.dumps(hits, ensure_ascii=False),
                "matched_queries": json.dumps(
                    list(dict.fromkeys(hit["query"] for hit in hits)), ensure_ascii=False
                ),
                "ontology_matches": json.dumps([
                    {
                        "concept_id": hit["concept_id"],
                        "path": hit["path"],
                        "tier": hit["tier"],
                    }
                    for hit in hits if hit["concept_id"]
                ], ensure_ascii=False),
            }
            documents.append(document)
        documents.sort(key=lambda item: item.metadata["retrieval_score"], reverse=True)

        if settings.rag_reranker_enabled:
            try:
                documents = self.reranker.rerank(query, documents)
            except Exception as exc:
                logger.warning(f"RAG reranker failed; using fused ranking: {exc}")
        output = documents[:k]
        metrics.inc("rag_retrieval_outcomes_total", outcome="result")
        metrics.observe("rag_retrieval_result_count", len(output))
        metrics.observe("rag_retrieval_duration_ms", (time.perf_counter() - started) * 1000)
        return output


def citation_id(document: Document) -> str:
    metadata = document.metadata or {}
    return f"{metadata.get('bvid', '')}#{metadata.get('chunk_index', '')}"


def citation_from_document(document: Document) -> dict[str, Any]:
    metadata = document.metadata or {}
    concepts = metadata.get("concept_ids", "[]")
    if isinstance(concepts, str):
        try:
            concepts = json.loads(concepts)
        except json.JSONDecodeError:
            concepts = []
    return {
        "citation_id": citation_id(document),
        "bvid": str(metadata.get("bvid", "")),
        "title": str(metadata.get("title", "")),
        "chunk_index": int(metadata.get("chunk_index", 0)),
        "start_time": metadata.get("start_time"),
        "end_time": metadata.get("end_time"),
        "concept_ids": concepts if isinstance(concepts, list) else [],
        "url": metadata.get(
            "url", f"https://www.bilibili.com/video/{metadata.get('bvid', '')}"
        ),
        "retrieval_score": float(
            metadata.get("rerank_score", metadata.get("retrieval_score", 0.0))
        ),
        "supporting_excerpt": document.page_content[:500],
    }


def build_grounded_context(documents: list[Document]) -> tuple[str, list[dict[str, Any]]]:
    citations = [citation_from_document(document) for document in documents]
    parts = []
    for document, citation in zip(documents, citations):
        time_range = ""
        if citation["start_time"] is not None and citation["end_time"] is not None:
            time_range = f" {citation['start_time']:.2f}s-{citation['end_time']:.2f}s"
        parts.append(
            f"[{citation['citation_id']}] {citation['title']}{time_range}\n"
            f"{document.page_content.strip()}"
        )
    return "\n\n---\n\n".join(parts), citations


def verify_answer_citations(
    answer: str, citations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Fail closed when generated citations do not resolve to retrieved chunks."""
    available = {citation["citation_id"] for citation in citations}
    referenced = set(re.findall(r"\[([A-Za-z0-9]+#\d+)\]", answer or ""))
    unknown = sorted(referenced - available)
    return {
        "valid": bool(referenced) and not unknown,
        "referenced_citation_ids": sorted(referenced),
        "unknown_citation_ids": unknown,
        "reason": (
            "verified" if referenced and not unknown
            else "unknown_citation" if unknown
            else "missing_citation"
        ),
    }


def grounded_refusal(reason: str = "insufficient_evidence") -> dict[str, Any]:
    return {
        "answer": "收藏知识库证据不足，暂时无法可靠回答这个问题。",
        "sources": [],
        "grounded": False,
        "retrieval_confidence": 0.0,
        "answerability": "insufficient_evidence",
        "citations": [],
        "ontology_matches": [],
        "citation_verification": {"valid": True, "reason": reason},
    }
