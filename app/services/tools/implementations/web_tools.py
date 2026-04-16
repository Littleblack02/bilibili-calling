"""
Web搜索相关工具实现
"""
import time
from app.services.tools.base import BaseTool, ToolResult
from app.services.web_search import WebSearchService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class WebSearchTool(BaseTool):
    """联网搜索工具"""

    name = "web_search"
    description = "通过DuckDuckGo在互联网上搜索信息，无需API Key。可用于获取最新新闻、技术资料等。"
    agent_type = "web"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "num_results": {
                "type": "integer",
                "description": "返回结果数量",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            service = WebSearchService()
            result = await service.search(query=query, num_results=num_results)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("results"),
                error=result.get("error"),
                source=result.get("source", "web_search"),
                execution_time_ms=execution_time,
                metadata={"query": query, "count": result.get("count", 0)}
            )
        except Exception as e:
            logger.error(f"WebSearchTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="web_search",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class WebNewsSearchTool(BaseTool):
    """新闻搜索工具"""

    name = "web_news_search"
    description = "搜索最新新闻资讯，适用于需要了解时事热点、行业动态等场景。"
    agent_type = "web"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "新闻关键词"
            },
            "num_results": {
                "type": "integer",
                "description": "返回结果数量",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            service = WebSearchService()
            result = await service.search_news(query=query, num_results=num_results)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("results"),
                error=result.get("error"),
                source=result.get("source", "web_news_search"),
                execution_time_ms=execution_time,
                metadata={"query": query, "count": result.get("count", 0)}
            )
        except Exception as e:
            logger.error(f"WebNewsSearchTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="web_news_search",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class WebVideoSearchTool(BaseTool):
    """视频搜索工具"""

    name = "web_video_search"
    description = "搜索网络上的视频内容，支持多个视频平台。"
    agent_type = "web"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "视频搜索关键词"
            },
            "num_results": {
                "type": "integer",
                "description": "返回结果数量",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            service = WebSearchService()
            result = await service.search_videos(query=query, num_results=num_results)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("results"),
                error=result.get("error"),
                source=result.get("source", "web_video_search"),
                execution_time_ms=execution_time,
                metadata={"query": query, "count": result.get("count", 0)}
            )
        except Exception as e:
            logger.error(f"WebVideoSearchTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="web_video_search",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetLatestInfoTool(BaseTool):
    """获取最新信息工具（综合搜索）"""

    name = "get_latest_info"
    description = "获取主题的最新综合信息，包括网页和新闻。适合快速了解某个话题的最新动态。"
    agent_type = "web"
    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "想了解的主题"
            }
        },
        "required": ["topic"]
    }

    async def execute(self, topic: str, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            service = WebSearchService()
            result = await service.get_latest_info(topic=topic)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data={
                    "web": result.get("web", []),
                    "news": result.get("news", [])
                },
                error=result.get("error"),
                source=result.get("source", "web_latest_info"),
                execution_time_ms=execution_time,
                metadata={
                    "topic": topic,
                    "total_count": result.get("total_count", 0)
                }
            )
        except Exception as e:
            logger.error(f"GetLatestInfoTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="web_latest_info",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
