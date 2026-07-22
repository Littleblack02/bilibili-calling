"""
Bilibili RAG 知识库系统

数据库管理模块
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as sync_sessionmaker
from contextlib import asynccontextmanager
from app.config import settings
from app.models import Base
import os


def _apply_compatible_schema_updates(sync_conn) -> None:
    """Apply additive SQLite migrations that ``create_all`` cannot perform.

    The project intentionally has no destructive automatic migrations.  This
    hook only adds nullable columns, preserving existing user data.
    """
    if sync_conn.dialect.name != "sqlite":
        return
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "user_interest_profiles" in tables:
        columns = {column["name"] for column in inspector.get_columns("user_interest_profiles")}
        if "profile_features" not in columns:
            sync_conn.exec_driver_sql(
                "ALTER TABLE user_interest_profiles ADD COLUMN profile_features JSON"
            )
    if "user_content_signals" in tables:
        columns = {column["name"] for column in inspector.get_columns("user_content_signals")}
        if "last_seen_sync_id" not in columns:
            sync_conn.exec_driver_sql(
                "ALTER TABLE user_content_signals ADD COLUMN last_seen_sync_id VARCHAR(64)"
            )


# 确保数据目录存在
os.makedirs("data", exist_ok=True)

# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True
)

# 创建异步会话工厂
async_session_factory = sync_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """初始化数据库（创建表）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_compatible_schema_updates)


async def get_db() -> AsyncSession:
    """获取数据库会话（用于 FastAPI 依赖注入）"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """获取数据库会话（用于上下文管理器）"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
