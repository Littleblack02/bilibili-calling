"""
Routers包初始化
"""
# 原有路由
from app.routers import auth, favorites, knowledge, chat

__all__ = [
    "auth",
    "favorites",
    "knowledge",
    "chat"
]
