"""
工具注册初始化
"""
from app.services.tools.registry import ToolRegistry, tool_registry

# 导入所有工具实现
from app.services.tools.implementations.bilibili_tools import (
    SearchBilibiliTool,
    GetCommentsTool,
    GetUpInfoTool,
    GetTrendingTool,
    GetTopicInfoTool
)
from app.services.tools.implementations.web_tools import (
    WebSearchTool,
    WebNewsSearchTool,
    WebVideoSearchTool,
    GetLatestInfoTool
)
from app.services.tools.implementations.knowledge_tools import (
    RAGSearchTool,
    SummarizeTool,
    ListContentTool
)
from app.services.tools.implementations.account_tools import (
    OrganizeFavoritesTool,
    ScheduleSyncTool,
    GetFavoritesTool
)
from app.services.tools.implementations.recommendation_tools import (
    GetRecommendationsTool,
    UpdateInterestTool,
    GetUserProfileTool,
    FeedbackTool
)
from app.services.tools.implementations.time_tools import (
    GetCurrentTimeTool,
    CheckRecommendationNeededTool
)


def register_all_tools(registry: ToolRegistry) -> None:
    """
    注册所有工具到工具注册中心

    Args:
        registry: 工具注册中心实例
    """
    # Bilibili 工具
    registry.register(SearchBilibiliTool())
    registry.register(GetCommentsTool())
    registry.register(GetUpInfoTool())
    registry.register(GetTrendingTool())
    registry.register(GetTopicInfoTool())

    # Web 工具
    registry.register(WebSearchTool())
    registry.register(WebNewsSearchTool())
    registry.register(WebVideoSearchTool())
    registry.register(GetLatestInfoTool())

    # Knowledge/RAG 工具
    registry.register(RAGSearchTool())
    registry.register(SummarizeTool())
    registry.register(ListContentTool())

    # Account 工具
    registry.register(OrganizeFavoritesTool())
    registry.register(ScheduleSyncTool())
    registry.register(GetFavoritesTool())

    # Recommendation 工具
    registry.register(GetRecommendationsTool())
    registry.register(UpdateInterestTool())
    registry.register(GetUserProfileTool())
    registry.register(FeedbackTool())

    # Time 工具
    registry.register(GetCurrentTimeTool())
    registry.register(CheckRecommendationNeededTool())


__all__ = [
    "ToolRegistry",
    "tool_registry",
    "register_all_tools"
]
