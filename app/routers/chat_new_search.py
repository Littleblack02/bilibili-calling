async def _search_bilibili_and_build_messages(session_id: str, question: str) -> tuple[list[dict], list[dict]]:
    """调用Bilibili搜索并构建消息"""
    try:
        # 获取用户会话信息
        session = await get_session(session_id)
        if not session:
            return _build_direct_messages(question), []

        cookies = session.get("cookies", {})
        bili = BilibiliService(
            sessdata=cookies.get("SESSDATA"),
            bili_jct=cookies.get("bili_jct"),
            dedeuserid=cookies.get("DedeUserID")
        )

        # 提取搜索关键词
        search_keyword = question

        # 处理"有什么X"这类问题，提取X作为关键词
        if "有什么" in question:
            # 提取"有什么"后面的内容
            parts = question.split("有什么")
            if len(parts) > 1 and parts[1].strip():
                search_keyword = parts[1].strip()
                # 移除"的吗"、"呢"等语气词
                for suffix in ["的吗", "吗", "呢", "啊", "？", "?"]:
                    search_keyword = search_keyword.removesuffix(suffix).strip()
        else:
            # 移除常见的推荐词汇和语气词
            remove_patterns = [
                "推荐", "建议", "介绍", "视频推荐", "好看的", "值得看",
                "可以给我", "能不能", "能否", "帮我", "请",
                "一下", "一些", "几个", "点", "呀", "呢", "吗", "？", "?"
            ]
            for pattern in remove_patterns:
                search_keyword = search_keyword.replace(pattern, "").strip()

        # 如果关键词为空或太短，使用通用搜索
        if not search_keyword or len(search_keyword) < 2:
            search_keyword = "热门视频"

        logger.info(f"正在搜索Bilibili: {search_keyword}")

        # 调用搜索API
        search_result = await bili.search_bilibili(
            keyword=search_keyword,
            search_type="video",
            page=1,
            order="totalrank"  # 综合排序
        )

        await bili.close()

        if not search_result.get("success") or not search_result.get("items"):
            logger.warning(f"Bilibili搜索失败或无结果: {search_result}")
            return _build_direct_messages(question), []

        # 格式化搜索结果
        items = search_result.get("items", [])[:10]  # 限制前10个结果
        search_context = "以下是为你搜索到的相关视频推荐：\n\n"

        sources = []
        for idx, item in enumerate(items, 1):
            title = item.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", "")
            author = item.get("author", "")
            description = item.get("description", "")[:100]  # 限制描述长度
            play = item.get("play", 0)
            duration = item.get("duration", "")

            search_context += f"{idx}. {title}\n"
            search_context += f"   UP主: {author} | 播放: {play:,} | 时长: {duration}\n"
            if description:
                search_context += f"   简介: {description}...\n"
            search_context += "\n"

            # 构建来源信息
            sources.append({
                "bvid": item.get("bvid", ""),
                "title": title,
                "author": author,
                "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}"
            })

        system = (
            "你是一个Bilibili视频推荐助手。\n"
            "根据以下搜索结果为用户提供视频推荐。\n"
            "回答要：\n"
            "1. 根据用户需求推荐最合适的视频\n"
            "2. 简要说明推荐理由\n"
            "3. 可以提及视频的播放数、UP主等信息\n"
            "4. 友好自然，不要机械罗列\n\n"
            f"{search_context}"
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": question}
        ]

        return messages, sources

    except Exception as e:
        logger.error(f"Bilibili搜索出错: {e}")
        return _build_direct_messages(question), []