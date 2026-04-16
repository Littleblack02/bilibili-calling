"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON, Float, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from enum import Enum

Base = declarative_base()


# ==================== SQLAlchemy 模型 ====================

class VideoCache(Base):
    """视频内容缓存表"""
    __tablename__ = 'video_cache'

    id = Column(Integer, primary_key=True, autoincrement=True)
    bvid = Column(String(20), unique=True, index=True, nullable=False)
    cid = Column(Integer, nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    owner_name = Column(String(100), nullable=True)  # UP主名称
    owner_mid = Column(Integer, nullable=True)  # UP主ID

    # 内容
    content = Column(Text, nullable=True)  # 摘要/字幕文本
    content_source = Column(String(20), nullable=True)  # ai_summary / subtitle / basic_info
    outline_json = Column(JSON, nullable=True)  # 分段提纲

    # 元信息
    duration = Column(Integer, nullable=True)  # 视频时长（秒）
    pic_url = Column(String(500), nullable=True)  # 封面URL

    # 处理状态
    is_processed = Column(Boolean, default=False)  # 是否已处理并加入向量库
    process_error = Column(Text, nullable=True)  # 处理错误信息

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserSession(Base):
    """用户会话表"""
    __tablename__ = 'user_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)

    # B站用户信息
    bili_mid = Column(Integer, nullable=True)  # B站用户ID
    bili_uname = Column(String(100), nullable=True)  # B站用户名
    bili_face = Column(String(500), nullable=True)  # 头像URL

    # Cookie 信息（加密存储更安全，这里简化处理）
    sessdata = Column(Text, nullable=True)
    bili_jct = Column(Text, nullable=True)
    dedeuserid = Column(String(50), nullable=True)

    # 状态
    is_valid = Column(Boolean, default=True)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class FavoriteFolder(Base):
    """收藏夹记录表"""
    __tablename__ = 'favorite_folders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)

    # B站收藏夹信息
    media_id = Column(Integer, nullable=False)  # 收藏夹ID
    fid = Column(Integer, nullable=True)  # 原始ID
    title = Column(String(200), nullable=False)
    media_count = Column(Integer, default=0)  # 视频数量

    # 状态
    is_selected = Column(Boolean, default=True)  # 是否选中用于知识库
    last_sync_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FavoriteVideo(Base):
    """收藏夹-视频关联表"""
    __tablename__ = 'favorite_videos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, index=True, nullable=False)  # 关联 FavoriteFolder.id
    bvid = Column(String(20), index=True, nullable=False)

    # 是否选中（用户可以取消选中某些视频）
    is_selected = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# ==================== 多Agent系统模型 ====================

class Favorite(Base):
    """B站收藏视频（兼容旧版）"""
    __tablename__ = 'favorites'

    id = Column(Integer, primary_key=True)
    bvid = Column(String(20), unique=True, index=True)
    title = Column(String(200))
    description = Column(Text)
    author = Column(String(100))
    mid = Column(Integer)  # UP主ID
    duration = Column(Integer)
    pubdate = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    folder_id = Column(Integer)
    tags = Column(JSON)
    extra_data = Column(JSON)


class ShortTermMemory(Base):
    """短期记忆表（会话级）- 主Agent专用"""
    __tablename__ = 'short_term_memory'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    content = Column(Text)
    memory_type = Column(String(30))
    importance = Column(Integer, default=1)
    tags = Column(JSON)
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, default=datetime.utcnow)


class PrefetchRecommendationCache(Base):
    """预取推荐缓存表（子Agent专用）

    用于存储预取-推送模式中子Agent提前检索的视频推荐。
    与主Agent的短期记忆（ShortTermMemory）完全独立。
    """
    __tablename__ = 'prefetch_recommendation_cache'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True, nullable=False)

    # 预取的目标推送时间（"12:00" 或 "18:00"）
    target_push_time = Column(String(10), nullable=False)

    # 推荐内容（JSON格式存储多个推荐）
    recommendations = Column(Text, nullable=False)

    # 预取信息
    prefetch_hour = Column(Integer, nullable=False)  # 预取时的小时（11或17）
    count = Column(Integer, default=0)              # 推荐数量

    # 时间戳
    prefetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)    # 过期时间

    # 推送状态
    is_pushed = Column(Boolean, default=False)
    pushed_at = Column(DateTime, nullable=True)

    # 推送来源标识
    push_source = Column(String(20), nullable=True)  # "prefetch" 或 "realtime"

    __table_args__ = (
        # 同一会话同一推送时间只有一条记录
        UniqueConstraint('session_id', 'target_push_time', name='uix_session_push_time'),
    )


class LongTermMemory(Base):
    """长期记忆表（跨会话）"""
    __tablename__ = 'long_term_memory'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    content = Column(Text)
    memory_type = Column(String(30))
    importance = Column(Integer, default=3)
    tags = Column(JSON)
    extra_data = Column(JSON)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    vector_id = Column(String(100), nullable=True)


class UserInterestProfile(Base):
    """用户兴趣画像（长期 + 短期）"""
    __tablename__ = 'user_interest_profiles'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), unique=True, index=True)

    # === 长期兴趣（统计性、稳定）===
    interest_tags = Column(JSON, nullable=True)  # {"AI": 0.8, "编程": 0.7, "机器学习": 0.6}
    followed_ups = Column(JSON, nullable=True)  # [{"mid": 123, "name": "UP主", "score": 0.9}]
    preferred_keywords = Column(JSON, nullable=True)  # 敏感关键词列表

    # 收藏分布
    category_distribution = Column(JSON, nullable=True)  # {"科技": 60, "知识": 30, "其他": 10}
    total_favorites = Column(Integer, default=0)

    # 封面风格偏好（从封面理解中归纳）
    visual_style_preference = Column(JSON, nullable=True)  # {"教程": 0.7, "高质量": 0.8}
    content_type_preference = Column(JSON, nullable=True)  # {"实战": 0.6, "理论": 0.4}

    # === 短期兴趣（动态、对话驱动）===
    recent_interest_shift = Column(JSON, nullable=True)  # 最近兴趣变化：{"from": "通用AI", "to": "LoRA微调", "detected_at": "2024-01-15"}
    short_term_focus = Column(JSON, nullable=True)  # 当前阶段偏好：{"focus": "入门教程", "reason": "连续3次对话问基础", "detected_at": "2024-01-15"}

    # 时间偏好
    update_frequency = Column(String(20), default='daily')  # daily/weekly/monthly
    active_hours = Column(JSON, nullable=True)  # [9, 10, 20, 21] 用户活跃时段

    # 更新追踪
    last_update_source = Column(String(50))  # sync/chat/recommend
    confidence_score = Column(Float, default=0.5)  # 画像置信度
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledTask(Base):
    """定时任务"""
    __tablename__ = 'scheduled_tasks'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    task_type = Column(String(50))
    schedule_type = Column(String(20))
    schedule_value = Column(String(100))
    is_enabled = Column(Boolean, default=True)
    task_params = Column(JSON)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    run_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class RecommendationHistory(Base):
    """推荐历史"""
    __tablename__ = 'recommendation_history'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    recommended_bvid = Column(String(20))
    rec_type = Column(String(50))
    rec_reason = Column(Text)
    user_action = Column(String(20))
    score = Column(Float, default=0.0)
    rec_id = Column(Integer, nullable=True)  # 关联候选推荐ID
    created_at = Column(DateTime, default=datetime.utcnow)
    shown_at = Column(DateTime, nullable=True)


class OrganizeRule(Base):
    """收藏夹整理规则"""
    __tablename__ = 'organize_rules'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    rule_name = Column(String(100))
    conditions = Column(JSON)
    action_type = Column(String(50))
    target_folder_id = Column(Integer, nullable=True)
    target_value = Column(String(200), nullable=True)
    is_enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_applied_at = Column(DateTime, nullable=True)
    apply_count = Column(Integer, default=0)


class AgentTaskLog(Base):
    """Agent 任务执行日志"""
    __tablename__ = 'agent_task_logs'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    task_id = Column(String(100), index=True)
    agent_name = Column(String(50))
    task_type = Column(String(50))
    input_params = Column(JSON)
    output_result = Column(JSON)
    status = Column(String(20))
    error_message = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AgentCollaboration(Base):
    """Agent 协作记录"""
    __tablename__ = 'agent_collaborations'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)
    user_query = Column(Text)
    intent = Column(String(200))
    agents_called = Column(JSON)
    execution_plan = Column(JSON)
    final_answer = Column(Text)
    satisfaction_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GlobalKnowledge(Base):
    """
    全局知识库（跨会话知识迁移）

    当某条记忆在多个 session 中重复出现时，
    说明是通用知识，迁移到此处供所有会话共享
    """
    __tablename__ = 'global_knowledge'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 核心内容
    content = Column(Text, nullable=False)
    content_summary = Column(Text, nullable=True)  # LLM 提取的核心摘要

    # 来源信息
    source_type = Column(String(30))  # fact / preference / interest / rule
    source_sessions = Column(JSON)    # 来源的 session_id 列表
    source_count = Column(Integer, default=1)  # 出现次数
    confidence = Column(Float, default=0.0)     # 置信度（出现次数/总会话数）

    # 标签和元数据
    tags = Column(JSON)
    importance = Column(Integer, default=3)
    extra_data = Column(JSON)

    # 访问统计
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, nullable=True)

    # 向量 ID（关联 ChromaDB）
    vector_id = Column(String(100), nullable=True)

    # 软删除
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== 智能推荐系统模型 ====================

class VideoCoverAnalysis(Base):
    """视频封面多模态理解结果（结构化存储）"""
    __tablename__ = 'video_cover_analysis'

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(20), unique=True, index=True, nullable=False)  # BV号
    cover_url = Column(String(500), nullable=False)  # 封面URL

    # Gemma 4 多模态理解结果（结构化）
    visual_tags = Column(JSON, nullable=True)  # 视觉标签列表 ["教程", "编程", "高质量封面"]
    visible_text = Column(JSON, nullable=True)  # 封面可见文字（OCR提取）
    style_label = Column(String(50), nullable=True)  # 风格标签：教程/新闻/娱乐/实战/科普/其他
    quality_score = Column(Float, default=0.0)  # 质量评分 0~1
    topic_guess = Column(String(100), nullable=True)  # 主题猜测（从封面推断）

    # 原始分析结果
    raw_caption = Column(Text, nullable=True)  # Gemma 4 原始输出

    # 技术细节
    model_name = Column(String(50), nullable=True)  # 使用的模型
    embedding_vector_id = Column(String(100), nullable=True)  # ChromaDB 向量ID（封面视觉向量）

    # 分析状态
    is_analyzed = Column(Boolean, default=False)  # 是否已分析
    analyzed_at = Column(DateTime, nullable=True)  # 分析时间

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CandidateRecommendation(Base):
    """候选推荐（重排前的候选视频）"""
    __tablename__ = 'candidate_recommendations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    bvid = Column(String(20), index=True, nullable=False)

    # 召回信息
    rec_type = Column(String(50), nullable=False)  # interest/category/trending/followed_up/related
    recall_source = Column(String(50), nullable=True)
    recall_tag = Column(String(100), nullable=True)

    # 推荐信息
    rec_score = Column(Float, default=0.0)
    rec_reason = Column(Text, nullable=True)
    status = Column(String(20), default='pending')  # pending/accepted/rejected

    # 用户反馈
    user_feedback = Column(Text, nullable=True)  # positive/negative/neutral
    feedback_score = Column(Float, nullable=True)  # 反馈评分
    feedback_at = Column(DateTime, nullable=True)  # 反馈时间

    # 视频信息
    title = Column(String(500), nullable=False)
    author = Column(String(100), nullable=True)
    mid = Column(Integer, nullable=True)
    play = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)
    pic_url = Column(String(500), nullable=True)
    pubdate = Column(DateTime, nullable=True)

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class CandidatePool(Base):
    """候选池（召回后但未经过重排的候选）"""
    __tablename__ = 'candidate_pool'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    bvid = Column(String(20), index=True, nullable=False)

    # 召回信息
    recall_source = Column(String(50), nullable=False)  # interest/category/trending/followed_up/related
    recall_tag = Column(String(100), nullable=True)  # 召回标签（如兴趣标签名）

    # 视频信息（冗余存储）
    title = Column(String(500), nullable=False)
    author = Column(String(100), nullable=True)
    mid = Column(Integer, nullable=True)
    play = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)
    pic_url = Column(String(500), nullable=True)
    pubdate = Column(DateTime, nullable=True)

    # 召回元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # 候选过期时间（24小时）


class FinalRecommendation(Base):
    """最终推荐（经过重排后展示给用户的推荐）"""
    __tablename__ = 'final_recommendations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    bvid = Column(String(20), index=True, nullable=False)

    # 推荐信息
    rec_score = Column(Float, default=0.0)  # Gemma 4 重排序后的得分
    rec_reason = Column(Text, nullable=True)  # Gemma 4 生成的推荐理由
    rec_version = Column(Integer, default=1)  # 推荐版本号（用于追踪算法迭代）

    # 视频信息（冗余存储）
    title = Column(String(500), nullable=False)
    author = Column(String(100), nullable=True)
    mid = Column(Integer, nullable=True)
    play = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)
    pic_url = Column(String(500), nullable=True)
    pubdate = Column(DateTime, nullable=True)

    # 状态
    status = Column(String(20), default='pending')  # pending / accepted / rejected / expired
    user_feedback = Column(Text, nullable=True)  # 用户反馈（可选）

    # 展示信息
    shown_at = Column(DateTime, nullable=True)  # 首次展示给用户的时间
    expires_at = Column(DateTime, nullable=True)  # 过期时间（7天后）

    # 追踪信息
    batch_id = Column(String(50), nullable=True)  # 推荐批次ID（用于每日推送追踪）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PushHistory(Base):
    """推送历史记录"""
    __tablename__ = 'push_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    message_type = Column(String(50), nullable=False)  # new_recommendations/trending_digest
    message_content = Column(Text, nullable=True)  # JSON格式的消息内容
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default='pending')  # pending/sent/failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserProfileEmbeddingIndex(Base):
    """用户画像向量元数据索引（向量本体在 ChromaDB）"""
    __tablename__ = 'user_profile_embedding_index'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)

    # 向量关联信息
    embedding_id = Column(String(100), nullable=False)  # ChromaDB 向量ID
    embedding_type = Column(String(50), default="user_profile")  # user_profile/interest_shift/temp_focus
    version = Column(Integer, default=1)  # 画像版本号

    # 元数据
    summary_text = Column(Text, nullable=True)  # 画像摘要（用于快速检索）
    model_name = Column(String(50), nullable=True)  # 使用的 embedding 模型

    # 统计信息
    total_videos = Column(Integer, default=0)  # 收藏视频总数
    total_tags = Column(Integer, default=0)  # 兴趣标签数量
    dominant_category = Column(String(50), nullable=True)  # 主导分区

    # 更新追踪
    last_updated_from = Column(String(50), nullable=True)  # 更新来源：sync/chat/recommend
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# 别名（兼容旧代码）
UserProfileEmbedding = UserProfileEmbeddingIndex


# ==================== Pydantic 模型 (API 用) ====================

class ContentSource(str, Enum):
    """内容来源"""
    AI_SUMMARY = "ai_summary"
    SUBTITLE = "subtitle"
    BASIC_INFO = "basic_info"
    ASR = "asr"


class VideoInfo(BaseModel):
    """视频信息"""
    bvid: str
    cid: Optional[int] = None
    title: str
    description: Optional[str] = None
    owner_name: Optional[str] = None
    owner_mid: Optional[int] = None
    duration: Optional[int] = None
    pic_url: Optional[str] = None


class VideoContent(BaseModel):
    """视频内容（含摘要）"""
    bvid: str
    title: str
    content: str
    source: ContentSource
    outline: Optional[list] = None


class QRCodeResponse(BaseModel):
    """二维码响应"""
    qrcode_key: str
    qrcode_url: str
    qrcode_image_base64: str


class LoginStatusResponse(BaseModel):
    """登录状态响应"""
    status: str  # waiting / scanned / confirmed / expired
    message: str
    user_info: Optional[dict] = None
    session_id: Optional[str] = None


class FavoriteFolderInfo(BaseModel):
    """收藏夹信息"""
    media_id: int
    title: str
    media_count: int
    is_selected: bool = True
    is_default: Optional[bool] = None


class ChatRequest(BaseModel):
    """对话请求"""
    question: str
    session_id: Optional[str] = None
    folder_ids: Optional[list[int]] = None


class ChatResponse(BaseModel):
    """对话响应"""
    answer: str
    sources: list[dict]


# ==================== 智能推荐系统 API 模型 ====================

class CandidateRecommendationCreate(BaseModel):
    """创建候选推荐"""
    session_id: str
    bvid: str
    rec_type: str
    rec_score: float = 0.0
    rec_reason: Optional[str] = None
    title: str
    author: Optional[str] = None
    mid: Optional[int] = None
    play: Optional[int] = None
    duration: Optional[int] = None
    pic_url: Optional[str] = None
    pubdate: Optional[datetime] = None


class CandidateRecommendationResponse(BaseModel):
    """候选推荐响应"""
    id: int
    bvid: str
    title: str
    author: Optional[str] = None
    play: Optional[int] = None
    pic_url: Optional[str] = None
    rec_score: float
    rec_reason: Optional[str] = None
    status: str
    created_at: datetime


class UserProfileResponse(BaseModel):
    """用户画像响应"""
    session_id: str
    interest_tags: dict
    followed_ups: list
    category_distribution: dict
    total_favorites: int
    confidence_score: float
    updated_at: datetime


class CoverAnalysisRequest(BaseModel):
    """封面分析请求"""
    bvid: str
    pic_url: str
    force_reanalyze: bool = False


class CoverAnalysisResponse(BaseModel):
    """封面分析响应"""
    video_id: str
    cover_url: str
    visual_tags: list
    visible_text: list
    style_label: str
    quality_score: float
    topic_guess: Optional[str] = None
    raw_caption: Optional[str] = None


class CandidateRecallResponse(BaseModel):
    """召���响应（未重排）"""
    bvid: str
    title: str
    author: Optional[str] = None
    play: Optional[int] = None
    recall_source: str  # interest/category/trending/followed_up/related
    recall_tag: Optional[str] = None


class RerankedRecommendationResponse(BaseModel):
    """重排后推荐响应"""
    bvid: str
    title: str
    author: Optional[str] = None
    play: Optional[int] = None
    rec_score: float
    rec_reason: str
    rec_version: int


# ==================== 扩展数据源模型（Phase 2）====================

class UserBangumi(Base):
    """用户追番表"""
    __tablename__ = 'user_bangumi'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)

    # 番剧信息
    season_id = Column(Integer, nullable=False)  # B站番剧season ID
    media_id = Column(Integer, nullable=False)    # 媒体ID
    title = Column(String(255), nullable=False)
    cover = Column(String(500), nullable=True)

    # 番剧类型: 1=番剧, 2=电影, 3=纪录片, 4=综艺, 5=电视剧
    bangumi_type = Column(Integer, default=1)

    # 观看状态
    status = Column(String(20), default='watching')  # watching/done/abandon
    watched_episodes = Column(Integer, default=0)   # 已看集数
    total_episodes = Column(Integer, default=0)    # 总集数

    # 元数据
    add_time = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # 同一用户同一番剧只存一条
        UniqueConstraint('session_id', 'season_id', name='uix_session_season'),
    )


class UserWatchHistory(Base):
    """用户观看历史表"""
    __tablename__ = 'user_watch_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)

    # 视频信息
    bvid = Column(String(20), nullable=False)
    aid = Column(Integer, nullable=True)
    title = Column(String(500), nullable=True)
    cover = Column(String(500), nullable=True)
    owner_mid = Column(Integer, nullable=True)
    owner_name = Column(String(100), nullable=True)

    # 观看信息
    duration = Column(Integer, nullable=True)  # 视频总时长（秒）
    progress = Column(Integer, nullable=True)  # 观看进度（秒）
    view_at = Column(Integer, nullable=True)   # 观看时间戳

    # 分区信息
    tname = Column(String(50), nullable=True)   # 分区名称

    # 元数据
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # 同一用户同一视频同一时间只存一条
        UniqueConstraint('session_id', 'bvid', 'view_at', name='uix_session_bvid_viewtime'),
    )


class UserWatchLater(Base):
    """用户稍后观看表"""
    __tablename__ = 'user_watch_later'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)

    # 视频信息
    bvid = Column(String(20), nullable=False)
    aid = Column(Integer, nullable=True)
    title = Column(String(500), nullable=True)
    cover = Column(String(500), nullable=True)
    owner_mid = Column(Integer, nullable=True)
    owner_name = Column(String(100), nullable=True)
    duration = Column(Integer, nullable=True)

    # 状态
    status = Column(String(20), default='pending')  # pending/watched/removed

    # 元数据
    add_time = Column(Integer, nullable=True)   # 添加时间戳
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('session_id', 'bvid', name='uix_session_watchlater_bvid'),
    )


class UserCinema(Base):
    """用户影视收藏表（电影/纪录片/综艺等）"""
    __tablename__ = 'user_cinema'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)

    # 收藏夹信息
    media_id = Column(Integer, nullable=False)  # 收藏夹ID
    folder_title = Column(String(200), nullable=True)  # 收藏夹名称

    # 影视信息（如果有的话）
    season_id = Column(Integer, nullable=True)  # 影视season ID
    bvid = Column(String(20), nullable=True)     # 视频BV号

    title = Column(String(255), nullable=True)
    cover = Column(String(500), nullable=True)

    # 影视类型
    media_type = Column(String(20), nullable=True)  # movie/documentary/variety/series/other

    # 元数据
    add_time = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BangumiUpdateLog(Base):
    """番剧更新记录表（用于追踪追番更新）"""
    __tablename__ = 'bangumi_update_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)

    # 番剧信息
    season_id = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)

    # 更新信息
    last_episode = Column(Integer, default=0)   # 上次记录的集数
    new_episode = Column(Integer, nullable=True) # 新增的集数
    update_time = Column(DateTime, nullable=True)

    # 通知状态
    notified = Column(Boolean, default=False)
    notified_at = Column(DateTime, nullable=True)

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('session_id', 'season_id', name='uix_session_bangumi_update'),
    )


# 扩展 UserInterestProfile 表字段
# 注意: 这些字段通过 JSON 列存储，不需要添加新的列
# 但我们添加新的便利属性来标识画像的完整性
