"""
推荐系统服务

负责：
- 候选召回（多路召回）
- LLM 重排
- 推荐理由生成
"""
from app.services.recommendation.recommendation_service import (
    RecommendationModelRequiredError,
    RecommendationService,
)

__all__ = ["RecommendationService", "RecommendationModelRequiredError"]
