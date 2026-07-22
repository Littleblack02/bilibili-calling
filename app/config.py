"""
Bilibili RAG 多Agent协作系统

核心配置模块
"""
from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices, SecretStr
from typing import Optional
import hashlib
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
    # Comma-separated versioned AES-256 keys: ``v1=<urlsafe-base64>,v0=<...>``.
    # There is intentionally no fallback key: authenticated persistence must
    # fail closed instead of silently writing plaintext cookies.
    bilibili_cookie_encryption_keys: SecretStr = Field(default=SecretStr(""))
    bilibili_cookie_active_key_id: str = Field(default="")

    # 记忆系统配置
    short_term_memory_max_size: int = Field(default=1000)
    short_term_memory_ttl_hours: int = Field(default=24)
    long_term_memory_threshold: int = Field(default=3)

    # 推荐系统配置
    recommendation_check_interval_minutes: int = Field(default=360)  # 改为6小时
    max_recommendations: int = Field(default=10)

    # 推荐排序：规则排序是可靠主链路，LLM 仅作为可选的小规模辅助重排。
    recommendation_algorithm_version: str = Field(default="temporal-ontology-xmix-v2")
    recommendation_llm_rerank_enabled: bool = Field(default=False)
    recommendation_llm_top_n: int = Field(default=20)
    recommendation_llm_timeout_seconds: float = Field(default=15.0)
    recommendation_recent_exposure_days: int = Field(default=7)
    recommendation_max_per_up: int = Field(default=2)
    recommendation_profile_max_age_hours: int = Field(default=24)
    recommendation_scoring_weights: dict[str, float] = Field(default_factory=lambda: {
        "content_match": 0.18,
        "ontology_match": 0.17,
        "recent_interest": 0.16,
        "multi_interest": 0.10,
        "up_affinity": 0.10,
        "freshness": 0.09,
        "quality": 0.08,
        "exploration": 0.07,
        "context": 0.05,
        "recall_confidence": 0.08,
    })

    # Ontology V2 is the production default.  Every material algorithm/data-
    # path change remains independently reversible through its environment
    # variable so deployments can still roll back one capability at a time.
    temporal_affinity_v2_enabled: bool = Field(default=True)
    # Calibration: a raw evidence mass of ``tau`` maps to 1-exp(-1)=0.632
    # absolute affinity. Tune on the dev split; never normalize by profile max.
    temporal_affinity_tau: float = Field(default=1.5, gt=0.0)
    temporal_secondary_signal_discount: float = Field(default=0.25, ge=0.0, le=1.0)
    interest_cluster_max_hops: int = Field(default=1, ge=0, le=4)
    multi_interest_temperature: float = Field(default=0.35, gt=0.0)
    rag_grounded_v2_enabled: bool = Field(default=True)
    rag_original_min_relevance: float = Field(default=0.35, ge=0.0, le=1.0)
    rag_synonym_min_relevance: float = Field(default=0.45, ge=0.0, le=1.0)
    rag_hierarchy_min_relevance: float = Field(default=0.55, ge=0.0, le=1.0)
    rag_associative_min_relevance: float = Field(default=0.65, ge=0.0, le=1.0)
    rag_retrieval_pool_size: int = Field(default=30, ge=5, le=100)
    rag_reranker_enabled: bool = Field(default=True)
    rag_reranker_max_chunks: int = Field(default=30, ge=1, le=50)
    rag_answerability_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    rag_answerability_query_coverage: float = Field(default=0.28, ge=0.0, le=1.0)
    rag_subtitle_chunk_seconds: float = Field(default=45.0, gt=1.0, le=300.0)
    profile_sync_v2_enabled: bool = Field(default=True)
    ontology_linker_v2_enabled: bool = Field(default=True)
    ontology_linker_accept_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    ontology_linker_ambiguity_margin: float = Field(default=0.08, ge=0.0, le=1.0)
    candidate_hydration_enabled: bool = Field(default=False)
    # Backward-compatible when omitted: a feature flag behaves as before.
    # Production .env.example explicitly starts rollout at 0.
    v2_rollout_percentage: int = Field(default=100, ge=0, le=100)
    # Comma-separated 16-char salted hashes, never raw session IDs.
    v2_test_session_hashes: SecretStr = Field(default=SecretStr(""))
    up_video_cache_ttl_seconds: int = Field(default=900, ge=0, le=86400)
    candidate_hydration_cache_ttl_seconds: int = Field(default=1800, ge=0, le=86400)
    candidate_hydration_concurrency: int = Field(default=8, ge=1, le=32)
    candidate_hydration_timeout_seconds: float = Field(default=12.0, gt=0.0, le=60.0)
    recommendation_baseline_algorithm_version: str = Field(
        default="temporal-ontology-xmix-v2"
    )

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

    def v2_rollout_state(self, session_id: str | None = None) -> dict[str, object]:
        if session_id is None:
            return {"eligible": True, "bucket": None, "test_session": False}
        digest = hashlib.sha256(("v2-rollout-v1:" + session_id).encode()).hexdigest()
        session_ref = digest[:16]
        allowlist = {
            value.strip() for value in self.v2_test_session_hashes.get_secret_value().split(",")
            if value.strip()
        }
        test_session = session_ref in allowlist
        bucket = int(digest[16:24], 16) % 100
        return {
            "eligible": test_session or bucket < self.v2_rollout_percentage,
            "bucket": bucket, "session_hash": session_ref,
            "test_session": test_session,
        }

    def v2_feature_flags(self, session_id: str | None = None) -> dict[str, bool]:
        """Return the exact rollout state stored with auditable batch output."""
        configured = {
            "temporal_affinity_v2": self.temporal_affinity_v2_enabled,
            "rag_grounded_v2": self.rag_grounded_v2_enabled,
            "profile_sync_v2": self.profile_sync_v2_enabled,
            "ontology_linker_v2": self.ontology_linker_v2_enabled,
            "candidate_hydration": self.candidate_hydration_enabled,
        }
        if session_id is None:
            return configured
        eligible = bool(self.v2_rollout_state(session_id)["eligible"])
        return {name: enabled and eligible for name, enabled in configured.items()}


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
