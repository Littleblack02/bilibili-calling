/**
 * API 客户端
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// 通用请求函数
async function request<T>(
    endpoint: string,
    options: RequestInit = {}
): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;

    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...options.headers,
        },
    });

    // 会话失效时自动清除登录状态并刷新页面
    if (response.status === 401) {
        if (typeof window !== "undefined") {
            localStorage.removeItem("bili_session");
            localStorage.removeItem("bili_user");
            window.location.href = "/";
        }
        throw new Error("会话已过期，请重新登录");
    }

    if (!response.ok) {
        const error = await response.text();
        throw new Error(error || `请求失败: ${response.status}`);
    }

    return response.json();
}

// ==================== 类型定义 ====================

export interface QRCodeResponse {
    qrcode_key: string;
    qrcode_url: string;
    qrcode_image_base64: string;
}

export interface LoginStatusResponse {
    status: "waiting" | "scanned" | "confirmed" | "expired";
    message: string;
    user_info?: UserInfo;
    session_id?: string;
}

export interface UserInfo {
    mid: number;
    uname: string;
    face: string;
    level?: number;
}

export interface FavoriteFolder {
    media_id: number;
    title: string;
    media_count: number;
    is_selected: boolean;
    is_default?: boolean;
}

export interface Video {
    bvid: string;
    title: string;
    cover?: string;
    duration?: number;
    owner?: string;
    play_count?: number;
    intro?: string;
    is_selected: boolean;
}

export interface FavoriteVideosResponse {
    folder_info: Record<string, unknown>;
    videos: Video[];
    has_more: boolean;
    page: number;
    page_size: number;
}

export interface OrganizePreviewItem {
    bvid: string;
    title: string;
    resource_id: number;
    resource_type: number;
    target_folder_id: number | null;
    target_folder_title: string;
    reason?: string;
}

export interface OrganizePreviewResponse {
    default_folder_id: number;
    default_folder_title: string;
    folders: FavoriteFolder[];
    items: OrganizePreviewItem[];
    stats: {
        total: number;
        matched: number;
        unmatched: number;
    };
}

export interface BuildRequest {
    folder_ids: number[];
    exclude_bvids?: string[];
}

export interface BuildStatus {
    task_id: string;
    status: "pending" | "running" | "completed" | "failed";
    progress: number;
    current_step: string;
    total_videos: number;
    processed_videos: number;
    message: string;
}

export interface FolderStatus {
    media_id: number;
    indexed_count: number;
    media_count?: number;
    last_sync_at?: string;
}

export interface SyncRequest {
    folder_ids?: number[];
}

export interface SyncResult {
    folder_id: number;
    total: number;
    added: number;
    removed: number;
    indexed: number;
    message: string;
    last_sync_at: string;
}

export interface KnowledgeStats {
    total_chunks: number;
    total_videos: number;
    collection_name: string;
}

export interface ChatResponse {
    answer: string;
    sources: Array<{
        bvid: string;
        title: string;
        url: string;
        chunk_index?: number;
        start_time?: number | null;
        end_time?: number | null;
    }>;
}

// ==================== API 函数 ====================

// 认证相关
export const authApi = {
    // 获取登录二维码
    getQRCode: () => request<QRCodeResponse>("/auth/qrcode"),

    // 轮询登录状态
    pollQRCode: (qrcodeKey: string) =>
        request<LoginStatusResponse>(`/auth/qrcode/poll/${qrcodeKey}`),

    // 获取会话信息
    getSession: (sessionId: string) =>
        request<{ valid: boolean; user_info: UserInfo }>(`/auth/session/${sessionId}`),

    // 退出登录
    logout: (sessionId: string) =>
        request(`/auth/session/${sessionId}`, { method: "DELETE" }),
};

// 收藏夹相关
export const favoritesApi = {
    // 获取收藏夹列表
    getList: (sessionId: string) =>
        request<FavoriteFolder[]>(`/favorites/list?session_id=${sessionId}`),

    // 获取收藏夹视频（分页）
    getVideos: (mediaId: number, sessionId: string, page = 1) =>
        request<FavoriteVideosResponse>(
            `/favorites/${mediaId}/videos?session_id=${sessionId}&page=${page}`
        ),

    // 获取收藏夹全部视频
    getAllVideos: (mediaId: number, sessionId: string) =>
        request<{ total: number; videos: Video[] }>(
            `/favorites/${mediaId}/all-videos?session_id=${sessionId}`
        ),

    // 预览整理
    organizePreview: (folderId: number, sessionId: string) =>
        request<OrganizePreviewResponse>(
            `/favorites/organize/preview?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify({ folder_id: folderId }),
            }
        ),

    // 执行整理
    organizeExecute: (
        data: {
            default_folder_id: number;
            moves: Array<{ resource_id: number; resource_type: number; target_folder_id: number }>;
        },
        sessionId: string
    ) =>
        request<{ message: string; moved: number; groups: number }>(
            `/favorites/organize/execute?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify(data),
            }
        ),

    // 清理失效内容
    cleanInvalid: (folderId: number, sessionId: string) =>
        request<{ message: string; data: Record<string, unknown> }>(
            `/favorites/organize/clean-invalid?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify({ folder_id: folderId }),
            }
        ),
};

// 知识库相关
export const knowledgeApi = {
    // 获取统计信息
    getStats: () => request<KnowledgeStats>("/knowledge/stats"),

    // 构建知识库
    build: (data: BuildRequest, sessionId: string) =>
        request<{ task_id: string; message: string }>(
            `/knowledge/build?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify(data),
            }
        ),

    // 获取构建状态
    getBuildStatus: (taskId: string) =>
        request<BuildStatus>(`/knowledge/build/status/${taskId}`),

    // 获取收藏夹入库状态
    getFolderStatus: (sessionId: string) =>
        request<FolderStatus[]>(`/knowledge/folders/status?session_id=${sessionId}`),

    // 同步收藏夹到向量库
    syncFolders: (data: SyncRequest, sessionId: string) =>
        request<SyncResult[]>(
            `/knowledge/folders/sync?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify(data),
            }
        ),

    // 清空知识库
    clear: () =>
        request<{ message: string }>("/knowledge/clear", { method: "DELETE" }),

    // 删除视频
    deleteVideo: (bvid: string) =>
        request<{ message: string }>(`/knowledge/video/${bvid}`, { method: "DELETE" }),
};

// 对话相关
export const chatApi = {
    // 提问
    ask: (question: string, sessionId?: string, folderIds?: number[]) =>
        request<ChatResponse>("/chat/ask", {
            method: "POST",
            body: JSON.stringify({ question, session_id: sessionId, folder_ids: folderIds }),
        }),

    // 搜索
    search: (query: string, k = 5) =>
        request<{ results: Array<{ bvid: string; title: string; url: string; content_preview: string }> }>(
            `/chat/search?query=${encodeURIComponent(query)}&k=${k}`,
            { method: "POST" }
        ),
};

// ==================== WebSocket 相关 ====================

// WebSocket 连接地址
export const getWebSocketUrl = (sessionId: string | null) => {
  if (!sessionId) return null;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") || "localhost:8000";
  return `${protocol}//${host}/recommendations/ws/${sessionId}`;
};

// ==================== 推荐相关 ====================

export interface VideoRecommendation {
    bvid: string;
    title: string;
    author: string;
    reason: string;
    score: number;
    type: string;
    pic?: string;
    duration?: number;
    play?: number;
    mid?: number;
    pubdate?: string;
    recall_tag?: string;
    recall_category?: string;
    matched_interest?: string;
    batch_id: string;
    algorithm_version: string;
    feature_scores?: Record<string, number>;
    matched_concepts?: Array<{ concept_id: string; label: string; matched_label?: string }>;
    ontology_path?: Array<{ from: string; relation: string; to: string }>;
}

export interface RecommendationEventInput {
    session_id: string;
    bvid: string;
    event_type: "impression" | "click" | "viewed" | "favorite" | "watch_later" | "dismiss" | "block_topic" | "block_up" | "like";
    batch_id?: string;
    reason_code?: string;
    topic?: string;
    up_mid?: number;
    position?: number;
    score?: number;
    event_data?: Record<string, unknown>;
}

export interface RecommendationsResponse {
    success: boolean;
    recommendations: VideoRecommendation[];
    count: number;
}

export interface RecommendationOptions {
    mode?: "balanced" | "learning" | "relax" | "following" | "explore" | "rediscover";
    query?: string;
    max_duration?: number;
    exploration_level?: number;
}

export interface RecommendationMetrics {
    window_days: number;
    events: Record<string, number>;
    dismiss_reasons?: Record<string, number>;
    ctr: number;
    dismiss_rate: number;
    favorite_rate: number;
    repeat_exposure_rate: number;
    topic_coverage: number;
    up_coverage: number;
    channel_contribution: Record<string, number>;
    inferred_watched_clicks: number;
    inferred_click_to_watch_rate: number;
    observed: boolean;
    watch_completion_available: boolean;
    inference_note: string;
}

export interface RecommendationPreferences {
    tags: Array<{ tag: string; score: number; source: "long_term" | "recent" | "historical" }>;
    current_intent?: string;
    confidence_score: number;
    updated_at?: string;
    blocked_topics: string[];
    blocked_up_mids: number[];
    ontology_version?: string;
    multi_interests?: Array<{ concept_id: string; label: string; weight: number }>;
    source_freshness?: Record<string, { newest_at?: string | null; average_effective_weight?: number }>;
    interest_evidence?: Array<{
        concept_id: string; concept_label: string; source: string; title?: string;
        age_days?: number; effective_weight?: number; occurred_at?: string;
    }>;
}

export interface PrivacyEvidence {
    id: number;
    source: string;
    item_id: string;
    title: string;
    occurred_at?: string | null;
    last_seen_at?: string | null;
    is_active: boolean;
}

export interface PrivacyControls {
    channels: Record<string, { evidence_count: number; enabled: boolean }>;
    paused_channels: string[];
    evidence: PrivacyEvidence[];
    deletion_scopes: Array<"cookies" | "profile" | "all">;
}

export interface InterestProfile {
    session_id: string;
    interest_tags: Record<string, number>;
    followed_ups: Array<{ mid: number; name: string; score: number }>;
    total_favorites: number;
}

export interface ScheduleTask {
    id: string;
    task_type: string;
    schedule_type: string;
    next_run_time?: string;
    created_at: string;
}

export interface ScheduleTaskResponse {
    success: boolean;
    tasks: ScheduleTask[];
    count: number;
}

// 推荐相关API
export const recommendationsApi = {
    // 获取个性化推荐
    get: (sessionId: string, num = 10, recType = "all", options: RecommendationOptions = {}) =>
        request<RecommendationsResponse>("/recommendations/", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, num, rec_type: recType, ...options }),
        }),

    // 更新兴趣画像
    updateInterest: (sessionId: string) =>
        request<{ success: boolean; profile: InterestProfile }>(
            `/recommendations/update-interest?session_id=${sessionId}`,
            { method: "POST" }
        ),

    // 提交反馈
    feedback: (
        sessionId: string,
        bvid: string,
        action: string,
        metadata: { batch_id?: string; reason_code?: string; topic?: string; up_mid?: number } = {}
    ) =>
        request<{ success: boolean; message: string }>("/recommendations/feedback", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, bvid, action, ...metadata }),
        }),

    event: (event: RecommendationEventInput) =>
        request<{ success: boolean; created: boolean }>("/recommendations/events", {
            method: "POST",
            body: JSON.stringify(event),
        }),

    metrics: (sessionId: string, days = 30) =>
        request<{ success: boolean; metrics: RecommendationMetrics }>(
            `/recommendations/metrics/${sessionId}?days=${days}`
        ),

    preferences: (sessionId: string) =>
        request<{ success: boolean; preferences: RecommendationPreferences }>(
            `/recommendations/preferences/${sessionId}`
        ),

    updatePreferences: (
        sessionId: string,
        data: { tag_updates?: Record<string, number | null>; current_intent?: string; reset_recent?: boolean }
    ) => request<{ success: boolean; message: string }>(
        `/recommendations/preferences/${sessionId}`,
        { method: "PUT", body: JSON.stringify(data) }
    ),

    unblock: (sessionId: string, data: { preference_type: "topic" | "up"; topic?: string; up_mid?: number }) =>
        request<{ success: boolean; message: string }>(
            `/recommendations/preferences/${sessionId}/unblock`,
            { method: "POST", body: JSON.stringify(data) }
        ),

    favoritePreview: (sessionId: string, bvid: string) =>
        request<{ success: boolean; requires_confirmation: boolean; folders: Array<{ media_id: number; title: string }> }>(
            "/recommendations/favorite/preview",
            { method: "POST", body: JSON.stringify({ session_id: sessionId, bvid }) }
        ),

    favoriteExecute: (data: {
        session_id: string; bvid: string; target_media_id: number; confirmed: boolean;
        batch_id?: string; topic?: string; up_mid?: number;
    }) => request<{ success: boolean; message: string }>(
        "/recommendations/favorite/execute",
        { method: "POST", body: JSON.stringify(data) }
    ),
};

export const privacyApi = {
    controls: (sessionId: string) =>
        request<PrivacyControls>(`/privacy/${encodeURIComponent(sessionId)}/controls`),
    setChannel: (sessionId: string, channel: string, enabled: boolean) =>
        request<{ channel: string; enabled: boolean; paused_channels: string[] }>(
            `/privacy/${encodeURIComponent(sessionId)}/channels/${encodeURIComponent(channel)}`,
            { method: "PUT", body: JSON.stringify({ enabled }) }
        ),
    deleteEvidence: (sessionId: string, signalId: number) =>
        request<{ deleted: boolean }>(
            `/privacy/${encodeURIComponent(sessionId)}/evidence/${signalId}?confirmed=true`,
            { method: "DELETE" }
        ),
    deleteData: (sessionId: string, scope: "cookies" | "profile" | "all", confirmation: string) =>
        request<{ success: boolean; scope: string; counts: Record<string, number> }>(
            `/privacy/${encodeURIComponent(sessionId)}/delete`,
            { method: "POST", body: JSON.stringify({ scope, confirmation }) }
        ),
};

// 定时任务API
export const scheduleApi = {
    // 创建收藏夹同步任务
    createSyncTask: (sessionId: string, folderIds: number[], scheduleType: string) =>
        request<{ success: boolean; task_id: string; message: string }>("/schedule/tasks/sync", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, folder_ids: folderIds, schedule_type: scheduleType }),
        }),

    // 创建推荐检查任务
    createRecommendationTask: (sessionId: string, intervalMinutes = 60) =>
        request<{ success: boolean; task_id: string; message: string }>("/schedule/tasks/recommendation", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, interval_minutes: intervalMinutes }),
        }),

    // 创建智能投送任务
    createAutoCollectTask: (sessionId: string, scheduleType = "daily", limit = 5) =>
        request<{ success: boolean; task_id: string; message: string }>("/schedule/tasks/auto-collect", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, schedule_type: scheduleType, limit }),
        }),

    // 获取任务列表
    getTasks: (sessionId: string) =>
        request<ScheduleTaskResponse>(`/schedule/tasks/${sessionId}`),

    // 删除任务
    removeTask: (taskId: string) =>
        request<{ success: boolean; message: string }>(`/schedule/tasks/${taskId}`, { method: "DELETE" }),

    // 暂停任务
    pauseTask: (taskId: string) =>
        request<{ success: boolean; message: string }>(`/schedule/tasks/${taskId}/pause`, { method: "POST" }),

    // 恢复任务
    resumeTask: (taskId: string) =>
        request<{ success: boolean; message: string }>(`/schedule/tasks/${taskId}/resume`, { method: "POST" }),

    // 立即执行任务
    runTaskNow: (taskId: string) =>
        request<{ success: boolean; message: string }>(`/schedule/tasks/${taskId}/run`, { method: "POST" }),
};
