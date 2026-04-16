"""
Bilibili Tools - Wrap bilibili-rag's BilibiliService and related services
as LangChain Tools for DeerFlow.

These tools expose bilibili-rag's business logic to DeerFlow's agent framework.
All tools are synchronous (returning str) since they are called from DeerFlow's
sync tool execution context.
"""

import json
import asyncio
import concurrent.futures
from typing import Optional

from langchain.tools import tool
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine in a new event loop (for use from sync tool context)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_session_sync(session_id: str = None) -> Optional[dict]:
    """Fetch session info synchronously (for use from sync tool context).

    If session_id is not provided, tries to get it from DeerFlow session context.
    """
    from app.routers.auth import login_sessions
    from app.deerflow_tools.deerflow_session import DeerFlowSessionContext

    # If no session_id provided, try to get from DeerFlow session context
    if not session_id:
        session_id = DeerFlowSessionContext.get_session_id()
        logger.info(f"[DEBUG] _get_session_sync: got session_id from DeerFlowSessionContext: {session_id}")

    if not session_id:
        logger.warning("[DEBUG] _get_session_sync: no session_id available")
        return None

    logger.info(f"[DEBUG] _get_session_sync: using session_id = {session_id}")
    session = login_sessions.get(session_id)
    if session:
        logger.info(f"[DEBUG] _get_session_sync: found in login_sessions")
        return session

    # Fallback to DB query
    try:
        from app.database import async_session_factory
        from sqlalchemy import select
        from app.models import UserSession as UserSessionModel

        async def _fetch():
            async with async_session_factory() as db:
                result = await db.execute(
                    select(UserSessionModel).where(UserSessionModel.session_id == session_id)
                )
                db_session = result.scalar_one_or_none()
                if not db_session or not db_session.is_valid:
                    logger.warning(f"[DEBUG] _get_session_sync: session not found in DB or invalid")
                    return None
                logger.info(f"[DEBUG] _get_session_sync: found session in DB")
                return {
                    "cookies": {
                        "SESSDATA": db_session.sessdata,
                        "bili_jct": db_session.bili_jct,
                        "DedeUserID": db_session.dedeuserid,
                    },
                    "user_info": {
                        "mid": db_session.bili_mid,
                        "uname": db_session.bili_uname,
                        "face": db_session.bili_face,
                    },
                }

        result = _run_async(_fetch())
        if result:
            login_sessions[session_id] = result
        return result
    except Exception as e:
        logger.error(f"[DEBUG] _get_session_sync: error = {e}")
        return None


def _build_bilibili_service(cookies: dict):
    """Create a BilibiliService with the given cookies (overrides default cookies)."""
    from app.services.bilibili import BilibiliService

    service = BilibiliService()
    service.cookies = cookies
    return service


def _is_default_folder(folder: dict) -> bool:
    """Check if a folder is the default folder (same logic as app/routers/favorites.py)."""
    for key in ("is_default", "default", "isDefault"):
        if key in folder:
            return bool(folder.get(key))
    if folder.get("type") == 1:
        return True
    if folder.get("fav_state") == 1:
        return True
    if folder.get("attr") == 1:
        return True
    title = (folder.get("title") or "").strip()
    return title == "默认收藏夹"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@tool("get_bilibili_favorites", parse_docstring=True)
def get_bilibili_favorites_tool(session_id: str) -> str:
    """Get the user's Bilibili favorite folder list.

    Use this tool to find out what favorite folders the user has on Bilibili.
    This is useful before syncing content to the knowledge base.

    Args:
        session_id: The session ID from the user's current conversation thread.
            This is required to authenticate with Bilibili.

    Returns:
        A JSON string containing the list of favorite folders with their media IDs and video counts.
    """
    session = _get_session_sync(session_id)
    if not session or not session.get("cookies"):
        return json.dumps(
            {"error": "Session not found or expired. Please ask the user to log in via B站扫码登录."},
            ensure_ascii=False,
        )

    cookies = session["cookies"]
    user_info = session.get("user_info", {})
    mid = user_info.get("mid") or cookies.get("DedeUserID")

    if not mid:
        return json.dumps({"error": "User mid not found in session."}, ensure_ascii=False)

    try:
        bili = _build_bilibili_service(cookies)

        async def _fetch():
            async with bili:
                return await bili.get_user_favorites(mid=mid)

        folders = _run_async(_fetch())
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch favorites: {e}"}, ensure_ascii=False)

    if not folders:
        return json.dumps({"folders": [], "total": 0, "message": "No favorite folders found."}, ensure_ascii=False)

    formatted = []
    for f in folders:
        formatted.append({
            "media_id": f.get("id"),
            "title": f.get("title", "未命名收藏夹"),
            "video_count": f.get("media_count", 0),
            "is_default": _is_default_folder(f),
        })

    return json.dumps(
        {
            "folders": formatted,
            "total": len(formatted),
            "message": f"Found {len(formatted)} favorite folders.",
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("sync_favorite_folder", parse_docstring=True)
def sync_favorite_folder_tool(media_id: int, session_id: str) -> str:
    """Sync a Bilibili favorite folder to the knowledge base.

    This fetches all videos in the specified folder, extracts their content
    (subtitles/summaries), and adds them to the RAG knowledge base.
    This is a long-running operation — call this and inform the user it may take a while.

    Args:
        media_id: The Bilibili media ID of the favorite folder to sync.
            Use get_bilibili_favorites_tool first to find the correct media_id.
        session_id: The session ID from the user's current conversation thread.

    Returns:
        A JSON string with the sync result (videos processed, chunks added, errors).
    """
    session = _get_session_sync(session_id)
    if not session or not session.get("cookies"):
        return json.dumps(
            {"error": "Session not found or expired. Please ask the user to log in via B站扫码登录."},
            ensure_ascii=False,
        )

    cookies = session["cookies"]

    try:
        bili = _build_bilibili_service(cookies)

        async def _fetch_all_videos():
            async with bili:
                return await bili.get_all_favorite_videos(media_id)

        videos = _run_async(_fetch_all_videos())
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch folder content: {e}"}, ensure_ascii=False)

    if not videos:
        return json.dumps({"message": "No videos found in this folder."}, ensure_ascii=False)

    from app.services.rag import RAGService
    from app.services.content_fetcher import ContentFetcher
    from app.models import VideoContent, ContentSource

    rag = RAGService(collection_name="bilibili_videos")
    fetcher = ContentFetcher()

    processed = 0
    failed = 0
    total_chunks = 0
    errors = []

    for video in videos:
        bvid = video.get("bvid")
        title = video.get("title", "Unknown")
        if not bvid:
            continue

        try:
            async def _fetch_one():
                return await fetcher.fetch_content(bvid)

            content = _run_async(_fetch_one())
            if content:
                video_content = VideoContent(
                    bvid=bvid,
                    title=title,
                    content=content.content if hasattr(content, "content") else str(content),
                    source=ContentSource.BILI_SUBTITLE,
                )
                chunks = rag.add_video_content(video_content)
                processed += 1
                total_chunks += chunks
        except Exception as e:
            failed += 1
            errors.append(f"{bvid} ({title}): {e}")

    return json.dumps(
        {
            "media_id": media_id,
            "processed": processed,
            "failed": failed,
            "chunks_added": total_chunks,
            "errors": errors[:10],
            "message": f"Sync complete: {processed} videos processed, {failed} failed.",
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("get_video_info", parse_docstring=True)
def get_video_info_tool(bvid: str) -> str:
    """Get detailed information about a Bilibili video.

    Args:
        bvid: The Bilibili video BV ID (e.g., "BV1xx411c7XZ").

    Returns:
        A JSON string with the video's title, description, author, view count, etc.
    """
    from app.services.bilibili import BilibiliService

    try:
        bili = BilibiliService()

        async def _fetch():
            async with bili:
                return await bili.get_video_info(bvid=bvid)

        result = _run_async(_fetch())
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch video info: {e}"}, ensure_ascii=False)

    if not result.get("success"):
        return json.dumps({"error": result.get("error", "Unknown error")}, ensure_ascii=False)

    data = result.get("data", {})
    return json.dumps(
        {
            "bvid": bvid,
            "title": data.get("title", "Unknown"),
            "description": data.get("desc", ""),
            "author": data.get("owner", {}).get("name", "Unknown"),
            "mid": data.get("owner", {}).get("mid"),
            "view": data.get("stat", {}).get("view", 0),
            "like": data.get("stat", {}).get("like", 0),
            "coin": data.get("stat", {}).get("coin", 0),
            "favorite": data.get("stat", {}).get("favorite", 0),
            "share": data.get("stat", {}).get("share", 0),
            "duration": data.get("duration", 0),
            "pubdate": data.get("pubdate", ""),
            "url": f"https://www.bilibili.com/video/{bvid}",
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("get_up_info", parse_docstring=True)
def get_up_info_tool(mid: int) -> str:
    """Get information about a Bilibili UP主 (content creator).

    Args:
        mid: The UP主的数字 ID (mid).

    Returns:
        A JSON string with the UP主's name, fan count, video count, description, etc.
    """
    from app.services.bilibili import BilibiliService

    try:
        bili = BilibiliService()

        async def _fetch():
            async with bili:
                return await bili.get_up_info(mid=mid)

        result = _run_async(_fetch())
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch UP info: {e}"}, ensure_ascii=False)

    if not result.get("success"):
        return json.dumps({"error": result.get("error", "Unknown error")}, ensure_ascii=False)

    data = result.get("data", {})
    return json.dumps(
        {
            "mid": mid,
            "name": data.get("name", "Unknown"),
            "sex": data.get("sex", "保密"),
            "face": data.get("face", ""),
            "fans": data.get("fans", 0),
            "friend": data.get("friend", 0),
            "attention": data.get("attention", 0),
            "video_count": data.get("article", 0),
            "sign": data.get("sign", ""),
            "level": data.get("level", 0),
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("bilibili_search", parse_docstring=True)
def bilibili_search_tool(
    keyword: str,
    search_type: str = "video",
    page: int = 1,
    order: str = "totalrank",
    session_id: str = "",
) -> str:
    """在Bilibili上搜索视频、用户、番剧或图片（补充搜索工具）。

    **IMPORTANT: This is a SUPPLEMENTARY search tool.**
    Only use this AFTER calling rag_search or rag_answer first.
    Use this when: RAG results are empty/insufficient, OR when asking about latest/trending content not in your knowledge base.

    当RAG检索结果不足时，或需要搜索最新内容/趋势时使用此工具。
    支持按关键词搜索视频，也可以搜索特定UP主或系列。

    Args:
        keyword: 搜索关键词，用户想查找的内容
        search_type: 搜索类型，可选: video(视频，默认), user(用户), bangumi(番剧), photo(图片)
        page: 页码，从1开始，默认为1
        order: 排序方式，可选: totalrank(综合排序), click(播放量), pubdate(发布时间), dm(评论数), stow(收藏数)
        session_id: 会话ID，用于获取B站登录态（如已登录请传入）

    Returns:
        JSON格式的搜索结果，包含视频标题、UP主、播放量等信息
    """
    from app.services.bilibili import BilibiliService

    try:
        # 自动获取已登录的 session cookies
        # 如果传入了 session_id 则使用，否则从 DeerFlow runtime context 获取
        session = _get_session_sync(session_id if session_id else None)
        if session and session.get("cookies"):
            bili = _build_bilibili_service(session["cookies"])
        else:
            bili = BilibiliService()

        async def _fetch():
            async with bili:
                return await bili.search_bilibili(
                    keyword=keyword,
                    search_type=search_type,
                    page=page,
                    order=order,
                )

        result = _run_async(_fetch())
    except Exception as e:
        return json.dumps({"error": f"Search failed: {e}"}, ensure_ascii=False)

    if not result.get("success"):
        return json.dumps({"error": result.get("error", "Unknown error")}, ensure_ascii=False)

    items = result.get("items", [])
    formatted = []
    for item in items[:20]:
        formatted.append({
            "bvid": item.get("bvid", ""),
            "title": item.get("title", ""),
            "author": item.get("author", ""),
            "description": item.get("description", ""),
            "play": item.get("play", 0),
            "video_review": item.get("video_review", 0),
            "favorites": item.get("favorites", 0),
            "mid": item.get("mid", ""),
            "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
        })

    return json.dumps(
        {
            "keyword": keyword,
            "search_type": search_type,
            "total_results": result.get("numResults", 0),
            "results": formatted,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("get_trending", parse_docstring=True)
def get_trending_tool(rid: int = 0, session_id: str = "") -> str:
    """Get Bilibili trending/ranking videos.

    Args:
        rid: Region ID. 0 = all (全站). Common values: 1=动画, 3=音乐, 4=游戏, 5=科技, 11=电视剧, 13=番剧, 36=科技, 119=美食, 160=生活, 211=美食.
        session_id: 会话ID，用于获取B站登录态（如已登录请传入）

    Returns:
        A JSON string with the trending video list.
    """
    from app.services.bilibili import BilibiliService

    try:
        # 自动获取已登录的 session cookies
        session = _get_session_sync(session_id if session_id else None)
        if session and session.get("cookies"):
            bili = _build_bilibili_service(session["cookies"])
        else:
            bili = BilibiliService()

        async def _fetch():
            async with bili:
                return await bili.get_trending(rid=rid)

        result = _run_async(_fetch())
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch trending: {e}"}, ensure_ascii=False)

    if not result.get("success"):
        return json.dumps({"error": result.get("error", "Unknown error")}, ensure_ascii=False)

    videos = result.get("videos", [])
    formatted = []
    for v in videos[:20]:
        formatted.append({
            "bvid": v.get("bvid", ""),
            "title": v.get("title", ""),
            "author": v.get("owner", {}).get("name", "Unknown"),
            "tname": v.get("tname", ""),
            "stat": v.get("stat", {}),
            "duration": v.get("duration", 0),
            "url": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
        })

    return json.dumps(
        {
            "rid": rid,
            "note": result.get("note", ""),
            "count": len(formatted),
            "videos": formatted,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("add_to_favorites", parse_docstring=True)
def add_to_favorites_tool(media_id: int, bvid: str, session_id: str) -> str:
    """Add a Bilibili video to a favorite folder.

    Args:
        media_id: The favorite folder ID (use get_bilibili_favorites_tool to find the correct ID).
        bvid: The Bilibili video BV ID (e.g., "BV1xx411c7XZ").
        session_id: The session ID from the user's current conversation thread.

    Returns:
        A JSON string with the operation result.
    """
    session = _get_session_sync(session_id)
    if not session or not session.get("cookies"):
        return json.dumps(
            {"error": "Session not found or expired. Please ask the user to log in via B站扫码登录."},
            ensure_ascii=False,
        )

    cookies = session["cookies"]

    try:
        bili = _build_bilibili_service(cookies)

        async def _add():
            async with bili:
                return await bili.add_to_favorites(media_id=media_id, bvid=bvid)

        result = _run_async(_add())
    except Exception as e:
        return json.dumps({"error": f"Failed to add to favorites: {e}"}, ensure_ascii=False)

    if not result.get("success"):
        return json.dumps({"error": result.get("error", "Unknown error")}, ensure_ascii=False)

    return json.dumps(
        {
            "success": True,
            "message": result.get("message", "Video added to favorites"),
            "media_id": media_id,
            "bvid": bvid,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("intelligent_recommend", parse_docstring=True)
def intelligent_recommend_tool(session_id: str, limit: int = 5) -> str:
    """Intelligently recommend videos based on user's favorite content and add them to favorites.

    This tool analyzes the user's existing favorites to understand their interests,
    searches for related high-quality content on Bilibili, and automatically adds
    recommended videos to their default favorite folder.

    Args:
        session_id: The session ID from the user's current conversation thread.
        limit: Maximum number of videos to recommend and add. Default is 5.

    Returns:
        A JSON string with the analysis, recommendations, and results.
    """
    session = _get_session_sync(session_id)
    if not session or not session.get("cookies"):
        return json.dumps(
            {"error": "Session not found or expired. Please ask the user to log in via B站扫码登录."},
            ensure_ascii=False,
        )

    cookies = session["cookies"]
    user_info = session.get("user_info", {})
    mid = user_info.get("mid") or cookies.get("DedeUserID")

    if not mid:
        return json.dumps({"error": "User mid not found in session."}, ensure_ascii=False)

    try:
        bili = _build_bilibili_service(cookies)

        # Step 1: Get user's favorites to analyze interests
        async def _get_favs():
            async with bili:
                return await bili.get_user_favorites(mid=mid)

        folders = _run_async(_get_favs())
        if not folders:
            return json.dumps({"error": "No favorite folders found"}, ensure_ascii=False)

        # Find default folder
        default_folder = None
        for f in folders:
            if _is_default_folder(f):
                default_folder = f
                break

        if not default_folder:
            default_folder = folders[0]

        default_media_id = default_folder.get("id")

        # Step 2: Get all videos from favorites to analyze
        async def _get_all_videos():
            async with bili:
                return await bili.get_all_favorite_videos(default_media_id)

        all_videos = _run_async(_get_all_videos())
        if not all_videos:
            return json.dumps({"error": "No videos in favorites to analyze"}, ensure_ascii=False)

        # Step 3: Analyze interests from favorite videos
        # Better approach: Extract categories + tags + keywords
        from collections import Counter

        categories = Counter()  # 分区统计
        keywords = Counter()   # 关键词统计
        up_mids = []
        all_tags = []  # 收集所有标签

        # Bilibili category name to rid mapping
        CATEGORY_TO_RID = {
            "科技": 36,
            "知识": 36,
            "社科": 36,
            "人文": 36,
            "历史": 36,
            "校园": 36,
            "汽车": 188,
            "美食": 211,
            "生活": 160,
            "日常": 160,
            "动物": 217,
            "动画": 1,
            "MAD": 24,
            "MMD": 25,
            "短片": 47,
            "手办": 18,
            "特摄": 208,
            "配音": 210,
            "二次元": 1,
            "游戏": 4,
            "单机游戏": 4,
            "网络游戏": 4,
            "手机游戏": 4,
            "电子竞技": 4,
            "桌游": 37,
            "GMAT": 37,
            "音游": 38,
            "游戏视频": 4,
            "影视": 5,
            "短片": 152,
            "连载动画": 33,
            "完结动画": 34,
            "资讯": 51,
            "官方延伸": 152,
            "电影": 1,
            "电视剧": 5,
            "综艺": 5,
            "纪录片": 1,
            "音乐": 3,
            "翻唱": 28,
            "演奏": 29,
            " Vocaloid": 30,
            "电音": 41,
            "MV": 42,
            "特摄": 208,
            "舞蹈": 20,
            "舞蹈教程": 156,
            "宅舞": 154,
            "娱乐": 5,
            "生活": 160,
        }

        # First pass: collect categories and mid from favorite videos
        for video in all_videos[:50]:
            title = video.get("title", "")
            tname = video.get("tname", "") or video.get("type_name", "")  # 分区名称
            mid = video.get("mid", "")
            tags = video.get("tag", "") or video.get("tags", "")

            # Count category
            if tname:
                categories[tname] += 1

                # 尝试获取对应的rid
                rid = CATEGORY_TO_RID.get(tname, 36)  # 默认科技/知识区
                if tname in ["科技", "知识", "社科", "人文", "历史"]:
                    categories["知识"] += 1

            # Collect tags (from video data if available)
            if tags:
                if isinstance(tags, str):
                    tag_list = [t.strip() for t in tags.split(",")]
                else:
                    tag_list = tags if isinstance(tags, list) else []
                all_tags.extend(tag_list)

            if mid and mid not in up_mids:
                up_mids.append(mid)

        # Second pass: get detailed video info to extract tags
        # We do this for a sample of videos to get better tags
        sample_videos = all_videos[:10]  # Sample first 10 videos for tag extraction

        async def _extract_tags():
            nonlocal all_tags
            for video in sample_videos:
                bvid = video.get("bvid", "")
                if not bvid:
                    continue

                async def _get_detail():
                    async with bili:
                        return await bili.get_video_info(bvid=bvid)

                detail_result = _run_async(_get_detail())
                if detail_result.get("success"):
                    video_data = detail_result.get("data", {})
                    # Get tags from video info if available
                    tags_str = video_data.get("tags", "") or video_data.get("tag", "")
                    if tags_str:
                        if isinstance(tags_str, str):
                            tag_list = [t.strip() for t in tags_str.split(",")]
                        else:
                            tag_list = tags_str if isinstance(tags_str, list) else []
                        all_tags.extend(tag_list)

        _run_async(_extract_tags())

        # Count tag frequency
        tag_counter = Counter(all_tags)

        # Get top interests: combine category + tags + keywords
        top_categories = [c for c, _ in categories.most_common(3)]
        top_tags = [t for t, _ in tag_counter.most_common(10) if len(t) >= 2]

        # Merge: categories (high priority) + tags + important keywords
        interests = []
        interests.extend(top_categories)  # 分区优先
        interests.extend(top_tags[:5])    # 标签

        # Deduplicate and limit
        seen = set()
        final_interests = []
        for item in interests:
            if item and item not in seen:
                seen.add(item)
                final_interests.append(item)

        if not final_interests:
            final_interests = ["教程", "学习"]

        # Determine primary category (for rid filtering)
        primary_category = top_categories[0] if top_categories else "知识"
        primary_rid = CATEGORY_TO_RID.get(primary_category, 36)

        # Step 4: Search for related videos using improved strategy
        # Strategy: Search by tags within the same category
        search_results = []

        async def _search_and_collect():
            nonlocal search_results
            # First: search by tags in the primary category (most relevant)
            for tag in top_tags[:3]:  # Top 3 tags
                async with bili:
                    # Search in primary category
                    result = await bili.search_bilibili(
                        keyword=tag,
                        search_type="video",
                        page=1,
                        order="totalrank",
                        rid=primary_rid
                    )

                if result.get("success") and result.get("items"):
                    for item in result["items"][:5]:  # Top 5 per tag
                        item["_search_tag"] = tag  # Track which tag found this
                        search_results.append(item)

            # Second: also search in other related categories
            for category in top_categories[1:3]:  # Other categories
                rid = CATEGORY_TO_RID.get(category, 0)
                if rid == 0:
                    continue

                for tag in top_tags[:2]:  # Top 2 tags per category
                    async with bili:
                        result = await bili.search_bilibili(
                            keyword=tag,
                            search_type="video",
                            page=1,
                            order="totalrank",
                            rid=rid
                        )

                    if result.get("success") and result.get("items"):
                        for item in result["items"][:3]:
                            item["_search_tag"] = tag
                            search_results.append(item)

        _run_async(_search_and_collect())

        # Step 5: Filter and rank recommendations
        recommended = []
        seen_bvids = set(v.get("bvid", "") for v in all_videos)

        # Get current timestamp for filtering
        from datetime import datetime, timedelta
        three_months_ago = (datetime.now() - timedelta(days=90)).timestamp()

        for item in search_results:
            bvid = item.get("bvid", "")
            if bvid and bvid not in seen_bvids:
                # Get detailed video info to check UP followers and publish time
                async def _get_video_detail():
                    async with bili:
                        return await bili.get_video_info(bvid=bvid)

                detail_result = _run_async(_get_video_detail())

                if not detail_result.get("success"):
                    continue

                video_data = detail_result.get("data", {})

                # Filter 1: Check publish time (within 3 months)
                pubdate = video_data.get("pubdate", 0)
                if pubdate and pubdate < three_months_ago:
                    continue  # Skip videos older than 3 months

                # Filter 2: Check UP follower count (must have 100+ followers)
                owner = video_data.get("owner", {})
                follower = owner.get("follower", 0) or owner.get("fans", 0) or 0
                if follower < 100:
                    continue  # Skip low-follower UPs

                # Scoring: prioritize hot (play count) then new (pubdate)
                score = 0
                title = item.get("title", "")

                # Relevance: title matches interest tags
                for interest in final_interests:
                    if interest in title:
                        score += 100  # High weight for relevance

                # Hot: play count (primary sorting factor)
                play = item.get("play", 0) or 0
                if play > 1000000:  # 100万+播放
                    score += 50
                elif play > 100000:  # 10万+播放
                    score += 30
                elif play > 10000:  # 1万+播放
                    score += 10

                # New: recency bonus (secondary sorting factor)
                if pubdate:
                    days_old = (datetime.now().timestamp() - pubdate) / (24 * 3600)
                    if days_old < 7:  # Within 1 week
                        score += 20
                    elif days_old < 30:  # Within 1 month
                        score += 10
                    elif days_old < 90:  # Within 3 months
                        score += 5

                # Additional quality signals
                stat = video_data.get("stat", {})
                like = stat.get("like", 0) or 0
                coin = stat.get("coin", 0) or 0
                favorite = stat.get("favorite", 0) or 0

                # Engagement ratio (likes per 100 views)
                if play > 0:
                    engagement = (like / play) * 100
                    if engagement > 5:  # 5%+ like rate is good
                        score += 15
                    elif engagement > 2:  # 2%+ like rate is decent
                        score += 8

                # Coin/favorite count indicates quality
                if coin > 100:
                    score += 5
                if favorite > 50:
                    score += 3

                recommended.append({
                    "bvid": bvid,
                    "title": title,
                    "author": owner.get("name", "Unknown"),
                    "mid": owner.get("mid", ""),
                    "follower": follower,
                    "play": play,
                    "like": like,
                    "coin": coin,
                    "favorite": favorite,
                    "pubdate": pubdate,
                    "duration": video_data.get("duration", 0),
                    "score": score,
                })

        # Sort by score (hot + new + relevance) and take top N
        recommended.sort(key=lambda x: x["score"], reverse=True)
        to_add = recommended[:limit]

        if not to_add:
            return json.dumps(
                {
                    "success": True,
                    "message": "No new recommendations found (filtered by: 3 months, 100+ followers)",
                    "analyzed_categories": top_categories,
                    "analyzed_tags": top_tags[:10],
                    "candidates_before_filter": len(search_results),
                    "recommended": [],
                    "added": [],
                },
                ensure_ascii=False,
                indent=2,
            )

        # Step 6: Add to favorites
        added = []
        failed = []

        async def _add_videos():
            nonlocal added, failed
            for video in to_add:
                async with bili:
                    result = await bili.add_to_favorites(
                        media_id=default_media_id,
                        bvid=video["bvid"]
                    )

                if result.get("success"):
                    added.append(video)
                else:
                    failed.append({
                        "video": video["title"],
                        "error": result.get("error", "Unknown error")
                    })

        _run_async(_add_videos())

        # Format response with detailed info
        from datetime import datetime as dt
        formatted_added = []
        for v in added:
            pub_date_str = ""
            if v.get("pubdate"):
                pub_date_str = dt.fromtimestamp(v["pubdate"]).strftime("%Y-%m-%d")

            formatted_added.append({
                "bvid": v["bvid"],
                "title": v["title"],
                "author": v["author"],
                "follower": v["follower"],
                "play": v["play"],
                "like": v["like"],
                "duration_seconds": v["duration"],
                "published_date": pub_date_str,
                "relevance_score": v["score"]
            })

        return json.dumps(
            {
                "success": True,
                "analyzed_categories": top_categories,
                "analyzed_tags": top_tags[:10],
                "primary_category": primary_category,
                "primary_rid": primary_rid,
                "candidates_before_filter": len(search_results),
                "candidates_after_filter": len(recommended),
                "recommended": formatted_added,
                "added_count": len(added),
                "failed_count": len(failed),
                "failed": failed[:3],
                "filter_criteria": {
                    "max_age_days": 90,
                    "min_followers": 100,
                    "priority": "hot_then_new"
                },
                "message": f"基于 {len(top_categories)} 个分区 + {len(top_tags[:5])} 个标签分析，从 {len(search_results)} 个候选中筛选出 {len(recommended)} 个，添加了 {len(added)} 个视频到收藏夹"
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        import traceback
        return json.dumps(
            {"error": f"Intelligent recommendation failed: {e}", "traceback": traceback.format_exc()},
            ensure_ascii=False,
            indent=2,
        )
