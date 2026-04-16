"""
Global session context for DeerFlow tools.

This module provides a thread-safe way to pass session_id from the API endpoint
to the tools executed by DeerFlow, even when they run in different threads.
"""

import threading
import time
from typing import Optional, Dict, Any

# Global storage for session context, keyed by a unique request ID
_session_store: Dict[str, Dict[str, Any]] = {}
_store_lock = threading.Lock()


def set_current_session(request_id: str, session_id: str, thread_id: str = None):
    """Set the current session context for a request.

    Args:
        request_id: Unique identifier for this request (can be thread_id or a UUID)
        session_id: The Bilibili session ID
        thread_id: Optional thread ID
    """
    global _session_store
    with _store_lock:
        _session_store[request_id] = {
            "session_id": session_id,
            "thread_id": thread_id,
            "timestamp": time.time()
        }


def get_current_session(request_id: str) -> Optional[Dict[str, Any]]:
    """Get the session context for a request.

    Args:
        request_id: The request identifier

    Returns:
        Dict with session_id and thread_id, or None if not found/expired
    """
    global _session_store
    with _store_lock:
        context = _session_store.get(request_id)
        if context:
            # Clean up entries older than 5 minutes
            if time.time() - context["timestamp"] > 300:
                del _session_store[request_id]
                return None
            return context
    return None


def clear_session(request_id: str):
    """Clear the session context for a request."""
    global _session_store
    with _store_lock:
        _session_store.pop(request_id, None)


def get_session_id(request_id: str) -> Optional[str]:
    """Get just the session_id for a request."""
    context = get_current_session(request_id)
    return context.get("session_id") if context else None
