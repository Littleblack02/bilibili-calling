"""
Routers包初始化
"""
# 原有路由
from app.routers import auth, favorites, knowledge, chat, ontology, privacy, observability

__all__ = [
    "auth",
    "favorites",
    "knowledge",
    "chat",
    "ontology",
    "privacy",
    "observability",
]
