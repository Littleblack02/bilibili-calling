import json

from langchain_core.documents import Document

from app.config import settings
from app.services.rag import RAGService
from app.services.rag_grounded import GroundedRetriever


class VariantOntology:
    def expand_query(self, query, max_terms=8):
        return [
            {"query": query, "weight": 1.0, "concept_id": None, "path": []},
            {"query": "检索增强生成", "weight": 0.9, "concept_id": "rag", "path": []},
            {
                "query": "向量数据库",
                "weight": 0.5,
                "concept_id": "vector-db",
                "path": [{"from": "RAG", "relation": "related", "to": "向量数据库"}],
            },
        ]


class ScoredStore:
    def __init__(self):
        self.calls = []

    def similarity_search_with_relevance_scores(self, query, k, filter=None):
        self.calls.append((query, k, filter))
        if query == "RAG question":
            return [
                (Document(page_content="RAG question evidence " * 20, metadata={
                    "bvid": "BV1GOOD00001", "chunk_index": 2, "title": "RAG"
                }), 0.80),
                (Document(page_content="noise", metadata={
                    "bvid": "BV1NOISE0001", "chunk_index": 0, "title": "noise"
                }), 0.20),
            ]
        if query == "检索增强生成":
            return [(Document(page_content="检索增强生成说明 " * 15, metadata={
                "bvid": "BV1SYN000001", "chunk_index": 1, "title": "同义词"
            }), 0.50)]
        return [(Document(page_content="向量数据库相关但证据较弱", metadata={
            "bvid": "BV1DRIFT001", "chunk_index": 3, "title": "漂移"
        }), 0.60)]


def test_grounded_retrieval_applies_relation_thresholds_and_keeps_trace(monkeypatch):
    monkeypatch.setattr(settings, "rag_retrieval_pool_size", 10)
    store = ScoredStore()
    docs = GroundedRetriever(store, ontology=VariantOntology()).search(
        "RAG question", k=5, bvids=["BV1GOOD00001"]
    )
    assert {doc.metadata["bvid"] for doc in docs} == {"BV1GOOD00001", "BV1SYN000001"}
    assert all(call[2] == {"bvid": {"$in": ["BV1GOOD00001"]}} for call in store.calls)
    assert all("retrieval_score" in doc.metadata for doc in docs)
    assert all("rerank_query_coverage" in doc.metadata for doc in docs)
    traces = [hit for doc in docs for hit in json.loads(doc.metadata["retrieval_hits"])]
    assert all(hit["relevance"] >= hit["threshold"] for hit in traces)
    assert not any(hit["tier"] == "associative" for hit in traces)


def test_reranker_can_be_disabled_and_empty_means_empty(monkeypatch):
    monkeypatch.setattr(settings, "rag_reranker_enabled", False)
    docs = GroundedRetriever(ScoredStore(), ontology=VariantOntology()).search(
        "RAG question", k=2
    )
    assert docs
    assert all("rerank_score" not in doc.metadata for doc in docs)

    monkeypatch.setattr(settings, "rag_original_min_relevance", 0.99)
    monkeypatch.setattr(settings, "rag_synonym_min_relevance", 0.99)
    monkeypatch.setattr(settings, "rag_associative_min_relevance", 0.99)
    assert GroundedRetriever(ScoredStore(), ontology=VariantOntology()).search(
        "RAG question", k=2
    ) == []


def test_rag_service_v2_flag_uses_score_bearing_path(monkeypatch):
    store = ScoredStore()
    service = object.__new__(RAGService)
    service.vectorstore = store
    monkeypatch.setattr(settings, "rag_grounded_v2_enabled", True)
    docs = service.search("RAG question", k=1)
    assert docs[0].metadata["retrieval_schema_version"] == "2.0"
    assert store.calls
