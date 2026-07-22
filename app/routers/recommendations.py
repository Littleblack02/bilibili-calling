from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Any, List, Literal, Optional
from app.services.recommendation import (
    RecommendationModelRequiredError,
    RecommendationService,
)
from app.services.recommendation.event_service import get_recommendation_event_service
from app.routers.websocket_manager import manager
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


class GetRecommendationsRequest(BaseModel):
    """获取推荐请求"""
    session_id: str
    num: int = Field(default=10, ge=1, le=50)
    rec_type: str = "all"
    mode: Literal["balanced", "learning", "relax", "following", "explore", "rediscover"] = "balanced"
    query: Optional[str] = Field(default=None, max_length=100)
    max_duration: Optional[int] = Field(default=None, ge=60, le=14400)
    exploration_level: float = Field(default=0.3, ge=0.0, le=1.0)


class FeedbackRequest(BaseModel):
    """反馈请求"""
    session_id: str
    bvid: str
    action: str  # viewed/favorited/dismissed/ignored
    batch_id: Optional[str] = None
    reason_code: Optional[str] = None
    topic: Optional[str] = None
    up_mid: Optional[int] = None


class RecommendationEventRequest(BaseModel):
    session_id: str
    bvid: str
    event_type: str
    batch_id: Optional[str] = None
    reason_code: Optional[str] = None
    topic: Optional[str] = None
    up_mid: Optional[int] = None
    position: Optional[int] = None
    score: Optional[float] = None
    event_data: dict[str, Any] = Field(default_factory=dict)


class ProfilePreferencesUpdate(BaseModel):
    tag_updates: dict[str, Optional[float]] = Field(default_factory=dict)
    current_intent: Optional[str] = Field(default=None, max_length=100)
    reset_recent: bool = False


class UnblockPreferenceRequest(BaseModel):
    preference_type: Literal["topic", "up"]
    topic: Optional[str] = None
    up_mid: Optional[int] = None


class FavoritePreviewRequest(BaseModel):
    session_id: str
    bvid: str


class FavoriteExecuteRequest(BaseModel):
    session_id: str
    bvid: str
    target_media_id: int
    confirmed: bool = False
    batch_id: Optional[str] = None
    topic: Optional[str] = None
    up_mid: Optional[int] = None


@router.post("/")
async def get_recommendations(request: GetRecommendationsRequest):
    """获取个性化推荐"""
    try:
        rec_service = RecommendationService()

        # generate_recommendations 即完整的推荐生成链路
        recommendations = await rec_service.generate_recommendations(
            session_id=request.session_id,
            limit=request.num,
            context={
                "mode": request.mode,
                "query": request.query,
                "max_duration": request.max_duration,
                "exploration_level": request.exploration_level,
            },
        )

        return {
            "success": True,
            "recommendations": recommendations,
            "count": len(recommendations)
        }

    except RecommendationModelRequiredError as e:
        logger.error(f"Required recommendation model unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))
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
        event_service = get_recommendation_event_service()

        event_mapping = {
            "viewed": "viewed",
            "favorited": "favorite",
            "favorite": "favorite",
            "liked": "like",
            "like": "like",
            "watch_later": "watch_later",
            "dismissed": "dismiss",
            "ignored": "dismiss",
            "block_topic": "block_topic",
            "block_up": "block_up",
        }
        event_type = event_mapping.get(request.action)
        if not event_type:
            raise HTTPException(status_code=422, detail="不支持的反馈类型")

        await event_service.record_event(
            session_id=request.session_id,
            bvid=request.bvid,
            event_type=event_type,
            batch_id=request.batch_id,
            reason_code=request.reason_code,
            topic=request.topic,
            up_mid=request.up_mid,
        )

        # 根据 action 映射到对应的反馈处理方法
        if request.action in ("dismissed", "ignored", "block_topic", "block_up"):
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
                success = True
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
                success = True

        return {
            "success": success,
            "message": "反馈已记录" if success else "未找到对应推荐记录"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Submit feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events")
async def record_recommendation_event(request: RecommendationEventRequest):
    """记录曝光、点击等推荐事件；同批次同类型事件自动去重。"""
    try:
        created = await get_recommendation_event_service().record_event(
            session_id=request.session_id,
            bvid=request.bvid,
            event_type=request.event_type,
            batch_id=request.batch_id,
            reason_code=request.reason_code,
            topic=request.topic,
            up_mid=request.up_mid,
            position=request.position,
            score=request.score,
            event_data=request.event_data,
        )
        return {"success": True, "created": created}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"Record recommendation event error: {exc}")
        raise HTTPException(status_code=500, detail="记录推荐事件失败")


@router.get("/metrics/{session_id}")
async def get_recommendation_metrics(session_id: str, days: int = 30):
    """返回仅基于真实事件的最小推荐指标。"""
    return {
        "success": True,
        "metrics": await get_recommendation_event_service().metrics(session_id, days),
    }


@router.get("/profile-sources/{session_id}")
async def get_profile_source_status(session_id: str):
    """Return channel coverage, local counts and freshness for profile auditing."""
    from sqlalchemy import func, select
    from app.database import async_session_factory
    from app.models import UserContentSignal, UserInterestProfile
    from app.services.bilibili import BilibiliService

    async with async_session_factory() as db:
        result = await db.execute(
            select(
                UserContentSignal.source,
                func.count(UserContentSignal.id),
                func.max(UserContentSignal.occurred_at),
                func.max(UserContentSignal.last_seen_at),
            )
            .where(
                UserContentSignal.session_id == session_id,
                UserContentSignal.is_active == True,
            )
            .group_by(UserContentSignal.source)
        )
        rows = result.all()
        profile_result = await db.execute(select(UserInterestProfile).where(
            UserInterestProfile.session_id == session_id
        ))
        profile = profile_result.scalar_one_or_none()
    features = profile.profile_features if profile and isinstance(profile.profile_features, dict) else {}
    return {
        "success": True,
        "capabilities": BilibiliService.profile_channel_capabilities(),
        "collected": {
            source: {
                "count": count,
                "newest_event_at": newest_event,
                "last_seen_at": last_seen,
                "freshness": (features.get("source_freshness") or {}).get(source),
            }
            for source, count, newest_event, last_seen in rows
        },
        "profile_model": features.get("model"),
        "ontology_version": features.get("ontology_version"),
    }


@router.get("/preferences/{session_id}")
async def get_recommendation_preferences(session_id: str):
    """返回可编辑画像标签、来源、置信度和当前屏蔽项。"""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models import UserInterestProfile
    from app.services.recommendation.profile_schema import normalize_profile

    async with async_session_factory() as db:
        result = await db.execute(select(UserInterestProfile).where(
            UserInterestProfile.session_id == session_id
        ))
        profile_row = result.scalar_one_or_none()
    raw = {
        "interest_tags": profile_row.interest_tags or {},
        "recent_interests": profile_row.recent_interest_shift or {},
        "followed_ups": profile_row.followed_ups or [],
        "category_distribution": profile_row.category_distribution or {},
        "confidence_score": profile_row.confidence_score or 0.0,
        "updated_at": profile_row.updated_at,
        "current_intent": (profile_row.short_term_focus or {}).get("focus")
            if isinstance(profile_row.short_term_focus, dict) else None,
        "profile_features": profile_row.profile_features or {},
    } if profile_row else {}
    profile = normalize_profile(raw)
    state = await get_recommendation_event_service().get_preference_state(session_id)
    interest_evidence = features.get("interest_evidence") or []
    def tag_period(tag: str) -> str:
        if tag in profile.recent_interests:
            return "recent"
        matching_ages = [
            float(row.get("age_days", 0.0)) for row in interest_evidence
            if isinstance(row, dict) and str(row.get("concept_label") or "") == tag
        ]
        return "historical" if matching_ages and min(matching_ages) > 180 else "long_term"
    tags = [
        {"tag": tag, "score": score, "source": tag_period(tag)}
        for tag, score in sorted(profile.interest_tags.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "success": True,
        "preferences": {
            "tags": tags,
            "current_intent": profile.current_intent,
            "confidence_score": profile.confidence_score,
            "updated_at": profile.updated_at,
            "blocked_topics": sorted(state["blocked_topics"]),
            "blocked_up_mids": sorted(state["blocked_up_mids"]),
            "ontology_version": profile.ontology_version,
            "multi_interests": profile.multi_interests,
            "source_freshness": profile.source_freshness,
            "interest_evidence": interest_evidence,
        },
    }


@router.put("/preferences/{session_id}")
async def update_recommendation_preferences(session_id: str, request: ProfilePreferencesUpdate):
    """显式调整画像；分数范围为 0~1，null 表示删除标签。"""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models import UserInterestProfile

    for tag, score in request.tag_updates.items():
        if not tag.strip() or len(tag) > 100:
            raise HTTPException(status_code=422, detail="画像标签无效")
        if score is not None and not 0.0 <= score <= 1.0:
            raise HTTPException(status_code=422, detail="标签分数必须在0到1之间")

    async with async_session_factory() as db:
        result = await db.execute(select(UserInterestProfile).where(
            UserInterestProfile.session_id == session_id
        ))
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="用户画像不存在，请先更新画像")
        tags = dict(profile.interest_tags or {})
        for tag, score in request.tag_updates.items():
            normalized_tag = tag.strip()
            if score is None:
                tags.pop(normalized_tag, None)
            else:
                tags[normalized_tag] = score
        profile.interest_tags = tags
        if request.current_intent is not None:
            profile.short_term_focus = {
                "focus": request.current_intent.strip(),
                "source": "user_explicit",
            }
        if request.reset_recent:
            profile.recent_interest_shift = {}
        profile.last_update_source = "user_explicit"
        await db.commit()
    return {"success": True, "message": "推荐偏好已更新"}


@router.post("/preferences/{session_id}/unblock")
async def unblock_recommendation_preference(session_id: str, request: UnblockPreferenceRequest):
    """解除主题或 UP 主屏蔽，同时保留可审计的解除事件。"""
    if request.preference_type == "topic" and request.topic:
        event_type = "unblock_topic"
    elif request.preference_type == "up" and request.up_mid:
        event_type = "unblock_up"
    else:
        raise HTTPException(status_code=422, detail="解除屏蔽参数无效")
    await get_recommendation_event_service().record_event(
        session_id=session_id,
        bvid="__preference__",
        event_type=event_type,
        topic=request.topic,
        up_mid=request.up_mid,
        event_data={"source": "user_explicit"},
    )
    return {"success": True, "message": "已解除屏蔽"}


@router.post("/favorite/preview")
async def preview_recommendation_favorite(request: FavoritePreviewRequest):
    """只返回可选目标收藏夹；不执行任何 B 站写操作。"""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models import FavoriteFolder
    from app.routers.auth import get_session

    if not await get_session(request.session_id):
        raise HTTPException(status_code=401, detail="会话已失效")
    async with async_session_factory() as db:
        result = await db.execute(
            select(FavoriteFolder).where(FavoriteFolder.session_id == request.session_id)
            .order_by(FavoriteFolder.title)
        )
        folders = list(result.scalars())
    return {
        "success": True,
        "bvid": request.bvid,
        "requires_confirmation": True,
        "folders": [{"media_id": folder.media_id, "title": folder.title} for folder in folders],
    }


@router.post("/favorite/execute")
async def execute_recommendation_favorite(request: FavoriteExecuteRequest):
    """用户明确选择收藏夹并确认后，才执行真实 B 站收藏写操作。"""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models import FavoriteFolder
    from app.routers.auth import get_session
    from app.services.bilibili import BilibiliService

    if not request.confirmed:
        raise HTTPException(status_code=409, detail="需要用户明确确认收藏操作")
    session = await get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=401, detail="会话已失效")
    async with async_session_factory() as db:
        result = await db.execute(select(FavoriteFolder).where(
            FavoriteFolder.session_id == request.session_id,
            FavoriteFolder.media_id == request.target_media_id,
        ))
        folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=422, detail="目标收藏夹不属于当前会话")

    cookies = session.get("cookies", {})
    bili = BilibiliService(
        sessdata=cookies.get("SESSDATA"),
        bili_jct=cookies.get("bili_jct"),
        dedeuserid=cookies.get("DedeUserID"),
    )
    async with bili:
        result = await bili.add_to_favorites(request.target_media_id, request.bvid)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail="B站收藏操作失败")

    await get_recommendation_event_service().record_event(
        session_id=request.session_id,
        bvid=request.bvid,
        event_type="favorite",
        batch_id=request.batch_id,
        topic=request.topic,
        up_mid=request.up_mid,
        event_data={"target_media_id": request.target_media_id, "confirmed": True},
    )
    return {"success": True, "message": f"已收藏到「{folder.title}」"}


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
    except RecommendationModelRequiredError as e:
        await websocket.send_json({
            "type": "recommendation_error",
            "code": "required_model_unavailable",
            "message": str(e),
        })
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
