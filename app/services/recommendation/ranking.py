"""确定性、可解释的推荐基础排序与多样性重排。"""
from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

from app.config import settings
from app.services.ontology import get_ontology_service
from app.services.recommendation.profile_schema import RecommendationProfile


DEFAULT_WEIGHTS = {
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
}


def _effective_weights(configured: dict[str, float] | None) -> dict[str, float]:
    """Merge old deployments with the current feature set and normalize safely."""
    merged = dict(DEFAULT_WEIGHTS)
    if configured:
        for name, value in configured.items():
            if name not in merged:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric) and numeric >= 0:
                merged[name] = numeric
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {name: value / total for name, value in merged.items()}


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    latin = set(re.findall(r"[a-z0-9_]+", text))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    bigrams = {chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))}
    return latin | bigrams


def _tag_match(candidate: dict[str, Any], interests: dict[str, float]) -> tuple[float, str | None]:
    haystack = f"{candidate.get('title', '')} {candidate.get('recall_tag', '')} {candidate.get('recall_category', '')}".lower()
    matches = [(tag, float(weight)) for tag, weight in interests.items() if tag.lower() in haystack]
    if not matches:
        return 0.0, None
    tag, weight = max(matches, key=lambda item: item[1])
    return min(1.0, weight), tag


def _freshness(pubdate: Any, now: datetime) -> float:
    if not isinstance(pubdate, datetime):
        return 0.2
    days = max(0, (now - pubdate).days)
    return math.exp(-days / 45.0)


def _quality(play: Any, pubdate: Any, now: datetime) -> float:
    try:
        views = max(0, int(play))
        age_days = max(1, (now - pubdate).days) if isinstance(pubdate, datetime) else 30
        views_per_day = views / age_days
        return min(1.0, math.log10(views_per_day + 1) / 5.0)
    except (TypeError, ValueError):
        return 0.0


def score_candidates(
    candidates: list[dict[str, Any]],
    profile: RecommendationProfile,
    negative_topics: set[str] | None = None,
    negative_up_mids: set[int] | None = None,
    positive_topics: set[str] | None = None,
    positive_up_mids: set[int] | None = None,
    topic_affinity: dict[str, float] | None = None,
    concept_affinity: dict[str, float] | None = None,
    up_affinity_feedback: dict[int, float] | None = None,
    weights: dict[str, float] | None = None,
    now: datetime | None = None,
    mode: str = "balanced",
    exploration_level: float = 0.3,
) -> list[dict[str, Any]]:
    weights = _effective_weights(weights)
    now = now or datetime.utcnow()
    negative_topics = {topic.lower() for topic in (negative_topics or set())}
    negative_up_mids = negative_up_mids or set()
    positive_topics = {topic.lower() for topic in (positive_topics or set())}
    positive_up_mids = positive_up_mids or set()
    topic_affinity = {str(key).lower(): float(value) for key, value in (topic_affinity or {}).items()}
    concept_affinity = {
        str(key): float(value) for key, value in (concept_affinity or {}).items()
    }
    up_affinity_feedback = up_affinity_feedback or {}
    followed = {int(up.get("mid")) for up in profile.followed_ups if up.get("mid")}
    recent_tags = profile.recent_interests
    ontology = get_ontology_service()
    absolute_affinities = (
        profile.concept_absolute_affinities or profile.concept_affinities
    )
    recent_absolute_affinities = (
        profile.recent_concept_absolute_affinities
        or profile.recent_concept_affinities
    )
    semantic_indexes = {
        "absolute": ontology.build_semantic_index(absolute_affinities),
        "relative": ontology.build_semantic_index(profile.concept_relative_shares),
        "recent_absolute": ontology.build_semantic_index(recent_absolute_affinities),
        "recent_relative": ontology.build_semantic_index(
            profile.recent_concept_relative_shares
        ),
    }
    cluster_configs: list[tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]] = []
    for cluster in profile.multi_interests:
        if not isinstance(cluster, dict):
            continue
        cluster_affinities = {
            str(concept.get("concept_id")): float(concept.get("weight", 0.0))
            for concept in (cluster.get("concepts") or [])
            if isinstance(concept, dict) and concept.get("concept_id")
        }
        cluster_configs.append((
            cluster,
            ontology.build_semantic_index(cluster_affinities, max_hops=1),
        ))
    scored: list[dict[str, Any]] = []

    for candidate in candidates:
        content_match, matched_tag = _tag_match(candidate, profile.interest_tags)
        if candidate.get("recall_source") in {"vector_rediscovery", "context_query"}:
            content_match = max(content_match, float(candidate.get("raw_recall_score", 0.0)))
        recent_match, recent_tag = _tag_match(candidate, recent_tags)
        candidate_text = " ".join(filter(None, [
            str(candidate.get("title") or ""),
            str(candidate.get("recall_tag") or ""),
            str(candidate.get("recall_category") or ""),
        ]))
        candidate_concepts: list[dict[str, Any]] = []
        seen_candidate_concepts: set[str] = set()
        for concept in candidate.get("concepts") or []:
            if not isinstance(concept, dict) or not concept.get("concept_id"):
                continue
            concept_id = str(concept["concept_id"])
            if concept_id in seen_candidate_concepts:
                continue
            seen_candidate_concepts.add(concept_id)
            candidate_concepts.append(concept)
        for concept_id_value in candidate.get("concept_ids") or []:
            concept_id = str(concept_id_value or "")
            if not concept_id or concept_id in seen_candidate_concepts:
                continue
            seen_candidate_concepts.add(concept_id)
            candidate_concepts.append({"concept_id": concept_id, "confidence": 1.0})
        if not candidate_concepts:
            candidate_concepts = [
                match.as_dict()
                for match in ontology.resolve_text(candidate_text, limit=12)
            ]
            seen_candidate_concepts = {
                str(concept["concept_id"]) for concept in candidate_concepts
            }

        ontology_match, matched_concepts, ontology_path = ontology.semantic_match_concepts(
            candidate_concepts,
            semantic_indexes["absolute"],
        )
        if profile.concept_relative_shares and ontology_match > 0:
            relative_match, relative_concepts, relative_path = ontology.semantic_match_concepts(
                candidate_concepts, semantic_indexes["relative"]
            )
            # Absolute evidence gates whether this is a real interest; relative
            # share only orders established interests and cannot inflate a weak
            # singleton to full strength.
            ontology_match *= 0.65 + 0.35 * relative_match
            if relative_concepts:
                matched_concepts = matched_concepts or relative_concepts
                ontology_path = ontology_path or relative_path
        recent_ontology_match, recent_concepts, recent_path = ontology.semantic_match_concepts(
            candidate_concepts,
            semantic_indexes["recent_absolute"],
        )
        if profile.recent_concept_relative_shares and recent_ontology_match > 0:
            recent_relative_match, _, _ = ontology.semantic_match_concepts(
                candidate_concepts, semantic_indexes["recent_relative"]
            )
            recent_ontology_match *= 0.65 + 0.35 * recent_relative_match
        if recent_ontology_match > recent_match:
            recent_match = recent_ontology_match
            recent_tag = (recent_concepts[0].get("label") if recent_concepts else recent_tag)

        cluster_matches: list[dict[str, Any]] = []
        for cluster, cluster_index in cluster_configs:
            cluster_score, cluster_concepts, cluster_path = ontology.semantic_match_concepts(
                candidate_concepts, cluster_index
            )
            try:
                cluster_weight = float(cluster.get("weight", 0.0))
            except (TypeError, ValueError):
                cluster_weight = 0.0
            cluster_matches.append({
                "concept_id": cluster.get("concept_id"),
                "label": cluster.get("label"),
                "score": cluster_score * max(0.0, min(1.0, cluster_weight)),
                "matched_concepts": cluster_concepts,
                "path": cluster_path,
            })
        positive_cluster_matches = [row for row in cluster_matches if row["score"] > 0]
        best_cluster = max(positive_cluster_matches, key=lambda row: row["score"], default=None)
        multi_interest = 0.0
        if positive_cluster_matches:
            temperature = max(0.01, float(settings.multi_interest_temperature))
            peak = max(row["score"] for row in positive_cluster_matches)
            exponentials = [
                math.exp((row["score"] - peak) / temperature)
                for row in positive_cluster_matches
            ]
            denominator = sum(exponentials) or 1.0
            for row, value in zip(positive_cluster_matches, exponentials):
                row["attention_weight"] = round(value / denominator, 6)
            multi_interest = sum(
                row["score"] * row["attention_weight"]
                for row in positive_cluster_matches
            )
        up_affinity = 1.0 if candidate.get("mid") in followed else 0.0
        freshness = _freshness(candidate.get("pubdate"), now)
        quality = _quality(candidate.get("play"), candidate.get("pubdate"), now)
        exploration = exploration_level if not matched_tag else max(0.0, exploration_level - 0.2)
        context_match = 0.0
        if profile.current_intent:
            context_match = 1.0 if profile.current_intent.lower() in candidate.get("title", "").lower() else 0.0

        mode_bonus = 0.0
        source = candidate.get("recall_source")
        if mode == "following" and source == "followed_up":
            mode_bonus = 0.20
        elif mode == "explore" and not matched_tag:
            mode_bonus = 0.15
        elif mode == "rediscover" and source == "vector_rediscovery":
            mode_bonus = 0.25
        elif mode == "learning" and any(word in candidate.get("title", "") for word in ("教程", "学习", "入门", "实战", "原理")):
            mode_bonus = 0.15
        elif mode == "relax" and any(word in candidate.get("title", "") for word in ("音乐", "娱乐", "搞笑", "游戏", "日常")):
            mode_bonus = 0.15

        feature_scores = {
            "content_match": round(content_match, 4),
            "ontology_match": round(ontology_match, 4),
            "recent_interest": round(recent_match, 4),
            "multi_interest": round(multi_interest, 4),
            "up_affinity": up_affinity,
            "freshness": round(freshness, 4),
            "quality": round(quality, 4),
            "exploration": exploration,
            "context": context_match,
            "recall_confidence": round(max(0.0, min(1.0, float(
                candidate.get(
                    "calibrated_recall_score",
                    candidate.get("raw_recall_score", 0.0),
                ) or 0.0
            ))), 4),
        }
        score = sum(feature_scores[name] * weights[name] for name in DEFAULT_WEIGHTS)

        topic = (candidate.get("recall_tag") or candidate.get("recall_category") or matched_tag or "").lower()
        negative_penalty = 0.0
        feedback_bonus = 0.0
        title_lower = candidate.get("title", "").lower()
        matched_feedback = [
            value for label, value in topic_affinity.items()
            if label and (label in topic or label in title_lower)
        ]
        topic_feedback = max(matched_feedback, key=abs) if matched_feedback else 0.0
        up_feedback = float(up_affinity_feedback.get(candidate.get("mid"), 0.0))
        concept_feedback_values = [
            concept_affinity[concept_id] for concept_id in seen_candidate_concepts
            if concept_id in concept_affinity
        ]
        concept_feedback = (
            max(concept_feedback_values, key=abs) if concept_feedback_values else 0.0
        )
        combined_feedback = max(-1.0, min(
            1.0, topic_feedback + up_feedback + concept_feedback
        ))
        if combined_feedback < 0:
            negative_penalty += abs(combined_feedback) * 0.5
        elif combined_feedback > 0:
            feedback_bonus += combined_feedback * 0.25

        # 兼容尚未产生衰减强度的调用方。
        if not topic_affinity and topic and any(blocked in topic or blocked in title_lower for blocked in negative_topics):
            negative_penalty += 0.35
        if not up_affinity_feedback and candidate.get("mid") in negative_up_mids:
            negative_penalty += 0.5
        if not topic_affinity and topic and any(liked in topic or liked in title_lower for liked in positive_topics):
            feedback_bonus += 0.15
        if not up_affinity_feedback and candidate.get("mid") in positive_up_mids:
            feedback_bonus += 0.10
        score = max(0.0, min(1.0, score + feedback_bonus + mode_bonus - negative_penalty))

        scored.append({
            **candidate,
            "rec_score": round(score, 4),
            "feature_scores": feature_scores,
            "matched_interest": recent_tag or matched_tag,
            "matched_concepts": matched_concepts or recent_concepts,
            "ontology_path": ontology_path or recent_path,
            "matched_interest_cluster": best_cluster,
            "matched_interest_clusters": positive_cluster_matches,
            "negative_penalty": round(negative_penalty, 4),
            "feedback_bonus": round(feedback_bonus, 4),
            "mode_bonus": round(mode_bonus, 4),
            "feedback_affinity": round(combined_feedback, 4),
            "concept_feedback_affinity": round(concept_feedback, 4),
        })

    return sorted(scored, key=lambda item: item["rec_score"], reverse=True)


def _candidate_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = _tokens(f"{left.get('title', '')} {left.get('recall_tag', '')}")
    right_tokens = _tokens(f"{right.get('title', '')} {right.get('recall_tag', '')}")
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _duration_bucket(candidate: dict[str, Any]) -> str:
    try:
        duration = int(candidate.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        return "unknown"
    if duration < 300:
        return "short"
    if duration <= 1200:
        return "medium"
    return "long"


def diversify(
    candidates: list[dict[str, Any]],
    limit: int,
    max_per_up: int = 2,
    diversity_strength: float = 0.25,
) -> list[dict[str, Any]]:
    """MMR 重排，并施加 UP 主硬上限、来源与时长覆盖奖励。"""
    selected: list[dict[str, Any]] = []
    remaining = [dict(candidate) for candidate in candidates]
    up_counts: dict[Any, int] = {}
    used_sources: set[str] = set()
    used_durations: set[str] = set()
    token_cache = {
        id(candidate): _tokens(
            f"{candidate.get('title', '')} {candidate.get('recall_tag', '')}"
        )
        for candidate in remaining
    }
    duration_cache = {
        id(candidate): _duration_bucket(candidate) for candidate in remaining
    }

    while remaining and len(selected) < limit:
        eligible = [
            item for item in remaining
            if up_counts.get(item.get("mid") or item.get("author"), 0) < max_per_up
        ]
        if not eligible:
            break

        best = None
        best_mmr = float("-inf")
        for candidate in eligible:
            candidate_tokens = token_cache[id(candidate)]
            similarity = max(
                (
                    len(candidate_tokens & token_cache[id(prior)])
                    / len(candidate_tokens | token_cache[id(prior)])
                    for prior in selected
                    if candidate_tokens and token_cache[id(prior)]
                ),
                default=0.0,
            )
            source = candidate.get("recall_source", "unknown")
            duration_bucket = duration_cache[id(candidate)]
            coverage_bonus = (0.05 if source not in used_sources else 0.0)
            coverage_bonus += (0.03 if duration_bucket not in used_durations else 0.0)
            mmr_score = float(candidate.get("rec_score", 0.0)) - diversity_strength * similarity + coverage_bonus
            if mmr_score > best_mmr:
                best = candidate
                best_mmr = mmr_score

        if best is None:
            break
        best["mmr_score"] = round(best_mmr, 4)
        selected.append(best)
        remaining.remove(best)
        identity = best.get("mid") or best.get("author")
        if identity:
            up_counts[identity] = up_counts.get(identity, 0) + 1
        used_sources.add(best.get("recall_source", "unknown"))
        used_durations.add(duration_cache[id(best)])
    return selected


def blend_llm_scores(
    ranked_candidates: list[dict[str, Any]],
    llm_candidates: list[dict[str, Any]],
    llm_weight: float = 0.25,
) -> list[dict[str, Any]]:
    """将可选 LLM 分与规则分混合；缺失/统一 LLM 分不会抹平规则差异。"""
    llm_weight = max(0.0, min(1.0, llm_weight))
    llm_by_bvid: dict[str, float] = {}
    for item in llm_candidates:
        bvid = item.get("bvid")
        try:
            score = float(item.get("rec_score"))
        except (TypeError, ValueError):
            continue
        if bvid and math.isfinite(score):
            llm_by_bvid[bvid] = max(0.0, min(1.0, score))
    # A constant (or nearly constant) auxiliary score contains no ranking
    # signal. Applying it only to the valid subset would reorder candidates
    # because of missing values, so keep the deterministic rule ranking.
    if len(set(round(value, 8) for value in llm_by_bvid.values())) <= 1:
        return [dict(candidate) for candidate in ranked_candidates]
    blended: list[dict[str, Any]] = []
    for candidate in ranked_candidates:
        item = dict(candidate)
        if item.get("bvid") in llm_by_bvid:
            item["llm_score"] = llm_by_bvid[item["bvid"]]
            item["rec_score"] = round(
                float(item.get("rec_score", 0.0)) * (1.0 - llm_weight)
                + item["llm_score"] * llm_weight,
                4,
            )
        blended.append(item)
    return sorted(blended, key=lambda item: item.get("rec_score", 0.0), reverse=True)
