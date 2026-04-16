"""
RAG Tools - Wrap bilibili-rag's RAGService as LangChain Tools for DeerFlow.
"""

import json
import asyncio
import concurrent.futures

from langchain.tools import tool


def _get_rag_service():
    """Lazily create a RAGService (avoids import cycle and premature initialization)."""
    from app.services.rag import RAGService

    return RAGService(collection_name="bilibili_videos")


@tool("rag_search", parse_docstring=True)
def rag_search_tool(
    query: str,
    k: int = 5,
) -> str:
    """Search the user's Bilibili video knowledge base using semantic vector similarity.

    **IMPORTANT: This is the FIRST tool to call for ANY user question.**
    This tool does NOT require login - it searches your local knowledge base.
    This tool does NOT make external network requests.

    Use this tool when: the user asks about content they've favorited/saved.
    Do NOT call bilibili_search or web_search before checking this tool first.

    Args:
        query: The search query (can be a question or keywords). Be specific for better results.
        k: Maximum number of results to return. Default is 5. Increase for broader coverage.

    Returns:
        A JSON string containing the retrieved video chunks with their titles and content.
    """
    rag = _get_rag_service()
    try:
        docs = rag.search(query, k=k)
    except Exception:
        docs = []

    if not docs:
        return json.dumps(
            {"query": query, "results": [], "message": "No relevant content found in knowledge base."},
            ensure_ascii=False,
        )

    results = []
    seen_bvids = set()
    for doc in docs:
        meta = doc.metadata or {}
        bvid = meta.get("bvid", "")
        title = meta.get("title", "Unknown")
        url = meta.get("url", f"https://www.bilibili.com/video/{bvid}")
        content = doc.page_content.strip()

        if bvid in seen_bvids:
            continue
        seen_bvids.add(bvid)

        results.append({
            "bvid": bvid,
            "title": title,
            "url": url,
            "content_preview": content[:300] + "..." if len(content) > 300 else content,
        })

    return json.dumps(
        {"query": query, "results": results, "count": len(results)},
        ensure_ascii=False,
        indent=2,
    )


async def rag_answer_impl(question: str) -> dict:
    """Internal async implementation for rag_answer."""
    rag = _get_rag_service()
    return await rag.answer_question(question, k=5)


@tool("rag_answer", parse_docstring=True)
def rag_answer_tool(question: str) -> str:
    """Answer a question based on the user's Bilibili video knowledge base.

    **IMPORTANT: This is the FIRST tool to call for ANY user question.**
    This tool does NOT require login - it searches your local knowledge base.
    This tool does NOT make external network requests.

    Use this tool when: the user asks a specific question that requires understanding
    the content of their favorited Bilibili videos. This tool performs both retrieval
    and generation to produce a grounded answer.

    Do NOT call bilibili_search or web_search before checking this tool first.

    Args:
        question: The user's question about their Bilibili video collection.

    Returns:
        A JSON string containing the answer and source videos.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(rag_answer_impl(question))
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"question": question, "answer": f"Failed to answer question: {e}", "sources": []},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "question": question,
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
        },
        ensure_ascii=False,
        indent=2,
    )
