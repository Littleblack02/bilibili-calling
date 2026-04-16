import json
from typing import Optional
from langchain.tools import tool

from app.services.gemma.cover_analyzer import get_cover_analyzer


@tool("analyze_cover", parse_docstring=True)
def analyze_cover_tool(
    video_id: str,
    cover_url: str,
    title: Optional[str] = None
) -> str:
    """分析视频封面的视觉内容和质量（Gemma 4 多模态理解）

    使用此工具来理解视频封面的视觉风格、质量评分和内容标签。
    这有助于判断视频是否符合用户的视觉偏好。

    Args:
        video_id: 视频 BV 号（如 "BV1xx411c7mD"）
        cover_url: 封面图片 URL（B站 CDN 地址）
        title: 视频标题（可选，提供上下文有助于更准确的分析）

    Returns:
        JSON 字符串，包含分析结果：
        {
            "video_id": str,
            "cover_url": str,
            "visual_tags": List[str],     # 视觉标签（如：教程、编程、高质量封面）
            "visible_text": List[str],    # 封面可见文字（OCR）
            "style_label": str,          # 风格分类（教程/新闻/娱乐/实战/科普/其他）
            "quality_score": float,      # 质量评分 0~1
            "topic_guess": str,          # 主题猜测
            "raw_caption": str           # Gemma 4 原始输出
        }
    """
    import asyncio

    async def _analyze():
        analyzer = get_cover_analyzer()
        return await analyzer.analyze_cover(
            bvid=video_id,
            pic_url=cover_url,
            title=title,
            force_reanalyze=False
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_analyze())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"video_id": video_id, "error": f"封面分析失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)
