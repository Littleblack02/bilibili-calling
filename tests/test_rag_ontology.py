import json

from langchain_core.documents import Document

from app.services.rag import RAGService


class FakeVectorStore:
    def __init__(self):
        self.queries = []

    def similarity_search(self, query, k, filter=None):
        self.queries.append((query, filter))
        return [Document(
            page_content="RAG combines retrieval with generation.",
            metadata={"bvid": "BV1", "chunk_index": 0, "title": "RAG 入门"},
        )]


def test_rag_search_uses_ontology_query_expansion_and_rrf():
    service = object.__new__(RAGService)
    service.vectorstore = FakeVectorStore()
    docs = service.search("知识库问答", k=2, bvids=["BV1"])
    assert len(service.vectorstore.queries) > 1
    assert service.vectorstore.queries[0][1] == {"bvid": {"$in": ["BV1"]}}
    assert docs[0].metadata["ontology_rrf_score"] > 0
    assert len(json.loads(docs[0].metadata["matched_queries"])) > 1
