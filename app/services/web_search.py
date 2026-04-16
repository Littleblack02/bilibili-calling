"""
Web搜索服务（使用 DuckDuckGo，无需API Key）
"""
from duckduckgo_search import DDGS
from typing import List, Dict, Any
from app.utils.logger import get_logger

logger = get_logger(__name__)


class WebSearchService:
    """联网搜索服务"""

    def __init__(self):
        self.ddgs = DDGS()

    async def search(
        self,
        query: str,
        num_results: int = 5
    ) -> Dict[str, Any]:
        """
        通用网页搜索

        Args:
            query: 搜索关键词
            num_results: 返回结果数量

        Returns:
            搜索结果字典
        """
        try:
            results = list(self.ddgs.text(
                query,
                max_results=num_results
            ))

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("link", ""),
                        "snippet": r.get("body", ""),
                        "source": "duckduckgo"
                    }
                    for r in results
                ],
                "count": len(results),
                "source": "web_search"
            }
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": [],
                "source": "web_search"
            }

    async def search_news(
        self,
        query: str,
        num_results: int = 5
    ) -> Dict[str, Any]:
        """
        新闻搜索

        Args:
            query: 搜索关键词
            num_results: 返回结果数量

        Returns:
            新闻搜索结果字典
        """
        try:
            results = list(self.ddgs.news(
                query,
                max_results=num_results
            ))

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("body", ""),
                        "date": r.get("date", ""),
                        "source": r.get("source", ""),
                        "source_type": "duckduckgo_news"
                    }
                    for r in results
                ],
                "count": len(results),
                "source": "web_news_search"
            }
        except Exception as e:
            logger.error(f"News search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": [],
                "source": "web_news_search"
            }

    async def search_videos(
        self,
        query: str,
        num_results: int = 5
    ) -> Dict[str, Any]:
        """
        视频搜索

        Args:
            query: 搜索关键词
            num_results: 返回结果数量

        Returns:
            视频搜索结果字典
        """
        try:
            results = list(self.ddgs.videos(
                query,
                max_results=num_results
            ))

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                        "duration": r.get("duration", ""),
                        "source": r.get("source", ""),
                        "source_type": "duckduckgo_videos"
                    }
                    for r in results
                ],
                "count": len(results),
                "source": "web_video_search"
            }
        except Exception as e:
            logger.error(f"Video search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": [],
                "source": "web_video_search"
            }

    async def get_latest_info(self, topic: str) -> Dict[str, Any]:
        """
        获取主题的最新信息（综合搜索）

        Args:
            topic: 主题

        Returns:
            综合信息字典
        """
        try:
            # 并行执行多种搜索
            import asyncio

            search_tasks = [
                self.search(topic, num_results=3),
                self.search_news(topic, num_results=3)
            ]

            results = await asyncio.gather(*search_tasks, return_exceptions=True)

            web_results = results[0] if not isinstance(results[0], Exception) else {"results": []}
            news_results = results[1] if not isinstance(results[1], Exception) else {"results": []}

            return {
                "success": True,
                "topic": topic,
                "web": web_results.get("results", []),
                "news": news_results.get("results", []),
                "total_count": len(web_results.get("results", [])) + len(news_results.get("results", [])),
                "source": "web_latest_info"
            }
        except Exception as e:
            logger.error(f"Get latest info failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "topic": topic,
                "web": [],
                "news": [],
                "source": "web_latest_info"
            }
