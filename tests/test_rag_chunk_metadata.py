import json

from app.config import settings
from app.models import ContentSource, VideoContent
from app.services.rag import RAGService


class CapturingVectorStore:
    def __init__(self):
        self.documents = []

    def add_documents(self, documents):
        self.documents.extend(documents)


def test_v2_subtitle_chunks_keep_time_range_and_independent_concepts(monkeypatch):
    service = object.__new__(RAGService)
    service.vectorstore = CapturingVectorStore()
    monkeypatch.setattr(settings, "rag_grounded_v2_enabled", True)
    video = VideoContent(
        bvid="BV1CHUNK0001",
        title="RAG 完整课程",
        content="音乐现场片段。RAG 检索增强生成片段。",
        source=ContentSource.SUBTITLE,
        segments=[
            {"start_time": 0.0, "end_time": 10.0, "text": "音乐现场和声演奏"},
            {"start_time": 60.0, "end_time": 72.5, "text": "RAG 检索增强生成的索引步骤"},
        ],
    )
    assert service.add_video_content(video) == 2
    first, second = service.vectorstore.documents
    assert first.metadata["start_time"] == 0.0
    assert first.metadata["end_time"] == 10.0
    assert second.metadata["start_time"] == 60.0
    assert second.metadata["end_time"] == 72.5
    first_concepts = json.loads(first.metadata["concept_ids"])
    second_concepts = json.loads(second.metadata["concept_ids"])
    assert "https://bilibili.local/ontology/Music" in first_concepts
    assert "https://bilibili.local/ontology/RAG" not in first_concepts
    assert "https://bilibili.local/ontology/RAG" in second_concepts
    assert first.metadata["concept_scope"] == "chunk"
    assert second.metadata["chunk_index"] == 1
