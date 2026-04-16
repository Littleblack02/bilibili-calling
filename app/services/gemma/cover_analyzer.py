"""
封面多模态理解服务

使用阿里云百炼（DashScope）的多模态模型分析视频封面
"""
import base64
import httpx
from typing import Optional, Dict, List, Any
from loguru import logger
from datetime import datetime

from app.models import VideoCoverAnalysis
from app.database import async_session_factory
from sqlalchemy import select, update


class CoverAnalyzer:
    """封面多模态理解服务"""

    def __init__(
        self,
        api_key: str = None,
        model_name: str = None,
        base_url: str = None,
        timeout: float = 60.0
    ):
        from app.config import settings
        self.api_key = api_key or settings.dashscope_api_key
        self.model_name = model_name or settings.cover_vision_model  # 模型
        self.base_url = base_url or settings.dashscope_base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def analyze_cover(
        self,
        bvid: str,
        pic_url: str,
        title: Optional[str] = None,
        force_reanalyze: bool = False
    ) -> Dict[str, Any]:
        """
        分析视频封面

        Args:
            bvid: 视频 BV 号
            pic_url: 封面图片 URL
            title: 视频标题（提供上下文）
            force_reanalyze: 是否强制重新分析

        Returns:
            分析结果字典：
            {
                "bvid": str,
                "visual_tags": List[str],  # 视觉标签
                "visual_summary": str,     # 封面描述
                "quality_score": float,   # 质量评分 0~1
                "style_category": str,    # 风格分类
                "analyzed_at": datetime
            }
        """
        # 检查是否已分析过
        if not force_reanalyze:
            existing = await self._get_existing_analysis(bvid)
            if existing:
                logger.info(f"封面分析结果已存在: {bvid}")
                return existing

        logger.info(f"开始分析封面: {bvid} - {pic_url}")

        try:
            # 构建提示词
            prompt = self._build_cover_analysis_prompt(title)

            # 调用百炼多模态 API
            result = await self._call_vision_api(prompt, pic_url)

            # 解析结果
            analysis = self._parse_analysis_result(bvid, result)

            # 保存到数据库
            await self._save_analysis(analysis)

            logger.info(f"封面分析完成: {bvid}")
            return analysis

        except Exception as e:
            logger.error(f"封面分析失败: {bvid}, 错误: {e}")
            # 返回默认分析结果
            return {
                "bvid": bvid,
                "visual_tags": [],
                "visual_summary": "分析失败",
                "quality_score": 0.5,
                "style_category": "unknown",
                "analyzed_at": datetime.utcnow()
            }

    def _build_cover_analysis_prompt(self, title: Optional[str] = None) -> str:
        """构建封面分析提示词"""
        base_prompt = """分析这个视频封面图片，提供以下信息：

        1. **视觉标签** (visual_tags): 提取 3-5 个关键词，如：教程、编程、高质量封面、新闻、娱乐等
        2. **视觉描述** (visual_summary): 用一句话描述封面的视觉内容和风格
        3. **质量评分** (quality_score): 给封面质量打分 0~1（考虑清晰度、设计感、信息密度）
        4. **风格分类** (style_category): 归类为：教程 / 新闻 / 娱乐 / 实战 / 科普 / 其他

        请以 JSON 格式返回：
        {
        "visual_tags": ["标签1", "标签2", ...],
        "visual_summary": "封面描述",
        "quality_score": 0.8,
        "style_category": "教程"
        }"""

        if title:
            base_prompt = f"""视频标题：《{title}》{base_prompt}"""

        return base_prompt

    async def _call_vision_api(self, prompt: str, image_url: str) -> str:
        """
        调用阿里云百炼多模态 API

        使用 OpenAI 兼容格式调用 DashScope
        """
        # 下载图片
        try:
            async with httpx.AsyncClient(timeout=30.0) as img_client:
                img_response = await img_client.get(image_url)
                img_response.raise_for_status()
                image_data = img_response.content
        except Exception as e:
            logger.error(f"下载封面图片失败: {image_url}, 错误: {e}")
            return '{"visual_tags": [], "visual_summary": "图片加载失败", "quality_score": 0.5, "style_category": "unknown"}'

        # 将图片转为 base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        # 构建百炼 API 请求
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            "max_tokens": 1000
        }

        try:
            client = await self._get_client()
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            result = response.json()

            # 提取生成的文本
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"百炼响应格式异常: {result}")
                return '{"visual_tags": [], "visual_summary": "API调用失败", "quality_score": 0.5, "style_category": "unknown"}'

        except httpx.HTTPStatusError as e:
            logger.error(f"百炼 API 调用失败: {e.response.text}")
            return '{"visual_tags": [], "visual_summary": "API调用失败", "quality_score": 0.5, "style_category": "unknown"}'
        except Exception as e:
            logger.error(f"调用百炼 API 异常: {e}")
            return '{"visual_tags": [], "visual_summary": "API调用失败", "quality_score": 0.5, "style_category": "unknown"}'

    def _parse_analysis_result(self, bvid: str, result: str) -> Dict[str, Any]:
        """解析多模态模型返回的分析结果"""
        import json

        try:
            # 尝试解析 JSON
            # 模型可能返回 markdown 格式，需要提取 JSON 部分
            if "```json" in result:
                start = result.find("```json") + 7
                end = result.find("```", start)
                json_str = result[start:end].strip()
            elif "```" in result:
                start = result.find("```") + 3
                end = result.find("```", start)
                json_str = result[start:end].strip()
            else:
                json_str = result.strip()

            data = json.loads(json_str)

            return {
                "bvid": bvid,
                "visual_tags": data.get("visual_tags", []),
                "visual_summary": data.get("visual_summary", ""),
                "quality_score": float(data.get("quality_score", 0.5)),
                "style_category": data.get("style_category", "unknown"),
                "analyzed_at": datetime.utcnow()
            }

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"解析结果失败: {e}, 原始结果: {result}")
            return {
                "bvid": bvid,
                "visual_tags": [],
                "visual_summary": "解析失败",
                "quality_score": 0.5,
                "style_category": "unknown",
                "analyzed_at": datetime.utcnow()
            }

    async def _get_existing_analysis(self, bvid: str) -> Optional[Dict[str, Any]]:
        """获取已有的分析结果"""
        async with async_session_factory() as db:
            result = await db.execute(
                select(VideoCoverAnalysis).where(VideoCoverAnalysis.video_id == bvid)
            )
            analysis = result.scalar_one_or_none()

            if analysis and analysis.is_analyzed:
                return {
                    "bvid": analysis.video_id,
                    "visual_tags": analysis.visual_tags,
                    "quality_score": analysis.quality_score,
                    "style_category": analysis.style_label,
                    "analyzed_at": analysis.analyzed_at
                }

            return None

    async def _save_analysis(self, analysis: Dict[str, Any]):
        """保存分析结果到数据库"""
        async with async_session_factory() as db:
            existing = await db.execute(
                select(VideoCoverAnalysis).where(VideoCoverAnalysis.video_id == analysis["bvid"])
            )
            existing_record = existing.scalar_one_or_none()

            if existing_record:
                await db.execute(
                    update(VideoCoverAnalysis)
                    .where(VideoCoverAnalysis.video_id == analysis["bvid"])
                    .values(
                        visual_tags=analysis["visual_tags"],
                        quality_score=analysis["quality_score"],
                        style_label=analysis["style_category"],
                        is_analyzed=True,
                        analyzed_at=analysis["analyzed_at"]
                    )
                )
            else:
                new_analysis = VideoCoverAnalysis(
                    video_id=analysis["bvid"],
                    cover_url=analysis.get("cover_url", ""),
                    visual_tags=analysis["visual_tags"],
                    quality_score=analysis["quality_score"],
                    style_label=analysis["style_category"],
                    is_analyzed=True,
                    analyzed_at=analysis["analyzed_at"]
                )
                db.add(new_analysis)

            await db.commit()

    async def batch_analyze(
        self,
        videos: List[Dict[str, Any]],
        force_reanalyze: bool = False
    ) -> List[Dict[str, Any]]:
        """批量分析封面"""
        results = []

        for video in videos:
            bvid = video.get("bvid")
            pic_url = video.get("pic_url")
            title = video.get("title")

            if not bvid or not pic_url:
                logger.warning(f"跳过无效视频: {video}")
                continue

            try:
                result = await self.analyze_cover(bvid, pic_url, title, force_reanalyze)
                results.append(result)
            except Exception as e:
                logger.error(f"分析封面失败: {bvid}, 错误: {e}")
                results.append({
                    "bvid": bvid,
                    "visual_tags": [],
                    "visual_summary": "分析失败",
                    "quality_score": 0.5,
                    "style_category": "unknown",
                    "analyzed_at": datetime.utcnow()
                })

        return results


# 单例
_cover_analyzer: Optional[CoverAnalyzer] = None


def get_cover_analyzer() -> CoverAnalyzer:
    """获取封面分析器单例"""
    global _cover_analyzer
    if _cover_analyzer is None:
        _cover_analyzer = CoverAnalyzer()
    return _cover_analyzer
