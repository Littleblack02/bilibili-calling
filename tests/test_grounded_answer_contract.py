from langchain_core.documents import Document
import asyncio

from app.services.rag_grounded import (
    build_grounded_context,
    grounded_refusal,
    verify_answer_citations,
)
from app.config import settings
from app.services.rag import RAGService


def _document():
    return Document(
        page_content="RAG 的索引阶段包括切分、向量化和入库。",
        metadata={
            "bvid": "BV1TEST00001",
            "title": "RAG 入门",
            "chunk_index": 2,
            "start_time": 60.0,
            "end_time": 75.0,
            "concept_ids": '["https://bilibili.local/ontology/RAG"]',
            "retrieval_score": 0.82,
        },
    )


def test_grounded_context_and_citation_contract_include_chunk_and_time_range():
    context, citations = build_grounded_context([_document()])
    assert "[BV1TEST00001#2]" in context
    assert citations[0]["start_time"] == 60.0
    assert citations[0]["end_time"] == 75.0
    assert citations[0]["concept_ids"] == ["https://bilibili.local/ontology/RAG"]


def test_citation_post_verification_rejects_missing_or_unknown_chunks():
    _, citations = build_grounded_context([_document()])
    assert verify_answer_citations("索引需要先切分。[BV1TEST00001#2]", citations)["valid"]
    assert not verify_answer_citations("索引需要先切分。", citations)["valid"]
    invalid = verify_answer_citations("错误引用。[BV1UNKNOWN00#9]", citations)
    assert not invalid["valid"]
    assert invalid["reason"] == "unknown_citation"


def test_grounded_refusal_never_fills_with_general_knowledge():
    result = grounded_refusal("no_result_above_threshold")
    assert result["answer"] == "收藏知识库证据不足，暂时无法可靠回答这个问题。"
    assert result["grounded"] is False
    assert result["answerability"] == "insufficient_evidence"
    assert result["citations"] == []


def test_rag_service_returns_grounding_contract_when_threshold_filters_everything(monkeypatch):
    service = object.__new__(RAGService)
    service.get_collection_stats = lambda: {"total_chunks": 1}
    service.search = lambda *_args, **_kwargs: []
    monkeypatch.setattr(settings, "rag_grounded_v2_enabled", True)
    result = asyncio.run(service.answer_question("没有答案的问题"))
    assert result["answerability"] == "insufficient_evidence"
    assert result["retrieval_confidence"] == 0.0
    assert result["citation_verification"]["reason"] == "no_result_above_threshold"


def test_grounded_answer_refuses_topic_match_without_question_evidence():
    service = object.__new__(RAGService)
    document = _document()
    document.metadata["rerank_query_coverage"] = 0.05
    result = asyncio.run(service._answer_grounded("作者的身份证号码是什么？", [document]))
    assert result["answerability"] == "insufficient_evidence"
    assert result["citation_verification"]["reason"] == "query_evidence_coverage_below_threshold"
