from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List
from app.services.recommendation import RecommendationService
from app.routers.websocket_manager import manager
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


class GetRecommendationsRequest(BaseModel):
    """获取推荐请求"""
    session_id: str
    num: int = 10
    rec_type: str = "all"


class FeedbackRequest(BaseModel):
    """反馈请求"""
    session_id: str
    bvid: str
    action: str  # viewed/favorited/dismissed/ignored


@router.post("/")
async def get_recommendations(request: GetRecommendationsRequest):
    """获取个性化推荐"""
    try:
        rec_service = RecommendationService()

        # generate_recommendations 即完整的推荐生成链路
        recommendations = await rec_service.generate_recommendations(
            session_id=request.session_id,
            limit=request.num
        )

        return {
            "success": True,
            "recommendations": recommendations,
            "count": len(recommendations)
        }

    except Exception as e:
        logger.error(f"Get recommendations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-interest")
async def update_interest_profile(session_id: str):
    """获取或更新兴趣画像"""
    try:
        from app.services.profile.multi_source_profile_builder import get_multi_source_profile_builder
        from app.models import UserSession
        from app.database import async_session_factory
        from sqlalchemy import select

        # 获取用户 cookies
        cookies = None
        async with async_session_factory() as db:
            result = await db.execute(
                select(UserSession).where(UserSession.session_id == session_id)
            )
            user_session = result.scalar_one_or_none()

        if user_session:
            cookies = {
                "SESSDATA": user_session.sessdata,
                "bili_jct": user_session.bili_jct,
                "DedeUserID": user_session.dedeuserid
            }

        # 使用多通道画像构建器
        profile_builder = get_multi_source_profile_builder()

        # 直接从数据库重新构建画像（确保数据完整）
        profile = await profile_builder.build_comprehensive_profile(
            session_id=session_id,
            cookies=cookies,
            force_rebuild=False  # 优先使用数据库缓存的数据，避免重复调用B站API
        )

        return {
            "success": True,
            "profile": profile
        }

    except Exception as e:
        logger.error(f"Update interest profile error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """提交推荐反馈"""
    try:
        rec_service = RecommendationService()

        # 根据 action 映射到对应的反馈处理方法
        if request.action in ("dismissed", "ignored"):
            # 拒绝推荐
            # 先查询 candidate_id
            candidates = await rec_service.get_candidate_recommendations(
                session_id=request.session_id,
                status="pending",
                limit=100
            )
            target = next((c for c in candidates if c.get("bvid") == request.bvid), None)
            if target:
                success = await rec_service.reject_recommendation(
                    session_id=request.session_id,
                    candidate_id=target["id"]
                )
            else:
                success = False
        else:
            # 接受推荐（viewed/favorited）
            # 查询候选记录并标记为 accepted
            candidates = await rec_service.get_candidate_recommendations(
                session_id=request.session_id,
                status="pending",
                limit=100
            )
            target = next((c for c in candidates if c.get("bvid") == request.bvid), None)
            if target:
                success = await rec_service.accept_recommendation(
                    session_id=request.session_id,
                    candidate_id=target["id"],
                    target_media_id=0  # 需前端传入目标收藏夹
                )
            else:
                success = False

        return {
            "success": success,
            "message": "反馈已记录" if success else "未找到对应推荐记录"
        }

    except Exception as e:
        logger.error(f"Submit feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/{session_id}")
async def websocket_recommendations(websocket: WebSocket, session_id: str):
    """WebSocket推荐推送接口"""
    await manager.connect(websocket, session_id)

    try:
        while True:
            # 等待客户端消息
            data = await websocket.receive_json()

            # 处理消息
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "get_recommendations":
                # 获取推荐
                rec_service = RecommendationService()
                recommendations = await rec_service.generate_recommendations(
                    session_id=session_id,
                    limit=data.get("num", 5)
                )
                await websocket.send_json({
                    "type": "recommendations",
                    "data": recommendations
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
