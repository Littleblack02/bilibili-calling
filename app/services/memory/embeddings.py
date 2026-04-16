"""
统一的 Embedding 服务（记忆系统专用）

避免重复初始化 embedding 函数，统一 ChromaDB 路径
"""
from typing import List, Optional, Dict, Any
import asyncio
from functools import lru_cache
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 全局缓存的 embedding 实例
_embeddings_instance: Optional["MemoryEmbeddings"] = None
_init_lock = asyncio.Lock()


class MemoryEmbeddings:
    """
    记忆系统专用 Embedding 封装

    统一管理：
    1. DashScope / OpenAI compatible embedding
    2. ChromaDB 客户端和路径
    """

    def __init__(self):
        self._embeddings = None
        self._chroma_client = None
        self._init_embeddings()
        self._init_chroma()

    def _init_embeddings(self):
        """初始化 embedding 函数"""
        try:
            from langchain_community.embeddings import DashScopeEmbeddings
            self._embeddings = DashScopeEmbeddings(
                dashscope_api_key=settings.openai_api_key,
                model=settings.embedding_model
            )
            logger.info(f"MemoryEmbeddings: DashScopeEmbeddings 初始化成功，模型={settings.embedding_model}")
        except Exception as e:
            logger.warning(f"DashScopeEmbeddings 不可用，尝试 OpenAIEmbeddings: {e}")
            try:
                from langchain_openai import OpenAIEmbeddings
                self._embeddings = OpenAIEmbeddings(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.embedding_model,
                    check_embedding_ctx_length=False
                )
                logger.info(f"MemoryEmbeddings: OpenAIEmbeddings 初始化成功，模型={settings.embedding_model}")
            except Exception as e2:
                logger.error(f"OpenAIEmbeddings 也不可用: {e2}")
                self._embeddings = None

    def _init_chroma(self):
        """初始化 ChromaDB 客户端，使用统一的路径"""
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            # 统一使用 settings.chroma_dir（兼容 .env 配置）
            chroma_path = str(settings.chroma_dir)

            self._chroma_client = chromadb.PersistentClient(
                path=chroma_path,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"MemoryEmbeddings: ChromaDB 初始化成功，路径={chroma_path}")

        except Exception as e:
            logger.error(f"MemoryEmbeddings: ChromaDB 初始化失败: {e}")
            self._chroma_client = None

    @property
    def embeddings(self):
        """获取 embedding 函数"""
        return self._embeddings

    @property
    def chroma_client(self):
        """获取 ChromaDB 客户端"""
        return self._chroma_client

    def embed_query(self, text: str) -> List[float]:
        """同步 embedding 查询"""
        if self._embeddings is None:
            raise RuntimeError("Embedding 函数未初始化")
        return self._embeddings.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """同步 embedding 文档"""
        if self._embeddings is None:
            raise RuntimeError("Embedding 函数未初始化")
        return self._embeddings.embed_documents(texts)

    async def aembed_query(self, text: str) -> List[float]:
        """异步 embedding 查询"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_query, text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """异步 embedding 文档"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_documents, texts)

    def get_or_create_collection(self, name: str, metadata: Optional[Dict] = None) -> Any:
        """
        获取或创建 ChromaDB collection

        Args:
            name: collection 名称
            metadata: collection 元数据

        Returns:
            ChromaDB collection 对象
        """
        if self._chroma_client is None:
            raise RuntimeError("ChromaDB 客户端未初始化")

        try:
            return self._chroma_client.get_collection(name=name)
        except Exception:
            # collection 不存在，创建新的
            col_metadata = metadata or {"hnsw:space": "cosine"}
            return self._chroma_client.create_collection(name=name, metadata=col_metadata)

    def delete_collection(self, name: str) -> bool:
        """删除 collection"""
        if self._chroma_client is None:
            return False
        try:
            self._chroma_client.delete_collection(name=name)
            return True
        except Exception as e:
            logger.error(f"删除 collection 失败 {name}: {e}")
            return False


@lru_cache(maxsize=1)
def get_memory_embeddings() -> MemoryEmbeddings:
    """
    获取全局单例 MemoryEmbeddings 实例（同步版本）

    使用 lru_cache 确保整个进程只初始化一次
    """
    global _embeddings_instance
    if _embeddings_instance is None:
        _embeddings_instance = MemoryEmbeddings()
    return _embeddings_instance


async def get_memory_embeddings_async() -> MemoryEmbeddings:
    """
    获取全局单例 MemoryEmbeddings 实例（异步版本）

    支持异步初始化锁，避免并发重复初始化
    """
    global _embeddings_instance
    if _embeddings_instance is not None:
        return _embeddings_instance

    async with _init_lock:
        # 双重检查
        if _embeddings_instance is None:
            _embeddings_instance = MemoryEmbeddings()
        return _embeddings_instance
