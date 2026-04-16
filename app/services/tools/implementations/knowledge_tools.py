"""
知识库相关工具实现（RAG）
"""
import time
from typing import Optional
from app.services.tools.base import BaseTool, ToolResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RAGSearchTool(BaseTool):
    """在用户收藏夹中搜索相关内容"""

    name = "rag_search"
    description = "在用户收藏的视频中搜索相关内容，基于向量相似度匹配。适用于查找收藏过的相关视频。"
    agent_type = "rag"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题"
            },
            "top_k": {
                "type": "integer",
                "description": "返回最相关的结果数量",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, top_k: int = 5, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        """
        在RAG知识库中搜索

        Args:
            query: 搜索查询
            top_k: 返回结果数量
            session_id: 会话ID（用于个性化）
        """
        start_time = time.time()
        try:
            # 调用实际的RAG搜索逻辑
            from app.services.rag import get_rag_service

            # 使用session_id或默认session获取RAG服务
            rag = get_rag_service(session_id or "default")

            # 执行向量搜索
            search_results = await rag.search(query, top_k=top_k)

            # 格式化返回结果
            formatted_results = []
            for result in search_results:
                formatted_results.append({
                    "bvid": result.get("bvid", ""),
                    "title": result.get("title", ""),
                    "content": result.get("content", ""),
                    "similarity": result.get("similarity", 0.0),
                    "summary": result.get("summary", result.get("content", "")[:200])
                })

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data=formatted_results,
                source="rag_search",
                execution_time_ms=execution_time,
                metadata={"query": query, "top_k": top_k, "count": len(formatted_results)}
            )
        except Exception as e:
            logger.error(f"RAGSearchTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="rag_search",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class SummarizeTool(BaseTool):
    """摘要工具"""

    name = "summarize"
    description = "对视频内容、文章或长文本进行摘要，提取关键信息。"
    agent_type = "rag"
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "需要摘要的内容"
            },
            "bvid": {
                "type": "string",
                "description": "视频BV号（可选）"
            },
            "max_length": {
                "type": "integer",
                "description": "摘要最大长度",
                "default": 200
            }
        },
        "required": ["content"]
    }

    async def execute(self, content: str, bvid: Optional[str] = None, max_length: int = 200, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            # 调用RAGService进行真实摘要
            from app.services.rag import get_rag_service

            # 获取RAG服务
            rag = get_rag_service("default")

            # 调用摘要功能
            summary = await rag.summarize_content(content, max_length=max_length)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data={
                    "summary": summary,
                    "original_length": len(content),
                    "summary_length": len(summary),
                    "bvid": bvid
                },
                source="rag_summarize",
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"SummarizeTool error: {e}")
            # Fallback到简单截断
            summary_fallback = content[:max_length] + "..." if len(content) > max_length else content
            return ToolResult(
                success=True,
                data={
                    "summary": summary_fallback,
                    "original_length": len(content),
                    "summary_length": len(summary_fallback),
                    "bvid": bvid,
                    "fallback": True
                },
                source="rag_summarize",
                execution_time_ms=int((time.time() - start_time) * 1000),
                error="LLM摘要失败，使用简单截断"
            )


class ListContentTool(BaseTool):
    """列出收藏内容工具"""

    name = "list_content"
    description = "列出用户收藏夹中的内容，支持按文件夹、标签筛选。"
    agent_type = "rag"
    parameters = {
        "type": "object",
        "properties": {
            "folder_id": {
                "type": "integer",
                "description": "收藏夹ID（可选）"
            },
            "limit": {
                "type": "integer",
                "description": "返回数量限制",
                "default": 20
            },
            "offset": {
                "type": "integer",
                "description": "偏移量",
                "default": 0
            }
        },
        "required": []
    }

    async def execute(self, folder_id: Optional[int] = None, limit: int = 20, offset: int = 0, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            # 从数据库查询收藏夹内容
            from app.database import get_db_context
            from app.models import FavoriteVideo, FavoriteFolder, VideoCache
            from sqlalchemy import select, and_, desc

            async with get_db_context() as db:
                # 如果指定了folder_id，查询该收藏夹的视频
                if folder_id:
                    stmt = (
                        select(FavoriteVideo, VideoCache)
                        .join(VideoCache, FavoriteVideo.bvid == VideoCache.bvid)
                        .where(
                            and_(
                                FavoriteVideo.folder_id == folder_id,
                                FavoriteVideo.is_selected == True
                            )
                        )
                        .order_by(desc(FavoriteVideo.created_at))
                        .limit(limit)
                        .offset(offset)
                    )

                    result = await db.execute(stmt)
                    rows = result.fetchall()

                    # 构建返回结果
                    results = []
                    for fav_video, video_cache in rows:
                        results.append({
                            "bvid": video_cache.bvid,
                            "title": video_cache.title,
                            "author": video_cache.owner_name,
                            "description": video_cache.description,
                            "duration": video_cache.duration,
                            "folder_id": folder_id,
                            "is_processed": video_cache.is_processed,
                            "created_at": video_cache.created_at.isoformat() if video_cache.created_at else None
                        })

                else:
                    # 如果没有指定folder_id，查询所有收藏夹
                    stmt = (
                        select(FavoriteFolder)
                        .where(FavoriteFolder.is_selected == True)
                        .order_by(desc(FavoriteFolder.created_at))
                        .limit(limit)
                        .offset(offset)
                    )

                    result = await db.execute(stmt)
                    folders = result.scalars().all()

                    # 构建返回结果
                    results = []
                    for folder in folders:
                        results.append({
                            "folder_id": folder.id,
                            "media_id": folder.media_id,
                            "title": folder.title,
                            "media_count": folder.media_count,
                            "is_selected": folder.is_selected,
                            "last_sync_at": folder.last_sync_at.isoformat() if folder.last_sync_at else None
                        })

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data=results,
                source="rag_list_content",
                execution_time_ms=execution_time,
                metadata={"folder_id": folder_id, "limit": limit, "offset": offset, "count": len(results)}
            )
        except Exception as e:
            logger.error(f"ListContentTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="rag_list_content",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
