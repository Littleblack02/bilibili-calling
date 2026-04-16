"""
Session context holder for DeerFlow tools.

This provides a way to pass session_id to tools when DeerFlow runs them
in its internal thread pool.
"""

import threading
import uuid
from typing import Optional


class DeerFlowSessionContext:
    """
    Holds the current session context for DeerFlow tool execution.

    This uses a thread-local storage approach where we set the session_id
    before calling DeerFlow and the tools can access it.
    """

    # Class-level storage (will be set before DeerFlow call)
    _current_request_id: Optional[str] = None
    _current_session_id: Optional[str] = None
    _current_thread_id: Optional[str] = None

    # Lock for thread safety
    _lock = threading.Lock()

    @classmethod
    def set_current(cls, session_id: str, thread_id: str = None) -> str:
        """Set the current session context.

        Returns the request_id that can be used to retrieve the context.
        """
        request_id = str(uuid.uuid4())
        with cls._lock:
            cls._current_request_id = request_id
            cls._current_session_id = session_id
            cls._current_thread_id = thread_id
        return request_id

    @classmethod
    def get_current(cls) -> tuple:
        """Get the current session context.

        Returns:
            tuple: (request_id, session_id, thread_id)
        """
        with cls._lock:
            return cls._current_request_id, cls._current_session_id, cls._current_thread_id

    @classmethod
    def get_session_id(cls) -> Optional[str]:
        """Get just the current session_id."""
        _, session_id, _ = cls.get_current()
        return session_id

    @classmethod
    def clear(cls):
        """Clear the current session context."""
        with cls._lock:
            cls._current_request_id = None
            cls._current_session_id = None
            cls._current_thread_id = None
