"""
候选合并器服务

职责：
- 合并多路召回结果
- 去重
- 统一候选格式
- 限制候选池大小
"""
from typing import List, Dict, Any, Optional
from loguru import logger
from collections import Counter

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import CandidatePool, FavoriteVideo, FavoriteFolder


class CandidateMerger:
    """候选合并器"""

    def __init__(self, max_pool_size: int = 100):
        self.max_pool_size = max_pool_size

    async def merge_and_deduplicate(
        self,
        session_id: str,
        recall_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        合并多路召回结果并去重

        Args:
            session_id: 用户会话 ID
            recall_results: 召回结果列表（来自不同召回源）

        Returns:
            去重后的候选列表
        """
        logger.info(f"开始合并候选: {session_id}, 召回数: {len(recall_results)}")

        # 1. 去重（按 bvid）
        unique_candidates = self._deduplicate_by_bvid(recall_results)

        # 2. 过滤已收藏的视频
        filtered_candidates = await self._filter_favorited(session_id, unique_candidates)

        # 3. 限制候选池大小
        limited_candidates = self._limit_pool_size(filtered_candidates)

        # 4. 统一格式
        unified_candidates = self._unify_format(limited_candidates)

        # 5. 保存到候选池
        await self._save_to_pool(session_id, unified_candidates)

        logger.info(f"候选合并完成: {session_id}, 最终数: {len(unified_candidates)}")
        return unified_candidates

    def _deduplicate_by_bvid(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按 bvid 去重，保留召回源优先级最高的"""
        bvid_map = {}

        # 召回源优先级
        RECALL_PRIORITY = {
            "interest": 4,
            "followed_up": 3,
            "category": 2,
            "trending": 1,
            "related": 1
        }

        for cand in candidates:
            bvid = cand.get("bvid", "")
            if not bvid:
                continue

            recall_source = cand.get("recall_source", "")

            if bvid not in bvid_map:
                bvid_map[bvid] = cand
            else:
                # 比较优先级
                existing_source = bvid_map[bvid].get("recall_source", "")
                if RECALL_PRIORITY.get(recall_source, 0) > RECALL_PRIORITY.get(existing_source, 0):
                    bvid_map[bvid] = cand
                    # 合并召回标签
                    if "recall_tag" in cand and cand["recall_tag"]:
                        bvid_map[bvid]["recall_tag"] = cand["recall_tag"]

        return list(bvid_map.values())

    async def _filter_favorited(
        self,
        session_id: str,
        candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """过滤已收藏的视频"""
        async with async_session_factory() as db:
            # 查询用户已收藏的视频 BV 号
            from app.models import VideoCache

            result = await db.execute(
                select(VideoCache.bvid)
                .join(FavoriteVideo, FavoriteVideo.bvid == VideoCache.bvid)
                .join(FavoriteFolder, FavoriteFolder.id == FavoriteVideo.folder_id)
                .where(FavoriteFolder.session_id == session_id)
                .where(FavoriteVideo.is_selected == True)
            )

            favorited_bvids = {row[0] for row in result.fetchall()}

            # 过滤
            filtered = [
                cand for cand in candidates
                if cand.get("bvid") not in favorited_bvids
            ]

            logger.info(f"过滤已收藏: {len(candidates)} -> {len(filtered)}")
            return filtered

    def _limit_pool_size(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """限制候选池大小"""
        if len(candidates) <= self.max_pool_size:
            return candidates

        # 按召回源优先级排序
        RECALL_PRIORITY = {
            "interest": 4,
            "followed_up": 3,
            "category": 2,
            "trending": 1,
            "related": 1
        }

        sorted_candidates = sorted(
            candidates,
            key=lambda x: (
                RECALL_PRIORITY.get(x.get("recall_source", ""), 0),
                x.get("play", 0)  # 同优先级内按播放量排序
            ),
            reverse=True
        )

        return sorted_candidates[:self.max_pool_size]

    def _unify_format(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """统一候选格式"""
        unified = []

        for cand in candidates:
            unified.append({
                "bvid": cand.get("bvid", ""),
                "title": cand.get("title", ""),
                "author": cand.get("author", ""),
                "mid": cand.get("mid", 0),
                "play": cand.get("play", 0),
                "duration": cand.get("duration", 0),
                "pic_url": cand.get("pic_url", ""),
                "pubdate": cand.get("pubdate"),
                "recall_source": cand.get("recall_source", "unknown"),
                "recall_tag": cand.get("recall_tag", "")
            })

        return unified

    async def _save_to_pool(
        self,
        session_id: str,
        candidates: List[Dict[str, Any]]
    ):
        """保存到候选池"""
        from datetime import datetime, timedelta

        async with async_session_factory() as db:
            for cand in candidates:
                # 检查是否已存在
                existing = await db.execute(
                    select(CandidatePool).where(
                        and_(
                            CandidatePool.session_id == session_id,
                            CandidatePool.bvid == cand.get("bvid")
                        )
                    )
                )
                existing_record = existing.scalar_one_or_none()

                # 计算过期时间（24小时后）
                expires_at = datetime.utcnow() + timedelta(hours=24)

                if not existing_record:
                    # 新增
                    new_candidate = CandidatePool(
                        session_id=session_id,
                        bvid=cand.get("bvid", ""),
                        recall_source=cand.get("recall_source", "unknown"),
                        recall_tag=cand.get("recall_tag", ""),
                        title=cand.get("title", ""),
                        author=cand.get("author", ""),
                        mid=cand.get("mid", 0),
                        play=cand.get("play", 0),
                        duration=cand.get("duration", 0),
                        pic_url=cand.get("pic_url", ""),
                        pubdate=cand.get("pubdate"),
                        expires_at=expires_at
                    )
                    db.add(new_candidate)

            await db.commit()

    async def get_candidate_pool(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取候选池"""
        async with async_session_factory() as db:
            result = await db.execute(
                select(CandidatePool)
                .where(
                    and_(
                        CandidatePool.session_id == session_id,
                        CandidatePool.expires_at > datetime.utcnow()
                    )
                )
                .order_by(CandidatePool.created_at.desc())
                .limit(limit)
            )

            candidates = []
            for record in result.scalars():
                candidates.append({
                    "bvid": record.bvid,
                    "title": record.title,
                    "author": record.author,
                    "play": record.play,
                    "recall_source": record.recall_source,
                    "recall_tag": record.recall_tag,
                    "created_at": record.created_at
                })

            return candidates


# 单例
_candidate_merger: Optional[CandidateMerger] = None


def get_candidate_merger() -> CandidateMerger:
    """获取候选合并器单例"""
    global _candidate_merger
    if _candidate_merger is None:
        _candidate_merger = CandidateMerger()
    return _candidate_merger
