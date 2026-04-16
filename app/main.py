"""
Bilibili RAG 多Agent协作系统

主应用入口
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import sys
import asyncio
from typing import Optional

from app.config import settings, ensure_directories
from app.database import init_db, async_session_factory

# 导入原有路由
from app.routers import auth, favorites, knowledge, chat

# 导入新路由（多Agent系统）
from app.services.tools import tool_registry, register_all_tools
from app.services.agents.agent_manager import AgentManager
from app.services.scheduler import scheduler_service

# 导入新路由
from app.routers.agent import router as agent_router
from app.routers.memory import router as memory_router
from app.routers.schedule import router as schedule_router
from app.routers.recommendations import router as recommendations_router
from app.routers.external_trigger import router as external_trigger_router
from app.routers.websocket_manager import heartbeat_loop

# DeerFlow Client singleton (separate module to avoid circular imports)
from app.deerflow_client import get_deerflow_client, _set_deerflow_client, _clear_deerflow_client

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG" if settings.debug else "INFO"
)
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG"
)


# WebSocket心跳任务
heartbeat_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global heartbeat_task

    # 启动时
    logger.info("🚀 Bilibili RAG 多Agent系统启动中...")

    ensure_directories()
    await init_db()
    logger.info("✅ 数据库初始化完成")

    # 初始化工具注册中心
    register_all_tools(tool_registry)
    logger.info(f"✅ 工具注册完成: {len(tool_registry.get_all_tool_names())} 个工具")

    # 初始化Agent管理器
    agent_manager = AgentManager.get_instance()
    logger.info(f"✅ Agent初始化完成: {', '.join(agent_manager.list_agents())}")

    # 初始化 DeerFlow Client（异步工具需要同步创建，stream 调用时才初始化 agent）
    try:
        import os

        # Change to the project root so DeerFlow resolves config.yaml and langgraph.json correctly
        original_cwd = os.getcwd()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # E:/bilibili-rag-main
        os.chdir(project_root)
        try:
            from deerflow.client import DeerFlowClient
            from app.deerflow_tools.middleware import SessionContextMiddleware

            # Create middleware for passing session_id to tools
            session_middleware = SessionContextMiddleware()

            # Enable checkpointer for multi-turn conversation persistence
            client = DeerFlowClient(
                config_path="config.yaml",
                thinking_enabled=False,
                subagent_enabled=True,
                middlewares=[session_middleware],  # Add custom middleware
            )
            # 强制重置 agent，创建一个全新的实例
            client.reset_agent()

            _set_deerflow_client(client)
            logger.info("✅ DeerFlowClient 初始化成功（已启用 SessionContextMiddleware，已启用 Checkpointer 多轮对话，已启用 Memory）")
        finally:
            os.chdir(original_cwd)
    except ImportError as e:
        logger.warning(f"⚠️ DeerFlow 未安装，跳过 DeerFlowClient 初始化: {e}")
    except Exception as e:
        logger.warning(f"⚠️ DeerFlowClient 初始化失败: {e}")

    # 启动调度器
    scheduler_service.start()
    logger.info("✅ 调度器启动完成")

    # 启动WebSocket心跳任务
    heartbeat_task = asyncio.create_task(heartbeat_loop(interval_seconds=settings.ws_heartbeat_interval))
    logger.info("✅ WebSocket心跳任务启动")

    logger.info("🎉 系统启动完成！")

    yield

    # 关闭时
    logger.info("👋 应用关闭中...")

    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    # 重置 DeerFlow Client
    if get_deerflow_client() is not None:
        try:
            get_deerflow_client().reset_agent()
        except Exception:
            pass
        _clear_deerflow_client()

    scheduler_service.stop()
    logger.info("👋 应用已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Bilibili RAG 多Agent协作系统",
    description="""
## 🎬 项目简介

基于多Agent协作的Bilibili智能RAG系统！

### 核心功能

- 🔐 **B站扫码登录** - 安全便捷
- 📁 **收藏夹管理** - 查看和选择收藏夹
- 🤖 **AI 内容提取** - 自动获取视频摘要/字幕
- 💬 **智能问答** - 基于收藏内容回答问题
- 🔍 **语义搜索** - 快速找到相关视频

### 🚀 多Agent系统

- **Supervisor Agent** - 主控Agent，意图分析与任务调度
- **RAG Agent** - 知识库检索与内容理解
- **Bilibili Agent** - B站API工具（搜索、评论、热榜）
- **Account Agent** - 收藏夹整理与定时同步
- **Recommendation Agent** - 个性化推荐与兴趣分析
- **Web Agent** - 联网搜索与最新资讯

### 🧠 分层记忆系统

- **短期记忆** - SQLite存储，会话级LRU
- **长期记忆** - ChromaDB向量检索，跨会话持久化
    """,
    version="2.0.0",
    lifespan=lifespan
)


# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 注册原有路由（已有 prefix 和 tags）
app.include_router(auth.router)
app.include_router(favorites.router)
app.include_router(knowledge.router)
app.include_router(chat.router)

# 注册新路由（多Agent系统，已有 prefix="/api/v1"）
app.include_router(agent_router)
app.include_router(memory_router)
app.include_router(schedule_router)
app.include_router(recommendations_router)
app.include_router(external_trigger_router)


@app.get("/")
async def root():
    """API 根路径"""
    return {
        "message": "🎬 Bilibili RAG 多Agent协作系统",
        "version": "2.0.0",
        "docs": "/docs",
        "status": "running",
        "features": [
            "多Agent协作",
            "分层记忆系统",
            "个性化推荐",
            "任务调度"
        ]
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    deerflow_available = get_deerflow_client() is not None
    return {
        "status": "healthy",
        "scheduler_running": scheduler_service.is_running(),
        "tools_count": len(tool_registry.get_all_tool_names()),
        "agents_count": len(AgentManager.get_instance().list_agents()),
        "deerflow_available": deerflow_available,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug
    )
