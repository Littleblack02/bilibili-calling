"""
DeerFlow Tools - Expose bilibili-rag services as LangChain Tools for DeerFlow.

This package bridges bilibili-rag's existing business logic (RAG, B站 API, 收藏夹)
with DeerFlow's agent framework by wrapping them as LangChain tools.

All tools use the @tool decorator from langchain.tools for consistency
with DeerFlow's tool loading system.
"""

from app.deerflow_tools.rag_tools import rag_search_tool, rag_answer_tool
from app.deerflow_tools.bilibili_tools import (
    get_bilibili_favorites_tool,
    sync_favorite_folder_tool,
    get_video_info_tool,
    get_up_info_tool,
    bilibili_search_tool,
    get_trending_tool,
    add_to_favorites_tool,
    intelligent_recommend_tool,
)
from app.deerflow_tools.gemma_tools import analyze_cover_tool
from app.deerflow_tools.profile_tools import (
    build_user_profile_tool,
    update_profile_from_conversation_tool,
    get_user_profile_tool,
)
from app.deerflow_tools.recommendation_tools import (
    generate_recommendations_tool,
    get_candidate_recommendations_tool,
    accept_recommendation_tool,
    reject_recommendation_tool,
    setup_recommendation_schedule_tool,
    get_schedule_tasks_tool,
    remove_schedule_task_tool,
    build_user_profile_tool as build_multi_source_profile_tool,
)
from app.deerflow_tools.time_tools import (
    get_current_time_tool,
    check_recommendation_needed_tool,
    save_prefetch_recommendations_tool,
    get_prefetch_recommendations_tool,
    mark_prefetch_as_pushed_tool,
    clear_prefetch_cache_tool,
    get_prefetch_cache_status_tool,
)

__all__ = [
    "rag_search_tool",
    "rag_answer_tool",
    "get_bilibili_favorites_tool",
    "sync_favorite_folder_tool",
    "get_video_info_tool",
    "get_up_info_tool",
    "bilibili_search_tool",
    "get_trending_tool",
    "add_to_favorites_tool",
    "intelligent_recommend_tool",
    "analyze_cover_tool",
    "build_user_profile_tool",
    "update_profile_from_conversation_tool",
    "get_user_profile_tool",
    "generate_recommendations_tool",
    "get_candidate_recommendations_tool",
    "accept_recommendation_tool",
    "reject_recommendation_tool",
    "setup_recommendation_schedule_tool",
    "get_schedule_tasks_tool",
    "remove_schedule_task_tool",
    "build_multi_source_profile_tool",
    "get_current_time_tool",
    "check_recommendation_needed_tool",
    "save_prefetch_recommendations_tool",
    "get_prefetch_recommendations_tool",
    "mark_prefetch_as_pushed_tool",
    "clear_prefetch_cache_tool",
    "get_prefetch_cache_status_tool",
]

# Re-export aliases matching the tool names in config.yaml
rag_search = rag_search_tool
rag_answer = rag_answer_tool
get_bilibili_favorites = get_bilibili_favorites_tool
sync_favorite_folder = sync_favorite_folder_tool
get_video_info = get_video_info_tool
get_up_info = get_up_info_tool
bilibili_search = bilibili_search_tool
get_trending = get_trending_tool
add_to_favorites = add_to_favorites_tool
intelligent_recommend = intelligent_recommend_tool
analyze_cover = analyze_cover_tool
build_user_profile = build_user_profile_tool
update_profile_from_conversation = update_profile_from_conversation_tool
get_user_profile = get_user_profile_tool
generate_recommendations = generate_recommendations_tool
get_candidate_recommendations = get_candidate_recommendations_tool
accept_recommendation = accept_recommendation_tool
reject_recommendation = reject_recommendation_tool
setup_recommendation_schedule = setup_recommendation_schedule_tool
get_schedule_tasks = get_schedule_tasks_tool
remove_schedule_task = remove_schedule_task_tool
build_multi_source_profile = build_multi_source_profile_tool
get_current_time = get_current_time_tool
check_recommendation_needed = check_recommendation_needed_tool
save_prefetch_recommendations = save_prefetch_recommendations_tool
get_prefetch_recommendations = get_prefetch_recommendations_tool
mark_prefetch_as_pushed = mark_prefetch_as_pushed_tool
clear_prefetch_cache = clear_prefetch_cache_tool
get_prefetch_cache_status = get_prefetch_cache_status_tool
