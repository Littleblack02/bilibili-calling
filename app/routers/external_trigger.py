from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.services.recommendation.recommendation_service import get_recommendation_service
from app.services.profile.multi_source_profile_builder import get_multi_source_profile_builder
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/external", tags=["External Trigger"])


class TriggerRecommendationRequest(BaseModel):
    """触发推荐请求"""
    session_id: str
    limit: int = 10
    push_immediately: bool = False  # 是否立即推送


class TriggerProfileBuildRequest(BaseModel):
    """触发画像构建请求"""
    session_id: str
    force_rebuild: bool = True


@router.post("/trigger/recommendation")
async def trigger_recommendation(request: TriggerRecommendationRequest):
    """
    外部触发推荐生成

    由外部调度系统调用，生成推荐并可选地立即推送
    """
    try:
        logger.info(f"外部触发推荐: {request.session_id}")

        # 获取推荐服务
        rec_service = get_recommendation_service()

        # 生成推荐
        recommendations = await rec_service.generate_recommendations(
            session_id=request.session_id,
            limit=request.limit,
            save_to_candidates=True
        )

        result = {
            "success": True,
            "session_id": request.session_id,
            "count": len(recommendations),
            "recommendations": recommendations[:5],  # 只返回前5个示例
            "message": f"已生成 {len(recommendations)} 条推荐"
        }

        # 如果需要立即推送
        if request.push_immediately and recommendations:
            try:
                from app.routers.websocket_manager import manager

                push_message = {
                    "type": "external_recommendations",
                    "session_id": request.session_id,
                    "data": {
                        "count": len(recommendations),
                        "recommendations": recommendations[:10],
                        "timestamp": datetime.utcnow().isoformat(),
                        "trigger_source": "external_scheduler"
                    }
                }

                await manager.send_personal_message(push_message, request.session_id)
                result["pushed"] = True
                logger.info(f"推荐已推送: {request.session_id}")

            except Exception as push_error:
                logger.warning(f"WebSocket推送失败: {push_error}")
                result["pushed"] = False

        return result

    except Exception as e:
        logger.error(f"外部触发推荐失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger/profile-build")
async def trigger_profile_build(request: TriggerProfileBuildRequest):
    """
    外部触发用户画像构建

    由外部调度系统调用，更新用户画像
    """
    try:
        logger.info(f"外部触发画像构建: {request.session_id}")

        # 获取用户会话信息
        from app.models import UserSession
        from app.database import async_session_factory
        from sqlalchemy import select

        async with async_session_factory() as db:
            result = await db.execute(
                select(UserSession).where(UserSession.session_id == request.session_id)
            )
            user_session = result.scalar_one_or_none()

        if not user_session:
            raise HTTPException(status_code=404, detail="用户会话不存在")

        # 构建cookies
        cookies = {
            "SESSDATA": user_session.sessdata,
            "bili_jct": user_session.bili_jct,
            "DedeUserID": user_session.dedeuserid
        }

        # 构建画像
        builder = get_multi_source_profile_builder()
        profile = await builder.build_comprehensive_profile(
            session_id=request.session_id,
            cookies=cookies,
            force_rebuild=request.force_rebuild
        )

        return {
            "success": True,
            "session_id": request.session_id,
            "data_sources": profile.get("data_sources", []),
            "total_analyzed": profile.get("total_analyzed", 0),
            "primary_interests": profile.get("primary_interests", [])[:10],
            "confidence_score": profile.get("confidence_score", 0.0),
            "message": f"画像构建完成，分析了 {profile.get('total_analyzed', 0)} 个内容"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"外部触发画像构建失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """健康检查接口，用于外部调度系统检测服务状态"""
    return {
        "status": "healthy",
        "service": "bilibili-rag-recommendation",
        "timestamp": datetime.utcnow().isoformat()
    }
