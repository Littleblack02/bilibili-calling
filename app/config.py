"""
Bilibili RAG 多Agent协作系统

核心配置模块
"""
from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
from typing import Optional
import os
from pathlib import Path


class Settings(BaseSettings):
    """应用配置"""

    # ========== 原有配置（原有用法保持不变）==========

    # OpenAI / LLM 配置
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DASHSCOPE_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    llm_model: str = Field(default="", env="LLM_MODEL")
    embedding_model: str = Field(default="text-embedding-3-small", env="EMBEDDING_MODEL")

    # DashScope ASR
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        env="DASHSCOPE_BASE_URL"
    )
    asr_model: str = Field(default="paraformer-v2", env="ASR_MODEL")
    asr_timeout: int = Field(default=600, env="ASR_TIMEOUT")
    asr_model_local: str = Field(default="paraformer-realtime-v2", env="ASR_MODEL_LOCAL")
    asr_input_format: str = Field(default="pcm", env="ASR_INPUT_FORMAT")

    # DashScope 多模态模型（封面分析）
    dashscope_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DASHSCOPE_API_KEY", "OPENAI_API_KEY"),
    )
    cover_vision_model: str = Field(default="", env="COVER_VISION_MODEL")

    # 应用配置（原有用法）
    app_host: str = Field(default="0.0.0.0", env="APP_HOST")
    app_port: int = Field(default=8000, env="APP_PORT")
    debug: bool = Field(default=True, env="DEBUG")

    # 数据库（原有用法）
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bilibili_rag.db",
        env="DATABASE_URL"
    )

    # ChromaDB（统一路径，修复路径不一致问题）
    # 优先级：CHROMA_PERSIST_DIRECTORY(.env) > ./data/chroma_db(默认值)
    # 所有使用 ChromaDB 的模块统一使用 chroma_dir 属性
    chroma_persist_directory: str = Field(
        default="chroma_db",
        env="CHROMA_PERSIST_DIRECTORY"
    )

    # ========== Ollama Gemma 4 配置 ==========
    ollama_base_url: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma4:e4b", env="OLLAMA_MODEL")
    ollama_timeout: float = Field(default=120.0, env="OLLAMA_TIMEOUT")

    # ========== 新增多Agent系统配置 ==========
    # 使用小写下划线格式，与原有代码兼容

    # 应用基本信息
    app_name: str = Field(default="Bilibili RAG Multi-Agent System")
    app_version: str = Field(default="2.0.0")

    # API 配置
    api_v1_prefix: str = Field(default="/api/v1")

    # LLM 配置
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_temperature: float = Field(default=0.7)
    llm_max_tokens: int = Field(default=2000)

    # 嵌入模型配置
    embedding_dim: int = Field(default=1536)

    # Bilibili 配置
    bilibili_cookies: dict = Field(default={})
    bilibili_session_file: str = Field(default="bilibili_session.json")

    # 记忆系统配置
    short_term_memory_max_size: int = Field(default=1000)
    short_term_memory_ttl_hours: int = Field(default=24)
    long_term_memory_threshold: int = Field(default=3)

    # 推荐系统配置
    recommendation_check_interval_minutes: int = Field(default=360)  # 改为6小时
    max_recommendations: int = Field(default=10)

    # 调度器配置
    scheduler_timezone: str = Field(default="Asia/Shanghai")

    # WebSocket 配置
    ws_heartbeat_interval: int = Field(default=30)

    # CORS 配置
    cors_origins: list = Field(default=["*"])
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: list = Field(default=["*"])
    cors_allow_headers: list = Field(default=["*"])

    # 目录配置
    _base_dir: Path = None
    _chroma_dir: Path = None
    _cache_dir: Path = None
    _log_dir: Path = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def base_dir(self) -> Path:
        if self._base_dir is None:
            self._base_dir = Path(__file__).resolve().parent.parent
        return self._base_dir

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def chroma_dir(self) -> Path:
        """统一 ChromaDB 目录路径

        修复：之前 chroma_dir 和 chroma_persist_directory 可能指向不同目录
        现在统一处理：
        1. 如果 chroma_persist_directory 是绝对路径，直接使用
        2. 如果是相对路径，从项目根目录解析（不是从 data_dir 拼接）
        """
        if self._chroma_dir is None:
            persist_dir = self.chroma_persist_directory

            # 去除常见的相对路径前缀
            name = persist_dir.lstrip("./").lstrip(".\\")

            # 如果是绝对路径，直接使用
            if Path(persist_dir).is_absolute():
                self._chroma_dir = Path(persist_dir)
            else:
                # 相对路径：从项目根目录（base_dir）解析，而不是 data_dir
                # 这样 "./data/chroma_db" -> base_dir / "data" / "chroma_db"
                # 而不是 base_dir / "data" / "data" / "chroma_db"
                self._chroma_dir = self.base_dir / name

        return self._chroma_dir

    @property
    def cache_dir(self) -> Path:
        if self._cache_dir is None:
            self._cache_dir = self.data_dir / "cache"
        return self._cache_dir

    @property
    def log_dir(self) -> Path:
        if self._log_dir is None:
            self._log_dir = self.data_dir / "logs"
        return self._log_dir


# 全局配置实例
settings = Settings()


def ensure_directories():
    """确保必要的目录存在"""
    dirs = [
        "data",
        "logs",
        settings.chroma_dir,
        settings.cache_dir,
        settings.log_dir
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    # 兼容旧路径：如果旧的 ./data/chroma_db 存在且与新路径不同，保留提示
    old_path = settings.data_dir / "chroma"
    if old_path.exists() and old_path.resolve() != settings.chroma_dir.resolve():
        # 延迟导入 logger 避免循环依赖
        from app.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.warning(
            f"检测到旧 ChromaDB 路径: {old_path.resolve()}，"
            f"新路径: {settings.chroma_dir.resolve()}。"
            f"建议手动迁移数据或修改 CHROMA_PERSIST_DIRECTORY。"
        )
