import asyncio
import json
import concurrent.futures
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, AsyncGenerator
from app.utils.logger import get_logger
from app.deerflow_client import get_deerflow_client
from app.deerflow_tools.deerflow_session import DeerFlowSessionContext

logger = get_logger(__name__)
router = APIRouter(prefix="/agent", tags=["Agent"])


class AgentChatRequest(BaseModel):
    """Agent聊天请求"""
    session_id: str
    message: str
    stream: bool = False


class AgentChatResponse(BaseModel):
    """Agent聊天响应"""
    success: bool
    answer: Optional[str] = None
    agents_called: list = []
    error: Optional[str] = None


def _run_deerflow_chat(message: str, thread_id: str, deerflow_client, session_id: str = None) -> str:
    """Run DeerFlowClient.chat() in a thread (blocking, for thread pool)."""
    # Set the session context before calling DeerFlow
    if session_id:
        DeerFlowSessionContext.set_current(session_id, thread_id)
        logger.info(f"[DEBUG] Set DeerFlow session context: session_id={session_id}")

    configurable = {"thread_id": thread_id}
    if session_id:
        configurable["session_id"] = session_id

    try:
        return deerflow_client.chat(message, thread_id=thread_id, config={"configurable": configurable})
    finally:
        # Clear the session context after the call
        DeerFlowSessionContext.clear()


async def agent_chat_deerflow(message: str, thread_id: str, session_id: str = None) -> str:
    """Call DeerFlowClient.chat() in a thread pool to avoid blocking the event loop."""
    deerflow = get_deerflow_client()
    if deerflow is None:
        raise RuntimeError("DeerFlow client not available. Check startup logs.")

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(
            pool, _run_deerflow_chat, message, thread_id, deerflow, session_id
        )


def _deerflow_stream_sse(message: str, thread_id: str, session_id: str = None):
    """Yield SSE-formatted strings from DeerFlow stream (sync generator)."""
    from app.deerflow_tools.deerflow_session import DeerFlowSessionContext

    deerflow = get_deerflow_client()
    if deerflow is None:
        yield f"data: {json.dumps({'type': 'error', 'content': 'DeerFlow not available'})}\n\n"
        return

    # 记录用户的问题
    logger.info(f"[DEBUG] ========== NEW REQUEST ==========")
    logger.info(f"[DEBUG] User message: {message}")
    logger.info(f"[DEBUG] Thread ID: {thread_id}")

    # Set the session context before calling DeerFlow
    if session_id:
        DeerFlowSessionContext.set_current(session_id, thread_id)
        logger.info(f"[DEBUG] Session context: session_id={session_id}")

    try:
        configurable = {"thread_id": thread_id}
        if session_id:
            configurable["session_id"] = session_id

        # 收集所有 AI 消息，最后只发送最新的（最终答案）
        ai_messages = []  # 存储 (id, content, index) 保持接收顺序
        seen_message_ids = set()
        message_index = 0

        for event in deerflow.stream(message, thread_id=thread_id, config={"configurable": configurable}):
            if event.type == "messages-tuple":
                data = event.data
                msg_type = data.get("type", "")
                msg_id = data.get("id", "")

                if msg_type == "ai":
                    content = data.get("content", "")
                    if content:
                        # 收集所有新的 AI 消息，保持接收顺序
                        if msg_id not in seen_message_ids:
                            seen_message_ids.add(msg_id)
                            ai_messages.append((msg_id, content, message_index))
                            message_index += 1

                elif msg_type == "tool":
                    content = data.get("content", "")
                    name = data.get("name", "")
                    # Truncate tool output to avoid huge SSE payloads
                    preview = content[:500] + ("..." if len(content) > 500 else "")
                    yield f"data: {json.dumps({'type': 'tool', 'name': name, 'content': preview}, ensure_ascii=False)}\n\n"

            elif event.type == "end":
                # 流式传输结束，发送最终答案（最新的 AI 消息）
                if ai_messages:
                    # 取最后一条消息（最新的，不是最长的）
                    final_id, final_content, final_index = ai_messages[-1]
                    logger.info(f"[DEBUG] Found {len(ai_messages)} AI messages, selected latest (index={final_index}, id={final_id}), length: {len(final_content)}")
                    logger.info(f"[DEBUG] Latest message first 200 chars: {final_content[:200]}")
                    yield f"data: {json.dumps({'type': 'ai', 'content': final_content}, ensure_ascii=False)}\n\n"
                else:
                    logger.warning("[DEBUG] No AI messages collected!")

                yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error(f"DeerFlow stream error: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
    finally:
        # Clear the session context after the call
        DeerFlowSessionContext.clear()


async def agent_stream_deerflow(message: str, thread_id: str, session_id: str = None) -> AsyncGenerator[str, None]:
    """Stream DeerFlow events as SSE lines, running the blocking stream in a thread pool."""
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        # Run the synchronous generator in a thread and stream results
        gen = await loop.run_in_executor(
            pool, _deerflow_stream_sse, message, thread_id, session_id
        )
        async for chunk in _sync_gen_to_async(gen):
            yield chunk


async def _sync_gen_to_async(sync_iter):
    """Convert a synchronous iterator to an async generator."""
    for item in sync_iter:
        yield item


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest):
    """
    多Agent协作对话接口（DeerFlow驱动）

    Args:
        request: 聊天请求

    Returns:
        Agent响应
    """
    deerflow = get_deerflow_client()
    if deerflow is None:
        # Fallback to old AgentManager if DeerFlow is not available
        logger.warning("DeerFlow unavailable, falling back to AgentManager")
        try:
            from app.services.agents.agent_manager import get_agent_manager
            agent_manager = get_agent_manager()
            supervisor = agent_manager.get_supervisor(request.session_id)
            task = {"content": request.message, "task_type": "chat"}
            result = await supervisor.execute(task, {"session_id": request.session_id})
            if result.success:
                return AgentChatResponse(
                    success=True,
                    answer=result.data.get("answer") if result.data else None,
                    agents_called=result.data.get("agents_called", []) if result.data else []
                )
            else:
                return AgentChatResponse(success=False, error=result.error)
        except Exception as e:
            logger.error(f"AgentManager fallback error: {e}")
            return AgentChatResponse(success=False, error=str(e))

    try:
        answer = await agent_chat_deerflow(
            message=request.message,
            thread_id=request.session_id,  # DeerFlow thread ID for conversation history
            session_id=request.session_id  # B站登录 session ID for tools
        )
        return AgentChatResponse(success=True, answer=answer)
    except Exception as e:
        logger.error(f"DeerFlow agent chat error: {e}")
        return AgentChatResponse(success=False, error=str(e))


@router.post("/chat/stream")
async def agent_chat_stream(request: AgentChatRequest):
    """
    流式多Agent协作对话接口（DeerFlow驱动）

    Yields SSE events:
      - data: {"type": "ai", "content": "..."}
      - data: {"type": "tool", "name": "...", "content": "..."}
      - data: [DONE]
    """
    deerflow = get_deerflow_client()
    if deerflow is None:
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'content': 'DeerFlow not available'})}\n\n"]),
            media_type="text/event-stream",
        )

    return StreamingResponse(
        agent_stream_deerflow(
            message=request.message,
            thread_id=request.session_id,  # DeerFlow thread ID for conversation history
            session_id=request.session_id  # B站登录 session ID for tools
        ),
        media_type="text/event-stream",
    )


@router.get("/status/{session_id}")
async def get_agent_status(session_id: str):
    """
    获取Agent状态

    Args:
        session_id: 会话ID

    Returns:
        Agent状态信息
    """
    try:
        from app.services.agents.agent_manager import get_agent_manager
        agent_manager = get_agent_manager()

        return {
            "session_id": session_id,
            "available_agents": agent_manager.list_agents(),
            "agents_info": agent_manager.get_all_agents_info(),
            "deerflow_available": get_deerflow_client() is not None,
        }

    except Exception as e:
        logger.error(f"Get agent status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/list")
async def list_agents():
    """列出所有可用的Agent"""
    try:
        from app.services.agents.agent_manager import get_agent_manager
        agent_manager = get_agent_manager()

        return {
            "agents": [
                {
                    "name": agent_type,
                    "info": agent_manager.get_agent_info(agent_type)
                }
                for agent_type in agent_manager.list_agents()
            ]
        }

    except Exception as e:
        logger.error(f"List agents error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute/{agent_type}")
async def execute_agent_task(agent_type: str, session_id: str, task: dict):
    """
    直接执行指定Agent的任务

    Args:
        agent_type: Agent类型
        session_id: 会话ID
        task: 任务字典

    Returns:
        执行结果
    """
    try:
        from app.services.agents.agent_manager import get_agent_manager
        agent_manager = get_agent_manager()
        agent = agent_manager.get_agent(agent_type, session_id)

        result = await agent.execute(task, {"session_id": session_id})

        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "source": result.source,
            "execution_time_ms": result.execution_time_ms
        }

    except Exception as e:
        logger.error(f"Execute agent task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
