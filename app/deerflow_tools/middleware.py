"""
DeerFlow Middleware for Bilibili RAG

Sets up runtime context for tool execution, including session_id for Bilibili authentication.
"""
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Tuple, Union

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

# Global storage for session context, keyed by a request ID
# This is a simple solution that works across threads
_session_context_store: Dict[str, Dict[str, Any]] = {}
_session_context_lock = None  # We'll use a simple approach


class SessionContextMiddleware(AgentMiddleware):
    """
    Middleware that extracts session_id from RunnableConfig and makes it available
    to Bilibili tools via a global store.
    """

    def __init__(self):
        # Import here to avoid circular dependency
        pass

    def _store_context(self, request_id: str, session_id: str, thread_id: str):
        """Store context in the global store."""
        global _session_context_store
        _session_context_store[request_id] = {
            "session_id": session_id,
            "thread_id": thread_id,
            "timestamp": time.time()
        }
        logger.info(f"[DEBUG] Stored context for request {request_id}: session_id={session_id}")

    def _get_context(self, request_id: str) -> Dict[str, Any]:
        """Get context from the global store."""
        global _session_context_store
        context = _session_context_store.get(request_id)
        if context:
            # Clean up old entries (older than 5 minutes)
            if time.time() - context["timestamp"] > 300:
                _session_context_store.pop(request_id, None)
                return None
        return context

    def _clear_context(self, request_id: str):
        """Clear context from the global store."""
        global _session_context_store
        _session_context_store.pop(request_id, None)

    def on_tool_start(
        self,
        tool_name: str,
        tool_arguments: Dict[str, Any],
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called before a tool is executed.

        Extracts session_id from config and sets it in the global store.
        """
        try:
            # Extract session_id from configurable
            configurable = config.get("configurable", {})
            session_id = configurable.get("session_id")
            thread_id = configurable.get("thread_id")

            logger.info(f"[DEBUG] SessionContextMiddleware.on_tool_start:")
            logger.info(f"[DEBUG]   tool_name = {tool_name}")
            logger.info(f"[DEBUG]   configurable = {configurable}")
            logger.info(f"[DEBUG]   session_id = {session_id}")
            logger.info(f"[DEBUG]   thread_id = {thread_id}")
            logger.info(f"[DEBUG]   run_id = {run_id}")

            if session_id:
                # Use run_id as the key since it's unique per tool call
                self._store_context(run_id, session_id, thread_id)
                logger.info(f"[DEBUG] Stored session_id in global store with key: {run_id}")
        except Exception as e:
            logger.error(f"SessionContextMiddleware: failed to set context: {e}")

    def on_tool_end(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        observation: str,
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called after a tool is executed."""
        self._clear_context(run_id)

    def on_tool_error(
        self,
        error: Exception,
        tool_name: str,
        tool_input: Dict[str, Any],
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool errors."""
        logger.warning(f"SessionContextMiddleware: tool {tool_name} error: {error}")
        self._clear_context(run_id)

    def on_llm_start(
        self,
        messages: List[List[Union[HumanMessage, SystemMessage, AIMessage, ToolMessage]]],
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called before the LLM is called."""
        pass

    def on_llm_end(
        self,
        response: Any,
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called after the LLM is called."""
        pass

    def on_agent_action(
        self,
        action: Any,
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called when the agent takes an action."""
        pass

    def on_agent_end(
        self,
        result: Any,
        config: RunnableConfig,
        *,
        run_id: str,
        parent_run_id: str | None,
        **kwargs: Any,
    ) -> None:
        """Called when the agent finishes."""
        pass


# Import at module level for type hints
from typing import Dict


def get_session_context_from_run_id(run_id: str) -> Dict[str, Any]:
    """Get session context from the global store by run_id."""
    global _session_context_store
    context = _session_context_store.get(run_id)
    if context:
        # Clean up old entries (older than 5 minutes)
        if time.time() - context["timestamp"] > 300:
            _session_context_store.pop(run_id, None)
            return None
    return context
