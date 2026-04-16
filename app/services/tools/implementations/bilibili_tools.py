"""
Bilibili相关工具实现
"""
import time
from app.services.tools.base import BaseTool, ToolResult
from app.services.bilibili import BilibiliService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SearchBilibiliTool(BaseTool):
    """B站搜索工具"""

    name = "search_bilibili"
    description = "在B站搜索视频、番剧、UP主等内容。支持按关键词搜索，可指定排序方式和时长筛选。"
    agent_type = "bilibili"
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "搜索关键词"
            },
            "search_type": {
                "type": "string",
                "enum": ["video", "mediakit", "bangumi", "foto", "user"],
                "description": "搜索类型：video=视频, user=UP主, bangumi=番剧",
                "default": "video"
            },
            "page": {
                "type": "integer",
                "description": "页码，从1开始",
                "default": 1
            },
            "order": {
                "type": "string",
                "enum": ["totalrank", "click", "pubdate", "dm", "stow"],
                "description": "排序方式：totalrank=综合排序, click=播放量, pubdate=发布时间, dm=评论数, stow=收藏数",
                "default": "totalrank"
            }
        },
        "required": ["keyword"]
    }

    async def execute(self, keyword: str, search_type: str = "video", page: int = 1, order: str = "totalrank", **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            async with BilibiliService() as bilibili:
                result = await bilibili.search_bilibili(
                    keyword=keyword,
                    search_type=search_type,
                    page=page,
                    order=order
                )

            execution_time = int((time.time() - start_time) * 1000)
            result["execution_time_ms"] = execution_time

            return ToolResult(
                success=result.get("success", False),
                data=result.get("data"),
                error=result.get("error"),
                source=result.get("source", "bilibili_search"),
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"SearchBilibiliTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="bilibili_search",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetCommentsTool(BaseTool):
    """获取视频评论工具"""

    name = "get_comments"
    description = "获取B站视频的评论，支持热门评论和时间线排序。"
    agent_type = "bilibili"
    parameters = {
        "type": "object",
        "properties": {
            "aid": {
                "type": "integer",
                "description": "视频的AV号（数字ID）"
            },
            "mode": {
                "type": "integer",
                "enum": [2, 3],
                "description": "评论模式：2=热门评论, 3=按时间排序",
                "default": 2
            },
            "ps": {
                "type": "integer",
                "description": "每页评论数量，最多20",
                "default": 20
            }
        },
        "required": ["aid"]
    }

    async def execute(self, aid: int, mode: int = 2, ps: int = 20, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            async with BilibiliService() as bilibili:
                result = await bilibili.get_comments(aid=aid, mode=mode, ps=ps)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("data"),
                error=result.get("error"),
                source=result.get("source", "bilibili_comments"),
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"GetCommentsTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="bilibili_comments",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetUpInfoTool(BaseTool):
    """获取UP主信息工具"""

    name = "get_up_info"
    description = "获取B站UP主的详细信息，包括粉丝数、头像、简介等。"
    agent_type = "bilibili"
    parameters = {
        "type": "object",
        "properties": {
            "mid": {
                "type": "integer",
                "description": "UP主的数字ID"
            }
        },
        "required": ["mid"]
    }

    async def execute(self, mid: int, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            async with BilibiliService() as bilibili:
                result = await bilibili.get_up_info(mid=mid)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("data"),
                error=result.get("error"),
                source=result.get("source", "bilibili_up_info"),
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"GetUpInfoTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="bilibili_up_info",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetTrendingTool(BaseTool):
    """获取排行榜工具"""

    name = "get_trending"
    description = "获取B站排行榜，包括全站和各分区的热门视频。"
    agent_type = "bilibili"
    parameters = {
        "type": "object",
        "properties": {
            "rid": {
                "type": "integer",
                "description": "分区ID，0表示全站排行榜。常见分区：1=动画, 3=音乐, 4=游戏, 5=科技, 11=电视剧",
                "default": 0
            }
        },
        "required": []
    }

    async def execute(self, rid: int = 0, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            async with BilibiliService() as bilibili:
                result = await bilibili.get_trending(rid=rid)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("data"),
                error=result.get("error"),
                source=result.get("source", "bilibili_trending"),
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"GetTrendingTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="bilibili_trending",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetTopicInfoTool(BaseTool):
    """获取话题信息工具"""

    name = "get_topic_info"
    description = "获取B站话题/标签的详细信息和相关视频。"
    agent_type = "bilibili"
    parameters = {
        "type": "object",
        "properties": {
            "tag_name": {
                "type": "string",
                "description": "话题/标签名称"
            }
        },
        "required": ["tag_name"]
    }

    async def execute(self, tag_name: str, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            async with BilibiliService() as bilibili:
                result = await bilibili.get_topic_info(tag_name=tag_name)

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.get("success", False),
                data=result.get("data"),
                error=result.get("error"),
                source=result.get("source", "bilibili_topic_info"),
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"GetTopicInfoTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="bilibili_topic_info",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
