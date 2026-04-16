from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from app.services.memory.manager import MemoryManager
from app.services.memory.promotion_criteria import PromotionScorer
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/memory", tags=["Memory"])


class RememberRequest(BaseModel):
    """存储记忆请求"""
    session_id: str
    content: str
    memory_type: str = "conversation"
    importance: int = 1
    tags: List[str] = []
    metadata: dict = {}
    enable_smart_promotion: bool = True


class RecallRequest(BaseModel):
    """检索记忆请求"""
    session_id: str
    query: str
    limit: int = 5
    memory_type: Optional[str] = None


class PromotionScoreRequest(BaseModel):
    """晋升评分请求"""
    session_id: str
    memory_id: int


@router.post("/remember")
async def remember(request: RememberRequest):
    """存储记忆（智能晋升）"""
    try:
        memory = MemoryManager(request.session_id)

        entry = await memory.remember(
            content=request.content,
            memory_type=request.memory_type,
            importance=request.importance,
            tags=request.tags,
            metadata=request.metadata,
            enable_smart_promotion=request.enable_smart_promotion
        )

        return {
            "success": True,
            "memory_id": entry.id,
            "message": "记忆已存储"
        }

    except Exception as e:
        logger.error(f"Remember error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recall")
async def recall(request: RecallRequest):
    """检索记忆"""
    try:
        memory = MemoryManager(request.session_id)

        memories = await memory.recall(
            query=request.query,
            limit=request.limit,
            memory_type=request.memory_type
        )

        return {
            "success": True,
            "memories": [m.to_dict() for m in memories],
            "count": len(memories)
        }

    except Exception as e:
        logger.error(f"Recall error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
async def get_memory_history(session_id: str, limit: int = 20):
    """获取记忆历史"""
    try:
        memory = MemoryManager(session_id)

        memories = await memory.get_recent(limit=limit)

        return {
            "success": True,
            "memories": [m.to_dict() for m in memories],
            "count": len(memories)
        }

    except Exception as e:
        logger.error(f"Get memory history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile/{session_id}")
async def get_user_profile(session_id: str):
    """获取用户画像"""
    try:
        memory = MemoryManager(session_id)

        profile = await memory.get_user_profile()

        return {
            "success": True,
            "profile": profile
        }

    except Exception as e:
        logger.error(f"Get user profile error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear/{session_id}")
async def clear_memory(session_id: str, memory_type: Optional[str] = None):
    """清空记忆"""
    try:
        memory = MemoryManager(session_id)

        count = await memory.clear(memory_type=memory_type)

        return {
            "success": True,
            "deleted_count": count
        }

    except Exception as e:
        logger.error(f"Clear memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup/{session_id}")
async def cleanup_expired_memory(session_id: str):
    """清理过期记忆"""
    try:
        memory = MemoryManager(session_id)

        result = await memory.cleanup_expired()

        return {
            "success": True,
            "cleaned": result
        }

    except Exception as e:
        logger.error(f"Cleanup memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/promotion/score")
async def score_promotion(request: PromotionScoreRequest):
    """对单条记忆进行晋升评分"""
    try:
        memory = MemoryManager(request.session_id)

        # 获取该记忆
        stm_memories = await memory.stm.get_recent(limit=1000)
        target_mem = next((m for m in stm_memories if m.id == request.memory_id), None)

        if not target_mem:
            raise HTTPException(status_code=404, detail="Memory not found")

        # 评分
        scorer = PromotionScorer()
        score_result = scorer.score(target_mem)

        return {
            "success": True,
            "score_result": score_result
        }

    except Exception as e:
        logger.error(f"Promotion score error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/forgetting/apply/{session_id}")
async def apply_forgetting_policy(
    session_id: str,
    dry_run: bool = Query(False, description="True 则只评估不删除")
):
    """应用遗忘策略清理长期记忆"""
    try:
        memory = MemoryManager(session_id)

        result = await memory.apply_forgetting_policy(dry_run=dry_run)

        return {
            "success": True,
            "result": result
        }

    except Exception as e:
        logger.error(f"Forgetting policy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compress/{session_id}")
async def compress_memories(
    session_id: str,
    target_count: int = Query(20, description="触发压缩的 STM 条数阈值"),
    importance_threshold: int = Query(3, description="只压缩低于此重要性的记忆")
):
    """压缩短期记忆"""
    try:
        memory = MemoryManager(session_id)

        result = await memory.compress_memories(
            target_count=target_count,
            importance_threshold=importance_threshold
        )

        return {
            "success": True,
            "result": result
        }

    except Exception as e:
        logger.error(f"Memory compression error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge/extract/{session_id}")
async def extract_global_knowledge(session_id: str):
    """提取跨会话全局知识"""
    try:
        memory = MemoryManager(session_id)

        result = await memory.extract_global_knowledge()

        return {
            "success": True,
            "result": result
        }

    except Exception as e:
        logger.error(f"Knowledge extraction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge/search")
async def search_global_knowledge(
    query: str = Query(..., description="搜索查询"),
    limit: int = Query(5, description="返回数量"),
    source_type: Optional[str] = Query(None, description="过滤来源类型")
):
    """搜索全局知识库"""
    try:
        from app.services.memory.knowledge_migration import KnowledgeMigrator

        migrator = KnowledgeMigrator()
        results = await migrator.search_global_knowledge(
            query=query,
            limit=limit,
            source_type=source_type
        )

        return {
            "success": True,
            "results": results,
            "count": len(results)
        }

    except Exception as e:
        logger.error(f"Global knowledge search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/enrich/{session_id}")
async def enrich_context(session_id: str, query: str):
    """获取增强上下文（包含全局知识）"""
    try:
        memory = MemoryManager(session_id)

        enriched_context = await memory.enrich_context_with_global_knowledge(query)

        return {
            "success": True,
            "context": enriched_context
        }

    except Exception as e:
        logger.error(f"Context enrichment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
