"""
添加封面分析方法到 multi_source_profile_builder.py
"""
async def _analyze_cover_styles(
    self,
    videos: List[Dict[str, Any]],
    session_id: str
) -> Dict[str, float]:
    """
    分析视频封面风格，提取视觉偏好

    Args:
        videos: 视频列表
        session_id: 会话ID

    Returns:
        视觉风格偏好字典，如 {"教程": 0.7, "高质量": 0.8}
    """
    if not videos:
        return {}

    visual_tags_counter = Counter()
    quality_scores = []
    style_categories = Counter()

    # 最多分析前10个视频的封面（避免耗时太长）
    for video in videos[:10]:
        bvid = video.get("bvid", "")
        pic_url = video.get("pic_url", "")
        title = video.get("title", "")

        if not bvid or not pic_url:
            continue

        try:
            # 调用封面分析器
            analysis = await self.cover_analyzer.analyze_cover(
                bvid=bvid,
                pic_url=pic_url,
                title=title,
                force_reanalyze=False  # 使用缓存结果
            )

            # 统计视觉标签
            for tag in analysis.get("visual_tags", []):
                visual_tags_counter[tag] += 1

            # 统计质量分数
            quality_score = analysis.get("quality_score", 0.5)
            quality_scores.append(quality_score)

            # 统计风格分类
            style_category = analysis.get("style_category", "unknown")
            style_categories[style_category] += 1

        except Exception as e:
            logger.warning(f"封面分析失败 {bvid}: {e}")
            continue

    # 计算视觉偏好
    visual_preference = {}

    # 1. 视觉标签偏好（归一化）
    if visual_tags_counter:
        total_tags = sum(visual_tags_counter.values())
        visual_preference.update({
            f"tag_{tag}": count / total_tags
            for tag, count in visual_tags_counter.most_common(10)
        })

    # 2. 平均质量分数
    if quality_scores:
        avg_quality = sum(quality_scores) / len(quality_scores)
        visual_preference["avg_quality"] = avg_quality

    # 3. 风格分类偏好
    if style_categories:
        total_styles = sum(style_categories.values())
        visual_preference.update({
            f"style_{style}": count / total_styles
            for style, count in style_categories.items()
        })

    logger.info(f"封面分析完成: 分析了{len(quality_scores)}个封面, "
                f"风格偏好: {dict(style_categories.most_common(3))}")

    return visual_preference


# 将方法添加到 MultiSourceProfileBuilder 类中
