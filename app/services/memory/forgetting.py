"""
遗忘策略

LTM 不再只进不出，基于多维度判断是否应该遗忘：
1. 长期未访问 + 访问次数少
2. 低重要性 + 超时
3. 存储告警时，从最低分开始清理
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.services.memory.base import MemoryEntry
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ForgettingPolicy:
    """
    遗忘策略

    触发条件（满足任一即遗忘）：
    1. 长期未访问：超过 max_age_days 天未被访问，且访问次数 < min_access_count
    2. 低重要性超时：importance <= 2 且超过 low_importance_ttl 天
    3. 存储超限：超过 max_total 时，从最低分开始清理
    """

    DEFAULT_THRESHOLDS = {
        "max_age_days": 30,           # 最大存活天数（无访问）
        "min_access_count": 2,       # 最少访问次数
        "low_importance_ttl": 7,      # 低重要性 TTL（天）
        "low_importance_max": 2,      # "低重要性" 的定义阈值
        "max_total": 10000,           # 最大总条数
        "min_score_to_keep": 3.0,     # 清理时最低保留分数
    }

    def __init__(self, thresholds: Optional[Dict[str, Any]] = None):
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}

    def should_forget(self, entry: MemoryEntry) -> bool:
        """
        判断单条记忆是否应该被遗忘

        Returns:
            (should_forget: bool, reason: str)
        """
        now = datetime.utcnow()

        # 条件1：长期未访问
        if entry.last_accessed:
            days_since_access = (now - entry.last_accessed).days
            if days_since_access > self.thresholds["max_age_days"]:
                if entry.access_count < self.thresholds["min_access_count"]:
                    return True, (
                        f"长期未访问({days_since_access}天)，访问次数({entry.access_count})"
                        f"< 阈值({self.thresholds['min_access_count']})"
                    )

        # 条件2：低重要性 + 超时
        if entry.importance <= self.thresholds["low_importance_max"]:
            if entry.created_at:
                days_since_create = (now - entry.created_at).days
                if days_since_create > self.thresholds["low_importance_ttl"]:
                    return True, (
                        f"低重要性({entry.importance})超过"
                        f"{self.thresholds['low_importance_ttl']}天"
                    )

        # 条件3：零访问的古老记忆（被动积累的噪音）
        if entry.access_count == 0 and entry.created_at:
            days_since_create = (now - entry.created_at).days
            if days_since_create > self.thresholds["max_age_days"] * 2:
                return True, (
                    f"创建{months_since_create}天但从未被访问，判定为噪音"
                )

        return False, ""

    def compute_forget_score(self, entry: MemoryEntry) -> float:
        """
        计算遗忘分数（越低越容易被遗忘）

        分数 = 基础分 - 时间衰减 - 访问稀疏惩罚
        """
        now = datetime.utcnow()
        base_score = entry.importance * 10.0

        # 时间衰减
        if entry.created_at:
            days_old = (now - entry.created_at).days
            time_decay = min(days_old / 90.0, 3.0)  # 最多衰减 3 分
        else:
            time_decay = 0

        # 访问频率奖励（访问次数越多越不容易忘）
        access_bonus = min(entry.access_count * 0.5, 5.0)

        # 最近访问奖励（越近访问越不容易忘）
        if entry.last_accessed:
            days_since_access = (now - entry.last_accessed).days
            recency_bonus = max(0, 2.0 - days_since_access / 15.0)
        else:
            recency_bonus = 0

        score = base_score + access_bonus + recency_bonus - time_decay
        return max(score, 0.0)

    def batch_eval(self, entries: List[MemoryEntry]) -> List[Dict[str, Any]]:
        """
        批量评估记忆

        Returns:
            每个条目的评估结果列表
        """
        results = []
        for entry in entries:
            should_forget, reason = self.should_forget(entry)
            forget_score = self.compute_forget_score(entry)
            results.append({
                "memory_id": entry.id,
                "should_forget": should_forget,
                "reason": reason,
                "forget_score": forget_score,
                "importance": entry.importance,
                "access_count": entry.access_count,
                "last_accessed": entry.last_accessed,
                "created_at": entry.created_at,
            })
        return results

    def get_cleanup_candidates(
        self,
        entries: List[MemoryEntry],
        max_to_delete: Optional[int] = None
    ) -> List[int]:
        """
        获取需要清理的记忆 ID 列表

        Args:
            entries: 所有待评估的记忆
            max_to_delete: 最大删除数量（超过存储上限时限制）

        Returns:
            需要删除的 memory_id 列表
        """
        # 先评估所有记忆
        evaluations = self.batch_eval(entries)

        # 分类
        must_delete = [e["memory_id"] for e in evaluations if e["should_forget"]]

        # 如果还不够，从最低分的中选取
        remaining_slots = (max_to_delete or 0) - len(must_delete)
        if remaining_slots > 0:
            non_must = [e for e in evaluations if not e["should_forget"]]
            non_must.sort(key=lambda x: x["forget_score"])

            # 选择分数最低的
            additional = [e["memory_id"] for e in non_must[:remaining_slots]]
            must_delete.extend(additional)

        return must_delete


class MemoryForgettingService:
    """
    遗忘服务

    管理 LTM 的遗忘逻辑，提供定时清理接口
    """

    def __init__(self, forgetting_policy: Optional[ForgettingPolicy] = None):
        self.policy = forgetting_policy or ForgettingPolicy()

    async def cleanup_session(
        self,
        session_id: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        清理单个 session 的可遗忘记忆

        Args:
            session_id: 会话 ID
            dry_run: True 则只评估不删除

        Returns:
            清理结果统计
        """
        from app.services.memory.manager import MemoryManager

        manager = MemoryManager(session_id)

        # 获取所有 LTM 记忆
        all_memories = await manager.ltm.get_recent(limit=self.policy.thresholds["max_total"])

        if not all_memories:
            return {"deleted_count": 0, "candidates": 0, "dry_run": dry_run}

        # 评估
        evaluations = self.policy.batch_eval(all_memories)
        candidates = [e for e in evaluations if e["should_forget"]]

        if dry_run:
            return {
                "deleted_count": 0,
                "candidates": len(candidates),
                "candidate_details": candidates,
                "dry_run": True
            }

        # 执行删除
        deleted = 0
        errors = 0
        for eval_item in candidates:
            try:
                ok = await manager.delete(eval_item["memory_id"], memory_type="long")
                if ok:
                    deleted += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"删除记忆失败 id={eval_item['memory_id']}: {e}")
                errors += 1

        logger.info(
            f"遗忘清理: session={session_id}, "
            f"候选={len(candidates)}, 删除={deleted}, 错误={errors}"
        )

        return {
            "deleted_count": deleted,
            "errors": errors,
            "candidates": len(candidates),
            "dry_run": False
        }

    async def global_cleanup(
        self,
        session_ids: List[str],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        全局遗忘清理（所有 session）

        Returns:
            各 session 的清理结果汇总
        """
        results = {}
        total_deleted = 0

        for session_id in session_ids:
            result = await self.cleanup_session(session_id, dry_run=dry_run)
            results[session_id] = result
            total_deleted += result.get("deleted_count", 0)

        return {
            "total_deleted": total_deleted,
            "sessions_processed": len(session_ids),
            "session_results": results,
            "dry_run": dry_run
        }
