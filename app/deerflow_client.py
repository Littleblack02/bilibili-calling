"""
DeerFlow Client singleton

This module is separated from app.main to avoid circular imports with routers.
"""

_deerflow_client = None


def get_deerflow_client():
    """Get the global DeerFlowClient instance. May be None if initialization failed."""
    return _deerflow_client


def _set_deerflow_client(client):
    """Internal: set the global DeerFlowClient instance (called by app.main)."""
    global _deerflow_client
    _deerflow_client = client


def _clear_deerflow_client():
    """Internal: clear the global DeerFlowClient instance (called by app.main)."""
    global _deerflow_client
    _deerflow_client = None
